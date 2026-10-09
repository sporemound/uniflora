from __future__ import annotations

import json
from collections import deque
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from io import StringIO

import pytest

from uniflora.engine.v2 import (
    V2_CLOCK_ALIGNMENT_METHOD,
    V2_CLOCK_ALIGNMENT_METHOD_ID,
    V2_CLOCK_ALIGNMENT_METHOD_VERSION,
    V2_CLOCK_ALIGNMENT_OUTPUT_KIND,
    V2_CLOCK_OBSERVATION_MEDIA_TYPE,
    V2AnalysisExecutionRequest,
    V2AnalysisInput,
    V2AnalysisJobStatus,
    V2AnalysisMethodExecutionError,
    V2AnalysisParameter,
    V2AnalysisWorker,
    V2AnalysisWorkerOutcomeStatus,
    V2ClockAlignmentError,
    V2ClockObservation,
    V2ClockObservationDataset,
    V2LocalAnalysisDatasetRepository,
    V2ResolvedAnalysisInput,
    V2SQLiteAnalysisStore,
    calculate_dataset_hash,
    create_analysis_job_envelope,
    create_analysis_method_registry,
    create_cross_source_clock_alignment_job,
    deserialize_clock_observation_dataset,
    execute_cross_source_clock_alignment,
    serialize_clock_observation_dataset,
)
from uniflora.engine.v2.analysis_cli import main as analysis_cli_main

BASE_TIME = datetime(2026, 7, 25, 20, 0, tzinfo=UTC)


def _dataset(
    clock_id: str,
    observations: tuple[tuple[str, int, int], ...],
) -> V2ClockObservationDataset:
    return V2ClockObservationDataset(
        clock_id=clock_id,
        observations=tuple(
            V2ClockObservation(
                event_id=event_id,
                timestamp_us=timestamp_us,
                uncertainty_us=uncertainty_us,
            )
            for event_id, timestamp_us, uncertainty_us in observations
        ),
    )


def _payloads() -> dict[str, bytes]:
    return {
        "boundary_optical": serialize_clock_observation_dataset(
            _dataset(
                "boundary_optical_clock",
                (
                    ("flash_start", 1_000_000, 10),
                    ("radio_peak", 2_000_000, 10),
                    ("flash_end", 3_000_000, 10),
                ),
            )
        ),
        "boundary_radio": serialize_clock_observation_dataset(
            _dataset(
                "boundary_radio_clock",
                (
                    ("flash_start", 999_900, 20),
                    ("radio_peak", 1_999_800, 20),
                    ("flash_end", 2_999_700, 20),
                ),
            )
        ),
    }


def _descriptor(
    dataset_id: str,
    payload: bytes,
    *,
    source_evidence_id: str | None = None,
    media_type: str = V2_CLOCK_OBSERVATION_MEDIA_TYPE,
) -> V2AnalysisInput:
    return V2AnalysisInput(
        dataset_id=dataset_id,
        source_evidence_id=source_evidence_id or dataset_id,
        content_hash=calculate_dataset_hash(payload),
        byte_length=len(payload),
        media_type=media_type,
        provenance=f"Retained source export for {dataset_id}.",
    )


def _job_and_request(
    *,
    payloads: dict[str, bytes] | None = None,
    reference_dataset_id: str = "boundary_optical",
    minimum_shared_events: int = 2,
    tolerance_us: int | None = None,
):
    retained = payloads or _payloads()
    descriptors = tuple(
        _descriptor(dataset_id, payload) for dataset_id, payload in retained.items()
    )
    envelope = create_cross_source_clock_alignment_job(
        job_id="job_clock_alignment",
        stream_id="investigation_alpha",
        position_id="boundary_event",
        requested_by_player_id="player_a",
        inputs=descriptors,
        reference_dataset_id=reference_dataset_id,
        minimum_shared_events=minimum_shared_events,
        tolerance_us=tolerance_us,
    )
    request = V2AnalysisExecutionRequest(
        job_envelope=envelope,
        inputs=tuple(
            V2ResolvedAnalysisInput(
                descriptor=descriptor,
                data=retained[descriptor.dataset_id],
            )
            for descriptor in envelope.job.inputs
        ),
    )
    return envelope, request


def _values(result) -> dict[str, object]:
    return {derived.name: derived.value.to_python() for derived in result.derived_values}


def test_clock_observation_dataset_round_trips_as_canonical_json() -> None:
    dataset = _dataset(
        "clock_a",
        (("event_b", 20, 2), ("event_a", 10, 1)),
    )

    payload = serialize_clock_observation_dataset(dataset)

    assert payload == (
        b'{"clock_id":"clock_a","observations":['
        b'{"event_id":"event_a","timestamp_us":10,"uncertainty_us":1},'
        b'{"event_id":"event_b","timestamp_us":20,"uncertainty_us":2}]}'
    )
    assert deserialize_clock_observation_dataset(payload) == dataset


