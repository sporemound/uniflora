from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from uniflora.content.v2 import V2InvestigationPack, load_investigation_pack
from uniflora.engine.v2 import (
    V2_CLOCK_ALIGNMENT_METHOD,
    V2_CLOCK_ALIGNMENT_OUTPUT_KIND,
    V2_CLOCK_OBSERVATION_MEDIA_TYPE,
    V2ActionAnalysisSubmissionResult,
    V2AnalysisActionBinding,
    V2AnalysisActionBindingError,
    V2AnalysisActionEventError,
    V2AnalysisActionRegistry,
    V2AnalysisApplicationError,
    V2AnalysisInput,
    V2AnalysisJobStatus,
    V2AnalysisMethod,
    V2ExamineEvidenceCommand,
    V2OptimisticConcurrencyError,
    V2PerformActionCommand,
    V2PersistentAnalysisApplicationService,
    V2SQLiteAnalysisStore,
    V2SQLiteEventStore,
    calculate_action_analysis_job_id,
    calculate_dataset_hash,
    create_analysis_job_envelope,
    create_cross_source_clock_alignment_job,
    create_missing_interior_analysis_action_registry,
)

FIXTURE_PATH = (
    Path(__file__).parent / "fixtures" / "v2" / "boundary_array_investigation" / "pack.yaml"
)
PRODUCTION_PACK_PATH = (
    Path(__file__).parents[1]
    / "src"
    / "uniflora"
    / "content"
    / "v2"
    / "packs"
    / "missing_interior"
    / "pack.yaml"
)
BASE_TIME = datetime(2026, 7, 25, 22, 0, tzinfo=UTC)
ACTION_ID = "compare_optical_radio_timing"


@pytest.fixture
def pack() -> V2InvestigationPack:
    return load_investigation_pack(FIXTURE_PATH)


def _registry(
    *,
    method: V2AnalysisMethod = V2_CLOCK_ALIGNMENT_METHOD,
    output_kind: str = V2_CLOCK_ALIGNMENT_OUTPUT_KIND,
) -> V2AnalysisActionRegistry:
    return V2AnalysisActionRegistry(
        (
            V2AnalysisActionBinding(
                action_id=ACTION_ID,
                method=method,
                output_kind=output_kind,
            ),
        )
    )


def _inputs(
    *,
    optical_source: str = "optical_record",
    radio_source: str = "radio_return",
) -> tuple[V2AnalysisInput, ...]:
    records = (
        (
            "boundary_optical",
            optical_source,
            b'{"clock_id":"optical","observations":[]}',
        ),
        (
            "boundary_radio",
            radio_source,
            b'{"clock_id":"radio","observations":[]}',
        ),
    )
    return tuple(
        V2AnalysisInput(
            dataset_id=dataset_id,
            source_evidence_id=source_evidence_id,
            content_hash=calculate_dataset_hash(payload),
            byte_length=len(payload),
            media_type=V2_CLOCK_OBSERVATION_MEDIA_TYPE,
            provenance=f"Retained export for {source_evidence_id}.",
        )
        for dataset_id, source_evidence_id, payload in records
    )


def _service(
    pack: V2InvestigationPack,
    event_store: V2SQLiteEventStore,
    analysis_store: V2SQLiteAnalysisStore,
    *,
    registry: V2AnalysisActionRegistry | None = None,
) -> V2PersistentAnalysisApplicationService:
    return V2PersistentAnalysisApplicationService(
        pack,
        event_store,
        analysis_store,
        registry or _registry(),
    )


def _execute(
    service: V2PersistentAnalysisApplicationService,
    sequence: int,
    command,
):
    return service.investigation_service.execute(
        "session",
        command,
        expected_sequence=sequence,
    )


def _prepare_compare_action(
    service: V2PersistentAnalysisApplicationService,
) -> int:
    service.investigation_service.create_session("session", ["player_a"])
    sequence = 0
    commands = (
        V2ExamineEvidenceCommand("player_a", "optical_record"),
        V2PerformActionCommand("player_a", "inspect_optical_record"),
        V2ExamineEvidenceCommand("player_a", "radio_return"),
        V2PerformActionCommand("player_a", "inspect_radio_return"),
    )
    for command in commands:
        result = _execute(service, sequence, command)
        assert result.accepted is True
        sequence = result.session.sequence
    return sequence


