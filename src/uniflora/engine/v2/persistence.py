from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Self

from uniflora.engine.v2.integrity import (
    V2EventEnvelope,
    V2IntegrityError,
    calculate_event_hash,
    deserialize_event_envelope,
    serialize_event_envelope,
    verify_event_envelopes,
)
from uniflora.engine.v2.reducer import V2ReplayError, apply_event
from uniflora.engine.v2.serialization import V2SerializationError
from uniflora.engine.v2.snapshots import (
    V2SnapshotEnvelope,
    V2SnapshotError,
    deserialize_snapshot_envelope,
    serialize_snapshot_envelope,
    verify_snapshot_envelope,
)
from uniflora.engine.v2.state import V2InvestigationState


class V2PersistenceError(ValueError):
    """Raised when persisted v2 investigation data cannot be used safely."""


class V2OptimisticConcurrencyError(V2PersistenceError):
    """Raised when a stream changed after the caller last observed it."""


class V2StreamNotFoundError(V2PersistenceError):
    """Raised when a requested persisted investigation stream does not exist."""


def _require_stream_id(stream_id: str) -> str:
    normalized = stream_id.strip()

    if not normalized:
        raise ValueError("stream ID must not be blank")

    return normalized


@dataclass(frozen=True, slots=True)
class V2RestoredInvestigation:
    stream_id: str
    snapshot: V2SnapshotEnvelope | None
    tail_envelopes: tuple[V2EventEnvelope, ...]
    state: V2InvestigationState
    last_sequence: int
    last_event_hash: str

    def __post_init__(self) -> None:
        _require_stream_id(self.stream_id)

        if self.last_sequence < 0:
            raise ValueError("restored last sequence must not be negative")

        if self.state.revision != self.last_sequence:
            raise ValueError("restored state revision must match the last event sequence")

        if self.snapshot is not None:
            if self.snapshot.stream_id != self.stream_id:
                raise ValueError("restored snapshot must match the stream ID")

            if self.snapshot.sequence > self.last_sequence:
                raise ValueError("restored snapshot cannot be newer than the stream")

        if self.tail_envelopes:
            last = self.tail_envelopes[-1]

            if last.event.sequence != self.last_sequence:
                raise ValueError("restored tail must end at the reported last sequence")

            if last.event_hash != self.last_event_hash:
                raise ValueError("restored tail must end at the reported event hash")
        elif self.snapshot is None:
            raise ValueError("a restored investigation requires a snapshot or event tail")
        elif self.snapshot.last_event_hash != self.last_event_hash:
            raise ValueError("restored snapshot must match the reported event hash")


def restore_snapshot_tail(
    snapshot: V2SnapshotEnvelope | None,
    tail_envelopes: Iterable[V2EventEnvelope],
) -> V2RestoredInvestigation:
    tail = tuple(tail_envelopes)

    if snapshot is None:
        if not tail:
            raise V2PersistenceError("cannot restore an investigation without events or a snapshot")

        try:
            state = verify_event_envelopes(tail)
        except (V2IntegrityError, V2ReplayError) as exc:
            raise V2PersistenceError(f"persisted event stream is invalid: {exc}") from exc

        last = tail[-1]
        return V2RestoredInvestigation(
            stream_id=last.event.stream_id,
            snapshot=None,
            tail_envelopes=tail,
            state=state,
            last_sequence=last.event.sequence,
            last_event_hash=last.event_hash,
        )

    try:
        state = verify_snapshot_envelope(snapshot)
    except V2SnapshotError as exc:
        raise V2PersistenceError(f"persisted snapshot is invalid: {exc}") from exc

    expected_sequence = snapshot.sequence + 1
    expected_previous_hash = snapshot.last_event_hash

    for envelope in tail:
        event = envelope.event

        if event.stream_id != snapshot.stream_id:
            raise V2PersistenceError("snapshot tail contains a different stream ID")

        if event.sequence != expected_sequence:
            raise V2PersistenceError(
                f"expected snapshot-tail sequence {expected_sequence}, received {event.sequence}"
            )

        if envelope.previous_hash != expected_previous_hash:
            raise V2PersistenceError(
                f"snapshot-tail sequence {event.sequence} has an invalid previous hash"
            )

        expected_hash = calculate_event_hash(event, expected_previous_hash)
        if envelope.event_hash != expected_hash:
            raise V2PersistenceError(
                f"snapshot-tail sequence {event.sequence} has an invalid event hash"
            )

        try:
            state = apply_event(state, event)
        except V2ReplayError as exc:
            raise V2PersistenceError(f"snapshot-tail replay failed: {exc}") from exc

        expected_previous_hash = envelope.event_hash
        expected_sequence += 1

    if tail:
        last_sequence = tail[-1].event.sequence
        last_event_hash = tail[-1].event_hash
    else:
        last_sequence = snapshot.sequence
        last_event_hash = snapshot.last_event_hash

    return V2RestoredInvestigation(
        stream_id=snapshot.stream_id,
        snapshot=snapshot,
        tail_envelopes=tail,
        state=state,
        last_sequence=last_sequence,
        last_event_hash=last_event_hash,
    )


