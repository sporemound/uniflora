from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from uniflora.content.v2.investigation_schema import (
    V2InvestigationActionDefinition,
    V2InvestigationPack,
)
from uniflora.engine.v2.analysis import (
    V2AnalysisInput,
    V2AnalysisJobEnvelope,
    V2AnalysisMethod,
    verify_analysis_job_envelope,
)
from uniflora.engine.v2.analysis_methods import (
    V2_CLOCK_ALIGNMENT_METHOD,
    V2_CLOCK_ALIGNMENT_OUTPUT_KIND,
    create_cross_source_clock_alignment_job,
)
from uniflora.engine.v2.analysis_persistence import (
    V2SQLiteAnalysisStore,
    V2StoredAnalysisJob,
)
from uniflora.engine.v2.application import (
    V2ApplicationCommandResult,
    V2ApplicationError,
    V2PersistentInvestigationService,
    V2SessionView,
)
from uniflora.engine.v2.commands import V2PerformActionCommand
from uniflora.engine.v2.events import V2ActionPerformedEvent
from uniflora.engine.v2.integrity import verify_event_envelopes
from uniflora.engine.v2.persistence import (
    V2OptimisticConcurrencyError,
    V2SQLiteEventStore,
)
from uniflora.engine.v2.serialization import canonical_json_bytes
from uniflora.engine.v2.state import V2InvestigationState


class V2AnalysisApplicationError(V2ApplicationError):
    """Raised when an action-bound analysis job cannot be submitted safely."""


class V2AnalysisActionBindingError(V2AnalysisApplicationError):
    """Raised when an action-to-method binding is absent or contradictory."""


class V2AnalysisActionEventError(V2AnalysisApplicationError):
    """Raised when a persisted event cannot authorize an analysis job."""


def _require_nonblank(value: str, *, label: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{label} must not be blank")
    return normalized


@dataclass(frozen=True, slots=True)
class V2AnalysisActionBinding:
    """Declare the one analysis contract authorized by an action ID."""

    action_id: str
    method: V2AnalysisMethod
    output_kind: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "action_id",
            _require_nonblank(self.action_id, label="analysis action ID"),
        )
        object.__setattr__(
            self,
            "output_kind",
            _require_nonblank(
                self.output_kind,
                label="analysis action output kind",
            ),
        )


class V2AnalysisActionRegistry:
    """Immutable lookup of investigation action IDs to analysis contracts."""

    def __init__(
        self,
        bindings: Iterable[V2AnalysisActionBinding] = (),
    ) -> None:
        normalized = tuple(sorted(bindings, key=lambda item: item.action_id))
        action_ids = tuple(item.action_id for item in normalized)
        if len(action_ids) != len(set(action_ids)):
            raise V2AnalysisActionBindingError(
                "analysis action bindings must not repeat action IDs"
            )
        self._bindings = normalized
        self._by_action_id = {item.action_id: item for item in normalized}

    def registered_bindings(self) -> tuple[V2AnalysisActionBinding, ...]:
        return self._bindings

    def resolve(self, action_id: str) -> V2AnalysisActionBinding | None:
        normalized = _require_nonblank(action_id, label="analysis action ID")
        return self._by_action_id.get(normalized)

    def require(self, action_id: str) -> V2AnalysisActionBinding:
        binding = self.resolve(action_id)
        if binding is None:
            raise V2AnalysisActionBindingError(
                f"action {action_id!r} has no registered analysis binding"
            )
        return binding


def create_missing_interior_analysis_action_registry() -> V2AnalysisActionRegistry:
    """Return the production binding for the Boundary Array timing action."""

    return V2AnalysisActionRegistry(
        (
            V2AnalysisActionBinding(
                action_id="compare_source_timing",
                method=V2_CLOCK_ALIGNMENT_METHOD,
                output_kind=V2_CLOCK_ALIGNMENT_OUTPUT_KIND,
            ),
        )
    )


def calculate_action_analysis_job_id(
    *,
    stream_id: str,
    event_sequence: int,
    action_id: str,
    method: V2AnalysisMethod,
) -> str:
    """Calculate a stable job ID from the authorizing action event."""

    normalized_stream = _require_nonblank(stream_id, label="stream ID")
    normalized_action = _require_nonblank(action_id, label="action ID")
    if event_sequence < 1:
        raise ValueError("analysis action event sequence must be at least one")

    digest = hashlib.sha256(
        canonical_json_bytes(
            {
                "action_id": normalized_action,
                "event_sequence": event_sequence,
                "method_id": method.method_id,
                "method_version": method.version,
                "stream_id": normalized_stream,
            }
        )
    ).hexdigest()
    return f"action-analysis-{digest}"


@dataclass(frozen=True, slots=True)
class V2ActionAnalysisSubmissionResult:
    application_result: V2ApplicationCommandResult
    analysis_job: V2StoredAnalysisJob | None

    def __post_init__(self) -> None:
        if not self.application_result.accepted and self.analysis_job is not None:
            raise ValueError("rejected actions cannot enqueue analysis jobs")


