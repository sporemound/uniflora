from __future__ import annotations

import hashlib
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from types import TracebackType
from typing import Self

from uniflora.engine.v2.analysis import (
    V2AnalysisArtifactEnvelope,
    V2AnalysisError,
    V2AnalysisIntegrityError,
    V2AnalysisJobEnvelope,
    deserialize_analysis_artifact_envelope,
    deserialize_analysis_job_envelope,
    serialize_analysis_artifact_envelope,
    serialize_analysis_job_envelope,
    verify_analysis_artifact_envelope,
    verify_analysis_job_envelope,
)
from uniflora.engine.v2.serialization import canonical_json_bytes


class V2AnalysisPersistenceError(ValueError):
    """Raised when persisted analysis work cannot be used safely."""


class V2AnalysisJobNotFoundError(V2AnalysisPersistenceError):
    """Raised when an analysis job ID is not present in the store."""


class V2AnalysisArtifactNotFoundError(V2AnalysisPersistenceError):
    """Raised when an analysis artifact ID is not present in the store."""


class V2AnalysisJobConflictError(V2AnalysisPersistenceError):
    """Raised when a job ID or artifact ID is reused incompatibly."""


class V2AnalysisLeaseError(V2AnalysisPersistenceError):
    """Raised when a worker does not hold the required active lease."""


class V2AnalysisResultConflictError(V2AnalysisPersistenceError):
    """Raised when a completed job receives a different result."""


class V2AnalysisJobStatus(StrEnum):
    QUEUED = "queued"
    LEASED = "leased"
    COMPLETED = "completed"
    FAILED = "failed"


_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def _require_nonblank(value: str, *, label: str) -> str:
    normalized = value.strip()

    if not normalized:
        raise ValueError(f"{label} must not be blank")

    return normalized


def _timestamp_to_microseconds(value: datetime, *, label: str) -> int:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")

    normalized = value.astimezone(UTC)
    delta = normalized - _EPOCH
    microseconds = (delta.days * 86_400 + delta.seconds) * 1_000_000 + delta.microseconds

    if microseconds < 0:
        raise ValueError(f"{label} must not precede the Unix epoch")

    return microseconds


def _timestamp_from_microseconds(value: int | None) -> datetime | None:
    if value is None:
        return None

    return _EPOCH + timedelta(microseconds=int(value))


def _require_positive_duration(value: timedelta) -> timedelta:
    if value <= timedelta(0):
        raise ValueError("lease duration must be positive")

    return value


def _duration_to_microseconds(value: timedelta) -> int:
    normalized = _require_positive_duration(value)
    microseconds = (
        normalized.days * 86_400 + normalized.seconds
    ) * 1_000_000 + normalized.microseconds

    if microseconds <= 0:
        raise ValueError("lease duration must be at least one microsecond")

    return microseconds


@dataclass(frozen=True, slots=True)
class V2StoredAnalysisJob:
    envelope: V2AnalysisJobEnvelope
    status: V2AnalysisJobStatus
    submitted_at: datetime
    updated_at: datetime
    attempt_count: int
    lease_worker_id: str | None = None
    lease_token: str | None = None
    lease_expires_at: datetime | None = None
    last_error: str | None = None
    artifact_id: str | None = None

    @property
    def job_id(self) -> str:
        return self.envelope.job.job_id

    @property
    def job_hash(self) -> str:
        return self.envelope.job_hash

    def __post_init__(self) -> None:
        verify_analysis_job_envelope(self.envelope)

        if self.attempt_count < 0:
            raise ValueError("analysis attempt count must not be negative")

        _timestamp_to_microseconds(self.submitted_at, label="submitted timestamp")
        _timestamp_to_microseconds(self.updated_at, label="updated timestamp")

        lease_fields = (
            self.lease_worker_id,
            self.lease_token,
            self.lease_expires_at,
        )

        if self.status is V2AnalysisJobStatus.LEASED:
            if any(value is None for value in lease_fields):
                raise ValueError("leased jobs require complete lease metadata")
            _require_nonblank(self.lease_worker_id or "", label="lease worker ID")
            _require_nonblank(self.lease_token or "", label="lease token")
            _timestamp_to_microseconds(
                self.lease_expires_at,
                label="lease expiration timestamp",
            )
        elif any(value is not None for value in lease_fields):
            raise ValueError("non-leased jobs must not retain lease metadata")

        if self.status is V2AnalysisJobStatus.COMPLETED:
            if self.artifact_id is None:
                raise ValueError("completed jobs require an artifact ID")
        elif self.artifact_id is not None:
            raise ValueError("only completed jobs may reference an artifact")

        if self.status is V2AnalysisJobStatus.FAILED and self.last_error is None:
            raise ValueError("failed jobs require an error statement")

        if self.last_error is not None:
            _require_nonblank(self.last_error, label="analysis error statement")


