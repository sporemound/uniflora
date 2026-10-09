from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from uniflora.engine.v2.analysis import (
    V2AnalysisInput,
    V2AnalysisParameter,
    V2AnalysisUncertainty,
)
from uniflora.engine.v2.analysis_persistence import (
    V2AnalysisJobStatus,
    V2SQLiteAnalysisStore,
    V2StoredAnalysisArtifact,
    V2StoredAnalysisJob,
)


@dataclass(frozen=True, slots=True)
class V2AnalysisInputView:
    dataset_id: str
    source_evidence_id: str
    content_hash: str
    byte_length: int
    media_type: str
    provenance: str
    preprocessing_steps: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class V2AnalysisValueView:
    name: str
    canonical_json: str
    unit: str | None


@dataclass(frozen=True, slots=True)
class V2AnalysisUncertaintyView:
    source: str
    statement: str
    canonical_json: str | None
    unit: str | None


@dataclass(frozen=True, slots=True)
class V2AnalysisSoftwareVersionView:
    name: str
    version: str


@dataclass(frozen=True, slots=True)
class V2AnalysisStatusView:
    job_id: str
    stream_id: str
    position_id: str
    requested_by_player_id: str
    method_id: str
    method_version: str
    output_kind: str
    status: V2AnalysisJobStatus
    submitted_at: str
    updated_at: str
    attempt_count: int
    job_hash: str
    artifact_id: str | None
    error: str | None
    inputs: tuple[V2AnalysisInputView, ...]
    parameters: tuple[V2AnalysisValueView, ...]


@dataclass(frozen=True, slots=True)
class V2AnalysisArtifactView:
    artifact_id: str
    job_id: str
    job_hash: str
    artifact_hash: str
    input_manifest_hash: str
    method_id: str
    method_version: str
    result_kind: str
    stored_at: str
    parameters: tuple[V2AnalysisValueView, ...]
    derived_values: tuple[V2AnalysisValueView, ...]
    uncertainties: tuple[V2AnalysisUncertaintyView, ...]
    limitations: tuple[str, ...]
    software_versions: tuple[V2AnalysisSoftwareVersionView, ...]
    provenance: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class V2RenderedAnalysisResponse:
    kind: Literal["analysis_status", "analysis_artifact"]
    code: str
    summary: str
    details: tuple[str, ...]
    job_id: str
    artifact_id: str | None = None

    def to_text(self) -> str:
        return "\n".join((self.summary, *self.details))


def _timestamp_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _input_view(value: V2AnalysisInput) -> V2AnalysisInputView:
    return V2AnalysisInputView(
        dataset_id=value.dataset_id,
        source_evidence_id=value.source_evidence_id,
        content_hash=value.content_hash,
        byte_length=value.byte_length,
        media_type=value.media_type,
        provenance=value.provenance,
        preprocessing_steps=value.preprocessing_steps,
    )


def _parameter_view(value: V2AnalysisParameter) -> V2AnalysisValueView:
    return V2AnalysisValueView(
        name=value.name,
        canonical_json=value.value.canonical_json,
        unit=value.unit,
    )


def _uncertainty_view(
    value: V2AnalysisUncertainty,
) -> V2AnalysisUncertaintyView:
    return V2AnalysisUncertaintyView(
        source=value.source,
        statement=value.statement,
        canonical_json=(None if value.value is None else value.value.canonical_json),
        unit=value.unit,
    )


def create_analysis_status_view(
    stored: V2StoredAnalysisJob,
) -> V2AnalysisStatusView:
    job = stored.envelope.job
    return V2AnalysisStatusView(
        job_id=job.job_id,
        stream_id=job.stream_id,
        position_id=job.position_id,
        requested_by_player_id=job.requested_by_player_id,
        method_id=job.method.method_id,
        method_version=job.method.version,
        output_kind=job.output_kind,
        status=stored.status,
        submitted_at=_timestamp_text(stored.submitted_at),
        updated_at=_timestamp_text(stored.updated_at),
        attempt_count=stored.attempt_count,
        job_hash=stored.job_hash,
        artifact_id=stored.artifact_id,
        error=stored.last_error,
        inputs=tuple(_input_view(value) for value in job.inputs),
        parameters=tuple(_parameter_view(value) for value in job.parameters),
    )


def create_analysis_artifact_view(
    stored: V2StoredAnalysisArtifact,
) -> V2AnalysisArtifactView:
    artifact = stored.envelope.artifact
    return V2AnalysisArtifactView(
        artifact_id=artifact.artifact_id,
        job_id=artifact.job_id,
        job_hash=artifact.job_hash,
        artifact_hash=stored.artifact_hash,
        input_manifest_hash=artifact.input_manifest_hash,
        method_id=artifact.method_id,
        method_version=artifact.method_version,
        result_kind=artifact.result_kind,
        stored_at=_timestamp_text(stored.stored_at),
        parameters=tuple(_parameter_view(value) for value in artifact.parameters),
        derived_values=tuple(
            V2AnalysisValueView(
                name=value.name,
                canonical_json=value.value.canonical_json,
                unit=value.unit,
            )
            for value in artifact.derived_values
        ),
        uncertainties=tuple(_uncertainty_view(value) for value in artifact.uncertainties),
        limitations=artifact.limitations,
        software_versions=tuple(
            V2AnalysisSoftwareVersionView(
                name=value.name,
                version=value.version,
            )
            for value in artifact.software_versions
        ),
        provenance=artifact.provenance,
    )


