from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from uniflora.engine.v2 import (
    ANALYSIS_COMMAND_HELP,
    V2AnalysisArtifactEnvelope,
    V2AnalysisArtifactNotFoundError,
    V2AnalysisDerivedValue,
    V2AnalysisInput,
    V2AnalysisJob,
    V2AnalysisJobEnvelope,
    V2AnalysisMethod,
    V2AnalysisPresentationService,
    V2AnalysisTextCommandAdapter,
    V2AnalysisUncertainty,
    V2GetAnalysisArtifactCommand,
    V2GetAnalysisArtifactForJobCommand,
    V2GetAnalysisStatusCommand,
    V2SoftwareVersion,
    V2SQLiteAnalysisStore,
    calculate_dataset_hash,
    create_analysis_artifact_envelope,
    create_analysis_job_envelope,
    parse_analysis_command,
)

BASE_TIME = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)


def _job_envelope(job_id: str = "job_clock_alignment") -> V2AnalysisJobEnvelope:
    retained = b"clock-observation-record"
    return create_analysis_job_envelope(
        V2AnalysisJob(
            job_id=job_id,
            stream_id="investigation_alpha",
            position_id="boundary_event",
            requested_by_player_id="player_a",
            method=V2AnalysisMethod(
                method_id="cross_source_clock_alignment",
                version="1.0.0",
                implementation=(
                    "uniflora.engine.v2.analysis_methods:execute_cross_source_clock_alignment"
                ),
                description="Estimate a constant cross-source clock offset.",
            ),
            inputs=(
                V2AnalysisInput(
                    dataset_id="boundary_optical",
                    source_evidence_id="optical_record",
                    content_hash=calculate_dataset_hash(retained),
                    byte_length=len(retained),
                    media_type="application/vnd.uniflora.clock-observations+json",
                    provenance="Retained optical clock export.",
                ),
            ),
            parameters=(),
            output_kind="cross_source_clock_alignment_report",
        )
    )


def _artifact_envelope(
    job: V2AnalysisJobEnvelope,
) -> V2AnalysisArtifactEnvelope:
    return create_analysis_artifact_envelope(
        job,
        artifact_id=f"artifact_{job.job.job_id}",
        derived_values=(
            V2AnalysisDerivedValue.from_value(
                "maximum_residual",
                {"denominator": 2, "numerator": 1},
                unit="microseconds",
            ),
        ),
        uncertainties=(
            V2AnalysisUncertainty(
                source="event_correspondence",
                statement="Matching labels do not establish a shared cause.",
            ),
        ),
        limitations=("Constant offset only; clock drift is not estimated.",),
        software_versions=(V2SoftwareVersion(name="uniflora-analysis", version="0.8.0"),),
        provenance=("Produced from retained SHA-256 identified inputs.",),
    )


def _adapter(store: V2SQLiteAnalysisStore) -> V2AnalysisTextCommandAdapter:
    return V2AnalysisTextCommandAdapter(V2AnalysisPresentationService(store))


def _complete(
    store: V2SQLiteAnalysisStore,
    job: V2AnalysisJobEnvelope | None = None,
) -> tuple[V2AnalysisJobEnvelope, V2AnalysisArtifactEnvelope]:
    job = job or _job_envelope()
    store.enqueue_job(job, submitted_at=BASE_TIME)
    claimed = store.claim_next_job(
        worker_id="worker_a",
        claimed_at=BASE_TIME + timedelta(minutes=1),
        lease_duration=timedelta(minutes=5),
    )
    assert claimed is not None
    artifact = _artifact_envelope(job)
    store.submit_artifact(
        job.job.job_id,
        artifact,
        worker_id="worker_a",
        lease_token=claimed.lease_token or "",
        completed_at=BASE_TIME + timedelta(minutes=2),
    )
    return job, artifact