@dataclass(frozen=True, slots=True)
class _V2PersistedActionContext:
    event: V2ActionPerformedEvent
    state: V2InvestigationState
    action: V2InvestigationActionDefinition
    binding: V2AnalysisActionBinding


class V2PersistentAnalysisApplicationService:
    """Coordinate persisted investigation actions with queued analysis jobs.

    This boundary only validates and enqueues work. Scientific method code remains
    in the out-of-process worker introduced by Milestone 6C.
    """

    def __init__(
        self,
        pack: V2InvestigationPack,
        event_store: V2SQLiteEventStore,
        analysis_store: V2SQLiteAnalysisStore,
        action_registry: V2AnalysisActionRegistry,
    ) -> None:
        self._pack = pack
        self._event_store = event_store
        self._analysis_store = analysis_store
        self._action_registry = action_registry
        self._investigation = V2PersistentInvestigationService(
            pack,
            event_store,
        )
        self._actions = {action.id: action for action in pack.actions}

        unknown_actions = sorted(
            binding.action_id
            for binding in action_registry.registered_bindings()
            if binding.action_id not in self._actions
        )
        if unknown_actions:
            raise V2AnalysisActionBindingError(
                "analysis bindings reference unknown pack actions: " + ", ".join(unknown_actions)
            )

    @property
    def investigation_service(self) -> V2PersistentInvestigationService:
        return self._investigation

    def _require_binding(self, action_id: str) -> V2AnalysisActionBinding:
        return self._action_registry.require(action_id)

    def _validate_pack_state(self, state: V2InvestigationState) -> None:
        if state.pack_id != self._pack.pack.id:
            raise V2AnalysisActionEventError(
                f"stream belongs to pack {state.pack_id!r}, not {self._pack.pack.id!r}"
            )

    def _validate_examined_inputs(
        self,
        state: V2InvestigationState,
        inputs: tuple[V2AnalysisInput, ...],
    ) -> None:
        known_evidence = {source.id for source in self._pack.evidence_sources}
        unknown = sorted(
            {
                item.source_evidence_id
                for item in inputs
                if item.source_evidence_id not in known_evidence
            }
        )
        if unknown:
            raise V2AnalysisApplicationError(
                "analysis inputs reference unknown evidence: " + ", ".join(unknown)
            )

        unexamined = sorted(
            {
                item.source_evidence_id
                for item in inputs
                if item.source_evidence_id not in state.examined_evidence_ids
            }
        )
        if unexamined:
            raise V2AnalysisApplicationError(
                "analysis inputs must come from examined evidence: " + ", ".join(unexamined)
            )

    def _validate_job_binding(
        self,
        envelope: V2AnalysisJobEnvelope,
        *,
        binding: V2AnalysisActionBinding,
        stream_id: str,
        event_sequence: int,
        position_id: str,
        player_id: str,
        state: V2InvestigationState,
    ) -> None:
        job = verify_analysis_job_envelope(envelope)
        expected_job_id = calculate_action_analysis_job_id(
            stream_id=stream_id,
            event_sequence=event_sequence,
            action_id=binding.action_id,
            method=binding.method,
        )

        mismatches: list[str] = []
        if job.job_id != expected_job_id:
            mismatches.append("deterministic job ID")
        if job.stream_id != stream_id:
            mismatches.append("stream ID")
        if job.position_id != position_id:
            mismatches.append("position ID")
        if job.requested_by_player_id != player_id:
            mismatches.append("requesting player ID")
        if job.method != binding.method:
            mismatches.append("method contract")
        if job.output_kind != binding.output_kind:
            mismatches.append("output kind")

        if mismatches:
            raise V2AnalysisActionBindingError(
                "analysis job does not match its action binding: " + ", ".join(mismatches)
            )

        self._validate_examined_inputs(state, job.inputs)

    def _load_persisted_action_context(
        self,
        stream_id: str,
        event_sequence: int,
    ) -> _V2PersistedActionContext:
        normalized_stream = _require_nonblank(stream_id, label="stream ID")
        if event_sequence < 1:
            raise ValueError("analysis action event sequence must be at least one")

        envelopes = self._event_store.load_event_envelopes(normalized_stream)
        if not envelopes:
            raise V2AnalysisActionEventError(
                f"stream {normalized_stream!r} has no persisted event history"
            )

        full_state = verify_event_envelopes(envelopes)
        self._validate_pack_state(full_state)

        index = next(
            (
                offset
                for offset, envelope in enumerate(envelopes)
                if envelope.event.sequence == event_sequence
            ),
            None,
        )
        if index is None:
            raise V2AnalysisActionEventError(
                f"stream {normalized_stream!r} has no event at sequence {event_sequence}"
            )

        event = envelopes[index].event
        if not isinstance(event, V2ActionPerformedEvent):
            raise V2AnalysisActionEventError(
                f"event sequence {event_sequence} is not an action event"
            )

        action = self._actions.get(event.action_id)
        if action is None:
            raise V2AnalysisActionEventError(
                f"persisted action {event.action_id!r} is absent from the pack"
            )
        binding = self._require_binding(event.action_id)

        state = verify_event_envelopes(envelopes[: index + 1])
        self._validate_pack_state(state)
        return _V2PersistedActionContext(
            event=event,
            state=state,
            action=action,
            binding=binding,
        )

    def submit_job_for_action_event(
        self,
        stream_id: str,
        event_sequence: int,
        envelope: V2AnalysisJobEnvelope,
        *,
        submitted_at: datetime,
    ) -> V2StoredAnalysisJob:
        """Verify one persisted action event and idempotently enqueue its job."""

        context = self._load_persisted_action_context(
            stream_id,
            event_sequence,
        )
        self._validate_job_binding(
            envelope,
            binding=context.binding,
            stream_id=context.event.stream_id,
            event_sequence=context.event.sequence,
            position_id=context.state.current_position_id,
            player_id=context.event.player_id,
            state=context.state,
        )
        return self._analysis_store.enqueue_job(
            envelope,
            submitted_at=submitted_at,
        )

    def execute_action_with_job(
        self,
        stream_id: str,
        command: V2PerformActionCommand,
        envelope: V2AnalysisJobEnvelope,
        *,
        expected_sequence: int,
        submitted_at: datetime,
    ) -> V2ActionAnalysisSubmissionResult:
        """Persist an action, then enqueue its prevalidated deterministic job."""

        if expected_sequence < 0:
            raise ValueError("expected sequence must not be negative")

        normalized_stream = _require_nonblank(stream_id, label="stream ID")
        binding = self._require_binding(command.action_id)
        session = self._investigation.load_session(normalized_stream)
        if session.sequence != expected_sequence:
            raise V2OptimisticConcurrencyError(
                f"stream {normalized_stream!r} expected sequence "
                f"{expected_sequence}, actual sequence {session.sequence}"
            )

        event_sequence = expected_sequence + 1
        self._validate_job_binding(
            envelope,
            binding=binding,
            stream_id=normalized_stream,
            event_sequence=event_sequence,
            position_id=session.state.current_position_id,
            player_id=command.player_id,
            state=session.state,
        )

        application_result = self._investigation.execute(
            normalized_stream,
            command,
            expected_sequence=expected_sequence,
        )
        if not application_result.accepted:
            return V2ActionAnalysisSubmissionResult(
                application_result=application_result,
                analysis_job=None,
            )

        event = application_result.event
        if not isinstance(event, V2ActionPerformedEvent):
            raise V2AnalysisActionEventError(
                "an accepted action command did not persist an action event"
            )
        if event.sequence != event_sequence or event.action_id != command.action_id:
            raise V2AnalysisActionEventError(
                "persisted action event does not match the submitted command"
            )

        stored_job = self.submit_job_for_action_event(
            normalized_stream,
            event.sequence,
            envelope,
            submitted_at=submitted_at,
        )
        return V2ActionAnalysisSubmissionResult(
            application_result=application_result,
            analysis_job=stored_job,
        )

    def execute_clock_alignment_action(
        self,
        stream_id: str,
        command: V2PerformActionCommand,
        *,
        expected_sequence: int,
        inputs: tuple[V2AnalysisInput, ...],
        reference_dataset_id: str,
        submitted_at: datetime,
        minimum_shared_events: int = 2,
        tolerance_us: int | None = None,
    ) -> V2ActionAnalysisSubmissionResult:
        """Build and enqueue the registered clock-alignment job for an action."""

        binding = self._require_binding(command.action_id)
        if (
            binding.method != V2_CLOCK_ALIGNMENT_METHOD
            or binding.output_kind != V2_CLOCK_ALIGNMENT_OUTPUT_KIND
        ):
            raise V2AnalysisActionBindingError(
                f"action {command.action_id!r} is not bound to clock alignment"
            )

        session: V2SessionView = self._investigation.load_session(stream_id)
        if session.sequence != expected_sequence:
            raise V2OptimisticConcurrencyError(
                f"stream {stream_id!r} expected sequence {expected_sequence}, "
                f"actual sequence {session.sequence}"
            )

        event_sequence = expected_sequence + 1
        job_id = calculate_action_analysis_job_id(
            stream_id=stream_id,
            event_sequence=event_sequence,
            action_id=command.action_id,
            method=binding.method,
        )
        envelope = create_cross_source_clock_alignment_job(
            job_id=job_id,
            stream_id=stream_id,
            position_id=session.state.current_position_id,
            requested_by_player_id=command.player_id,
            inputs=inputs,
            reference_dataset_id=reference_dataset_id,
            minimum_shared_events=minimum_shared_events,
            tolerance_us=tolerance_us,
        )
        return self.execute_action_with_job(
            stream_id,
            command,
            envelope,
            expected_sequence=expected_sequence,
            submitted_at=submitted_at,
        )
