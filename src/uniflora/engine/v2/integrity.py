from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Literal, cast

from uniflora.engine.v2.event_stream import (
    V2InvestigationStream,
    verify_event_stream,
)
from uniflora.engine.v2.events import V2InvestigationEvent
from uniflora.engine.v2.reducer import V2ReplayError, replay_events
from uniflora.engine.v2.serialization import (
    V2SerializationError,
    canonical_json_bytes,
    event_from_record,
    event_to_record,
)
from uniflora.engine.v2.state import V2InvestigationState

V2_EVENT_ENVELOPE_SCHEMA_VERSION = 1
_HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class V2IntegrityError(ValueError):
    """Raised when an event hash chain or envelope is invalid."""


def _require_hash(value: str, *, label: str) -> None:
    if not _HASH_PATTERN.fullmatch(value):
        raise ValueError(f"{label} must be a lowercase SHA-256 hex digest")


def _hash_material(
    event: V2InvestigationEvent,
    previous_hash: str | None,
) -> dict[str, object]:
    return {
        "event": event_to_record(event),
        "previous_hash": previous_hash,
        "schema_version": V2_EVENT_ENVELOPE_SCHEMA_VERSION,
    }


def calculate_event_hash(
    event: V2InvestigationEvent,
    previous_hash: str | None,
) -> str:
    return hashlib.sha256(canonical_json_bytes(_hash_material(event, previous_hash))).hexdigest()


@dataclass(frozen=True, slots=True)
class V2EventEnvelope:
    event: V2InvestigationEvent
    previous_hash: str | None
    event_hash: str
    schema_version: Literal[1] = V2_EVENT_ENVELOPE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != V2_EVENT_ENVELOPE_SCHEMA_VERSION:
            raise ValueError(f"unsupported event-envelope schema version: {self.schema_version}")

        _require_hash(self.event_hash, label="event hash")

        if self.event.sequence == 0:
            if self.previous_hash is not None:
                raise ValueError("the first event envelope cannot have a previous hash")
        else:
            if self.previous_hash is None:
                raise ValueError("noninitial event envelopes require a previous hash")

            _require_hash(self.previous_hash, label="previous event hash")


def create_event_envelope(
    event: V2InvestigationEvent,
    *,
    previous_hash: str | None,
) -> V2EventEnvelope:
    return V2EventEnvelope(
        event=event,
        previous_hash=previous_hash,
        event_hash=calculate_event_hash(event, previous_hash),
    )


def event_envelope_to_record(envelope: V2EventEnvelope) -> dict[str, object]:
    return {
        "event": event_to_record(envelope.event),
        "event_hash": envelope.event_hash,
        "previous_hash": envelope.previous_hash,
        "schema_version": envelope.schema_version,
    }


def serialize_event_envelope(envelope: V2EventEnvelope) -> bytes:
    return canonical_json_bytes(event_envelope_to_record(envelope))


def _require_mapping(value: object, *, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise V2SerializationError(f"{label} must be a JSON object")

    return value


def event_envelope_from_record(value: object) -> V2EventEnvelope:
    record = _require_mapping(value, label="event envelope")
    expected = frozenset({"event", "event_hash", "previous_hash", "schema_version"})

    if frozenset(record) != expected:
        raise V2SerializationError("event envelope has invalid fields")

    schema_version = record["schema_version"]
    if isinstance(schema_version, bool) or not isinstance(schema_version, int):
        raise V2SerializationError("event-envelope schema version must be an integer")

    previous_hash = record["previous_hash"]
    if previous_hash is not None and not isinstance(previous_hash, str):
        raise V2SerializationError("previous event hash must be a string or null")

    event_hash = record["event_hash"]
    if not isinstance(event_hash, str):
        raise V2SerializationError("event hash must be a string")

    try:
        envelope = V2EventEnvelope(
            event=event_from_record(record["event"]),
            previous_hash=previous_hash,
            event_hash=event_hash,
            schema_version=cast(Literal[1], schema_version),
        )
    except ValueError as exc:
        raise V2IntegrityError(str(exc)) from exc

    expected_hash = calculate_event_hash(
        envelope.event,
        envelope.previous_hash,
    )
    if envelope.event_hash != expected_hash:
        raise V2IntegrityError("event envelope hash does not match its contents")

    return envelope


def deserialize_event_envelope(
    data: bytes | bytearray | memoryview | str,
) -> V2EventEnvelope:
    try:
        text = data if isinstance(data, str) else bytes(data).decode("utf-8")
        value = json.loads(text)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise V2SerializationError(f"invalid event-envelope JSON: {exc}") from exc

    return event_envelope_from_record(value)


def seal_events(
    events: Iterable[V2InvestigationEvent],
) -> tuple[V2EventEnvelope, ...]:
    event_tuple = tuple(events)

    if not event_tuple:
        raise V2IntegrityError("cannot seal an empty event stream")

    envelopes: list[V2EventEnvelope] = []
    previous_hash: str | None = None

    for event in event_tuple:
        envelope = create_event_envelope(
            event,
            previous_hash=previous_hash,
        )
        envelopes.append(envelope)
        previous_hash = envelope.event_hash

    result = tuple(envelopes)
    verify_event_envelopes(result)
    return result


def seal_event_stream(
    stream: V2InvestigationStream,
) -> tuple[V2EventEnvelope, ...]:
    verify_event_stream(stream)
    return seal_events(stream.events)


def verify_event_envelopes(
    envelopes: Iterable[V2EventEnvelope],
) -> V2InvestigationState:
    envelope_tuple = tuple(envelopes)

    if not envelope_tuple:
        raise V2IntegrityError("event envelope stream must not be empty")

    stream_id = envelope_tuple[0].event.stream_id
    expected_previous_hash: str | None = None

    for expected_sequence, envelope in enumerate(envelope_tuple):
        event = envelope.event

        if event.sequence != expected_sequence:
            raise V2IntegrityError(
                f"expected event sequence {expected_sequence}, received {event.sequence}"
            )

        if event.stream_id != stream_id:
            raise V2IntegrityError("all event envelopes must use the same stream ID")

        if envelope.previous_hash != expected_previous_hash:
            raise V2IntegrityError(f"event sequence {event.sequence} has an invalid previous hash")

        expected_hash = calculate_event_hash(event, expected_previous_hash)
        if envelope.event_hash != expected_hash:
            raise V2IntegrityError(f"event sequence {event.sequence} has an invalid event hash")

        expected_previous_hash = envelope.event_hash

    try:
        return replay_events(envelope.event for envelope in envelope_tuple)
    except V2ReplayError as exc:
        raise V2IntegrityError(f"hashed event replay failed: {exc}") from exc