def test_help_defines_only_explicit_read_commands() -> None:
    assert [item.name for item in ANALYSIS_COMMAND_HELP] == [
        "analysis-status",
        "analysis-artifact",
        "analysis-artifact-for-job",
    ]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "analysis-status job_1",
            V2GetAnalysisStatusCommand(job_id="job_1"),
        ),
        (
            "/analysis-artifact artifact-1",
            V2GetAnalysisArtifactCommand(artifact_id="artifact-1"),
        ),
        (
            "v2 analysis-artifact-for-job job:1",
            V2GetAnalysisArtifactForJobCommand(job_id="job:1"),
        ),
    ],
)
def test_parser_creates_typed_commands(text, expected) -> None:
    assert parse_analysis_command(text) == expected


def test_parser_normalizes_command_underscores_only() -> None:
    assert parse_analysis_command("analysis_status job_1") == (
        V2GetAnalysisStatusCommand(job_id="job_1")
    )


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("", "empty_analysis_command"),
        ("v2", "empty_analysis_command"),
        ("analysis-status", "invalid_analysis_arguments"),
        ("analysis-status job extra", "invalid_analysis_arguments"),
        ("status job", "unknown_analysis_command"),
        ('analysis-status "job with spaces"', "invalid_analysis_identifier"),
        ("analysis-artifact ../secret", "invalid_analysis_identifier"),
        ('analysis-status "unterminated', "invalid_analysis_quoting"),
    ],
)
def test_parse_errors_render_as_controlled_responses(tmp_path, text, code) -> None:
    with V2SQLiteAnalysisStore(tmp_path / "analysis.sqlite3") as store:
        response = _adapter(store).execute(text)

    assert response.accepted is False
    assert response.kind == "analysis_error"
    assert response.code == code


def test_status_command_renders_queued_job(tmp_path) -> None:
    with V2SQLiteAnalysisStore(tmp_path / "analysis.sqlite3") as store:
        job = _job_envelope()
        store.enqueue_job(job, submitted_at=BASE_TIME)
        response = _adapter(store).execute(f"analysis-status {job.job.job_id}")

    assert response.accepted is True
    assert response.kind == "analysis_status"
    assert response.code == "analysis_queued"
    assert response.job_id == job.job.job_id
    assert "queued" in response.summary


def test_status_command_does_not_expose_worker_or_lease_token(tmp_path) -> None:
    with V2SQLiteAnalysisStore(tmp_path / "analysis.sqlite3") as store:
        job = _job_envelope()
        store.enqueue_job(job, submitted_at=BASE_TIME)
        claimed = store.claim_next_job(
            worker_id="private-worker",
            claimed_at=BASE_TIME + timedelta(minutes=1),
            lease_duration=timedelta(minutes=5),
        )
        assert claimed is not None
        response = _adapter(store).execute(f"analysis-status {job.job.job_id}")

    rendered = response.to_text()
    assert response.code == "analysis_processing"
    assert "private-worker" not in rendered
    assert claimed.lease_token not in rendered


def test_artifact_command_preserves_epistemic_context(tmp_path) -> None:
    with V2SQLiteAnalysisStore(tmp_path / "analysis.sqlite3") as store:
        _, artifact = _complete(store)
        response = _adapter(store).execute(f"analysis-artifact {artifact.artifact.artifact_id}")

    rendered = response.to_text()
    assert response.accepted is True
    assert response.kind == "analysis_artifact"
    assert response.code == "analysis_artifact"
    assert "maximum_residual" in rendered
    assert "Matching labels do not establish a shared cause" in rendered
    assert "Constant offset only" in rendered
    assert "Provenance:" in rendered
    assert "Artifact hash:" in rendered


def test_artifact_for_job_resolves_completed_artifact(tmp_path) -> None:
    with V2SQLiteAnalysisStore(tmp_path / "analysis.sqlite3") as store:
        job, artifact = _complete(store)
        response = _adapter(store).execute(f"analysis-artifact-for-job {job.job.job_id}")

    assert response.accepted is True
    assert response.job_id == job.job.job_id
    assert response.artifact_id == artifact.artifact.artifact_id


