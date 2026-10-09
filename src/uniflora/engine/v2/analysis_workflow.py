from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from uniflora.content.v2.investigation_schema import V2InvestigationPack
from uniflora.engine.v2.analysis import (
    V2AnalysisInput,
    V2AnalysisJobEnvelope,
)
from uniflora.engine.v2.analysis_application import (
    V2ActionAnalysisSubmissionResult,
    V2AnalysisActionEventError,
    V2AnalysisActionRegistry,
    V2PersistentAnalysisApplicationService,
    calculate_action_analysis_job_id,
    create_missing_interior_analysis_action_registry,
)
from uniflora.engine.v2.analysis_methods import (
    V2_CLOCK_ALIGNMENT_METHOD,
    create_cross_source_clock_alignment_job,
    create_registry as create_analysis_method_registry,
)
from uniflora.engine.v2.analysis_persistence import (
    V2SQLiteAnalysisStore,
    V2StoredAnalysisJob,
)
from uniflora.engine.v2.analysis_presentation import V2AnalysisPresentationService
from uniflora.engine.v2.analysis_transport import V2AnalysisTextCommandAdapter
from uniflora.engine.v2.analysis_worker import (
    V2AnalysisDatasetResolver,
    V2AnalysisMethodRegistry,
    V2AnalysisWorker,
    V2AnalysisWorkerOutcome,
)
from uniflora.engine.v2.commands import V2PerformActionCommand
from uniflora.engine.v2.events import V2ActionPerformedEvent
from uniflora.engine.v2.integrity import verify_event_envelopes
from uniflora.engine.v2.persistence import V2SQLiteEventStore
from uniflora.engine.v2.transport import V2TextCommandAdapter
from uniflora.engine.v2.transport_facade import V2TransportFacade


@dataclass(frozen=True, slots=True)
class V2AnalysisWorkflow:
    """Compose the persistent v2 analysis path without owning its resources.

    The interactive application and unified transport can submit and read work,
    but they never claim jobs. ``analysis_worker`` remains a separately invoked
    boundary and may use a distinct SQLite connection to the same database.
    """

    analysis_application: V2PersistentAnalysisApplicationService
    dataset_resolver: V2AnalysisDatasetResolver
    analysis_presentation: V2AnalysisPresentationService
    analysis_worker: V2AnalysisWorker
    transport_facade: V2TransportFacade
    _event_store: V2SQLiteEventStore = field(repr=False)

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
        """Persist one accepted action and enqueue its deterministic job."""

        return self.analysis_application.execute_clock_alignment_action(
            stream_id,
            command,
            expected_sequence=expected_sequence,
            inputs=inputs,
            reference_dataset_id=reference_dataset_id,
            submitted_at=submitted_at,
            minimum_shared_events=minimum_shared_events,
            tolerance_us=tolerance_us,
        )

    def submit_clock_alignment_job_for_action_event(
        self,
        stream_id: str,
        event_sequence: int,
        *,
        inputs: tuple[V2AnalysisInput, ...],
        reference_dataset_id: str,
        submitted_at: datetime,
        minimum_shared_events: int = 2,
        tolerance_us: int | None = None,
    ) -> V2StoredAnalysisJob:
        """Recover idempotently when an action event persisted before its job.

        The persisted event supplies the player, action, position, and stable job
        identity. The application service revalidates the action binding and all
        input evidence before enqueueing.
        """

        envelopes = self._event_store.load_event_envelopes(stream_id)
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
                f"stream {stream_id!r} has no event at sequence {event_sequence}"
            )

        event = envelopes[index].event
        if not isinstance(event, V2ActionPerformedEvent):
            raise V2AnalysisActionEventError(
                f"event sequence {event_sequence} is not an action event"
            )

        state = verify_event_envelopes(envelopes[: index + 1])
        job_id = calculate_action_analysis_job_id(
            stream_id=event.stream_id,
            event_sequence=event.sequence,
            action_id=event.action_id,
            method=V2_CLOCK_ALIGNMENT_METHOD,
        )
        envelope: V2AnalysisJobEnvelope = create_cross_source_clock_alignment_job(
            job_id=job_id,
            stream_id=event.stream_id,
            position_id=state.current_position_id,
            requested_by_player_id=event.player_id,
            inputs=inputs,
            reference_dataset_id=reference_dataset_id,
            minimum_shared_events=minimum_shared_events,
            tolerance_us=tolerance_us,
        )
        return self.analysis_application.submit_job_for_action_event(
            event.stream_id,
            event.sequence,
            envelope,
            submitted_at=submitted_at,
        )

    def run_worker_once(self) -> V2AnalysisWorkerOutcome:
        """Invoke the external-worker boundary for at most one queued job."""

        return self.analysis_worker.run_once()


def create_analysis_workflow(
    pack: V2InvestigationPack,
    event_store: V2SQLiteEventStore,
    analysis_store: V2SQLiteAnalysisStore,
    dataset_resolver: V2AnalysisDatasetResolver,
    *,
    action_registry: V2AnalysisActionRegistry,
    method_registry: V2AnalysisMethodRegistry,
    worker_id: str,
    lease_duration: timedelta,
    worker_analysis_store: V2SQLiteAnalysisStore | None = None,
    clock: Callable[[], datetime] | None = None,
    artifact_id_factory: Callable[[V2AnalysisJobEnvelope], str] | None = None,
) -> V2AnalysisWorkflow:
    """Create one transport-neutral composition of the complete analysis path.

    Resource ownership stays with the caller. Supplying ``worker_analysis_store``
    allows the worker to use a separate database connection, matching the
    out-of-process production boundary while retaining one persistent job store.
    """

    application = V2PersistentAnalysisApplicationService(
        pack,
        event_store,
        analysis_store,
        action_registry,
    )
    presentation = V2AnalysisPresentationService(analysis_store)
    worker = V2AnalysisWorker(
        store=(analysis_store if worker_analysis_store is None else worker_analysis_store),
        registry=method_registry,
        dataset_resolver=dataset_resolver,
        worker_id=worker_id,
        lease_duration=lease_duration,
        clock=clock,
        artifact_id_factory=artifact_id_factory,
    )
    transport = V2TransportFacade(
        V2TextCommandAdapter(application.investigation_service),
        V2AnalysisTextCommandAdapter(presentation),
    )
    return V2AnalysisWorkflow(
        analysis_application=application,
        dataset_resolver=dataset_resolver,
        analysis_presentation=presentation,
        analysis_worker=worker,
        transport_facade=transport,
        _event_store=event_store,
    )


def create_missing_interior_analysis_workflow(
    pack: V2InvestigationPack,
    event_store: V2SQLiteEventStore,
    analysis_store: V2SQLiteAnalysisStore,
    dataset_resolver: V2AnalysisDatasetResolver,
    *,
    worker_id: str,
    lease_duration: timedelta,
    worker_analysis_store: V2SQLiteAnalysisStore | None = None,
    clock: Callable[[], datetime] | None = None,
    artifact_id_factory: Callable[[V2AnalysisJobEnvelope], str] | None = None,
) -> V2AnalysisWorkflow:
    """Compose the production Missing Interior action and method registries."""

    return create_analysis_workflow(
        pack,
        event_store,
        analysis_store,
        dataset_resolver,
        action_registry=create_missing_interior_analysis_action_registry(),
        method_registry=create_analysis_method_registry(),
        worker_id=worker_id,
        lease_duration=lease_duration,
        worker_analysis_store=worker_analysis_store,
        clock=clock,
        artifact_id_factory=artifact_id_factory,
    )
