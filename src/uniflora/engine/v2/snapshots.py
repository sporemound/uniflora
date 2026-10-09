from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Literal, cast

from uniflora.engine.v2.integrity import (
    V2EventEnvelope,
    V2IntegrityError,
    verify_event_envelopes,
)
from uniflora.engine.v2.serialization import (
    V2SerializationError,
    canonical_json_bytes,
    state_from_record,
    state_to_record,
)
from uniflora.engine.v2.state import V2InvestigationState

V2_SNAPSHOT_SCHEMA_VERSION = 1
_HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class V2SnapshotError(ValueError):
    """Raised when a snapshot envelope is invalid or does not match a stream."""


def calculate_state_hash(state: V2InvestigationState) -> str:
    return hashlib.sha256(canonical_json_bytes(state_to_record(state))).hexdigest()


def _snapshot_hash_material(
    *,
    stream_id: str,
    sequence: int,
    last_event_hash: str,
    state: V2InvestigationState,
    state_hash: str,
) -> dict[str, object]:
    return {
        "last_event_hash": last_event_hash,
        "schema_version": V2_SNAPSHOT_SCHEMA_VERSION,
        "sequence": sequence,
        "state": state_to_record(state),
        "state_hash": state_hash,
        "stream_id": stream_id,
    }


def calculate_snapshot_hash(
    *,
    stream_id: str,
    sequence: int,
    last_event_hash: str,
    state: V2InvestigationState,
    state_hash: str,
) -> str:
    return hashlib.sha256(
        canonical_json_bytes(
            _snapshot_hash_material(
                stream_id=stream_id,
                sequence=sequence,
                last_event_hash=last_event_hash,
                state=state,
                state_hash=state_hash,
            )
        )
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class V2SnapshotEnvelope:
    stream_id: str
    sequence: int
    last_event_hash: str
    state: V2InvestigationState
    state_hash: str
    snapshot_hash: str
    schema_version: Literal[1] = V2_SNAPSHOT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != V2_SNAPSHOT_SCHEMA_VERSION:
            raise ValueError(f"unsupported snapshot schema version: {self.schema_version}")

        if not self.stream_id.strip():
            raise ValueError("snapshot stream ID must not be blank")

        if self.sequence < 0:
            raise ValueError("snapshot sequence must not be negative")

        if self.state.revision != self.sequence:
            raise ValueError("snapshot state revision must match its sequence")

        for value, label in (
            (self.last_event_hash, "last event hash"),
            (self.state_hash, "state hash"),
            (self.snapshot_hash, "snapshot hash"),
        ):
            if not _HASH_PATTERN.fullmatch(value):
                raise ValueError(f"snapshot {label} must be a lowercase SHA-256 hex digest")


def create_snapshot_envelope(
    envelopes: Iterable[V2EventEnvelope],
) -> V2SnapshotEnvelope:
    envelope_tuple = tuple(envelopes)

    if not envelope_tuple:
        raise V2SnapshotError("cannot create a snapshot from an empty stream")

    state = verify_event_envelopes(envelope_tuple)
    last = envelope_tuple[-1]
    state_hash = calculate_state_hash(state)
    snapshot_hash = calculate_snapshot_hash(
        stream_id=last.event.stream_id,
        sequence=last.event.sequence,
        last_event_hash=last.event_hash,
        state=state,
        state_hash=state_hash,
    )

    return V2SnapshotEnvelope(
        stream_id=last.event.stream_id,
        sequence=last.event.sequence,
        last_event_hash=last.event_hash,
        state=state,
        state_hash=state_hash,
        snapshot_hash=snapshot_hash,
    )


def snapshot_envelope_to_record(
    snapshot: V2SnapshotEnvelope,
) -> dict[str, object]:
    return {
        "last_event_hash": snapshot.last_event_hash,
        "schema_version": snapshot.schema_version,
        "sequence": snapshot.sequence,
        "snapshot_hash": snapshot.snapshot_hash,
        "state": state_to_record(snapshot.state),
        "state_hash": snapshot.state_hash,
        "stream_id": snapshot.stream_id,
    }


def verify_snapshot_envelope(
    snapshot: V2SnapshotEnvelope,
    envelopes: Iterable[V2EventEnvelope] | None = None,
) -> V2InvestigationState:
    expected_state_hash = calculate_state_hash(snapshot.state)
    if snapshot.state_hash != expected_state_hash:
        raise V2SnapshotError("snapshot state hash does not match its state")

    expected_snapshot_hash = calculate_snapshot_hash(
        stream_id=snapshot.stream_id,
        sequence=snapshot.sequence,
        last_event_hash=snapshot.last_event_hash,
        state=snapshot.state,
        state_hash=snapshot.state_hash,
    )
    if snapshot.snapshot_hash != expected_snapshot_hash:
        raise V2SnapshotError("snapshot hash does not match its envelope")

    if envelopes is None:
        return snapshot.state

    envelope_tuple = tuple(envelopes)
    if not envelope_tuple:
        raise V2SnapshotError("snapshot verification requires event envelopes")

    try:
        replayed = verify_event_envelopes(envelope_tuple)
    except V2IntegrityError as exc:
        raise V2SnapshotError(f"snapshot event chain is invalid: {exc}") from exc

    last = envelope_tuple[-1]
    if last.event.stream_id != snapshot.stream_id:
        raise V2SnapshotError("snapshot stream ID does not match the event chain")

    if last.event.sequence != snapshot.sequence:
        raise V2SnapshotError("snapshot sequence does not match the event chain")

    if last.event_hash != snapshot.last_event_hash:
        raise V2SnapshotError("snapshot last event hash does not match the event chain")

    if replayed != snapshot.state:
        raise V2SnapshotError("snapshot state does not match deterministic replay")

    return snapshot.state


def serialize_snapshot_envelope(snapshot: V2SnapshotEnvelope) -> bytes:
    verify_snapshot_envelope(snapshot)
    return canonical_json_bytes(snapshot_envelope_to_record(snapshot))


def snapshot_envelope_from_record(value: object) -> V2SnapshotEnvelope:
    if not isinstance(value, Mapping):
        raise V2SerializationError("snapshot envelope must be a JSON object")

    expected = frozenset(
        {
            "last_event_hash",
            "schema_version",
            "sequence",
            "snapshot_hash",
            "state",
            "state_hash",
            "stream_id",
        }
    )
    if frozenset(value) != expected:
        raise V2SerializationError("snapshot envelope has invalid fields")

    schema_version = value["schema_version"]
    sequence = value["sequence"]

    if isinstance(schema_version, bool) or not isinstance(schema_version, int):
        raise V2SerializationError("snapshot schema version must be an integer")

    if isinstance(sequence, bool) or not isinstance(sequence, int):
        raise V2SerializationError("snapshot sequence must be an integer")

    string_fields: dict[str, str] = {}
    for key in ("last_event_hash", "snapshot_hash", "state_hash", "stream_id"):
        item = value[key]
        if not isinstance(item, str):
            raise V2SerializationError(f"snapshot {key} must be a string")
        string_fields[key] = item

    try:
        snapshot = V2SnapshotEnvelope(
            stream_id=string_fields["stream_id"],
            sequence=sequence,
            last_event_hash=string_fields["last_event_hash"],
            state=state_from_record(value["state"]),
            state_hash=string_fields["state_hash"],
            snapshot_hash=string_fields["snapshot_hash"],
            schema_version=cast(Literal[1], schema_version),
        )
    except ValueError as exc:
        raise V2SnapshotError(str(exc)) from exc

    verify_snapshot_envelope(snapshot)
    return snapshot


def deserialize_snapshot_envelope(
    data: bytes | bytearray | memoryview | str,
) -> V2SnapshotEnvelope:
    try:
        text = data if isinstance(data, str) else bytes(data).decode("utf-8")
        value = json.loads(text)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise V2SerializationError(f"invalid snapshot-envelope JSON: {exc}") from exc

    return snapshot_envelope_from_record(value)