def _prepare_examined_only(
    service: V2PersistentAnalysisApplicationService,
) -> int:
    service.investigation_service.create_session("session", ["player_a"])
    first = _execute(
        service,
        0,
        V2ExamineEvidenceCommand("player_a", "optical_record"),
    )
    second = _execute(
        service,
        first.session.sequence,
        V2ExamineEvidenceCommand("player_a", "radio_return"),
    )
    return second.session.sequence


def _job(
    *,
    sequence: int,
    inputs: tuple[V2AnalysisInput, ...] | None = None,
    stream_id: str = "session",
    position_id: str = "boundary_event",
    player_id: str = "player_a",
    method: V2AnalysisMethod = V2_CLOCK_ALIGNMENT_METHOD,
    action_id: str = ACTION_ID,
):
    job_id = calculate_action_analysis_job_id(
        stream_id=stream_id,
        event_sequence=sequence,
        action_id=action_id,
        method=method,
    )
    envelope = create_cross_source_clock_alignment_job(
        job_id=job_id,
        stream_id=stream_id,
        position_id=position_id,
        requested_by_player_id=player_id,
        inputs=inputs or _inputs(),
        reference_dataset_id="boundary_optical",
        tolerance_us=100,
    )
    if method != V2_CLOCK_ALIGNMENT_METHOD:
        envelope = create_analysis_job_envelope(replace(envelope.job, method=method))
    return envelope


def test_action_registry_is_sorted_and_resolves_exact_bindings() -> None:
    other_method = V2AnalysisMethod(
        method_id="other_method",
        version="1.0.0",
        implementation="tests:other",
        description="Other deterministic method.",
    )
    first = V2AnalysisActionBinding(
        action_id="z_action",
        method=other_method,
        output_kind="z_output",
    )
    second = V2AnalysisActionBinding(
        action_id="a_action",
        method=V2_CLOCK_ALIGNMENT_METHOD,
        output_kind=V2_CLOCK_ALIGNMENT_OUTPUT_KIND,
    )

    registry = V2AnalysisActionRegistry((first, second))

    assert registry.registered_bindings() == (second, first)
    assert registry.resolve("a_action") == second
    assert registry.resolve("missing") is None


def test_action_registry_rejects_duplicate_action_ids() -> None:
    binding = V2AnalysisActionBinding(
        action_id=ACTION_ID,
        method=V2_CLOCK_ALIGNMENT_METHOD,
        output_kind=V2_CLOCK_ALIGNMENT_OUTPUT_KIND,
    )

    with pytest.raises(V2AnalysisActionBindingError, match="repeat action IDs"):
        V2AnalysisActionRegistry((binding, binding))


def test_production_registry_binds_the_boundary_timing_action() -> None:
    binding = create_missing_interior_analysis_action_registry().registered_bindings()[0]

    assert binding.action_id == "compare_source_timing"
    assert binding.method == V2_CLOCK_ALIGNMENT_METHOD
    assert binding.output_kind == V2_CLOCK_ALIGNMENT_OUTPUT_KIND
    production_pack = load_investigation_pack(PRODUCTION_PACK_PATH)
    assert binding.action_id in {action.id for action in production_pack.actions}


def test_service_rejects_bindings_for_actions_absent_from_the_pack(
    tmp_path: Path,
    pack: V2InvestigationPack,
) -> None:
    registry = V2AnalysisActionRegistry(
        (
            V2AnalysisActionBinding(
                action_id="absent_action",
                method=V2_CLOCK_ALIGNMENT_METHOD,
                output_kind=V2_CLOCK_ALIGNMENT_OUTPUT_KIND,
            ),
        )
    )
    with (
        V2SQLiteEventStore(tmp_path / "events.sqlite3") as events,
        V2SQLiteAnalysisStore(tmp_path / "analysis.sqlite3") as analyses,
        pytest.raises(V2AnalysisActionBindingError, match="unknown pack actions"),
    ):
        _service(pack, events, analyses, registry=registry)


def test_action_job_id_is_deterministic_and_event_specific() -> None:
    first = calculate_action_analysis_job_id(
        stream_id="session",
        event_sequence=5,
        action_id=ACTION_ID,
        method=V2_CLOCK_ALIGNMENT_METHOD,
    )
    repeated = calculate_action_analysis_job_id(
        stream_id="session",
        event_sequence=5,
        action_id=ACTION_ID,
        method=V2_CLOCK_ALIGNMENT_METHOD,
    )
    next_event = calculate_action_analysis_job_id(
        stream_id="session",
        event_sequence=6,
        action_id=ACTION_ID,
        method=V2_CLOCK_ALIGNMENT_METHOD,
    )

    assert first == repeated
    assert first.startswith("action-analysis-")
    assert first != next_event