class V2AnalysisPresentationService:
    """Read-only transport-neutral views over persisted analysis work."""

    def __init__(self, store: V2SQLiteAnalysisStore) -> None:
        self._store = store

    def get_status(self, job_id: str) -> V2AnalysisStatusView:
        return create_analysis_status_view(self._store.get_job(job_id))

    def list_statuses(
        self,
        *,
        status: V2AnalysisJobStatus | None = None,
        stream_id: str | None = None,
        position_id: str | None = None,
    ) -> tuple[V2AnalysisStatusView, ...]:
        jobs = self._store.list_jobs(status=status)
        views = tuple(create_analysis_status_view(job) for job in jobs)

        if stream_id is not None:
            normalized_stream = stream_id.strip()
            if not normalized_stream:
                raise ValueError("stream ID filter must not be blank")
            views = tuple(view for view in views if view.stream_id == normalized_stream)

        if position_id is not None:
            normalized_position = position_id.strip()
            if not normalized_position:
                raise ValueError("position ID filter must not be blank")
            views = tuple(view for view in views if view.position_id == normalized_position)

        return views

    def get_artifact(self, artifact_id: str) -> V2AnalysisArtifactView:
        return create_analysis_artifact_view(self._store.get_artifact(artifact_id))

    def get_artifact_for_job(
        self,
        job_id: str,
    ) -> V2AnalysisArtifactView | None:
        stored = self._store.get_artifact_for_job(job_id)
        if stored is None:
            return None
        return create_analysis_artifact_view(stored)


def _value_text(value: V2AnalysisValueView) -> str:
    unit = "" if value.unit is None else f" {value.unit}"
    return f"{value.name}: {value.canonical_json}{unit}."


def _uncertainty_text(value: V2AnalysisUncertaintyView) -> str:
    if value.canonical_json is None:
        return f"Uncertainty [{value.source}]: {value.statement}"

    unit = "" if value.unit is None else f" {value.unit}"
    return (
        f"Uncertainty [{value.source}]: {value.statement} "
        f"Quantified value: {value.canonical_json}{unit}."
    )


def render_analysis_status(
    view: V2AnalysisStatusView,
) -> V2RenderedAnalysisResponse:
    summaries = {
        V2AnalysisJobStatus.QUEUED: (
            "analysis_queued",
            f"Analysis job {view.job_id!r} is queued.",
        ),
        V2AnalysisJobStatus.LEASED: (
            "analysis_processing",
            f"Analysis job {view.job_id!r} is being processed.",
        ),
        V2AnalysisJobStatus.COMPLETED: (
            "analysis_completed",
            f"Analysis job {view.job_id!r} is complete.",
        ),
        V2AnalysisJobStatus.FAILED: (
            "analysis_failed",
            f"Analysis job {view.job_id!r} failed.",
        ),
    }
    code, summary = summaries[view.status]
    details = [
        f"Stream: {view.stream_id}",
        f"Position: {view.position_id}",
        f"Requested by: {view.requested_by_player_id}",
        f"Method: {view.method_id} {view.method_version}",
        f"Output kind: {view.output_kind}",
        f"Attempts: {view.attempt_count}",
        f"Submitted: {view.submitted_at}",
        f"Updated: {view.updated_at}",
        f"Inputs: {', '.join(value.dataset_id for value in view.inputs)}",
    ]

    if view.artifact_id is not None:
        details.append(f"Artifact: {view.artifact_id}")

    if view.error is not None:
        details.append(f"Error: {view.error}")

    return V2RenderedAnalysisResponse(
        kind="analysis_status",
        code=code,
        summary=summary,
        details=tuple(details),
        job_id=view.job_id,
        artifact_id=view.artifact_id,
    )


def render_analysis_artifact(
    view: V2AnalysisArtifactView,
) -> V2RenderedAnalysisResponse:
    details = [
        f"Job: {view.job_id}",
        f"Method: {view.method_id} {view.method_version}",
        f"Result kind: {view.result_kind}",
        f"Stored: {view.stored_at}",
        *(f"Derived {_value_text(value)}" for value in view.derived_values),
        *(_uncertainty_text(value) for value in view.uncertainties),
        *(f"Limitation: {value}" for value in view.limitations),
        *(f"Software: {value.name} {value.version}" for value in view.software_versions),
        *(f"Provenance: {value}" for value in view.provenance),
        f"Input manifest hash: {view.input_manifest_hash}",
        f"Artifact hash: {view.artifact_hash}",
    ]
    return V2RenderedAnalysisResponse(
        kind="analysis_artifact",
        code="analysis_artifact",
        summary=f"Analysis artifact {view.artifact_id!r} is available.",
        details=tuple(details),
        job_id=view.job_id,
        artifact_id=view.artifact_id,
    )
