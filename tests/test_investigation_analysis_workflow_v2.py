from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from uniflora.content.v2 import V2InvestigationPack, load_missing_interior_pack
from uniflora.engine.v2 import (
    V2BeginInvestigationCommand,
    V2AnalysisJobStatus,
    V2AnalysisMethodRegistry,
    V2AnalysisWorkerOutcomeStatus,
    V2AssignRoleCommand,
    V2ExamineEvidenceCommand,
    V2LocalAnalysisDatasetRepository,
    V2PerformActionCommand,
    V2ReleaseRoleCommand,
    V2SQLiteAnalysisStore,
    V2SQLiteEventStore,
    calculate_action_analysis_job_id,
    calculate_worker_artifact_id,
    create_analysis_workflow,
    create_missing_interior_analysis_action_registry,
    create_missing_interior_analysis_workflow,
    serialize_clock_observation_dataset,
    V2ClockObservation,
    V2ClockObservationDataset,
    V2_CLOCK_ALIGNMENT_METHOD,
    V2_CLOCK_OBSERVATION_MEDIA_TYPE,
)

BASE_TIME = datetime(2026, 7, 25, 18, 0, tzinfo=UTC)
STREAM_ID = "workflow-session"
PLAYER_ID = "player_a"
ACTION_ID = "compare_source_timing"


def _clock(*values: datetime):
    timestamps = iter(values)
    return lambda: next(timestamps)


def _datasets(
    root: Path,
) -> tuple[V2LocalAnalysisDatasetRepository, tuple]:
    repository = V2LocalAnalysisDatasetRepository(root)
    optical = serialize_clock_observation_dataset(
        V2ClockObservationDataset(
            clock_id="optical-clock",
            observations=(
                V2ClockObservation("event-a", 1_000_000, 40),
                V2ClockObservation("event-b", 2_000_000, 40),
                V2ClockObservation("event-c", 3_000_000, 50),
            ),
        )
    )
    radio = serialize_clock_observation_dataset(
        V2ClockObservationDataset(
            clock_id="radio-clock",
            observations=(
                V2ClockObservation("event-a", 999_750, 60),
                V2ClockObservation("event-b", 1_999_750, 60),
                V2ClockObservation("event-c", 2_999_750, 70),
            ),
        )
    )
    stored = (
        repository.import_bytes(
            optical,
            dataset_id="boundary-optical-clock",
            source_evidence_id="optical_record",
            media_type=V2_CLOCK_OBSERVATION_MEDIA_TYPE,
            provenance="Retained Boundary Array optical event export.",
            preprocessing_steps=("Matched stable event identifiers.",),
        ),
        repository.import_bytes(
            radio,
            dataset_id="boundary-radio-clock",
            source_evidence_id="radio_return",
            media_type=V2_CLOCK_OBSERVATION_MEDIA_TYPE,
            provenance="Retained Boundary Array radio event export.",
            preprocessing_steps=("Matched stable event identifiers.",),
        ),
    )
    return repository, tuple(item.descriptor for item in stored)


def _execute(service, sequence: int, command):
    result = service.execute(
        STREAM_ID,
        command,
        expected_sequence=sequence,
    )
    assert result.accepted is True, (result.code, result.message)
    return result.session.sequence


def _prepare_compare_action(workflow) -> int:
    service = workflow.analysis_application.investigation_service
    service.create_session(STREAM_ID, [PLAYER_ID])
    sequence = 0

    for command in (
        V2BeginInvestigationCommand(PLAYER_ID),
        V2AssignRoleCommand(PLAYER_ID, "field_observer"),
        V2ExamineEvidenceCommand(PLAYER_ID, "optical_record"),
        V2PerformActionCommand(PLAYER_ID, "inspect_optical_record"),
        V2ReleaseRoleCommand(PLAYER_ID),
        V2AssignRoleCommand(PLAYER_ID, "instrument_operator"),
        V2ExamineEvidenceCommand(PLAYER_ID, "radio_return"),
        V2PerformActionCommand(PLAYER_ID, "calibrate_radio_receiver"),
        V2ExamineEvidenceCommand(PLAYER_ID, "receiver_diagnostic"),
        V2ReleaseRoleCommand(PLAYER_ID),
        V2AssignRoleCommand(PLAYER_ID, "atmospheric_analyst"),
        V2PerformActionCommand(PLAYER_ID, "request_weather_record"),
        V2ExamineEvidenceCommand(PLAYER_ID, "weather_record"),
        V2ReleaseRoleCommand(PLAYER_ID),
        V2AssignRoleCommand(PLAYER_ID, "signal_correlator"),
    ):
        sequence = _execute(service, sequence, command)
    return sequence


