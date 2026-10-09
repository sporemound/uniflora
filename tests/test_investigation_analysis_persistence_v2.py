from __future__ import annotations

import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from uniflora.engine.v2 import (
    V2AnalysisArtifactNotFoundError,
    V2AnalysisDerivedValue,
    V2AnalysisInput,
    V2AnalysisJob,
    V2AnalysisJobConflictError,
    V2AnalysisJobNotFoundError,
    V2AnalysisJobStatus,
    V2AnalysisLeaseError,
    V2AnalysisMethod,
    V2AnalysisParameter,
    V2AnalysisPersistenceError,
    V2AnalysisResultConflictError,
    V2AnalysisUncertainty,
    V2SoftwareVersion,
    V2SQLiteAnalysisStore,
    calculate_dataset_hash,
    create_analysis_artifact_envelope,
    create_analysis_job_envelope,
)

BASE_TIME = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)
LEASE_DURATION = timedelta(minutes=10)


def _job_envelope(
    job_id: str = "job_phase_alignment",
    *,
    payload: bytes = b"retained-input-bytes",
    stream_id: str = "investigation_alpha",
):
    job = V2AnalysisJob(
        job_id=job_id,
        stream_id=stream_id,
        position_id="boundary_event",
        requested_by_player_id="player_a",
        method=V2AnalysisMethod(
            method_id="cross_source_phase_alignment",
            version="1.0.0",
            implementation="uniflora.science.phase_alignment",
            description=("Estimate timing alignment without inferring a physical trajectory."),
        ),
        inputs=(
            V2AnalysisInput(
                dataset_id=f"{job_id}_input",
                source_evidence_id="optical_record",
                content_hash=calculate_dataset_hash(payload),
                byte_length=len(payload),
                media_type="application/octet-stream",
                provenance="Retained source bytes.",
            ),
        ),
        parameters=(
            V2AnalysisParameter.from_value(
                "window_size",
                256,
                unit="samples",
            ),
        ),
        output_kind="phase_alignment_report",
    )
    return create_analysis_job_envelope(job)


def _artifact_envelope(
    job_envelope,
    *,
    artifact_id: str | None = None,
    offset: float = 0.018,
):
    return create_analysis_artifact_envelope(
        job_envelope,
        artifact_id=artifact_id or f"artifact_{job_envelope.job.job_id}",
        derived_values=(
            V2AnalysisDerivedValue.from_value(
                "relative_offset",
                offset,
                unit="seconds",
            ),
        ),
        uncertainties=(
            V2AnalysisUncertainty.quantified(
                "clock_alignment",
                "Station clocks bound absolute alignment.",
                0.006,
                unit="seconds",
            ),
        ),
        limitations=("The result does not establish source distance.",),
        software_versions=(V2SoftwareVersion(name="uniflora-analysis", version="0.1.0"),),
        provenance=("Produced by a local analysis worker from hashed inputs.",),
    )


def _enqueue_and_claim(store, envelope=None, *, worker_id="worker_a"):
    envelope = envelope or _job_envelope()
    store.enqueue_job(envelope, submitted_at=BASE_TIME)
    claimed = store.claim_next_job(
        worker_id=worker_id,
        claimed_at=BASE_TIME + timedelta(minutes=1),
        lease_duration=LEASE_DURATION,
    )
    assert claimed is not None
    return envelope, claimed


def test_enqueue_persists_a_queued_job(tmp_path) -> None:
    database = tmp_path / "analysis.sqlite3"
    envelope = _job_envelope()

    with V2SQLiteAnalysisStore(database) as store:
        stored = store.enqueue_job(envelope, submitted_at=BASE_TIME)

        assert stored.envelope == envelope
        assert stored.status is V2AnalysisJobStatus.QUEUED
        assert stored.attempt_count == 0
        assert stored.lease_token is None
        assert stored.artifact_id is None
        assert store.get_artifact_for_job(stored.job_id) is None


def test_enqueue_is_idempotent_for_the_same_canonical_job(tmp_path) -> None:
    database = tmp_path / "analysis.sqlite3"
    envelope = _job_envelope()

    with V2SQLiteAnalysisStore(database) as store:
        first = store.enqueue_job(envelope, submitted_at=BASE_TIME)
        second = store.enqueue_job(
            envelope,
            submitted_at=BASE_TIME + timedelta(hours=1),
        )

        assert second == first
        assert second.submitted_at == BASE_TIME
        assert len(store.list_jobs()) == 1


def test_reused_job_id_with_different_hash_is_rejected(tmp_path) -> None:
    database = tmp_path / "analysis.sqlite3"

    with V2SQLiteAnalysisStore(database) as store:
        store.enqueue_job(_job_envelope(), submitted_at=BASE_TIME)

        with pytest.raises(V2AnalysisJobConflictError, match="different"):
            store.enqueue_job(
                _job_envelope(payload=b"changed-input"),
                submitted_at=BASE_TIME,
            )