def test_clock_observation_dataset_rejects_duplicate_event_ids() -> None:
    with pytest.raises(V2ClockAlignmentError, match="repeat event IDs"):
        _dataset(
            "clock_a",
            (("same", 10, 1), ("same", 20, 1)),
        )


def test_production_registry_contains_the_exact_clock_alignment_method() -> None:
    registry = create_analysis_method_registry()

    assert registry.registered_methods() == (V2_CLOCK_ALIGNMENT_METHOD,)
    assert registry.resolve(V2_CLOCK_ALIGNMENT_METHOD) is (execute_cross_source_clock_alignment)
    assert V2_CLOCK_ALIGNMENT_METHOD.method_id == V2_CLOCK_ALIGNMENT_METHOD_ID
    assert V2_CLOCK_ALIGNMENT_METHOD.version == V2_CLOCK_ALIGNMENT_METHOD_VERSION


def test_job_helper_binds_method_output_and_explicit_parameter_units() -> None:
    payloads = _payloads()
    descriptors = tuple(
        _descriptor(dataset_id, payload) for dataset_id, payload in payloads.items()
    )

    envelope = create_cross_source_clock_alignment_job(
        job_id="job_clock_alignment",
        stream_id="investigation_alpha",
        position_id="boundary_event",
        requested_by_player_id="player_a",
        inputs=descriptors,
        reference_dataset_id="boundary_optical",
        minimum_shared_events=3,
        tolerance_us=125,
    )

    parameters = {item.name: item for item in envelope.job.parameters}
    assert envelope.job.method == V2_CLOCK_ALIGNMENT_METHOD
    assert envelope.job.output_kind == V2_CLOCK_ALIGNMENT_OUTPUT_KIND
    assert parameters["reference_dataset_id"].unit is None
    assert parameters["minimum_shared_events"].unit == "events"
    assert parameters["tolerance_us"].unit == "microseconds"


def test_job_helper_requires_two_inputs_and_a_present_reference() -> None:
    payload = _payloads()["boundary_optical"]
    descriptor = _descriptor("boundary_optical", payload)

    with pytest.raises(V2ClockAlignmentError, match="at least two"):
        create_cross_source_clock_alignment_job(
            job_id="job",
            stream_id="stream",
            position_id="position",
            requested_by_player_id="player",
            inputs=(descriptor,),
            reference_dataset_id="boundary_optical",
        )

    with pytest.raises(V2ClockAlignmentError, match="supplied input"):
        create_cross_source_clock_alignment_job(
            job_id="job",
            stream_id="stream",
            position_id="position",
            requested_by_player_id="player",
            inputs=(descriptor, replace(descriptor, dataset_id="second")),
            reference_dataset_id="missing",
        )


def test_method_estimates_constant_offsets_and_exact_residuals() -> None:
    _, request = _job_and_request()

    result = execute_cross_source_clock_alignment(request)
    values = _values(result)

    assert values["reference_dataset_id"] == "boundary_optical"
    assert values["reference_clock_id"] == "boundary_optical_clock"
    assert values["alignment_offsets"] == {
        "boundary_optical": {"denominator": 1, "numerator": 0},
        "boundary_radio": {"denominator": 1, "numerator": 200},
    }
    assert values["shared_event_counts"] == {"boundary_radio": 3}
    assert values["residual_summary"] == {
        "boundary_radio": {
            "maximum_absolute_residual_us": {
                "denominator": 1,
                "numerator": 100,
            },
            "median_absolute_residual_us": {
                "denominator": 1,
                "numerator": 100,
            },
        }
    }
    assert values["maximum_absolute_residual"] == {
        "denominator": 1,
        "numerator": 100,
    }


def test_even_shared_event_count_preserves_half_microsecond_offset() -> None:
    payloads = {
        "reference": serialize_clock_observation_dataset(
            _dataset(
                "reference_clock",
                (("first", 1000, 1), ("second", 2000, 1)),
            )
        ),
        "source": serialize_clock_observation_dataset(
            _dataset(
                "source_clock",
                (("first", 900, 1), ("second", 1899, 1)),
            )
        ),
    }
    _, request = _job_and_request(
        payloads=payloads,
        reference_dataset_id="reference",
    )

    values = _values(execute_cross_source_clock_alignment(request))

    assert values["alignment_offsets"]["source"] == {
        "denominator": 2,
        "numerator": 201,
    }
    assert values["maximum_absolute_residual"] == {
        "denominator": 2,
        "numerator": 1,
    }