def test_accepted_action_enqueues_work_without_executing_science(
    tmp_path: Path,
    pack: V2InvestigationPack,
) -> None:
    with (
        V2SQLiteEventStore(tmp_path / "events.sqlite3") as events,
        V2SQLiteAnalysisStore(tmp_path / "analysis.sqlite3") as analyses,
    ):
        service = _service(pack, events, analyses)
        sequence = _prepare_compare_action(service)

        result = service.execute_clock_alignment_action(
            "session",
            V2PerformActionCommand("player_a", ACTION_ID),
            expected_sequence=sequence,
            inputs=_inputs(),
            reference_dataset_id="boundary_optical",
            tolerance_us=100,
            submitted_at=BASE_TIME,
        )

        assert isinstance(result, V2ActionAnalysisSubmissionResult)
        assert result.application_result.accepted is True
        assert result.application_result.session.sequence == sequence + 1
        assert result.analysis_job is not None
        assert result.analysis_job.status is V2AnalysisJobStatus.QUEUED
        assert result.analysis_job.attempt_count == 0
        assert analyses.list_jobs() == (result.analysis_job,)
        assert analyses.get_artifact_for_job(result.analysis_job.job_id) is None


def test_rejected_action_does_not_enqueue_a_job(
    tmp_path: Path,
    pack: V2InvestigationPack,
) -> None:
    with (
        V2SQLiteEventStore(tmp_path / "events.sqlite3") as events,
        V2SQLiteAnalysisStore(tmp_path / "analysis.sqlite3") as analyses,
    ):
        service = _service(pack, events, analyses)
        sequence = _prepare_examined_only(service)
        envelope = _job(sequence=sequence + 1)

        result = service.execute_action_with_job(
            "session",
            V2PerformActionCommand("player_a", ACTION_ID),
            envelope,
            expected_sequence=sequence,
            submitted_at=BASE_TIME,
        )

        assert result.application_result.accepted is False
        assert result.analysis_job is None
        assert events.latest_sequence("session") == sequence
        assert analyses.list_jobs() == ()


def test_unbound_action_is_rejected_before_it_is_persisted(
    tmp_path: Path,
    pack: V2InvestigationPack,
) -> None:
    with (
        V2SQLiteEventStore(tmp_path / "events.sqlite3") as events,
        V2SQLiteAnalysisStore(tmp_path / "analysis.sqlite3") as analyses,
    ):
        service = _service(pack, events, analyses)
        service.investigation_service.create_session("session", ["player_a"])
        envelope = _job(sequence=1, action_id=ACTION_ID)

        with pytest.raises(V2AnalysisActionBindingError, match="no registered"):
            service.execute_action_with_job(
                "session",
                V2PerformActionCommand("player_a", "inspect_optical_record"),
                envelope,
                expected_sequence=0,
                submitted_at=BASE_TIME,
            )

        assert events.latest_sequence("session") == 0
        assert analyses.list_jobs() == ()


def test_unexamined_input_is_rejected_before_action_persistence(
    tmp_path: Path,
    pack: V2InvestigationPack,
) -> None:
    with (
        V2SQLiteEventStore(tmp_path / "events.sqlite3") as events,
        V2SQLiteAnalysisStore(tmp_path / "analysis.sqlite3") as analyses,
    ):
        service = _service(pack, events, analyses)
        sequence = _prepare_compare_action(service)
        envelope = _job(
            sequence=sequence + 1,
            inputs=_inputs(radio_source="weather_record"),
        )

        with pytest.raises(
            V2AnalysisApplicationError,
            match="examined evidence: weather_record",
        ):
            service.execute_action_with_job(
                "session",
                V2PerformActionCommand("player_a", ACTION_ID),
                envelope,
                expected_sequence=sequence,
                submitted_at=BASE_TIME,
            )

        assert events.latest_sequence("session") == sequence
        assert analyses.list_jobs() == ()


