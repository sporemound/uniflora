from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from uniflora.engine.v2 import (
    V2AnalysisArtifactNotFoundError,
    V2AnalysisDerivedValue,
    V2AnalysisInput,
    V2AnalysisJob,
    V2AnalysisJobNotFoundError,
    V2AnalysisJobStatus,
    V2AnalysisMethod,
    V2AnalysisParameter,
    V2AnalysisPresentationService,
    V2AnalysisUncertainty,
    V2SoftwareVersion,
    V2SQLiteAnalysisStore,
    calculate_dataset_hash,
    create_analysis_artifact_envelope,
    create_analysis_job_envelope,
    render_analysis_artifact,
    render_analysis_status,
)

BASE_TIME = datetime(2026, 7, 26, 12, 0, tzinfo=UTC)
LEASE_DURATION = timedelta(minutes=10)


def _job_envelope(
    job_id: str = "job_clock_alignment",
    *,
    stream_id: str = "investigation_alpha",
    position_id: str = "boundary_event",
):
    optical = b"optical-clock-observations"
    radio = b"radio-clock-observations"
    return create_analysis_job_envelope(
        V2AnalysisJob(
            job_id=job_id,
            stream_id=stream_id,
            position_id=position_id,
            requested_by_player_id="player_a",
            method=V2AnalysisMethod(
                method_id="cross_source_clock_alignment",
                version="1.0.0",
                implementation=(
                    "uniflora.engine.v2.analysis_methods:execute_cross_source_clock_alignment"
                ),
                description=("Estimate a constant offset without inferring shared cause."),
            ),
            inputs=(
                V2AnalysisInput(
                    dataset_id="boundary_optical",
                    source_evidence_id="optical_record",
                    content_hash=calculate_dataset_hash(optical),
                    byte_length=len(optical),
                    media_type="application/vnd.uniflora.clock-observations+json",
                    provenance="Retained optical timing export.",
                    preprocessing_steps=("normalized event labels",),
                ),
                V2AnalysisInput(
                    dataset_id="boundary_radio",
                    source_evidence_id="radio_return",
                    content_hash=calculate_dataset_hash(radio),
                    byte_length=len(radio),
                    media_type="application/vnd.uniflora.clock-observations+json",
                    provenance="Retained radio timing export.",
                ),
            ),
            parameters=(
                V2AnalysisParameter.from_value(
                    "minimum_shared_events",
                    2,
                    unit="events",
                ),
                V2AnalysisParameter.from_value(
                    "reference_dataset_id",
                    "boundary_optical",
                ),
            ),
            output_kind="cross_source_clock_alignment_report",
        )
    )


def _artifact_envelope(envelope):
    return create_analysis_artifact_envelope(
        envelope,
        artifact_id=f"artifact_{envelope.job.job_id}",
        derived_values=(
            V2AnalysisDerivedValue.from_value(
                "alignment_offsets",
                {
                    "boundary_optical": {"denominator": 1, "numerator": 0},
                    "boundary_radio": {"denominator": 2, "numerator": 201},
                },
                unit="microseconds",
            ),
            V2AnalysisDerivedValue.from_value(
                "maximum_residual",
                {"denominator": 2, "numerator": 1},
                unit="microseconds",
            ),
        ),
        uncertainties=(
            V2AnalysisUncertainty.quantified(
                "declared_clock_uncertainty",
                "Source clocks bound the attainable alignment precision.",
                {"denominator": 1, "numerator": 20},
                unit="microseconds",
            ),
            V2AnalysisUncertainty(
                source="event_correspondence",
                statement=("Matching event labels do not establish a shared physical cause."),
            ),
        ),
        limitations=(
            "The method estimates a constant offset and does not model drift.",
            "The result does not establish source distance or trajectory.",
        ),
        software_versions=(
            V2SoftwareVersion(name="python", version="3.13"),
            V2SoftwareVersion(name="uniflora-analysis", version="0.6.0"),
        ),
        provenance=(
            "Produced from retained inputs identified by SHA-256.",
            "Authorized by the compare_source_timing investigation action.",
        ),
    )


def _claim(store: V2SQLiteAnalysisStore, job_id: str = "job_clock_alignment"):
    claimed = store.claim_next_job(
        worker_id="worker_a",
        claimed_at=BASE_TIME + timedelta(minutes=1),
        lease_duration=LEASE_DURATION,
    )
    assert claimed is not None
    assert claimed.job_id == job_id
    return claimed