def test_tolerance_result_is_explicit_and_deterministic() -> None:
    _, permissive = _job_and_request(tolerance_us=100)
    _, strict = _job_and_request(tolerance_us=99)

    permissive_values = _values(execute_cross_source_clock_alignment(permissive))
    strict_values = _values(execute_cross_source_clock_alignment(strict))

    assert permissive_values["all_sources_within_tolerance"] is True
    assert permissive_values["tolerance"] == 100
    assert strict_values["all_sources_within_tolerance"] is False


def test_result_preserves_uncertainty_limitations_software_and_provenance() -> None:
    _, request = _job_and_request()

    result = execute_cross_source_clock_alignment(request)
    uncertainties = {item.source: item for item in result.uncertainties}

    assert uncertainties["declared_timestamp_uncertainty"].value.to_python() == {
        "boundary_radio": 30
    }
    assert uncertainties["alignment_residual_dispersion"].value.to_python() == {
        "boundary_radio": {"denominator": 1, "numerator": 100}
    }
    assert uncertainties["event_correspondence_assumption"].value is None
    assert any("clock drift" in item for item in result.limitations)
    assert {item.name for item in result.software_versions} == {
        "python",
        "uniflora-clock-alignment",
    }
    assert any("boundary_optical" in item for item in result.provenance)
    assert any("boundary_radio" in item for item in result.provenance)


def test_method_is_independent_of_input_order() -> None:
    payloads = _payloads()
    descriptors = tuple(
        _descriptor(dataset_id, payload) for dataset_id, payload in payloads.items()
    )
    first = create_cross_source_clock_alignment_job(
        job_id="job",
        stream_id="stream",
        position_id="position",
        requested_by_player_id="player",
        inputs=descriptors,
        reference_dataset_id="boundary_optical",
    )
    second = create_cross_source_clock_alignment_job(
        job_id="job",
        stream_id="stream",
        position_id="position",
        requested_by_player_id="player",
        inputs=tuple(reversed(descriptors)),
        reference_dataset_id="boundary_optical",
    )

    assert first == second


def test_method_rejects_insufficient_shared_events() -> None:
    payloads = _payloads()
    _, request = _job_and_request(payloads=payloads, minimum_shared_events=4)

    with pytest.raises(
        V2AnalysisMethodExecutionError,
        match="shares 3 events",
    ):
        execute_cross_source_clock_alignment(request)


def test_method_rejects_wrong_media_type() -> None:
    payloads = _payloads()
    descriptors = tuple(
        _descriptor(
            dataset_id,
            payload,
            media_type="application/octet-stream",
        )
        for dataset_id, payload in payloads.items()
    )
    envelope = create_cross_source_clock_alignment_job(
        job_id="job",
        stream_id="stream",
        position_id="position",
        requested_by_player_id="player",
        inputs=descriptors,
        reference_dataset_id="boundary_optical",
    )
    request = V2AnalysisExecutionRequest(
        job_envelope=envelope,
        inputs=tuple(
            V2ResolvedAnalysisInput(
                descriptor=descriptor,
                data=payloads[descriptor.dataset_id],
            )
            for descriptor in envelope.job.inputs
        ),
    )

    with pytest.raises(V2AnalysisMethodExecutionError, match="media type"):
        execute_cross_source_clock_alignment(request)


def test_method_rejects_repeated_clock_ids_across_datasets() -> None:
    payloads = {
        "first": serialize_clock_observation_dataset(
            _dataset("same_clock", (("a", 10, 1), ("b", 20, 1)))
        ),
        "second": serialize_clock_observation_dataset(
            _dataset("same_clock", (("a", 11, 1), ("b", 21, 1)))
        ),
    }
    _, request = _job_and_request(
        payloads=payloads,
        reference_dataset_id="first",
    )

    with pytest.raises(V2AnalysisMethodExecutionError, match="repeated"):
        execute_cross_source_clock_alignment(request)


def test_method_rejects_unknown_parameters_and_output_kind() -> None:
    envelope, request = _job_and_request()
    changed_job = replace(
        envelope.job,
        parameters=envelope.job.parameters + (V2AnalysisParameter.from_value("unknown", True),),
    )
    changed_envelope = create_analysis_job_envelope(changed_job)
    changed_request = replace(request, job_envelope=changed_envelope)

    with pytest.raises(V2AnalysisMethodExecutionError, match="unsupported"):
        execute_cross_source_clock_alignment(changed_request)

    output_envelope = create_analysis_job_envelope(
        replace(envelope.job, output_kind="wrong_report")
    )
    output_request = replace(request, job_envelope=output_envelope)
    with pytest.raises(V2AnalysisMethodExecutionError, match="output kind"):
        execute_cross_source_clock_alignment(output_request)