def _submit(workflow, sequence: int, inputs: tuple):
    return workflow.execute_clock_alignment_action(
        STREAM_ID,
        V2PerformActionCommand(PLAYER_ID, ACTION_ID),
        expected_sequence=sequence,
        inputs=inputs,
        reference_dataset_id="boundary-optical-clock",
        tolerance_us=100,
        submitted_at=BASE_TIME,
    )


def test_end_to_end_workflow_survives_retries_reopen_and_repeated_reads(
    tmp_path: Path,
) -> None:
    pack = load_missing_interior_pack()
    repository, inputs = _datasets(tmp_path / "datasets")
    event_database = tmp_path / "events.sqlite3"
    analysis_database = tmp_path / "analysis.sqlite3"

    with (
        V2SQLiteEventStore(event_database) as events,
        V2SQLiteAnalysisStore(analysis_database) as application_analyses,
        V2SQLiteAnalysisStore(analysis_database) as worker_analyses,
    ):
        workflow = create_missing_interior_analysis_workflow(
            pack,
            events,
            application_analyses,
            repository,
            worker_id="external-worker-secret",
            lease_duration=timedelta(minutes=5),
            worker_analysis_store=worker_analyses,
            clock=_clock(
                BASE_TIME + timedelta(minutes=3),
                BASE_TIME + timedelta(minutes=4),
                BASE_TIME + timedelta(minutes=5),
            ),
        )
        sequence = _prepare_compare_action(workflow)
        submission = _submit(workflow, sequence, inputs)

        assert submission.application_result.accepted is True
        assert submission.analysis_job is not None
        job = submission.analysis_job
        expected_job_id = calculate_action_analysis_job_id(
            stream_id=STREAM_ID,
            event_sequence=sequence + 1,
            action_id=ACTION_ID,
            method=V2_CLOCK_ALIGNMENT_METHOD,
        )
        assert job.job_id == expected_job_id
        assert job.status is V2AnalysisJobStatus.QUEUED
        assert application_analyses.list_jobs() == (job,)
        assert application_analyses.get_artifact_for_job(job.job_id) is None

        queued = workflow.transport_facade.execute(
            STREAM_ID,
            player_id=PLAYER_ID,
            text=f"analysis-status {job.job_id}",
            expected_sequence=999,
        )
        assert queued.route == "analysis"
        assert queued.code == "analysis_queued"

        claimed = worker_analyses.claim_next_job(
            worker_id="manual-worker-secret",
            claimed_at=BASE_TIME + timedelta(minutes=1),
            lease_duration=timedelta(minutes=5),
        )
        assert claimed is not None
        assert claimed.lease_token is not None
        processing = workflow.transport_facade.execute(
            STREAM_ID,
            player_id=PLAYER_ID,
            text=f"analysis-status {job.job_id}",
            expected_sequence=999,
        )
        assert processing.code == "analysis_processing"
        processing_text = processing.to_text()
        assert "manual-worker-secret" not in processing_text
        assert claimed.lease_token not in processing_text

        retried = worker_analyses.fail_job(
            job.job_id,
            worker_id="manual-worker-secret",
            lease_token=claimed.lease_token,
            failed_at=BASE_TIME + timedelta(minutes=2),
            error="retained dataset mount was temporarily unavailable",
            retryable=True,
        )
        assert retried.status is V2AnalysisJobStatus.QUEUED
        assert retried.attempt_count == 1
        retry_status = workflow.transport_facade.execute(
            STREAM_ID,
            player_id=PLAYER_ID,
            text=f"analysis-status {job.job_id}",
            expected_sequence=999,
        )
        assert retry_status.code == "analysis_queued"
        assert "temporarily unavailable" in retry_status.to_text()

        outcome = workflow.run_worker_once()
        assert outcome.status is V2AnalysisWorkerOutcomeStatus.COMPLETED
        assert outcome.job_id == job.job_id
        assert outcome.attempt_count == 2
        assert outcome.artifact_id == calculate_worker_artifact_id(job.envelope)

        completed = workflow.transport_facade.execute(
            STREAM_ID,
            player_id=PLAYER_ID,
            text=f"analysis-status {job.job_id}",
            expected_sequence=999,
        )
        artifact = workflow.transport_facade.execute(
            STREAM_ID,
            player_id=PLAYER_ID,
            text=f"analysis-artifact-for-job {job.job_id}",
            expected_sequence=999,
        )
        assert completed.code == "analysis_completed"
        assert completed.artifact_id == outcome.artifact_id
        assert artifact.code == "analysis_artifact"
        assert artifact.artifact_id == outcome.artifact_id

        artifact_view = workflow.analysis_presentation.get_artifact_for_job(job.job_id)
        assert artifact_view is not None
        assert artifact_view.artifact_id == calculate_worker_artifact_id(job.envelope)
        assert artifact_view.artifact_hash == application_analyses.get_artifact(
            artifact_view.artifact_id
        ).artifact_hash
        assert {item.name for item in artifact_view.derived_values} >= {
            "alignment_offsets",
            "all_sources_within_tolerance",
        }
        assert artifact_view.uncertainties
        assert artifact_view.limitations
        assert {item.name for item in artifact_view.software_versions} == {
            "python",
            "uniflora-clock-alignment",
        }
        assert any("optical_record" in item for item in artifact_view.provenance)
        assert any("radio_return" in item for item in artifact_view.provenance)

        repeated_status_text = workflow.transport_facade.execute(
            STREAM_ID,
            player_id=PLAYER_ID,
            text=f"analysis-status {job.job_id}",
            expected_sequence=0,
        ).to_text()
        repeated_artifact_text = workflow.transport_facade.execute(
            STREAM_ID,
            player_id=PLAYER_ID,
            text=f"analysis-artifact-for-job {job.job_id}",
            expected_sequence=0,
        ).to_text()
        assert workflow.run_worker_once().status is V2AnalysisWorkerOutcomeStatus.IDLE
        assert len(application_analyses.list_jobs()) == 1

    with (
        V2SQLiteEventStore(event_database) as reopened_events,
        V2SQLiteAnalysisStore(analysis_database) as reopened_analyses,
    ):
        reopened = create_missing_interior_analysis_workflow(
            pack,
            reopened_events,
            reopened_analyses,
            repository,
            worker_id="reopened-worker",
            lease_duration=timedelta(minutes=5),
        )
        assert reopened.analysis_application.investigation_service.load_session(
            STREAM_ID
        ).sequence == sequence + 1
        assert reopened.transport_facade.execute(
            STREAM_ID,
            player_id=PLAYER_ID,
            text=f"analysis-status {job.job_id}",
            expected_sequence=0,
        ).to_text() == repeated_status_text
        assert reopened.transport_facade.execute(
            STREAM_ID,
            player_id=PLAYER_ID,
            text=f"analysis-artifact-for-job {job.job_id}",
            expected_sequence=0,
        ).to_text() == repeated_artifact_text
        assert len(reopened_analyses.list_jobs()) == 1