def _complete(store: V2SQLiteAnalysisStore, envelope=None):
    envelope = envelope or _job_envelope()
    store.enqueue_job(envelope, submitted_at=BASE_TIME)
    claimed = _claim(store, envelope.job.job_id)
    artifact = _artifact_envelope(envelope)
    store.submit_artifact(
        envelope.job.job_id,
        artifact,
        worker_id="worker_a",
        lease_token=claimed.lease_token or "",
        completed_at=BASE_TIME + timedelta(minutes=2),
    )
    return envelope, artifact


def test_queued_status_view_preserves_job_identity_and_inputs(tmp_path) -> None:
    with V2SQLiteAnalysisStore(tmp_path / "analysis.sqlite3") as store:
        envelope = _job_envelope()
        store.enqueue_job(envelope, submitted_at=BASE_TIME)
        view = V2AnalysisPresentationService(store).get_status(envelope.job.job_id)

    assert view.status is V2AnalysisJobStatus.QUEUED
    assert view.stream_id == "investigation_alpha"
    assert view.position_id == "boundary_event"
    assert view.method_id == "cross_source_clock_alignment"
    assert view.inputs[0].dataset_id == "boundary_optical"
    assert view.inputs[0].preprocessing_steps == ("normalized event labels",)
    assert view.inputs[1].provenance == "Retained radio timing export."
    assert view.artifact_id is None
    assert view.error is None


def test_status_view_preserves_canonical_parameter_values(tmp_path) -> None:
    with V2SQLiteAnalysisStore(tmp_path / "analysis.sqlite3") as store:
        envelope = _job_envelope()
        store.enqueue_job(envelope, submitted_at=BASE_TIME)
        view = V2AnalysisPresentationService(store).get_status(envelope.job.job_id)

    values = {value.name: value for value in view.parameters}
    assert values["minimum_shared_events"].canonical_json == "2"
    assert values["minimum_shared_events"].unit == "events"
    assert values["reference_dataset_id"].canonical_json == '"boundary_optical"'


def test_status_timestamps_are_explicit_utc_strings(tmp_path) -> None:
    with V2SQLiteAnalysisStore(tmp_path / "analysis.sqlite3") as store:
        envelope = _job_envelope()
        store.enqueue_job(envelope, submitted_at=BASE_TIME)
        view = V2AnalysisPresentationService(store).get_status(envelope.job.job_id)

    assert view.submitted_at == "2026-07-26T12:00:00.000000Z"
    assert view.updated_at == "2026-07-26T12:00:00.000000Z"


def test_leased_status_does_not_expose_worker_or_lease_token(tmp_path) -> None:
    with V2SQLiteAnalysisStore(tmp_path / "analysis.sqlite3") as store:
        envelope = _job_envelope()
        store.enqueue_job(envelope, submitted_at=BASE_TIME)
        claimed = _claim(store)
        view = V2AnalysisPresentationService(store).get_status(claimed.job_id)
        rendered = render_analysis_status(view).to_text()

    assert view.status is V2AnalysisJobStatus.LEASED
    assert view.attempt_count == 1
    assert "worker_a" not in repr(view)
    assert claimed.lease_token not in repr(view)
    assert "worker_a" not in rendered
    assert claimed.lease_token not in rendered


def test_terminal_failure_view_preserves_controlled_error(tmp_path) -> None:
    with V2SQLiteAnalysisStore(tmp_path / "analysis.sqlite3") as store:
        envelope = _job_envelope()
        store.enqueue_job(envelope, submitted_at=BASE_TIME)
        claimed = _claim(store)
        store.fail_job(
            claimed.job_id,
            worker_id="worker_a",
            lease_token=claimed.lease_token or "",
            failed_at=BASE_TIME + timedelta(minutes=2),
            error="Dataset content hash did not match retained bytes.",
            retryable=False,
        )
        view = V2AnalysisPresentationService(store).get_status(claimed.job_id)

    assert view.status is V2AnalysisJobStatus.FAILED
    assert view.error == "Dataset content hash did not match retained bytes."
    assert view.artifact_id is None