def test_claims_jobs_in_submission_order(tmp_path) -> None:
    database = tmp_path / "analysis.sqlite3"

    with V2SQLiteAnalysisStore(database) as store:
        later = _job_envelope("job_later")
        earlier = _job_envelope("job_earlier")
        store.enqueue_job(later, submitted_at=BASE_TIME + timedelta(minutes=1))
        store.enqueue_job(earlier, submitted_at=BASE_TIME)

        claimed = store.claim_next_job(
            worker_id="worker_a",
            claimed_at=BASE_TIME + timedelta(minutes=2),
            lease_duration=LEASE_DURATION,
        )

        assert claimed is not None
        assert claimed.job_id == "job_earlier"
        assert claimed.status is V2AnalysisJobStatus.LEASED
        assert claimed.attempt_count == 1
        assert claimed.lease_worker_id == "worker_a"
        assert len(claimed.lease_token or "") == 64


def test_unexpired_lease_is_not_claimed_by_another_worker(tmp_path) -> None:
    database = tmp_path / "analysis.sqlite3"

    with V2SQLiteAnalysisStore(database) as store:
        _enqueue_and_claim(store)

        claimed = store.claim_next_job(
            worker_id="worker_b",
            claimed_at=BASE_TIME + timedelta(minutes=5),
            lease_duration=LEASE_DURATION,
        )

        assert claimed is None


def test_expired_lease_is_reclaimed_with_new_token(tmp_path) -> None:
    database = tmp_path / "analysis.sqlite3"

    with V2SQLiteAnalysisStore(database) as store:
        _, first = _enqueue_and_claim(store)
        second = store.claim_next_job(
            worker_id="worker_b",
            claimed_at=BASE_TIME + timedelta(minutes=12),
            lease_duration=LEASE_DURATION,
        )

        assert second is not None
        assert second.job_id == first.job_id
        assert second.attempt_count == 2
        assert second.lease_worker_id == "worker_b"
        assert second.lease_token != first.lease_token


def test_lease_renewal_extends_the_same_lease(tmp_path) -> None:
    database = tmp_path / "analysis.sqlite3"

    with V2SQLiteAnalysisStore(database) as store:
        _, claimed = _enqueue_and_claim(store)
        renewed = store.renew_lease(
            claimed.job_id,
            worker_id="worker_a",
            lease_token=claimed.lease_token or "",
            renewed_at=BASE_TIME + timedelta(minutes=5),
            lease_duration=timedelta(minutes=20),
        )

        assert renewed.lease_token == claimed.lease_token
        assert renewed.attempt_count == 1
        assert renewed.lease_expires_at == BASE_TIME + timedelta(minutes=25)


def test_wrong_worker_or_token_cannot_renew_a_lease(tmp_path) -> None:
    database = tmp_path / "analysis.sqlite3"

    with V2SQLiteAnalysisStore(database) as store:
        _, claimed = _enqueue_and_claim(store)

        with pytest.raises(V2AnalysisLeaseError, match="different worker"):
            store.renew_lease(
                claimed.job_id,
                worker_id="worker_b",
                lease_token=claimed.lease_token or "",
                renewed_at=BASE_TIME + timedelta(minutes=2),
                lease_duration=LEASE_DURATION,
            )

        with pytest.raises(V2AnalysisLeaseError, match="token"):
            store.renew_lease(
                claimed.job_id,
                worker_id="worker_a",
                lease_token="wrong-token",
                renewed_at=BASE_TIME + timedelta(minutes=2),
                lease_duration=LEASE_DURATION,
            )


def test_retryable_failure_returns_job_to_queue(tmp_path) -> None:
    database = tmp_path / "analysis.sqlite3"

    with V2SQLiteAnalysisStore(database) as store:
        _, claimed = _enqueue_and_claim(store)
        failed = store.fail_job(
            claimed.job_id,
            worker_id="worker_a",
            lease_token=claimed.lease_token or "",
            failed_at=BASE_TIME + timedelta(minutes=2),
            error="Optional science dependency was unavailable.",
            retryable=True,
        )

        assert failed.status is V2AnalysisJobStatus.QUEUED
        assert failed.last_error == "Optional science dependency was unavailable."
        assert failed.lease_token is None

        retried = store.claim_next_job(
            worker_id="worker_b",
            claimed_at=BASE_TIME + timedelta(minutes=3),
            lease_duration=LEASE_DURATION,
        )
        assert retried is not None
        assert retried.attempt_count == 2