@pytest.mark.parametrize("leased", [False, True])
def test_artifact_for_pending_job_reports_status(tmp_path, leased) -> None:
    with V2SQLiteAnalysisStore(tmp_path / "analysis.sqlite3") as store:
        job = _job_envelope()
        store.enqueue_job(job, submitted_at=BASE_TIME)
        if leased:
            assert (
                store.claim_next_job(
                    worker_id="worker_a",
                    claimed_at=BASE_TIME + timedelta(minutes=1),
                    lease_duration=timedelta(minutes=5),
                )
                is not None
            )
        response = _adapter(store).execute(f"analysis-artifact-for-job {job.job.job_id}")

    assert response.accepted is False
    assert response.code == "analysis_artifact_pending"
    assert response.job_id == job.job.job_id
    expected_status = "leased" if leased else "queued"
    assert f"Status: {expected_status}" in response.details


def test_artifact_for_failed_job_preserves_controlled_error(tmp_path) -> None:
    with V2SQLiteAnalysisStore(tmp_path / "analysis.sqlite3") as store:
        job = _job_envelope()
        store.enqueue_job(job, submitted_at=BASE_TIME)
        claimed = store.claim_next_job(
            worker_id="worker_a",
            claimed_at=BASE_TIME + timedelta(minutes=1),
            lease_duration=timedelta(minutes=5),
        )
        assert claimed is not None
        store.fail_job(
            job.job.job_id,
            worker_id="worker_a",
            lease_token=claimed.lease_token or "",
            failed_at=BASE_TIME + timedelta(minutes=2),
            error="Retained bytes failed integrity verification.",
            retryable=False,
        )
        response = _adapter(store).execute(f"analysis-artifact-for-job {job.job.job_id}")

    assert response.accepted is False
    assert response.code == "analysis_artifact_unavailable"
    assert "Error: Retained bytes failed integrity verification." in response.details


def test_unknown_job_returns_stable_error_code(tmp_path) -> None:
    with V2SQLiteAnalysisStore(tmp_path / "analysis.sqlite3") as store:
        response = _adapter(store).execute("analysis-status missing_job")

    assert response.accepted is False
    assert response.code == "analysis_job_not_found"
    assert response.job_id == "missing_job"


def test_unknown_artifact_returns_stable_error_code(tmp_path) -> None:
    with V2SQLiteAnalysisStore(tmp_path / "analysis.sqlite3") as store:
        response = _adapter(store).execute("analysis-artifact missing_artifact")

    assert response.accepted is False
    assert response.code == "analysis_artifact_not_found"
    assert response.artifact_id == "missing_artifact"


def test_unknown_job_artifact_lookup_reports_job_not_found(tmp_path) -> None:
    with V2SQLiteAnalysisStore(tmp_path / "analysis.sqlite3") as store:
        response = _adapter(store).execute("analysis-artifact-for-job missing_job")

    assert response.code == "analysis_job_not_found"
    assert response.job_id == "missing_job"


def test_persistence_integrity_error_is_not_disclosed(monkeypatch, tmp_path) -> None:
    with V2SQLiteAnalysisStore(tmp_path / "analysis.sqlite3") as store:
        service = V2AnalysisPresentationService(store)

        def unsafe_read(_job_id: str):
            raise V2AnalysisArtifactNotFoundError("private storage detail")

        monkeypatch.setattr(service, "get_artifact", unsafe_read)
        response = V2AnalysisTextCommandAdapter(service).execute("analysis-artifact missing")

    assert response.code == "analysis_artifact_not_found"
    assert "private storage detail" not in response.to_text()


def test_general_persistence_failure_has_generic_message(monkeypatch, tmp_path) -> None:
    with V2SQLiteAnalysisStore(tmp_path / "analysis.sqlite3") as store:
        service = V2AnalysisPresentationService(store)

        def unsafe_read(_job_id: str):
            from uniflora.engine.v2 import V2AnalysisPersistenceError

            raise V2AnalysisPersistenceError("database internals")

        monkeypatch.setattr(service, "get_status", unsafe_read)
        response = V2AnalysisTextCommandAdapter(service).execute("analysis-status job_1")

    assert response.code == "analysis_storage_error"
    assert response.summary == "Analysis records could not be read safely."
    assert "database internals" not in response.to_text()
