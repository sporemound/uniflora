from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from uniflora.content.v2.investigation_schema import V2InvestigationPack
from uniflora.engine.v2.commands import V2InvestigationCommand
from uniflora.engine.v2.event_stream import (
    V2InvestigationStream,
    execute_command as execute_in_memory_command,
    initialize_event_stream,
)
from uniflora.engine.v2.events import V2InvestigationEvent
from uniflora.engine.v2.integrity import (
    V2EventEnvelope,
    create_event_envelope,
    seal_event_stream,
    verify_event_envelopes,
)
from uniflora.engine.v2.persistence import (
    V2OptimisticConcurrencyError,
    V2RestoredInvestigation,
    V2SQLiteEventStore,
)
from uniflora.engine.v2.snapshots import (
    V2SnapshotEnvelope,
    create_snapshot_envelope,
)
from uniflora.engine.v2.state import V2InvestigationState
from uniflora.engine.v2.stochastic import V2RandomSource, V2SecretsRandomSource


class V2ApplicationError(ValueError):
    """Raised when the persistent application boundary cannot proceed safely."""


class V2SessionAlreadyExistsError(V2ApplicationError):
    """Raised when an investigation stream already uses a requested ID."""


def _require_nonblank(value: str, *, label: str) -> str:
    normalized = value.strip()

    if not normalized:
        raise ValueError(f"{label} must not be blank")

    return normalized


@dataclass(frozen=True, slots=True)
class V2SessionView:
    stream_id: str
    state: V2InvestigationState
    sequence: int
    last_event_hash: str

    def __post_init__(self) -> None:
        _require_nonblank(self.stream_id, label="stream ID")

        if self.sequence < 0:
            raise ValueError("session sequence must not be negative")

        if self.state.revision != self.sequence:
            raise ValueError("session state revision must match its persisted sequence")

        _require_nonblank(self.last_event_hash, label="last event hash")


@dataclass(frozen=True, slots=True)
class V2ApplicationCommandResult:
    accepted: bool
    code: str
    message: str
    session: V2SessionView
    event: V2InvestigationEvent | None