def test_terminal_failure_is_not_claimable(tmp_path) -> None:
    database = tmp_path / "analysis.sqlite3"

    with V2SQLiteAnalysisStore(database) as store:
        _, claimed = _enqueue_and_claim(store)
        failed = store.fail_job(
            claimed.job_id,
            worker_id="worker_a",
            lease_token=claimed.lease_token or "",
            failed_at=BASE_TIME + timedelta(minutes=2),
            error="Input format is unsupported by this method version.",
            retryable=False,
        )

        assert failed.status is V2AnalysisJobStatus.FAILED
        assert (
            store.claim_next_job(
                worker_id="worker_b",
                claimed_at=BASE_TIME + timedelta(hours=1),
                lease_duration=LEASE_DURATION,
            )
            is None
        )


def test_stale_lease_cannot_submit_an_artifact(tmp_path) -> None:
    database = tmp_path / "analysis.sqlite3"

    with V2SQLiteAnalysisStore(database) as store:
        envelope, first = _enqueue_and_claim(store)
        second = store.claim_next_job(
            worker_id="worker_b",
            claimed_at=BASE_TIME + timedelta(minutes=12),
            lease_duration=LEASE_DURATION,
        )
        assert second is not None

        with pytest.raises(V2AnalysisLeaseError, match="different worker"):
            store.submit_artifact(
                envelope.job.job_id,
                _artifact_envelope(envelope),
                worker_id="worker_a",
                lease_token=first.lease_token or "",
                completed_at=BASE_TIME + timedelta(minutes=13),
            )


def test_successful_submission_completes_job_and_supports_retrieval(tmp_path) -> None:
    database = tmp_path / "analysis.sqlite3"

    with V2SQLiteAnalysisStore(database) as store:
        envelope, claimed = _enqueue_and_claim(store)
        artifact_envelope = _artifact_envelope(envelope)
        stored_artifact = store.submit_artifact(
            claimed.job_id,
            artifact_envelope,
            worker_id="worker_a",
            lease_token=claimed.lease_token or "",
            completed_at=BASE_TIME + timedelta(minutes=2),
        )
        completed = store.get_job(claimed.job_id)

        assert completed.status is V2AnalysisJobStatus.COMPLETED
        assert completed.artifact_id == artifact_envelope.artifact.artifact_id
        assert completed.lease_token is None
        assert stored_artifact.envelope == artifact_envelope
        assert store.get_artifact(stored_artifact.artifact_id) == stored_artifact
        assert store.get_artifact_for_job(claimed.job_id) == stored_artifact


def test_identical_result_submission_is_idempotent_after_completion(tmp_path) -> None:
    database = tmp_path / "analysis.sqlite3"

    with V2SQLiteAnalysisStore(database) as store:
        envelope, claimed = _enqueue_and_claim(store)
        artifact_envelope = _artifact_envelope(envelope)
        first = store.submit_artifact(
            claimed.job_id,
            artifact_envelope,
            worker_id="worker_a",
            lease_token=claimed.lease_token or "",
            completed_at=BASE_TIME + timedelta(minutes=2),
        )
        second = store.submit_artifact(
            claimed.job_id,
            artifact_envelope,
            worker_id="worker_a",
            lease_token=claimed.lease_token or "",
            completed_at=BASE_TIME + timedelta(minutes=3),
        )

        assert second == first


def test_different_result_is_rejected_after_completion(tmp_path) -> None:
    database = tmp_path / "analysis.sqlite3"

    with V2SQLiteAnalysisStore(database) as store:
        envelope, claimed = _enqueue_and_claim(store)
        store.submit_artifact(
            claimed.job_id,
            _artifact_envelope(envelope),
            worker_id="worker_a",
            lease_token=claimed.lease_token or "",
            completed_at=BASE_TIME + timedelta(minutes=2),
        )

        with pytest.raises(V2AnalysisResultConflictError, match="different"):
            store.submit_artifact(
                claimed.job_id,
                _artifact_envelope(envelope, offset=0.019),
                worker_id="worker_a",
                lease_token=claimed.lease_token or "",
                completed_at=BASE_TIME + timedelta(minutes=3),
            )


def test_artifact_must_match_the_persisted_job(tmp_path) -> None:
    database = tmp_path / "analysis.sqlite3"
    first_job = _job_envelope("job_first")
    other_job = _job_envelope("job_other", payload=b"other")

    with V2SQLiteAnalysisStore(database) as store:
        _, claimed = _enqueue_and_claim(store, first_job)
        mismatched = _artifact_envelope(other_job)

        with pytest.raises(V2AnalysisResultConflictError, match="job ID"):
            store.submit_artifact(
                claimed.job_id,
                mismatched,
                worker_id="worker_a",
                lease_token=claimed.lease_token or "",
                completed_at=BASE_TIME + timedelta(minutes=2),
            )