def test_rejected_action_never_enqueues_analysis(tmp_path: Path) -> None:
    pack = load_missing_interior_pack()
    repository, inputs = _datasets(tmp_path / "datasets")
    with (
        V2SQLiteEventStore(tmp_path / "events.sqlite3") as events,
        V2SQLiteAnalysisStore(tmp_path / "analysis.sqlite3") as analyses,
    ):
        workflow = create_missing_interior_analysis_workflow(
            pack,
            events,
            analyses,
            repository,
            worker_id="worker",
            lease_duration=timedelta(minutes=5),
        )
        service = workflow.analysis_application.investigation_service
        service.create_session(STREAM_ID, [PLAYER_ID])
        sequence = _execute(
            service,
            0,
            V2ExamineEvidenceCommand(PLAYER_ID, "optical_record"),
        )
        sequence = _execute(
            service,
            0,
            V2BeginInvestigationCommand(PLAYER_ID),
        )
        sequence = _execute(
            service,
            sequence,
            V2ExamineEvidenceCommand(PLAYER_ID, "optical_record"),
        )

        result = _submit(workflow, sequence, inputs)

        assert result.application_result.accepted is False
        assert result.analysis_job is None
        assert analyses.list_jobs() == ()
        assert events.latest_sequence(STREAM_ID) == sequence