def test_retryable_failure_returns_to_queued_with_error_context(tmp_path) -> None:
    with V2SQLiteAnalysisStore(tmp_path / "analysis.sqlite3") as store:
        envelope = _job_envelope()
        store.enqueue_job(envelope, submitted_at=BASE_TIME)
        claimed = _claim(store)
        store.fail_job(
            claimed.job_id,
            worker_id="worker_a",
            lease_token=claimed.lease_token or "",
            failed_at=BASE_TIME + timedelta(minutes=2),
            error="Required dataset is not retained locally.",
            retryable=True,
        )
        view = V2AnalysisPresentationService(store).get_status(claimed.job_id)

    assert view.status is V2AnalysisJobStatus.QUEUED
    assert view.error == "Required dataset is not retained locally."
    assert view.attempt_count == 1


def test_completed_status_links_the_persisted_artifact(tmp_path) -> None:
    with V2SQLiteAnalysisStore(tmp_path / "analysis.sqlite3") as store:
        envelope, artifact = _complete(store)
        view = V2AnalysisPresentationService(store).get_status(envelope.job.job_id)

    assert view.status is V2AnalysisJobStatus.COMPLETED
    assert view.artifact_id == artifact.artifact.artifact_id
    assert view.error is None


def test_status_rendering_has_distinct_transport_neutral_codes(tmp_path) -> None:
    with V2SQLiteAnalysisStore(tmp_path / "analysis.sqlite3") as store:
        queued_envelope = _job_envelope("job_queued")
        store.enqueue_job(queued_envelope, submitted_at=BASE_TIME)
        service = V2AnalysisPresentationService(store)
        queued = render_analysis_status(service.get_status("job_queued"))
        _claim(store, "job_queued")
        processing = render_analysis_status(service.get_status("job_queued"))

    assert queued.kind == "analysis_status"
    assert queued.code == "analysis_queued"
    assert processing.code == "analysis_processing"
    assert processing.summary == "Analysis job 'job_queued' is being processed."


def test_failed_status_rendering_includes_error_without_traceback(tmp_path) -> None:
    with V2SQLiteAnalysisStore(tmp_path / "analysis.sqlite3") as store:
        envelope = _job_envelope()
        store.enqueue_job(envelope, submitted_at=BASE_TIME)
        claimed = _claim(store)
        store.fail_job(
            claimed.job_id,
            worker_id="worker_a",
            lease_token=claimed.lease_token or "",
            failed_at=BASE_TIME + timedelta(minutes=2),
            error="Invalid observation schema.",
            retryable=False,
        )
        rendered = render_analysis_status(
            V2AnalysisPresentationService(store).get_status(claimed.job_id)
        )

    text = rendered.to_text()
    assert rendered.code == "analysis_failed"
    assert "Error: Invalid observation schema." in text
    assert "Traceback" not in text


def test_list_statuses_preserves_submission_order(tmp_path) -> None:
    with V2SQLiteAnalysisStore(tmp_path / "analysis.sqlite3") as store:
        store.enqueue_job(
            _job_envelope("job_second"),
            submitted_at=BASE_TIME + timedelta(minutes=1),
        )
        store.enqueue_job(
            _job_envelope("job_first"),
            submitted_at=BASE_TIME,
        )
        views = V2AnalysisPresentationService(store).list_statuses()

    assert tuple(view.job_id for view in views) == ("job_first", "job_second")


def test_list_statuses_filters_by_status_stream_and_position(tmp_path) -> None:
    with V2SQLiteAnalysisStore(tmp_path / "analysis.sqlite3") as store:
        store.enqueue_job(
            _job_envelope("job_a", stream_id="stream_a", position_id="p1"),
            submitted_at=BASE_TIME,
        )
        store.enqueue_job(
            _job_envelope("job_b", stream_id="stream_b", position_id="p2"),
            submitted_at=BASE_TIME + timedelta(seconds=1),
        )
        _claim(store, "job_a")
        service = V2AnalysisPresentationService(store)

        leased = service.list_statuses(status=V2AnalysisJobStatus.LEASED)
        stream_b = service.list_statuses(stream_id="stream_b")
        position_2 = service.list_statuses(position_id="p2")

    assert tuple(view.job_id for view in leased) == ("job_a",)
    assert tuple(view.job_id for view in stream_b) == ("job_b",)
    assert tuple(view.job_id for view in position_2) == ("job_b",)


def test_blank_status_filters_are_rejected(tmp_path) -> None:
    with V2SQLiteAnalysisStore(tmp_path / "analysis.sqlite3") as store:
        service = V2AnalysisPresentationService(store)
        with pytest.raises(ValueError, match="stream ID"):
            service.list_statuses(stream_id="  ")
        with pytest.raises(ValueError, match="position ID"):
            service.list_statuses(position_id="\t")