@dataclass(frozen=True, slots=True)
class V2StoredAnalysisArtifact:
    envelope: V2AnalysisArtifactEnvelope
    stored_at: datetime

    @property
    def artifact_id(self) -> str:
        return self.envelope.artifact.artifact_id

    @property
    def job_id(self) -> str:
        return self.envelope.artifact.job_id

    @property
    def artifact_hash(self) -> str:
        return self.envelope.artifact_hash

    def __post_init__(self) -> None:
        verify_analysis_artifact_envelope(self.envelope)
        _timestamp_to_microseconds(self.stored_at, label="artifact timestamp")


_SCHEMA = """
CREATE TABLE IF NOT EXISTS v2_analysis_jobs (
    job_id TEXT PRIMARY KEY,
    stream_id TEXT NOT NULL,
    position_id TEXT NOT NULL,
    job_hash TEXT NOT NULL UNIQUE,
    job_json BLOB NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN ('queued', 'leased', 'completed', 'failed')
    ),
    submitted_at_us INTEGER NOT NULL CHECK (submitted_at_us >= 0),
    updated_at_us INTEGER NOT NULL CHECK (updated_at_us >= 0),
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    lease_worker_id TEXT,
    lease_token TEXT,
    lease_expires_at_us INTEGER,
    last_error TEXT,
    CHECK (
        (status = 'leased'
            AND lease_worker_id IS NOT NULL
            AND lease_token IS NOT NULL
            AND lease_expires_at_us IS NOT NULL)
        OR
        (status <> 'leased'
            AND lease_worker_id IS NULL
            AND lease_token IS NULL
            AND lease_expires_at_us IS NULL)
    ),
    CHECK (status <> 'failed' OR last_error IS NOT NULL)
);

CREATE TABLE IF NOT EXISTS v2_analysis_artifacts (
    artifact_id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL UNIQUE,
    artifact_hash TEXT NOT NULL UNIQUE,
    artifact_json BLOB NOT NULL,
    stored_at_us INTEGER NOT NULL CHECK (stored_at_us >= 0),
    FOREIGN KEY (job_id)
        REFERENCES v2_analysis_jobs (job_id)
        ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS ix_v2_analysis_jobs_claim_order
    ON v2_analysis_jobs (status, submitted_at_us, job_id);

CREATE INDEX IF NOT EXISTS ix_v2_analysis_jobs_stream_position
    ON v2_analysis_jobs (stream_id, position_id, submitted_at_us);

CREATE INDEX IF NOT EXISTS ix_v2_analysis_jobs_lease_expiration
    ON v2_analysis_jobs (status, lease_expires_at_us);
"""