def test_unknown_evidence_input_is_rejected_before_action_persistence(
    tmp_path: Path,
    pack: V2InvestigationPack,
) -> None:
    with (
        V2SQLiteEventStore(tmp_path / "events.sqlite3") as events,
        V2SQLiteAnalysisStore(tmp_path / "analysis.sqlite3") as analyses,
    ):
        service = _service(pack, events, analyses)
        sequence = _prepare_compare_action(service)
        envelope = _job(
            sequence=sequence + 1,
            inputs=_inputs(radio_source="invented_record"),
        )

        with pytest.raises(
            V2AnalysisApplicationError,
            match="unknown evidence: invented_record",
        ):
            service.execute_action_with_job(
                "session",
                V2PerformActionCommand("player_a", ACTION_ID),
                envelope,
                expected_sequence=sequence,
                submitted_at=BASE_TIME,
            )

        assert events.latest_sequence("session") == sequence


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    (
        ("job_id", "wrong-job-id", "deterministic job ID"),
        ("stream_id", "other_stream", "stream ID"),
        ("position_id", "other_position", "position ID"),
        ("requested_by_player_id", "player_b", "requesting player ID"),
        ("output_kind", "other_output", "output kind"),
    ),
)
def test_mismatched_job_binding_is_rejected_before_action_persistence(
    tmp_path: Path,
    pack: V2InvestigationPack,
    field: str,
    value: str,
    expected: str,
) -> None:
    with (
        V2SQLiteEventStore(tmp_path / "events.sqlite3") as events,
        V2SQLiteAnalysisStore(tmp_path / "analysis.sqlite3") as analyses,
    ):
        service = _service(pack, events, analyses)
        sequence = _prepare_compare_action(service)
        original = _job(sequence=sequence + 1)
        envelope = create_analysis_job_envelope(replace(original.job, **{field: value}))

        with pytest.raises(V2AnalysisActionBindingError, match=expected):
            service.execute_action_with_job(
                "session",
                V2PerformActionCommand("player_a", ACTION_ID),
                envelope,
                expected_sequence=sequence,
                submitted_at=BASE_TIME,
            )

        assert events.latest_sequence("session") == sequence
        assert analyses.list_jobs() == ()


def test_method_mismatch_is_rejected_before_action_persistence(
    tmp_path: Path,
    pack: V2InvestigationPack,
) -> None:
    other_method = V2AnalysisMethod(
        method_id="other_method",
        version="1.0.0",
        implementation="tests:other",
        description="Other deterministic method.",
    )
    with (
        V2SQLiteEventStore(tmp_path / "events.sqlite3") as events,
        V2SQLiteAnalysisStore(tmp_path / "analysis.sqlite3") as analyses,
    ):
        service = _service(pack, events, analyses)
        sequence = _prepare_compare_action(service)
        original = _job(sequence=sequence + 1)
        envelope = create_analysis_job_envelope(replace(original.job, method=other_method))

        with pytest.raises(V2AnalysisActionBindingError, match="method contract"):
            service.execute_action_with_job(
                "session",
                V2PerformActionCommand("player_a", ACTION_ID),
                envelope,
                expected_sequence=sequence,
                submitted_at=BASE_TIME,
            )

        assert events.latest_sequence("session") == sequence


def test_stale_expected_sequence_is_rejected_before_submission(
    tmp_path: Path,
    pack: V2InvestigationPack,
) -> None:
    with (
        V2SQLiteEventStore(tmp_path / "events.sqlite3") as events,
        V2SQLiteAnalysisStore(tmp_path / "analysis.sqlite3") as analyses,
    ):
        service = _service(pack, events, analyses)
        sequence = _prepare_compare_action(service)

        with pytest.raises(
            V2OptimisticConcurrencyError,
            match=f"expected sequence {sequence - 1}, actual sequence {sequence}",
        ):
            service.execute_clock_alignment_action(
                "session",
                V2PerformActionCommand("player_a", ACTION_ID),
                expected_sequence=sequence - 1,
                inputs=_inputs(),
                reference_dataset_id="boundary_optical",
                submitted_at=BASE_TIME,
            )

        assert analyses.list_jobs() == ()


