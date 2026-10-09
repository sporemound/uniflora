from __future__ import annotations

from collections import deque
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from uniflora.engine.v2 import (
    V2AnalysisDatasetResolutionError,
    V2AnalysisDerivedValue,
    V2AnalysisExecutionResult,
    V2AnalysisInput,
    V2AnalysisJob,
    V2AnalysisJobStatus,
    V2AnalysisLeaseError,
    V2AnalysisMethod,
    V2AnalysisMethodExecutionError,
    V2AnalysisMethodNotRegisteredError,
    V2AnalysisMethodRegistrationError,
    V2AnalysisMethodRegistry,
    V2AnalysisParameter,
    V2AnalysisUncertainty,
    V2AnalysisWorker,
    V2AnalysisWorkerOutcomeStatus,
    V2SoftwareVersion,
    V2SQLiteAnalysisStore,
    calculate_dataset_hash,
    calculate_worker_artifact_id,
    create_analysis_job_envelope,
)

BASE_TIME = datetime(2026, 7, 25, 15, 0, tzinfo=UTC)
LEASE_DURATION = timedelta(minutes=10)
PAYLOAD = b"retained-analysis-input"


def _method(
    *,
    version: str = "1.0.0",
    description: str = "Compare retained timing constraints.",
) -> V2AnalysisMethod:
    return V2AnalysisMethod(
        method_id="cross_source_phase_alignment",
        version=version,
        implementation="uniflora.science.phase_alignment",
        description=description,
    )