class V2PersistentInvestigationService:
    """Transport-neutral application service for one investigation pack."""

    def __init__(
        self,
        pack: V2InvestigationPack,
        store: V2SQLiteEventStore,
        *,
        random_source: V2RandomSource | None = None,
    ) -> None:
        self._pack = pack
        self._store = store
        self._random_source = random_source or V2SecretsRandomSource()

    @property
    def pack(self) -> V2InvestigationPack:
        return self._pack

    def _validate_pack_state(self, state: V2InvestigationState) -> None:
        if state.pack_id != self._pack.pack.id:
            raise V2ApplicationError(
                f"stream belongs to pack {state.pack_id!r}, not {self._pack.pack.id!r}"
            )

    def _view_from_restored(
        self,
        restored: V2RestoredInvestigation,
    ) -> V2SessionView:
        self._validate_pack_state(restored.state)

        return V2SessionView(
            stream_id=restored.stream_id,
            state=restored.state,
            sequence=restored.last_sequence,
            last_event_hash=restored.last_event_hash,
        )

    def _load_verified_history(
        self,
        stream_id: str,
        restored: V2RestoredInvestigation,
    ) -> tuple[V2EventEnvelope, ...]:
        envelopes = self._store.load_event_envelopes(stream_id)

        if not envelopes:
            raise V2ApplicationError(f"stream {stream_id!r} has no persisted event history")

        replayed_state = verify_event_envelopes(envelopes)

        if replayed_state != restored.state:
            raise V2ApplicationError("full event replay does not match snapshot-tail restoration")

        if envelopes[-1].event.sequence != restored.last_sequence:
            raise V2ApplicationError("full event history does not reach the restored sequence")

        if envelopes[-1].event_hash != restored.last_event_hash:
            raise V2ApplicationError("full event history does not reach the restored hash")

        return envelopes

    def create_session(
        self,
        stream_id: str,
        player_ids: Iterable[str],
    ) -> V2ApplicationCommandResult:
        normalized_stream_id = _require_nonblank(
            stream_id,
            label="stream ID",
        )

        if self._store.latest_sequence(normalized_stream_id) is not None:
            raise V2SessionAlreadyExistsError(f"stream {normalized_stream_id!r} already exists")

        stream = initialize_event_stream(
            self._pack,
            player_ids,
            stream_id=normalized_stream_id,
        )
        envelopes = seal_event_stream(stream)
        self._store.append_event_envelopes(
            envelopes,
            expected_sequence=-1,
        )

        envelope = envelopes[-1]
        return V2ApplicationCommandResult(
            accepted=True,
            code="session_created",
            message=(f"Investigation stream {normalized_stream_id!r} was created."),
            session=V2SessionView(
                stream_id=normalized_stream_id,
                state=stream.state,
                sequence=envelope.event.sequence,
                last_event_hash=envelope.event_hash,
            ),
            event=envelope.event,
        )

    def load_session(self, stream_id: str) -> V2SessionView:
        normalized_stream_id = _require_nonblank(
            stream_id,
            label="stream ID",
        )
        restored = self._store.restore(normalized_stream_id)
        return self._view_from_restored(restored)

    def execute(
        self,
        stream_id: str,
        command: V2InvestigationCommand,
        *,
        expected_sequence: int,
    ) -> V2ApplicationCommandResult:
        normalized_stream_id = _require_nonblank(
            stream_id,
            label="stream ID",
        )

        if expected_sequence < 0:
            raise ValueError("expected sequence must not be negative")

        restored = self._store.restore(normalized_stream_id)
        current_view = self._view_from_restored(restored)

        if restored.last_sequence != expected_sequence:
            raise V2OptimisticConcurrencyError(
                f"stream {normalized_stream_id!r} expected sequence "
                f"{expected_sequence}, actual sequence "
                f"{restored.last_sequence}"
            )

        envelopes = self._load_verified_history(
            normalized_stream_id,
            restored,
        )
        stream = V2InvestigationStream(
            stream_id=normalized_stream_id,
            events=tuple(envelope.event for envelope in envelopes),
            state=restored.state,
        )
        result = execute_in_memory_command(
            self._pack,
            stream,
            command,
            random_source=self._random_source,
        )

        if not result.accepted:
            return V2ApplicationCommandResult(
                accepted=False,
                code=result.code,
                message=result.message,
                session=current_view,
                event=None,
            )

        if result.event is None:
            if result.stream.state != restored.state:
                raise V2ApplicationError(
                    "an eventless accepted command changed persistent state"
                )
            return V2ApplicationCommandResult(
                accepted=True,
                code=result.code,
                message=result.message,
                session=current_view,
                event=None,
            )

        envelope = create_event_envelope(
            result.event,
            previous_hash=restored.last_event_hash,
        )
        self._store.append_event_envelopes(
            (envelope,),
            expected_sequence=expected_sequence,
        )

        return V2ApplicationCommandResult(
            accepted=True,
            code=result.code,
            message=result.message,
            session=V2SessionView(
                stream_id=normalized_stream_id,
                state=result.stream.state,
                sequence=envelope.event.sequence,
                last_event_hash=envelope.event_hash,
            ),
            event=result.event,
        )

    def save_snapshot(
        self,
        stream_id: str,
        *,
        expected_sequence: int,
    ) -> V2SnapshotEnvelope:
        normalized_stream_id = _require_nonblank(
            stream_id,
            label="stream ID",
        )

        if expected_sequence < 0:
            raise ValueError("expected sequence must not be negative")

        restored = self._store.restore(normalized_stream_id)
        self._validate_pack_state(restored.state)

        if restored.last_sequence != expected_sequence:
            raise V2OptimisticConcurrencyError(
                f"stream {normalized_stream_id!r} expected sequence "
                f"{expected_sequence}, actual sequence "
                f"{restored.last_sequence}"
            )

        envelopes = self._load_verified_history(
            normalized_stream_id,
            restored,
        )
        snapshot = create_snapshot_envelope(envelopes)
        self._store.save_snapshot(
            snapshot,
            expected_sequence=expected_sequence,
        )
        return snapshot