def test_persisted_action_can_be_submitted_after_process_recovery(
    tmp_path: Path,
    pack: V2InvestigationPack,
) -> None:
    event_database = tmp_path / "events.sqlite3"
    analysis_database = tmp_path / "analysis.sqlite3"
    with (
        V2SQLiteEventStore(event_database) as events,
        V2SQLiteAnalysisStore(analysis_database) as analyses,
    ):
        service = _service(pack, events, analyses)
        sequence = _prepare_compare_action(service)
        action = _execute(
            service,
            sequence,
            V2PerformActionCommand("player_a", ACTION_ID),
        )
        assert action.accepted is True
        event_sequence = action.session.sequence

    envelope = _job(sequence=event_sequence)
    with (
        V2SQLiteEventStore(event_database) as reopened_events,
        V2SQLiteAnalysisStore(analysis_database) as reopened_analyses,
    ):
        recovered = _service(pack, reopened_events, reopened_analyses)
        stored = recovered.submit_job_for_action_event(
            "session",
            event_sequence,
            envelope,
            submitted_at=BASE_TIME,
        )

        assert stored.status is V2AnalysisJobStatus.QUEUED
        assert reopened_analyses.get_job(stored.job_id) == stored


def test_recovered_submission_is_idempotent(
    tmp_path: Path,
    pack: V2InvestigationPack,
) -> None:
    with (
        V2SQLiteEventStore(tmp_path / "events.sqlite3") as events,
        V2SQLiteAnalysisStore(tmp_path / "analysis.sqlite3") as analyses,
    ):
        service = _service(pack, events, analyses)
        sequence = _prepare_compare_action(service)
        action = _execute(
            service,
            sequence,
            V2PerformActionCommand("player_a", ACTION_ID),
        )
        envelope = _job(sequence=action.session.sequence)

        first = service.submit_job_for_action_event(
            "session",
            action.session.sequence,
            envelope,
            submitted_at=BASE_TIME,
        )
        second = service.submit_job_for_action_event(
            "session",
            action.session.sequence,
            envelope,
            submitted_at=BASE_TIME,
        )

        assert second == first
        assert analyses.list_jobs() == (first,)


def test_non_action_event_cannot_authorize_analysis_work(
    tmp_path: Path,
    pack: V2InvestigationPack,
) -> None:
    with (
        V2SQLiteEventStore(tmp_path / "events.sqlite3") as events,
        V2SQLiteAnalysisStore(tmp_path / "analysis.sqlite3") as analyses,
    ):
        service = _service(pack, events, analyses)
        service.investigation_service.create_session("session", ["player_a"])
        examined = _execute(
            service,
            0,
            V2ExamineEvidenceCommand("player_a", "optical_record"),
        )
        envelope = _job(sequence=examined.session.sequence)

        with pytest.raises(V2AnalysisActionEventError, match="not an action event"):
            service.submit_job_for_action_event(
                "session",
                examined.session.sequence,
                envelope,
                submitted_at=BASE_TIME,
            )

        assert analyses.list_jobs() == ()


def test_missing_event_sequence_cannot_authorize_analysis_work(
    tmp_path: Path,
    pack: V2InvestigationPack,
) -> None:
    with (
        V2SQLiteEventStore(tmp_path / "events.sqlite3") as events,
        V2SQLiteAnalysisStore(tmp_path / "analysis.sqlite3") as analyses,
    ):
        service = _service(pack, events, analyses)
        service.investigation_service.create_session("session", ["player_a"])
        envelope = _job(sequence=9)

        with pytest.raises(V2AnalysisActionEventError, match="no event at sequence 9"):
            service.submit_job_for_action_event(
                "session",
                9,
                envelope,
                submitted_at=BASE_TIME,
            )

        assert analyses.list_jobs() == ()


def test_clock_alignment_convenience_requires_a_clock_alignment_binding(
    tmp_path: Path,
    pack: V2InvestigationPack,
) -> None:
    other_method = V2AnalysisMethod(
        method_id="other_method",
        version="1.0.0",
        implementation="tests:other",
        description="Other deterministic method.",
    )
    with (
        V2SQLiteEventStore(tmp_path / "events.sqlite3") as events,
        V2SQLiteAnalysisStore(tmp_path / "analysis.sqlite3") as analyses,
    ):
        service = _service(
            pack,
            events,
            analyses,
            registry=_registry(method=other_method),
        )
        sequence = _prepare_compare_action(service)

        with pytest.raises(
            V2AnalysisActionBindingError,
            match="not bound to clock alignment",
        ):
            service.execute_clock_alignment_action(
                "session",
                V2PerformActionCommand("player_a", ACTION_ID),
                expected_sequence=sequence,
                inputs=_inputs(),
                reference_dataset_id="boundary_optical",
                submitted_at=BASE_TIME,
            )

        assert events.latest_sequence("session") == sequence
        assert analyses.list_jobs() == ()