def _job_envelope(
    job_id: str = "job_phase_alignment",
    *,
    method: V2AnalysisMethod | None = None,
    payload: bytes = PAYLOAD,
):
    return create_analysis_job_envelope(
        V2AnalysisJob(
            job_id=job_id,
            stream_id="investigation_alpha",
            position_id="boundary_event",
            requested_by_player_id="player_a",
            method=method or _method(),
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
    )


def _result(offset: float = 0.018) -> V2AnalysisExecutionResult:
    return V2AnalysisExecutionResult(
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
        provenance=("Produced from exact retained input bytes.",),
    )


class _Resolver:
    def __init__(self, payload=PAYLOAD) -> None:
        self.payload = payload
        self.seen = []

    def resolve(self, analysis_input):
        self.seen.append(analysis_input)
        if isinstance(self.payload, BaseException):
            raise self.payload
        return self.payload


class _SequenceResolver:
    def __init__(self, values) -> None:
        self.values = deque(values)

    def resolve(self, analysis_input):
        value = self.values.popleft()
        if isinstance(value, BaseException):
            raise value
        return value


class _Clock:
    def __init__(self, *values: datetime) -> None:
        self.values = deque(values)

    def __call__(self) -> datetime:
        return self.values.popleft()


def _worker(
    store,
    *,
    registry=None,
    resolver=None,
    clock=None,
    worker_id="worker_a",
):
    registry = registry or V2AnalysisMethodRegistry()
    if not registry.registered_methods():
        registry.register(_method(), lambda request: _result())
    return V2AnalysisWorker(
        store=store,
        registry=registry,
        dataset_resolver=resolver or _Resolver(),
        worker_id=worker_id,
        lease_duration=LEASE_DURATION,
        clock=clock or _Clock(BASE_TIME, BASE_TIME + timedelta(minutes=1)),
    )


def test_registry_dispatches_only_an_exact_method_version() -> None:
    registry = V2AnalysisMethodRegistry()
    first = _method(version="1.0.0")
    second = _method(version="2.0.0")
    first_handler = lambda request: _result(0.01)
    second_handler = lambda request: _result(0.02)
    registry.register(second, second_handler)
    registry.register(first, first_handler)

    assert registry.resolve(first) is first_handler
    assert registry.resolve(second) is second_handler
    assert registry.registered_methods() == (first, second)

    with pytest.raises(V2AnalysisMethodNotRegisteredError, match="3.0.0"):
        registry.resolve(_method(version="3.0.0"))


def test_registry_rejects_duplicate_method_versions() -> None:
    registry = V2AnalysisMethodRegistry()
    registry.register(_method(), lambda request: _result())

    with pytest.raises(V2AnalysisMethodRegistrationError, match="already"):
        registry.register(_method(), lambda request: _result())


def test_registry_rejects_persisted_method_metadata_drift() -> None:
    registry = V2AnalysisMethodRegistry()
    registry.register(_method(), lambda request: _result())

    with pytest.raises(V2AnalysisMethodNotRegisteredError, match="metadata"):
        registry.resolve(_method(description="Changed after job submission."))


def test_worker_returns_idle_without_claiming_work(tmp_path) -> None:
    with V2SQLiteAnalysisStore(tmp_path / "analysis.sqlite3") as store:
        outcome = _worker(store).run_once()

    assert outcome.status is V2AnalysisWorkerOutcomeStatus.IDLE
    assert outcome.job_id is None


def test_worker_executes_one_job_and_persists_verified_artifact(tmp_path) -> None:
    envelope = _job_envelope()
    resolver = _Resolver()
    seen_requests = []
    registry = V2AnalysisMethodRegistry()

    def handler(request):
        seen_requests.append(request)
        assert request.input_for(envelope.job.inputs[0].dataset_id).data == PAYLOAD
        return _result()

    registry.register(envelope.job.method, handler)

    with V2SQLiteAnalysisStore(tmp_path / "analysis.sqlite3") as store:
        store.enqueue_job(envelope, submitted_at=BASE_TIME - timedelta(minutes=1))
        outcome = _worker(
            store,
            registry=registry,
            resolver=resolver,
        ).run_once()
        completed = store.get_job(envelope.job.job_id)
        artifact = store.get_artifact_for_job(envelope.job.job_id)

    assert outcome.status is V2AnalysisWorkerOutcomeStatus.COMPLETED
    assert outcome.artifact_id == calculate_worker_artifact_id(envelope)
    assert completed.status is V2AnalysisJobStatus.COMPLETED
    assert artifact is not None
    assert artifact.envelope.artifact.provenance == ("Produced from exact retained input bytes.",)
    assert len(seen_requests) == 1
    assert resolver.seen == [envelope.job.inputs[0]]


def test_one_worker_run_claims_at_most_one_job(tmp_path) -> None:
    first = _job_envelope("job_first")
    second = _job_envelope("job_second")

    with V2SQLiteAnalysisStore(tmp_path / "analysis.sqlite3") as store:
        store.enqueue_job(first, submitted_at=BASE_TIME - timedelta(minutes=2))
        store.enqueue_job(second, submitted_at=BASE_TIME - timedelta(minutes=1))
        outcome = _worker(store).run_once()

        assert outcome.job_id == "job_first"
        assert store.get_job("job_first").status is V2AnalysisJobStatus.COMPLETED
        assert store.get_job("job_second").status is V2AnalysisJobStatus.QUEUED


def test_hash_mismatch_is_a_terminal_failure(tmp_path) -> None:
    envelope = _job_envelope()

    with V2SQLiteAnalysisStore(tmp_path / "analysis.sqlite3") as store:
        store.enqueue_job(envelope, submitted_at=BASE_TIME)
        outcome = _worker(store, resolver=_Resolver(b"changed-input")).run_once()
        failed = store.get_job(envelope.job.job_id)

    assert outcome.status is V2AnalysisWorkerOutcomeStatus.FAILED
    assert "hash" in (outcome.error or "") or "byte length" in (outcome.error or "")
    assert failed.status is V2AnalysisJobStatus.FAILED


def test_resolver_non_byte_content_is_a_terminal_failure(tmp_path) -> None:
    envelope = _job_envelope()
    resolver = _Resolver(payload="not bytes")

    with V2SQLiteAnalysisStore(tmp_path / "analysis.sqlite3") as store:
        store.enqueue_job(envelope, submitted_at=BASE_TIME)
        outcome = _worker(store, resolver=resolver).run_once()

    assert outcome.status is V2AnalysisWorkerOutcomeStatus.FAILED
    assert "non-byte" in (outcome.error or "")


def test_controlled_retryable_dataset_failure_returns_job_to_queue(tmp_path) -> None:
    envelope = _job_envelope()
    resolver = _Resolver(
        V2AnalysisDatasetResolutionError(
            "Dataset volume is temporarily unavailable.",
            retryable=True,
        )
    )

    with V2SQLiteAnalysisStore(tmp_path / "analysis.sqlite3") as store:
        store.enqueue_job(envelope, submitted_at=BASE_TIME)
        outcome = _worker(store, resolver=resolver).run_once()
        queued = store.get_job(envelope.job.job_id)

    assert outcome.status is V2AnalysisWorkerOutcomeStatus.RETRY_QUEUED
    assert queued.status is V2AnalysisJobStatus.QUEUED
    assert queued.last_error == "Dataset volume is temporarily unavailable."


def test_controlled_terminal_dataset_failure_marks_job_failed(tmp_path) -> None:
    envelope = _job_envelope()
    resolver = _Resolver(
        V2AnalysisDatasetResolutionError(
            "Dataset format is unsupported.",
            retryable=False,
        )
    )

    with V2SQLiteAnalysisStore(tmp_path / "analysis.sqlite3") as store:
        store.enqueue_job(envelope, submitted_at=BASE_TIME)
        outcome = _worker(store, resolver=resolver).run_once()

    assert outcome.status is V2AnalysisWorkerOutcomeStatus.FAILED


def test_unexpected_resolver_exception_is_reported_without_traceback(tmp_path) -> None:
    envelope = _job_envelope()
    resolver = _Resolver(OSError("volume offline"))

    with V2SQLiteAnalysisStore(tmp_path / "analysis.sqlite3") as store:
        store.enqueue_job(envelope, submitted_at=BASE_TIME)
        outcome = _worker(store, resolver=resolver).run_once()

    assert outcome.status is V2AnalysisWorkerOutcomeStatus.RETRY_QUEUED
    assert outcome.error == (
        "dataset resolver raised an unexpected exception: OSError: volume offline"
    )
    assert "Traceback" not in (outcome.error or "")


def test_unregistered_method_is_a_terminal_failure(tmp_path) -> None:
    envelope = _job_envelope()
    registry = V2AnalysisMethodRegistry()

    with V2SQLiteAnalysisStore(tmp_path / "analysis.sqlite3") as store:
        store.enqueue_job(envelope, submitted_at=BASE_TIME)
        worker = V2AnalysisWorker(
            store=store,
            registry=registry,
            dataset_resolver=_Resolver(),
            worker_id="worker_a",
            lease_duration=LEASE_DURATION,
            clock=_Clock(BASE_TIME, BASE_TIME + timedelta(minutes=1)),
        )
        outcome = worker.run_once()

    assert outcome.status is V2AnalysisWorkerOutcomeStatus.FAILED
    assert "not registered" in (outcome.error or "")


def test_registered_metadata_drift_is_a_terminal_failure(tmp_path) -> None:
    job_method = _method(description="Persisted description.")
    envelope = _job_envelope(method=job_method)
    registry = V2AnalysisMethodRegistry()
    registry.register(
        _method(description="Locally changed description."),
        lambda request: _result(),
    )

    with V2SQLiteAnalysisStore(tmp_path / "analysis.sqlite3") as store:
        store.enqueue_job(envelope, submitted_at=BASE_TIME)
        outcome = _worker(store, registry=registry).run_once()

    assert outcome.status is V2AnalysisWorkerOutcomeStatus.FAILED
    assert "metadata" in (outcome.error or "")


def test_controlled_retryable_method_failure_returns_job_to_queue(tmp_path) -> None:
    envelope = _job_envelope()
    registry = V2AnalysisMethodRegistry()

    def handler(request):
        raise V2AnalysisMethodExecutionError(
            "Optional dependency is unavailable.",
            retryable=True,
        )

    registry.register(envelope.job.method, handler)

    with V2SQLiteAnalysisStore(tmp_path / "analysis.sqlite3") as store:
        store.enqueue_job(envelope, submitted_at=BASE_TIME)
        outcome = _worker(store, registry=registry).run_once()

    assert outcome.status is V2AnalysisWorkerOutcomeStatus.RETRY_QUEUED


def test_controlled_terminal_method_failure_marks_job_failed(tmp_path) -> None:
    envelope = _job_envelope()
    registry = V2AnalysisMethodRegistry()

    def handler(request):
        raise V2AnalysisMethodExecutionError(
            "Input shape is invalid for this method.",
            retryable=False,
        )

    registry.register(envelope.job.method, handler)

    with V2SQLiteAnalysisStore(tmp_path / "analysis.sqlite3") as store:
        store.enqueue_job(envelope, submitted_at=BASE_TIME)
        outcome = _worker(store, registry=registry).run_once()

    assert outcome.status is V2AnalysisWorkerOutcomeStatus.FAILED


def test_unexpected_method_exception_is_a_controlled_terminal_failure(tmp_path) -> None:
    envelope = _job_envelope()
    registry = V2AnalysisMethodRegistry()

    def handler(request):
        raise ArithmeticError("singular matrix")

    registry.register(envelope.job.method, handler)

    with V2SQLiteAnalysisStore(tmp_path / "analysis.sqlite3") as store:
        store.enqueue_job(envelope, submitted_at=BASE_TIME)
        outcome = _worker(store, registry=registry).run_once()

    assert outcome.status is V2AnalysisWorkerOutcomeStatus.FAILED
    assert outcome.error == (
        "analysis method raised an unexpected exception: ArithmeticError: singular matrix"
    )


def test_invalid_handler_return_type_is_a_terminal_failure(tmp_path) -> None:
    envelope = _job_envelope()
    registry = V2AnalysisMethodRegistry()
    registry.register(envelope.job.method, lambda request: {"offset": 0.018})

    with V2SQLiteAnalysisStore(tmp_path / "analysis.sqlite3") as store:
        store.enqueue_job(envelope, submitted_at=BASE_TIME)
        outcome = _worker(store, registry=registry).run_once()

    assert outcome.status is V2AnalysisWorkerOutcomeStatus.FAILED
    assert "invalid execution-result type" in (outcome.error or "")


def test_result_missing_required_uncertainty_is_a_terminal_failure(tmp_path) -> None:
    envelope = _job_envelope()
    registry = V2AnalysisMethodRegistry()
    malformed = replace(_result(), uncertainties=())
    registry.register(envelope.job.method, lambda request: malformed)

    with V2SQLiteAnalysisStore(tmp_path / "analysis.sqlite3") as store:
        store.enqueue_job(envelope, submitted_at=BASE_TIME)
        outcome = _worker(store, registry=registry).run_once()

    assert outcome.status is V2AnalysisWorkerOutcomeStatus.FAILED
    assert "uncertainty" in (outcome.error or "")


def test_retryable_failure_can_be_completed_by_a_later_attempt(tmp_path) -> None:
    envelope = _job_envelope()
    resolver = _SequenceResolver(
        [
            V2AnalysisDatasetResolutionError(
                "Dataset volume is temporarily unavailable.",
                retryable=True,
            ),
            PAYLOAD,
        ]
    )

    with V2SQLiteAnalysisStore(tmp_path / "analysis.sqlite3") as store:
        store.enqueue_job(envelope, submitted_at=BASE_TIME - timedelta(minutes=1))
        first = _worker(
            store,
            resolver=resolver,
            clock=_Clock(BASE_TIME, BASE_TIME + timedelta(minutes=1)),
        ).run_once()
        second = _worker(
            store,
            resolver=resolver,
            worker_id="worker_b",
            clock=_Clock(
                BASE_TIME + timedelta(minutes=2),
                BASE_TIME + timedelta(minutes=3),
            ),
        ).run_once()
        completed = store.get_job(envelope.job.job_id)

    assert first.status is V2AnalysisWorkerOutcomeStatus.RETRY_QUEUED
    assert second.status is V2AnalysisWorkerOutcomeStatus.COMPLETED
    assert second.attempt_count == 2
    assert completed.status is V2AnalysisJobStatus.COMPLETED


def test_expired_lease_submission_is_not_hidden_by_worker_failure_handling(
    tmp_path,
) -> None:
    envelope = _job_envelope()

    with V2SQLiteAnalysisStore(tmp_path / "analysis.sqlite3") as store:
        store.enqueue_job(envelope, submitted_at=BASE_TIME - timedelta(minutes=1))
        worker = _worker(
            store,
            clock=_Clock(BASE_TIME, BASE_TIME + timedelta(minutes=11)),
        )

        with pytest.raises(V2AnalysisLeaseError, match="expired"):
            worker.run_once()

        assert store.get_job(envelope.job.job_id).status is (V2AnalysisJobStatus.LEASED)


def test_worker_rejects_naive_clock_values_before_claiming(tmp_path) -> None:
    with V2SQLiteAnalysisStore(tmp_path / "analysis.sqlite3") as store:
        worker = _worker(
            store,
            clock=_Clock(datetime(2026, 7, 25, 15, 0)),
        )

        with pytest.raises(ValueError, match="timezone-aware"):
            worker.run_once()