def test_method_rejects_malformed_clock_json() -> None:
    payloads = _payloads()
    payloads["boundary_radio"] = b"not-json"
    descriptors = tuple(
        _descriptor(dataset_id, payload) for dataset_id, payload in payloads.items()
    )
    envelope = create_cross_source_clock_alignment_job(
        job_id="job",
        stream_id="stream",
        position_id="position",
        requested_by_player_id="player",
        inputs=descriptors,
        reference_dataset_id="boundary_optical",
    )
    request = V2AnalysisExecutionRequest(
        job_envelope=envelope,
        inputs=tuple(
            V2ResolvedAnalysisInput(
                descriptor=descriptor,
                data=payloads[descriptor.dataset_id],
            )
            for descriptor in envelope.job.inputs
        ),
    )

    with pytest.raises(V2AnalysisMethodExecutionError, match="invalid.*JSON"):
        execute_cross_source_clock_alignment(request)


def test_worker_executes_real_method_from_local_repository(tmp_path) -> None:
    payloads = _payloads()
    repository = V2LocalAnalysisDatasetRepository(tmp_path / "datasets")
    stored = tuple(
        repository.import_bytes(
            payload,
            dataset_id=dataset_id,
            source_evidence_id=dataset_id,
            media_type=V2_CLOCK_OBSERVATION_MEDIA_TYPE,
            provenance=f"Retained {dataset_id} export.",
        )
        for dataset_id, payload in payloads.items()
    )
    envelope = create_cross_source_clock_alignment_job(
        job_id="job_worker_alignment",
        stream_id="investigation_alpha",
        position_id="boundary_event",
        requested_by_player_id="player_a",
        inputs=tuple(item.descriptor for item in stored),
        reference_dataset_id="boundary_optical",
        tolerance_us=100,
    )
    times = deque((BASE_TIME, BASE_TIME + timedelta(seconds=1)))

    with V2SQLiteAnalysisStore(tmp_path / "analysis.sqlite3") as store:
        store.enqueue_job(envelope, submitted_at=BASE_TIME - timedelta(minutes=1))
        outcome = V2AnalysisWorker(
            store=store,
            registry=create_analysis_method_registry(),
            dataset_resolver=repository,
            worker_id="clock-worker",
            lease_duration=timedelta(minutes=5),
            clock=times.popleft,
        ).run_once()
        artifact = store.get_artifact_for_job(envelope.job.job_id)
        completed = store.get_job(envelope.job.job_id)

    assert outcome.status is V2AnalysisWorkerOutcomeStatus.COMPLETED
    assert completed.status is V2AnalysisJobStatus.COMPLETED
    assert artifact is not None
    values = {
        item.name: item.value.to_python() for item in artifact.envelope.artifact.derived_values
    }
    assert values["all_sources_within_tolerance"] is True
    assert artifact.envelope.artifact.method_id == V2_CLOCK_ALIGNMENT_METHOD_ID


def test_cli_runs_one_job_with_the_real_registry_factory(tmp_path) -> None:
    payloads = _payloads()
    repository_path = tmp_path / "datasets"
    database_path = tmp_path / "analysis.sqlite3"
    repository = V2LocalAnalysisDatasetRepository(repository_path)
    stored = tuple(
        repository.import_bytes(
            payload,
            dataset_id=dataset_id,
            source_evidence_id=dataset_id,
            media_type=V2_CLOCK_OBSERVATION_MEDIA_TYPE,
            provenance=f"Retained {dataset_id} export.",
        )
        for dataset_id, payload in payloads.items()
    )
    envelope = create_cross_source_clock_alignment_job(
        job_id="job_cli_alignment",
        stream_id="investigation_alpha",
        position_id="boundary_event",
        requested_by_player_id="player_a",
        inputs=tuple(item.descriptor for item in stored),
        reference_dataset_id="boundary_optical",
    )
    with V2SQLiteAnalysisStore(database_path) as store:
        store.enqueue_job(envelope, submitted_at=BASE_TIME)

    stdout = StringIO()
    stderr = StringIO()
    exit_code = analysis_cli_main(
        [
            "run-once",
            "--database",
            str(database_path),
            "--repository",
            str(repository_path),
            "--registry-factory",
            "uniflora.engine.v2.analysis_methods:create_registry",
            "--worker-id",
            "cli-clock-worker",
            "--lease-seconds",
            "300",
        ],
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 0
    assert stderr.getvalue() == ""
    assert json.loads(stdout.getvalue()) == {
        "artifact_id": f"artifact_{envelope.job_hash}",
        "attempt_count": 1,
        "error": None,
        "job_id": "job_cli_alignment",
        "status": "completed",
    }