def test_artifact_id_cannot_be_reused_for_another_job(tmp_path) -> None:
    database = tmp_path / "analysis.sqlite3"
    first_job = _job_envelope("job_first")
    second_job = _job_envelope("job_second", payload=b"second")

    with V2SQLiteAnalysisStore(database) as store:
        _, first_claim = _enqueue_and_claim(store, first_job)
        store.submit_artifact(
            first_claim.job_id,
            _artifact_envelope(first_job, artifact_id="artifact_shared"),
            worker_id="worker_a",
            lease_token=first_claim.lease_token or "",
            completed_at=BASE_TIME + timedelta(minutes=2),
        )

        store.enqueue_job(
            second_job,
            submitted_at=BASE_TIME + timedelta(minutes=3),
        )
        second_claim = store.claim_next_job(
            worker_id="worker_b",
            claimed_at=BASE_TIME + timedelta(minutes=4),
            lease_duration=LEASE_DURATION,
        )
        assert second_claim is not None

        with pytest.raises(V2AnalysisJobConflictError, match="artifact ID"):
            store.submit_artifact(
                second_claim.job_id,
                _artifact_envelope(second_job, artifact_id="artifact_shared"),
                worker_id="worker_b",
                lease_token=second_claim.lease_token or "",
                completed_at=BASE_TIME + timedelta(minutes=5),
            )


def test_store_survives_close_and_reopen(tmp_path) -> None:
    database = tmp_path / "analysis.sqlite3"
    envelope = _job_envelope()

    with V2SQLiteAnalysisStore(database) as store:
        _, claimed = _enqueue_and_claim(store, envelope)
        artifact = store.submit_artifact(
            claimed.job_id,
            _artifact_envelope(envelope),
            worker_id="worker_a",
            lease_token=claimed.lease_token or "",
            completed_at=BASE_TIME + timedelta(minutes=2),
        )

    with V2SQLiteAnalysisStore(database) as reopened:
        assert reopened.get_job(envelope.job.job_id).status is (V2AnalysisJobStatus.COMPLETED)
        assert reopened.get_artifact(artifact.artifact_id) == artifact


def test_tampered_persisted_job_is_detected(tmp_path) -> None:
    database = tmp_path / "analysis.sqlite3"

    with V2SQLiteAnalysisStore(database) as store:
        store.enqueue_job(_job_envelope(), submitted_at=BASE_TIME)

    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            UPDATE v2_analysis_jobs
            SET job_json = ?
            WHERE job_id = ?
            """,
            (b"{}", "job_phase_alignment"),
        )
        connection.commit()

    with V2SQLiteAnalysisStore(database) as reopened:
        with pytest.raises(V2AnalysisPersistenceError, match="job is invalid"):
            reopened.get_job("job_phase_alignment")


def test_tampered_persisted_artifact_is_detected(tmp_path) -> None:
    database = tmp_path / "analysis.sqlite3"
    envelope = _job_envelope()

    with V2SQLiteAnalysisStore(database) as store:
        _, claimed = _enqueue_and_claim(store, envelope)
        artifact = store.submit_artifact(
            claimed.job_id,
            _artifact_envelope(envelope),
            worker_id="worker_a",
            lease_token=claimed.lease_token or "",
            completed_at=BASE_TIME + timedelta(minutes=2),
        )

    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            UPDATE v2_analysis_artifacts
            SET artifact_json = ?
            WHERE artifact_id = ?
            """,
            (b"{}", artifact.artifact_id),
        )
        connection.commit()

    with V2SQLiteAnalysisStore(database) as reopened:
        with pytest.raises(
            V2AnalysisPersistenceError,
            match="artifact is invalid",
        ):
            reopened.get_artifact(artifact.artifact_id)


def test_missing_jobs_and_artifacts_raise_specific_errors(tmp_path) -> None:
    database = tmp_path / "analysis.sqlite3"

    with V2SQLiteAnalysisStore(database) as store:
        with pytest.raises(V2AnalysisJobNotFoundError):
            store.get_job("missing_job")

        with pytest.raises(V2AnalysisArtifactNotFoundError):
            store.get_artifact("missing_artifact")


def test_timestamps_must_be_timezone_aware(tmp_path) -> None:
    database = tmp_path / "analysis.sqlite3"

    with V2SQLiteAnalysisStore(database) as store:
        with pytest.raises(ValueError, match="timezone-aware"):
            store.enqueue_job(
                _job_envelope(),
                submitted_at=datetime(2026, 7, 25, 12, 0),
            )


def test_stored_job_rejects_inconsistent_status_metadata(tmp_path) -> None:
    database = tmp_path / "analysis.sqlite3"

    with V2SQLiteAnalysisStore(database) as store:
        stored = store.enqueue_job(_job_envelope(), submitted_at=BASE_TIME)

        with pytest.raises(ValueError, match="lease metadata"):
            replace(
                stored,
                status=V2AnalysisJobStatus.LEASED,
            )