_SCHEMA = """
CREATE TABLE IF NOT EXISTS v2_event_envelopes (
    stream_id TEXT NOT NULL,
    sequence INTEGER NOT NULL CHECK (sequence >= 0),
    event_hash TEXT NOT NULL,
    previous_hash TEXT,
    envelope_json BLOB NOT NULL,
    PRIMARY KEY (stream_id, sequence),
    UNIQUE (event_hash)
);

CREATE TABLE IF NOT EXISTS v2_snapshot_envelopes (
    stream_id TEXT NOT NULL,
    sequence INTEGER NOT NULL CHECK (sequence >= 0),
    last_event_hash TEXT NOT NULL,
    snapshot_hash TEXT NOT NULL,
    snapshot_json BLOB NOT NULL,
    PRIMARY KEY (stream_id, sequence),
    UNIQUE (snapshot_hash),
    FOREIGN KEY (stream_id, sequence)
        REFERENCES v2_event_envelopes (stream_id, sequence)
        ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS ix_v2_event_envelopes_stream_sequence
    ON v2_event_envelopes (stream_id, sequence);

CREATE INDEX IF NOT EXISTS ix_v2_snapshot_envelopes_stream_sequence
    ON v2_snapshot_envelopes (stream_id, sequence);
"""


class V2SQLiteEventStore:
    def __init__(self, database: str | Path) -> None:
        self._database = str(database)
        self._connection = sqlite3.connect(
            self._database,
            isolation_level=None,
            timeout=30.0,
        )
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.execute("PRAGMA synchronous = FULL")

        if self._database != ":memory:":
            self._connection.execute("PRAGMA journal_mode = WAL")

        self._connection.executescript(_SCHEMA)

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        self._connection.close()

    @contextmanager
    def _transaction(self):
        try:
            self._connection.execute("BEGIN IMMEDIATE")
            yield
        except Exception:
            self._connection.rollback()
            raise
        else:
            self._connection.commit()

    def latest_sequence(self, stream_id: str) -> int | None:
        normalized = _require_stream_id(stream_id)
        row = self._connection.execute(
            """
            SELECT MAX(sequence) AS latest_sequence
            FROM v2_event_envelopes
            WHERE stream_id = ?
            """,
            (normalized,),
        ).fetchone()

        if row is None or row["latest_sequence"] is None:
            return None

        return int(row["latest_sequence"])

    def _latest_event_row(self, stream_id: str) -> sqlite3.Row | None:
        return self._connection.execute(
            """
            SELECT sequence, event_hash
            FROM v2_event_envelopes
            WHERE stream_id = ?
            ORDER BY sequence DESC
            LIMIT 1
            """,
            (stream_id,),
        ).fetchone()

    def append_event_envelopes(
        self,
        envelopes: Iterable[V2EventEnvelope],
        *,
        expected_sequence: int,
    ) -> tuple[V2EventEnvelope, ...]:
        recorded = tuple(envelopes)

        if not recorded:
            raise ValueError("at least one event envelope is required")

        if expected_sequence < -1:
            raise ValueError("expected sequence must be -1 or greater")

        stream_id = _require_stream_id(recorded[0].event.stream_id)

        with self._transaction():
            latest = self._latest_event_row(stream_id)
            actual_sequence = -1 if latest is None else int(latest["sequence"])
            previous_hash = None if latest is None else str(latest["event_hash"])

            if actual_sequence != expected_sequence:
                raise V2OptimisticConcurrencyError(
                    f"stream {stream_id!r} expected sequence "
                    f"{expected_sequence}, actual sequence {actual_sequence}"
                )

            next_sequence = actual_sequence + 1
            validated: list[tuple[V2EventEnvelope, bytes]] = []

            for envelope in recorded:
                event = envelope.event

                if event.stream_id != stream_id:
                    raise V2PersistenceError("an atomic append cannot mix stream IDs")

                if event.sequence != next_sequence:
                    raise V2PersistenceError(
                        f"expected appended event sequence {next_sequence}, "
                        f"received {event.sequence}"
                    )

                if envelope.previous_hash != previous_hash:
                    raise V2PersistenceError(
                        f"event sequence {event.sequence} does not continue "
                        "the persisted hash chain"
                    )

                expected_hash = calculate_event_hash(event, previous_hash)
                if envelope.event_hash != expected_hash:
                    raise V2PersistenceError(f"event sequence {event.sequence} has an invalid hash")

                validated.append((envelope, serialize_event_envelope(envelope)))
                previous_hash = envelope.event_hash
                next_sequence += 1

            try:
                self._connection.executemany(
                    """
                    INSERT INTO v2_event_envelopes (
                        stream_id,
                        sequence,
                        event_hash,
                        previous_hash,
                        envelope_json
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        (
                            envelope.event.stream_id,
                            envelope.event.sequence,
                            envelope.event_hash,
                            envelope.previous_hash,
                            serialized,
                        )
                        for envelope, serialized in validated
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise V2PersistenceError(f"event append violated SQLite integrity: {exc}") from exc

        return recorded

    def load_event_envelopes(
        self,
        stream_id: str,
        *,
        after_sequence: int = -1,
    ) -> tuple[V2EventEnvelope, ...]:
        normalized = _require_stream_id(stream_id)

        if after_sequence < -1:
            raise ValueError("after sequence must be -1 or greater")

        rows = self._connection.execute(
            """
            SELECT sequence, event_hash, previous_hash, envelope_json
            FROM v2_event_envelopes
            WHERE stream_id = ? AND sequence > ?
            ORDER BY sequence ASC
            """,
            (normalized, after_sequence),
        ).fetchall()

        envelopes: list[V2EventEnvelope] = []

        for row in rows:
            try:
                envelope = deserialize_event_envelope(row["envelope_json"])
            except (V2SerializationError, V2IntegrityError) as exc:
                raise V2PersistenceError(f"stored event envelope is invalid: {exc}") from exc

            if envelope.event.stream_id != normalized:
                raise V2PersistenceError("stored event envelope does not match its stream row")

            if envelope.event.sequence != int(row["sequence"]):
                raise V2PersistenceError("stored event sequence does not match its row")

            if envelope.event_hash != str(row["event_hash"]):
                raise V2PersistenceError("stored event hash does not match its row")

            row_previous_hash = row["previous_hash"]
            if row_previous_hash is not None:
                row_previous_hash = str(row_previous_hash)

            if envelope.previous_hash != row_previous_hash:
                raise V2PersistenceError("stored previous hash does not match its row")

            envelopes.append(envelope)

        return tuple(envelopes)

    def save_snapshot(
        self,
        snapshot: V2SnapshotEnvelope,
        *,
        expected_sequence: int,
    ) -> bool:
        if expected_sequence < 0:
            raise ValueError("snapshot expected sequence must not be negative")

        try:
            verify_snapshot_envelope(snapshot)
            serialized = serialize_snapshot_envelope(snapshot)
        except V2SnapshotError as exc:
            raise V2PersistenceError(f"cannot persist invalid snapshot: {exc}") from exc

        with self._transaction():
            latest = self._latest_event_row(snapshot.stream_id)

            if latest is None:
                raise V2StreamNotFoundError(f"stream {snapshot.stream_id!r} does not exist")

            actual_sequence = int(latest["sequence"])
            if actual_sequence != expected_sequence:
                raise V2OptimisticConcurrencyError(
                    f"stream {snapshot.stream_id!r} expected sequence "
                    f"{expected_sequence}, actual sequence {actual_sequence}"
                )

            event_row = self._connection.execute(
                """
                SELECT event_hash
                FROM v2_event_envelopes
                WHERE stream_id = ? AND sequence = ?
                """,
                (snapshot.stream_id, snapshot.sequence),
            ).fetchone()

            if event_row is None:
                raise V2PersistenceError("snapshot sequence is not present in the event store")

            if str(event_row["event_hash"]) != snapshot.last_event_hash:
                raise V2PersistenceError(
                    "snapshot last event hash does not match persisted history"
                )

            existing = self._connection.execute(
                """
                SELECT sequence, last_event_hash, snapshot_hash, snapshot_json
                FROM v2_snapshot_envelopes
                WHERE stream_id = ? AND sequence = ?
                """,
                (snapshot.stream_id, snapshot.sequence),
            ).fetchone()

            if existing is not None:
                if bytes(existing["snapshot_json"]) == serialized:
                    return False

                raise V2PersistenceError("a different snapshot already exists at this sequence")

            try:
                self._connection.execute(
                    """
                    INSERT INTO v2_snapshot_envelopes (
                        stream_id,
                        sequence,
                        last_event_hash,
                        snapshot_hash,
                        snapshot_json
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        snapshot.stream_id,
                        snapshot.sequence,
                        snapshot.last_event_hash,
                        snapshot.snapshot_hash,
                        serialized,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise V2PersistenceError(f"snapshot save violated SQLite integrity: {exc}") from exc

        return True

    def load_latest_snapshot(
        self,
        stream_id: str,
        *,
        at_or_before_sequence: int | None = None,
    ) -> V2SnapshotEnvelope | None:
        normalized = _require_stream_id(stream_id)

        if at_or_before_sequence is not None and at_or_before_sequence < 0:
            raise ValueError("snapshot sequence bound must not be negative")

        if at_or_before_sequence is None:
            row = self._connection.execute(
                """
                SELECT sequence, last_event_hash, snapshot_hash, snapshot_json
                FROM v2_snapshot_envelopes
                WHERE stream_id = ?
                ORDER BY sequence DESC
                LIMIT 1
                """,
                (normalized,),
            ).fetchone()
        else:
            row = self._connection.execute(
                """
                SELECT sequence, last_event_hash, snapshot_hash, snapshot_json
                FROM v2_snapshot_envelopes
                WHERE stream_id = ? AND sequence <= ?
                ORDER BY sequence DESC
                LIMIT 1
                """,
                (normalized, at_or_before_sequence),
            ).fetchone()

        if row is None:
            return None

        try:
            snapshot = deserialize_snapshot_envelope(row["snapshot_json"])
        except (V2SerializationError, V2SnapshotError) as exc:
            raise V2PersistenceError(f"stored snapshot envelope is invalid: {exc}") from exc

        if snapshot.stream_id != normalized:
            raise V2PersistenceError("stored snapshot does not match its stream row")

        if snapshot.sequence != int(row["sequence"]):
            raise V2PersistenceError("stored snapshot sequence does not match its row")

        if snapshot.last_event_hash != str(row["last_event_hash"]):
            raise V2PersistenceError("stored snapshot event hash does not match its row")

        if snapshot.snapshot_hash != str(row["snapshot_hash"]):
            raise V2PersistenceError("stored snapshot hash does not match its row")

        return snapshot

    def restore(self, stream_id: str) -> V2RestoredInvestigation:
        normalized = _require_stream_id(stream_id)
        latest = self.latest_sequence(normalized)

        if latest is None:
            raise V2StreamNotFoundError(f"stream {normalized!r} does not exist")

        snapshot = self.load_latest_snapshot(
            normalized,
            at_or_before_sequence=latest,
        )
        after_sequence = -1 if snapshot is None else snapshot.sequence
        tail = self.load_event_envelopes(
            normalized,
            after_sequence=after_sequence,
        )
        restored = restore_snapshot_tail(snapshot, tail)

        if restored.last_sequence != latest:
            raise V2PersistenceError("restored stream does not reach the latest persisted event")

        return restored
