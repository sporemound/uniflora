from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Protocol, runtime_checkable

from uniflora.engine.v2.analysis import (
    V2AnalysisDerivedValue,
    V2AnalysisError,
    V2AnalysisInput,
    V2AnalysisJobEnvelope,
    V2AnalysisMethod,
    V2AnalysisUncertainty,
    V2SoftwareVersion,
    calculate_dataset_hash,
    create_analysis_artifact_envelope,
    verify_analysis_job_envelope,
)
from uniflora.engine.v2.analysis_persistence import (
    V2SQLiteAnalysisStore,
    V2StoredAnalysisJob,
)


class V2AnalysisWorkerError(RuntimeError):
    """Raised when an out-of-process analysis worker cannot execute safely."""


class V2AnalysisMethodRegistrationError(V2AnalysisWorkerError):
    """Raised when the method registry would become ambiguous."""


class V2AnalysisMethodNotRegisteredError(V2AnalysisWorkerError):
    """Raised when no exact method implementation is registered for a job."""


class V2AnalysisInputIntegrityError(V2AnalysisWorkerError):
    """Raised when resolved bytes do not match their retained input record."""


class V2AnalysisDatasetResolutionError(V2AnalysisWorkerError):
    """Controlled dataset-resolution failure with an explicit retry policy."""

    def __init__(self, message: str, *, retryable: bool) -> None:
        super().__init__(_require_nonblank(message, label="dataset error"))
        self.retryable = retryable


class V2AnalysisMethodExecutionError(V2AnalysisWorkerError):
    """Controlled method failure with an explicit retry policy."""

    def __init__(self, message: str, *, retryable: bool) -> None:
        super().__init__(_require_nonblank(message, label="method error"))
        self.retryable = retryable