class V2SQLiteAnalysisStore:
    """Persistent queue and artifact store for out-of-process analysis workers."""

    def __init__(self, database: str | Path) -> None:
        self._database = str(database)
        self._connection = sqlite3.connect(
            self._database,
            isolation_level=None,
            timeout=30.0,
        )
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.execute("PRAGMA synchronous = FULL")

        if self._database != ":memory:":
            self._connection.execute("PRAGMA journal_mode = WAL")

        self._connection.executescript(_SCHEMA)

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        self._connection.close()

    @contextmanager
    def _transaction(self):
        try:
            self._connection.execute("BEGIN IMMEDIATE")
            yield
        except Exception:
            self._connection.rollback()
            raise
        else:
            self._connection.commit()

    def _job_row(self, job_id: str) -> sqlite3.Row | None:
        return self._connection.execute(
            """
            SELECT
                jobs.*,
                artifacts.artifact_id AS completed_artifact_id
            FROM v2_analysis_jobs AS jobs
            LEFT JOIN v2_analysis_artifacts AS artifacts
                ON artifacts.job_id = jobs.job_id
            WHERE jobs.job_id = ?
            """,
            (job_id,),
        ).fetchone()

    def _stored_job_from_row(self, row: sqlite3.Row) -> V2StoredAnalysisJob:
        try:
            envelope = deserialize_analysis_job_envelope(row["job_json"])
        except (V2AnalysisError, V2AnalysisIntegrityError) as exc:
            raise V2AnalysisPersistenceError(f"persisted analysis job is invalid: {exc}") from exc

        if envelope.job.job_id != row["job_id"]:
            raise V2AnalysisPersistenceError(
                "persisted analysis job ID does not match its indexed ID"
            )

        if envelope.job.stream_id != row["stream_id"]:
            raise V2AnalysisPersistenceError(
                "persisted analysis stream ID does not match its indexed value"
            )

        if envelope.job.position_id != row["position_id"]:
            raise V2AnalysisPersistenceError(
                "persisted analysis position ID does not match its indexed value"
            )

        if envelope.job_hash != row["job_hash"]:
            raise V2AnalysisPersistenceError(
                "persisted analysis job hash does not match its indexed hash"
            )

        try:
            status = V2AnalysisJobStatus(str(row["status"]))
        except ValueError as exc:
            raise V2AnalysisPersistenceError(
                f"persisted analysis job has an invalid status: {row['status']!r}"
            ) from exc

        return V2StoredAnalysisJob(
            envelope=envelope,
            status=status,
            submitted_at=_timestamp_from_microseconds(row["submitted_at_us"]),
            updated_at=_timestamp_from_microseconds(row["updated_at_us"]),
            attempt_count=int(row["attempt_count"]),
            lease_worker_id=row["lease_worker_id"],
            lease_token=row["lease_token"],
            lease_expires_at=_timestamp_from_microseconds(row["lease_expires_at_us"]),
            last_error=row["last_error"],
            artifact_id=row["completed_artifact_id"],
        )

    def _artifact_row(self, artifact_id: str) -> sqlite3.Row | None:
        return self._connection.execute(
            """
            SELECT *
            FROM v2_analysis_artifacts
            WHERE artifact_id = ?
            """,
            (artifact_id,),
        ).fetchone()

    def _artifact_row_for_job(self, job_id: str) -> sqlite3.Row | None:
        return self._connection.execute(
            """
            SELECT *
            FROM v2_analysis_artifacts
            WHERE job_id = ?
            """,
            (job_id,),
        ).fetchone()

    def _stored_artifact_from_row(
        self,
        row: sqlite3.Row,
    ) -> V2StoredAnalysisArtifact:
        try:
            envelope = deserialize_analysis_artifact_envelope(row["artifact_json"])
        except (V2AnalysisError, V2AnalysisIntegrityError) as exc:
            raise V2AnalysisPersistenceError(
                f"persisted analysis artifact is invalid: {exc}"
            ) from exc

        if envelope.artifact.artifact_id != row["artifact_id"]:
            raise V2AnalysisPersistenceError("persisted artifact ID does not match its indexed ID")

        if envelope.artifact.job_id != row["job_id"]:
            raise V2AnalysisPersistenceError(
                "persisted artifact job ID does not match its indexed job"
            )

        if envelope.artifact_hash != row["artifact_hash"]:
            raise V2AnalysisPersistenceError(
                "persisted artifact hash does not match its indexed hash"
            )

        return V2StoredAnalysisArtifact(
            envelope=envelope,
            stored_at=_timestamp_from_microseconds(row["stored_at_us"]),
        )

    def enqueue_job(
        self,
        envelope: V2AnalysisJobEnvelope,
        *,
        submitted_at: datetime,
    ) -> V2StoredAnalysisJob:
        job = verify_analysis_job_envelope(envelope)
        submitted_at_us = _timestamp_to_microseconds(
            submitted_at,
            label="submission timestamp",
        )
        encoded = serialize_analysis_job_envelope(envelope)

        with self._transaction():
            existing = self._job_row(job.job_id)

            if existing is not None:
                stored = self._stored_job_from_row(existing)

                if stored.job_hash != envelope.job_hash:
                    raise V2AnalysisJobConflictError(
                        f"analysis job ID {job.job_id!r} already belongs to "
                        "a different canonical job"
                    )

                return stored

            try:
                self._connection.execute(
                    """
                    INSERT INTO v2_analysis_jobs (
                        job_id,
                        stream_id,
                        position_id,
                        job_hash,
                        job_json,
                        status,
                        submitted_at_us,
                        updated_at_us,
                        attempt_count
                    )
                    VALUES (?, ?, ?, ?, ?, 'queued', ?, ?, 0)
                    """,
                    (
                        job.job_id,
                        job.stream_id,
                        job.position_id,
                        envelope.job_hash,
                        encoded,
                        submitted_at_us,
                        submitted_at_us,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise V2AnalysisJobConflictError(
                    "analysis job hash or ID is already stored"
                ) from exc

            row = self._job_row(job.job_id)
            assert row is not None
            return self._stored_job_from_row(row)

    def get_job(self, job_id: str) -> V2StoredAnalysisJob:
        normalized = _require_nonblank(job_id, label="analysis job ID")
        row = self._job_row(normalized)

        if row is None:
            raise V2AnalysisJobNotFoundError(f"analysis job {normalized!r} was not found")

        return self._stored_job_from_row(row)

    def list_jobs(
        self,
        *,
        status: V2AnalysisJobStatus | None = None,
    ) -> tuple[V2StoredAnalysisJob, ...]:
        if status is None:
            rows = self._connection.execute(
                """
                SELECT
                    jobs.*,
                    artifacts.artifact_id AS completed_artifact_id
                FROM v2_analysis_jobs AS jobs
                LEFT JOIN v2_analysis_artifacts AS artifacts
                    ON artifacts.job_id = jobs.job_id
                ORDER BY jobs.submitted_at_us, jobs.job_id
                """
            ).fetchall()
        else:
            rows = self._connection.execute(
                """
                SELECT
                    jobs.*,
                    artifacts.artifact_id AS completed_artifact_id
                FROM v2_analysis_jobs AS jobs
                LEFT JOIN v2_analysis_artifacts AS artifacts
                    ON artifacts.job_id = jobs.job_id
                WHERE jobs.status = ?
                ORDER BY jobs.submitted_at_us, jobs.job_id
                """,
                (status.value,),
            ).fetchall()

        return tuple(self._stored_job_from_row(row) for row in rows)

    def claim_next_job(
        self,
        *,
        worker_id: str,
        claimed_at: datetime,
        lease_duration: timedelta,
    ) -> V2StoredAnalysisJob | None:
        normalized_worker = _require_nonblank(worker_id, label="worker ID")
        claimed_at_us = _timestamp_to_microseconds(
            claimed_at,
            label="lease claim timestamp",
        )
        expires_at_us = claimed_at_us + _duration_to_microseconds(lease_duration)

        with self._transaction():
            row = self._connection.execute(
                """
                SELECT *
                FROM v2_analysis_jobs
                WHERE status = 'queued'
                   OR (
                        status = 'leased'
                        AND lease_expires_at_us <= ?
                   )
                ORDER BY submitted_at_us, job_id
                LIMIT 1
                """,
                (claimed_at_us,),
            ).fetchone()

            if row is None:
                return None

            attempt_count = int(row["attempt_count"]) + 1
            lease_token = hashlib.sha256(
                canonical_json_bytes(
                    {
                        "attempt_count": attempt_count,
                        "claimed_at_us": claimed_at_us,
                        "expires_at_us": expires_at_us,
                        "job_hash": row["job_hash"],
                        "job_id": row["job_id"],
                        "worker_id": normalized_worker,
                    }
                )
            ).hexdigest()

            self._connection.execute(
                """
                UPDATE v2_analysis_jobs
                SET
                    status = 'leased',
                    updated_at_us = ?,
                    attempt_count = ?,
                    lease_worker_id = ?,
                    lease_token = ?,
                    lease_expires_at_us = ?
                WHERE job_id = ?
                """,
                (
                    claimed_at_us,
                    attempt_count,
                    normalized_worker,
                    lease_token,
                    expires_at_us,
                    row["job_id"],
                ),
            )

            claimed = self._job_row(str(row["job_id"]))
            assert claimed is not None
            return self._stored_job_from_row(claimed)

    def _require_active_lease(
        self,
        row: sqlite3.Row,
        *,
        worker_id: str,
        lease_token: str,
        observed_at_us: int,
    ) -> None:
        if row["status"] != V2AnalysisJobStatus.LEASED.value:
            raise V2AnalysisLeaseError("analysis job is not currently leased")

        if row["lease_worker_id"] != worker_id:
            raise V2AnalysisLeaseError("analysis job is leased by a different worker")

        if row["lease_token"] != lease_token:
            raise V2AnalysisLeaseError("analysis lease token does not match")

        expires_at_us = row["lease_expires_at_us"]

        if expires_at_us is None or int(expires_at_us) <= observed_at_us:
            raise V2AnalysisLeaseError("analysis job lease has expired")

    def renew_lease(
        self,
        job_id: str,
        *,
        worker_id: str,
        lease_token: str,
        renewed_at: datetime,
        lease_duration: timedelta,
    ) -> V2StoredAnalysisJob:
        normalized_job_id = _require_nonblank(job_id, label="analysis job ID")
        normalized_worker = _require_nonblank(worker_id, label="worker ID")
        normalized_token = _require_nonblank(lease_token, label="lease token")
        renewed_at_us = _timestamp_to_microseconds(
            renewed_at,
            label="lease renewal timestamp",
        )
        expires_at_us = renewed_at_us + _duration_to_microseconds(lease_duration)

        with self._transaction():
            row = self._job_row(normalized_job_id)

            if row is None:
                raise V2AnalysisJobNotFoundError(
                    f"analysis job {normalized_job_id!r} was not found"
                )

            self._require_active_lease(
                row,
                worker_id=normalized_worker,
                lease_token=normalized_token,
                observed_at_us=renewed_at_us,
            )
            self._connection.execute(
                """
                UPDATE v2_analysis_jobs
                SET updated_at_us = ?, lease_expires_at_us = ?
                WHERE job_id = ?
                """,
                (renewed_at_us, expires_at_us, normalized_job_id),
            )

            renewed = self._job_row(normalized_job_id)
            assert renewed is not None
            return self._stored_job_from_row(renewed)

    def fail_job(
        self,
        job_id: str,
        *,
        worker_id: str,
        lease_token: str,
        failed_at: datetime,
        error: str,
        retryable: bool,
    ) -> V2StoredAnalysisJob:
        normalized_job_id = _require_nonblank(job_id, label="analysis job ID")
        normalized_worker = _require_nonblank(worker_id, label="worker ID")
        normalized_token = _require_nonblank(lease_token, label="lease token")
        normalized_error = _require_nonblank(
            error,
            label="analysis failure statement",
        )
        failed_at_us = _timestamp_to_microseconds(
            failed_at,
            label="failure timestamp",
        )
        next_status = V2AnalysisJobStatus.QUEUED if retryable else V2AnalysisJobStatus.FAILED

        with self._transaction():
            row = self._job_row(normalized_job_id)

            if row is None:
                raise V2AnalysisJobNotFoundError(
                    f"analysis job {normalized_job_id!r} was not found"
                )

            self._require_active_lease(
                row,
                worker_id=normalized_worker,
                lease_token=normalized_token,
                observed_at_us=failed_at_us,
            )
            self._connection.execute(
                """
                UPDATE v2_analysis_jobs
                SET
                    status = ?,
                    updated_at_us = ?,
                    lease_worker_id = NULL,
                    lease_token = NULL,
                    lease_expires_at_us = NULL,
                    last_error = ?
                WHERE job_id = ?
                """,
                (
                    next_status.value,
                    failed_at_us,
                    normalized_error,
                    normalized_job_id,
                ),
            )

            failed = self._job_row(normalized_job_id)
            assert failed is not None
            return self._stored_job_from_row(failed)

    def submit_artifact(
        self,
        job_id: str,
        envelope: V2AnalysisArtifactEnvelope,
        *,
        worker_id: str,
        lease_token: str,
        completed_at: datetime,
    ) -> V2StoredAnalysisArtifact:
        normalized_job_id = _require_nonblank(job_id, label="analysis job ID")
        normalized_worker = _require_nonblank(worker_id, label="worker ID")
        normalized_token = _require_nonblank(lease_token, label="lease token")
        completed_at_us = _timestamp_to_microseconds(
            completed_at,
            label="completion timestamp",
        )
        verify_analysis_artifact_envelope(envelope)

        if envelope.artifact.job_id != normalized_job_id:
            raise V2AnalysisResultConflictError(
                "analysis artifact job ID does not match the submitted job"
            )

        encoded = serialize_analysis_artifact_envelope(envelope)

        with self._transaction():
            row = self._job_row(normalized_job_id)

            if row is None:
                raise V2AnalysisJobNotFoundError(
                    f"analysis job {normalized_job_id!r} was not found"
                )

            existing = self._artifact_row_for_job(normalized_job_id)

            if row["status"] == V2AnalysisJobStatus.COMPLETED.value:
                if existing is None:
                    raise V2AnalysisPersistenceError(
                        "completed analysis job has no persisted artifact"
                    )

                stored = self._stored_artifact_from_row(existing)

                if stored.artifact_hash != envelope.artifact_hash:
                    raise V2AnalysisResultConflictError(
                        "analysis job is already completed with a different artifact"
                    )

                return stored

            self._require_active_lease(
                row,
                worker_id=normalized_worker,
                lease_token=normalized_token,
                observed_at_us=completed_at_us,
            )
            job_envelope = deserialize_analysis_job_envelope(row["job_json"])

            try:
                verify_analysis_artifact_envelope(
                    envelope,
                    job_envelope=job_envelope,
                )
            except V2AnalysisIntegrityError as exc:
                raise V2AnalysisResultConflictError(
                    f"analysis artifact does not match its persisted job: {exc}"
                ) from exc

            try:
                self._connection.execute(
                    """
                    INSERT INTO v2_analysis_artifacts (
                        artifact_id,
                        job_id,
                        artifact_hash,
                        artifact_json,
                        stored_at_us
                    )
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        envelope.artifact.artifact_id,
                        normalized_job_id,
                        envelope.artifact_hash,
                        encoded,
                        completed_at_us,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise V2AnalysisJobConflictError(
                    "analysis artifact ID or hash is already stored"
                ) from exc

            self._connection.execute(
                """
                UPDATE v2_analysis_jobs
                SET
                    status = 'completed',
                    updated_at_us = ?,
                    lease_worker_id = NULL,
                    lease_token = NULL,
                    lease_expires_at_us = NULL,
                    last_error = NULL
                WHERE job_id = ?
                """,
                (completed_at_us, normalized_job_id),
            )

            stored_row = self._artifact_row(envelope.artifact.artifact_id)
            assert stored_row is not None
            return self._stored_artifact_from_row(stored_row)

    def get_artifact(
        self,
        artifact_id: str,
    ) -> V2StoredAnalysisArtifact:
        normalized = _require_nonblank(artifact_id, label="artifact ID")
        row = self._artifact_row(normalized)

        if row is None:
            raise V2AnalysisArtifactNotFoundError(f"analysis artifact {normalized!r} was not found")

        return self._stored_artifact_from_row(row)

    def get_artifact_for_job(
        self,
        job_id: str,
    ) -> V2StoredAnalysisArtifact | None:
        normalized = _require_nonblank(job_id, label="analysis job ID")

        if self._job_row(normalized) is None:
            raise V2AnalysisJobNotFoundError(f"analysis job {normalized!r} was not found")

        row = self._artifact_row_for_job(normalized)

        if row is None:
            return None

        return self._stored_artifact_from_row(row)