def test_artifact_view_preserves_exact_derived_values(tmp_path) -> None:
    with V2SQLiteAnalysisStore(tmp_path / "analysis.sqlite3") as store:
        _, artifact = _complete(store)
        view = V2AnalysisPresentationService(store).get_artifact(artifact.artifact.artifact_id)

    values = {value.name: value for value in view.derived_values}
    assert values["maximum_residual"].canonical_json == ('{"denominator":2,"numerator":1}')
    assert values["maximum_residual"].unit == "microseconds"
    assert values["alignment_offsets"].canonical_json.startswith('{"boundary_optical"')


def test_artifact_view_preserves_uncertainty_limitations_and_provenance(
    tmp_path,
) -> None:
    with V2SQLiteAnalysisStore(tmp_path / "analysis.sqlite3") as store:
        _, artifact = _complete(store)
        view = V2AnalysisPresentationService(store).get_artifact(artifact.artifact.artifact_id)

    assert len(view.uncertainties) == 2
    assert view.uncertainties[0].source == "declared_clock_uncertainty"
    assert view.uncertainties[0].canonical_json == ('{"denominator":1,"numerator":20}')
    assert "does not model drift" in view.limitations[0]
    assert any("SHA-256" in item for item in view.provenance)
    assert tuple(item.name for item in view.software_versions) == (
        "python",
        "uniflora-analysis",
    )


def test_artifact_view_preserves_integrity_hashes(tmp_path) -> None:
    with V2SQLiteAnalysisStore(tmp_path / "analysis.sqlite3") as store:
        envelope, artifact = _complete(store)
        view = V2AnalysisPresentationService(store).get_artifact(artifact.artifact.artifact_id)

    assert view.job_hash == envelope.job_hash
    assert view.artifact_hash == artifact.artifact_hash
    assert view.input_manifest_hash == artifact.artifact.input_manifest_hash


def test_artifact_can_be_retrieved_by_job_id(tmp_path) -> None:
    with V2SQLiteAnalysisStore(tmp_path / "analysis.sqlite3") as store:
        envelope, artifact = _complete(store)
        view = V2AnalysisPresentationService(store).get_artifact_for_job(envelope.job.job_id)

    assert view is not None
    assert view.artifact_id == artifact.artifact.artifact_id


def test_job_without_result_has_no_artifact_view(tmp_path) -> None:
    with V2SQLiteAnalysisStore(tmp_path / "analysis.sqlite3") as store:
        envelope = _job_envelope()
        store.enqueue_job(envelope, submitted_at=BASE_TIME)
        view = V2AnalysisPresentationService(store).get_artifact_for_job(envelope.job.job_id)

    assert view is None


def test_artifact_rendering_surfaces_epistemic_context(tmp_path) -> None:
    with V2SQLiteAnalysisStore(tmp_path / "analysis.sqlite3") as store:
        _, artifact = _complete(store)
        view = V2AnalysisPresentationService(store).get_artifact(artifact.artifact.artifact_id)
        rendered = render_analysis_artifact(view)

    text = rendered.to_text()
    assert rendered.kind == "analysis_artifact"
    assert rendered.code == "analysis_artifact"
    assert "Derived maximum_residual:" in text
    assert "Uncertainty [event_correspondence]" in text
    assert "Limitation: The method estimates a constant offset" in text
    assert "Provenance: Produced from retained inputs" in text
    assert "Software: uniflora-analysis 0.6.0" in text
    assert "shared physical cause" in text


def test_artifact_rendering_does_not_add_narrative_conclusions(tmp_path) -> None:
    with V2SQLiteAnalysisStore(tmp_path / "analysis.sqlite3") as store:
        _, artifact = _complete(store)
        view = V2AnalysisPresentationService(store).get_artifact(artifact.artifact.artifact_id)
        text = render_analysis_artifact(view).to_text().lower()

    assert "therefore" not in text
    assert "proves" not in text
    assert "extraterrestrial" not in text


def test_missing_jobs_and_artifacts_preserve_store_errors(tmp_path) -> None:
    with V2SQLiteAnalysisStore(tmp_path / "analysis.sqlite3") as store:
        service = V2AnalysisPresentationService(store)
        with pytest.raises(V2AnalysisJobNotFoundError):
            service.get_status("missing_job")
        with pytest.raises(V2AnalysisArtifactNotFoundError):
            service.get_artifact("missing_artifact")
        with pytest.raises(V2AnalysisJobNotFoundError):
            service.get_artifact_for_job("missing_job")