def _require_nonblank(value: str, *, label: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{label} must not be blank")
    return normalized


def _require_positive_duration(value: timedelta) -> timedelta:
    if value <= timedelta(0):
        raise ValueError("worker lease duration must be positive")
    return value


def _require_aware_timestamp(value: datetime, *, label: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")
    return value


def _controlled_exception_statement(prefix: str, exc: BaseException) -> str:
    message = str(exc).strip()
    if message:
        return f"{prefix}: {type(exc).__name__}: {message}"
    return f"{prefix}: {type(exc).__name__}"


@runtime_checkable
class V2AnalysisDatasetResolver(Protocol):
    """Resolve retained bytes for one declared analysis input."""

    def resolve(
        self,
        analysis_input: V2AnalysisInput,
    ) -> bytes | bytearray | memoryview: ...


@dataclass(frozen=True, slots=True)
class V2ResolvedAnalysisInput:
    descriptor: V2AnalysisInput
    data: bytes

    def __post_init__(self) -> None:
        normalized = bytes(self.data)
        object.__setattr__(self, "data", normalized)

        if len(normalized) != self.descriptor.byte_length:
            raise V2AnalysisInputIntegrityError(
                f"dataset {self.descriptor.dataset_id!r} byte length does not "
                "match its retained input record"
            )

        if calculate_dataset_hash(normalized) != self.descriptor.content_hash:
            raise V2AnalysisInputIntegrityError(
                f"dataset {self.descriptor.dataset_id!r} hash does not match "
                "its retained input record"
            )

    @property
    def dataset_id(self) -> str:
        return self.descriptor.dataset_id


@dataclass(frozen=True, slots=True)
class V2AnalysisExecutionRequest:
    job_envelope: V2AnalysisJobEnvelope
    inputs: tuple[V2ResolvedAnalysisInput, ...]

    def __post_init__(self) -> None:
        job = verify_analysis_job_envelope(self.job_envelope)
        normalized = tuple(sorted(self.inputs, key=lambda value: value.dataset_id))

        if tuple(value.descriptor for value in normalized) != job.inputs:
            raise V2AnalysisInputIntegrityError(
                "resolved analysis inputs do not exactly match the job manifest"
            )

        object.__setattr__(self, "inputs", normalized)

    def input_for(self, dataset_id: str) -> V2ResolvedAnalysisInput:
        normalized = _require_nonblank(dataset_id, label="dataset ID")
        for resolved in self.inputs:
            if resolved.dataset_id == normalized:
                return resolved
        raise KeyError(normalized)


@dataclass(frozen=True, slots=True)
class V2AnalysisExecutionResult:
    derived_values: tuple[V2AnalysisDerivedValue, ...]
    uncertainties: tuple[V2AnalysisUncertainty, ...]
    limitations: tuple[str, ...]
    software_versions: tuple[V2SoftwareVersion, ...]
    provenance: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "derived_values", tuple(self.derived_values))
        object.__setattr__(self, "uncertainties", tuple(self.uncertainties))
        object.__setattr__(self, "limitations", tuple(self.limitations))
        object.__setattr__(self, "software_versions", tuple(self.software_versions))
        object.__setattr__(self, "provenance", tuple(self.provenance))


@runtime_checkable
class V2AnalysisMethodHandler(Protocol):
    """Execute one exact version of a scientific analysis method."""

    def __call__(
        self,
        request: V2AnalysisExecutionRequest,
    ) -> V2AnalysisExecutionResult: ...


@dataclass(frozen=True, slots=True)
class _RegisteredAnalysisMethod:
    method: V2AnalysisMethod
    handler: V2AnalysisMethodHandler


class V2AnalysisMethodRegistry:
    """Exact-version registry used by standalone scientific workers."""

    def __init__(self) -> None:
        self._entries: dict[tuple[str, str], _RegisteredAnalysisMethod] = {}

    def register(
        self,
        method: V2AnalysisMethod,
        handler: V2AnalysisMethodHandler,
    ) -> None:
        if not callable(handler):
            raise TypeError("analysis method handler must be callable")

        key = (method.method_id, method.version)
        if key in self._entries:
            raise V2AnalysisMethodRegistrationError(
                f"analysis method {method.method_id!r} version "
                f"{method.version!r} is already registered"
            )

        self._entries[key] = _RegisteredAnalysisMethod(
            method=method,
            handler=handler,
        )

    def resolve(self, method: V2AnalysisMethod) -> V2AnalysisMethodHandler:
        key = (method.method_id, method.version)
        registered = self._entries.get(key)

        if registered is None:
            raise V2AnalysisMethodNotRegisteredError(
                f"analysis method {method.method_id!r} version {method.version!r} is not registered"
            )

        if registered.method != method:
            raise V2AnalysisMethodNotRegisteredError(
                "registered analysis method metadata does not exactly match the persisted job"
            )

        return registered.handler

    def registered_methods(self) -> tuple[V2AnalysisMethod, ...]:
        return tuple(
            entry.method for _, entry in sorted(self._entries.items(), key=lambda item: item[0])
        )


class V2AnalysisWorkerOutcomeStatus(StrEnum):
    IDLE = "idle"
    COMPLETED = "completed"
    RETRY_QUEUED = "retry_queued"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class V2AnalysisWorkerOutcome:
    status: V2AnalysisWorkerOutcomeStatus
    job_id: str | None = None
    attempt_count: int | None = None
    artifact_id: str | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        if self.status is V2AnalysisWorkerOutcomeStatus.IDLE:
            if any(
                value is not None
                for value in (
                    self.job_id,
                    self.attempt_count,
                    self.artifact_id,
                    self.error,
                )
            ):
                raise ValueError("idle worker outcomes must not contain job metadata")
            return

        if self.job_id is None or self.attempt_count is None:
            raise ValueError("non-idle worker outcomes require job metadata")
        _require_nonblank(self.job_id, label="analysis job ID")
        if self.attempt_count < 1:
            raise ValueError("worker attempt count must be positive")

        if self.status is V2AnalysisWorkerOutcomeStatus.COMPLETED:
            if self.artifact_id is None or self.error is not None:
                raise ValueError("completed worker outcomes require an artifact and no error")
            _require_nonblank(self.artifact_id, label="analysis artifact ID")
        else:
            if self.error is None or self.artifact_id is not None:
                raise ValueError("failed worker outcomes require an error and no artifact")
            _require_nonblank(self.error, label="analysis worker error")


def calculate_worker_artifact_id(job_envelope: V2AnalysisJobEnvelope) -> str:
    verify_analysis_job_envelope(job_envelope)
    return f"artifact_{job_envelope.job_hash}"


class V2AnalysisWorker:
    """Claim and execute at most one persisted analysis job."""

    def __init__(
        self,
        *,
        store: V2SQLiteAnalysisStore,
        registry: V2AnalysisMethodRegistry,
        dataset_resolver: V2AnalysisDatasetResolver,
        worker_id: str,
        lease_duration: timedelta,
        clock: Callable[[], datetime] | None = None,
        artifact_id_factory: Callable[[V2AnalysisJobEnvelope], str] | None = None,
    ) -> None:
        self._store = store
        self._registry = registry
        self._dataset_resolver = dataset_resolver
        self._worker_id = _require_nonblank(worker_id, label="worker ID")
        self._lease_duration = _require_positive_duration(lease_duration)
        self._clock = clock or (lambda: datetime.now(UTC))
        self._artifact_id_factory = artifact_id_factory or calculate_worker_artifact_id

    def _now(self, *, label: str) -> datetime:
        return _require_aware_timestamp(self._clock(), label=label)

    def _resolve_inputs(
        self,
        envelope: V2AnalysisJobEnvelope,
    ) -> tuple[V2ResolvedAnalysisInput, ...]:
        resolved: list[V2ResolvedAnalysisInput] = []

        for analysis_input in envelope.job.inputs:
            try:
                payload = self._dataset_resolver.resolve(analysis_input)
            except (
                V2AnalysisDatasetResolutionError,
                V2AnalysisInputIntegrityError,
            ):
                raise
            except Exception as exc:
                raise V2AnalysisDatasetResolutionError(
                    _controlled_exception_statement(
                        "dataset resolver raised an unexpected exception",
                        exc,
                    ),
                    retryable=True,
                ) from exc

            try:
                data = bytes(payload)
            except (TypeError, ValueError) as exc:
                raise V2AnalysisInputIntegrityError(
                    f"dataset resolver returned non-byte content for {analysis_input.dataset_id!r}"
                ) from exc

            resolved.append(
                V2ResolvedAnalysisInput(
                    descriptor=analysis_input,
                    data=data,
                )
            )

        return tuple(resolved)

    def _execute_method(
        self,
        claimed: V2StoredAnalysisJob,
    ) -> V2AnalysisExecutionResult:
        handler = self._registry.resolve(claimed.envelope.job.method)
        request = V2AnalysisExecutionRequest(
            job_envelope=claimed.envelope,
            inputs=self._resolve_inputs(claimed.envelope),
        )

        try:
            result = handler(request)
        except V2AnalysisMethodExecutionError:
            raise
        except Exception as exc:
            raise V2AnalysisMethodExecutionError(
                _controlled_exception_statement(
                    "analysis method raised an unexpected exception",
                    exc,
                ),
                retryable=False,
            ) from exc

        if not isinstance(result, V2AnalysisExecutionResult):
            raise V2AnalysisMethodExecutionError(
                "analysis method returned an invalid execution-result type",
                retryable=False,
            )

        return result

    def _fail_claimed_job(
        self,
        claimed: V2StoredAnalysisJob,
        *,
        error: str,
        retryable: bool,
    ) -> V2AnalysisWorkerOutcome:
        lease_token = claimed.lease_token
        assert lease_token is not None
        failed = self._store.fail_job(
            claimed.job_id,
            worker_id=self._worker_id,
            lease_token=lease_token,
            failed_at=self._now(label="analysis failure timestamp"),
            error=error,
            retryable=retryable,
        )
        status = (
            V2AnalysisWorkerOutcomeStatus.RETRY_QUEUED
            if retryable
            else V2AnalysisWorkerOutcomeStatus.FAILED
        )
        return V2AnalysisWorkerOutcome(
            status=status,
            job_id=claimed.job_id,
            attempt_count=failed.attempt_count,
            error=error,
        )

    def run_once(self) -> V2AnalysisWorkerOutcome:
        claimed = self._store.claim_next_job(
            worker_id=self._worker_id,
            claimed_at=self._now(label="analysis claim timestamp"),
            lease_duration=self._lease_duration,
        )
        if claimed is None:
            return V2AnalysisWorkerOutcome(status=V2AnalysisWorkerOutcomeStatus.IDLE)

        try:
            result = self._execute_method(claimed)
            artifact_id = _require_nonblank(
                self._artifact_id_factory(claimed.envelope),
                label="analysis artifact ID",
            )
            artifact = create_analysis_artifact_envelope(
                claimed.envelope,
                artifact_id=artifact_id,
                derived_values=result.derived_values,
                uncertainties=result.uncertainties,
                limitations=result.limitations,
                software_versions=result.software_versions,
                provenance=result.provenance,
            )
        except V2AnalysisDatasetResolutionError as exc:
            return self._fail_claimed_job(
                claimed,
                error=str(exc),
                retryable=exc.retryable,
            )
        except V2AnalysisMethodExecutionError as exc:
            return self._fail_claimed_job(
                claimed,
                error=str(exc),
                retryable=exc.retryable,
            )
        except (
            V2AnalysisMethodNotRegisteredError,
            V2AnalysisInputIntegrityError,
        ) as exc:
            return self._fail_claimed_job(
                claimed,
                error=str(exc),
                retryable=False,
            )
        except (V2AnalysisError, TypeError, ValueError) as exc:
            return self._fail_claimed_job(
                claimed,
                error=_controlled_exception_statement(
                    "analysis result could not be encoded",
                    exc,
                ),
                retryable=False,
            )

        lease_token = claimed.lease_token
        assert lease_token is not None
        stored = self._store.submit_artifact(
            claimed.job_id,
            artifact,
            worker_id=self._worker_id,
            lease_token=lease_token,
            completed_at=self._now(label="analysis completion timestamp"),
        )
        return V2AnalysisWorkerOutcome(
            status=V2AnalysisWorkerOutcomeStatus.COMPLETED,
            job_id=claimed.job_id,
            attempt_count=claimed.attempt_count,
            artifact_id=stored.artifact_id,
        )