def test_event_before_job_recovery_is_idempotent_and_replay_safe(
    tmp_path: Path,
) -> None:
    pack = load_missing_interior_pack()
    repository, inputs = _datasets(tmp_path / "datasets")
    with (
        V2SQLiteEventStore(tmp_path / "events.sqlite3") as events,
        V2SQLiteAnalysisStore(tmp_path / "analysis.sqlite3") as analyses,
    ):
        workflow = create_missing_interior_analysis_workflow(
            pack,
            events,
            analyses,
            repository,
            worker_id="worker",
            lease_duration=timedelta(minutes=5),
        )
        sequence = _prepare_compare_action(workflow)
        action = workflow.analysis_application.investigation_service.execute(
            STREAM_ID,
            V2PerformActionCommand(PLAYER_ID, ACTION_ID),
            expected_sequence=sequence,
        )
        assert action.accepted is True
        assert action.event is not None
        assert analyses.list_jobs() == ()

        first = workflow.submit_clock_alignment_job_for_action_event(
            STREAM_ID,
            action.event.sequence,
            inputs=inputs,
            reference_dataset_id="boundary-optical-clock",
            tolerance_us=100,
            submitted_at=BASE_TIME,
        )
        repeated = workflow.submit_clock_alignment_job_for_action_event(
            STREAM_ID,
            action.event.sequence,
            inputs=inputs,
            reference_dataset_id="boundary-optical-clock",
            tolerance_us=100,
            submitted_at=BASE_TIME + timedelta(hours=1),
        )

        assert repeated == first
        assert analyses.list_jobs() == (first,)
        assert workflow.analysis_application.investigation_service.load_session(
            STREAM_ID
        ).sequence == action.event.sequence
        assert workflow.analysis_application.investigation_service.load_session(
            STREAM_ID
        ).sequence == action.event.sequence
        assert analyses.list_jobs() == (first,)


def test_terminal_worker_failure_is_visible_without_transport_secrets(
    tmp_path: Path,
) -> None:
    pack: V2InvestigationPack = load_missing_interior_pack()
    repository, inputs = _datasets(tmp_path / "datasets")
    with (
        V2SQLiteEventStore(tmp_path / "events.sqlite3") as events,
        V2SQLiteAnalysisStore(tmp_path / "analysis.sqlite3") as application_analyses,
        V2SQLiteAnalysisStore(tmp_path / "analysis.sqlite3") as worker_analyses,
    ):
        workflow = create_analysis_workflow(
            pack,
            events,
            application_analyses,
            repository,
            action_registry=create_missing_interior_analysis_action_registry(),
            method_registry=V2AnalysisMethodRegistry(),
            worker_id="terminal-worker-secret",
            lease_duration=timedelta(minutes=5),
            worker_analysis_store=worker_analyses,
            clock=_clock(
                BASE_TIME + timedelta(minutes=1),
                BASE_TIME + timedelta(minutes=2),
            ),
        )
        sequence = _prepare_compare_action(workflow)
        submission = _submit(workflow, sequence, inputs)
        assert submission.analysis_job is not None

        outcome = workflow.run_worker_once()
        assert outcome.status is V2AnalysisWorkerOutcomeStatus.FAILED
        assert outcome.error is not None
        assert "not registered" in outcome.error

        response = workflow.transport_facade.execute(
            STREAM_ID,
            player_id=PLAYER_ID,
            text=f"analysis-status {submission.analysis_job.job_id}",
            expected_sequence=0,
        )
        assert response.code == "analysis_failed"
        assert "not registered" in response.to_text()
        assert "terminal-worker-secret" not in response.to_text()
        assert application_analyses.get_job(
            submission.analysis_job.job_id
        ).status is V2AnalysisJobStatus.FAILED
