from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from uniflora.engine.v2.serialization import canonical_json_bytes

V2_ANALYSIS_JOB_SCHEMA_VERSION = 1
V2_ANALYSIS_ARTIFACT_SCHEMA_VERSION = 1
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class V2AnalysisError(ValueError):
    """Raised when a scientific-analysis contract is invalid."""


class V2AnalysisIntegrityError(V2AnalysisError):
    """Raised when a scientific-analysis hash or binding is invalid."""


def _require_nonblank(value: str, *, label: str) -> str:
    normalized = value.strip()

    if not normalized:
        raise V2AnalysisError(f"{label} must not be blank")

    return normalized


def _require_sha256(value: str, *, label: str) -> str:
    normalized = value.strip().lower()

    if not _SHA256_PATTERN.fullmatch(normalized):
        raise V2AnalysisError(f"{label} must be a lowercase 64-character SHA-256 digest")

    return normalized


def _require_optional_nonblank(
    value: str | None,
    *,
    label: str,
) -> str | None:
    if value is None:
        return None

    return _require_nonblank(value, label=label)


def _require_unique_names(
    values: Iterable[object],
    *,
    attribute: str,
    label: str,
) -> None:
    names = tuple(getattr(value, attribute) for value in values)

    if len(names) != len(set(names)):
        raise V2AnalysisError(f"{label} must not contain duplicate names")


def _require_nonempty_strings(
    values: tuple[str, ...],
    *,
    label: str,
) -> tuple[str, ...]:
    normalized = tuple(_require_nonblank(value, label=label) for value in values)

    if not normalized:
        raise V2AnalysisError(f"{label} must contain at least one entry")

    if len(normalized) != len(set(normalized)):
        raise V2AnalysisError(f"{label} must not contain duplicates")

    return tuple(sorted(normalized))


def _load_json(
    data: bytes | bytearray | memoryview | str,
    *,
    label: str,
) -> object:
    try:
        if isinstance(data, str):
            text = data
        else:
            text = bytes(data).decode("utf-8")

        return json.loads(text)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise V2AnalysisError(f"invalid {label} JSON: {exc}") from exc


def _require_mapping(value: object, *, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise V2AnalysisError(f"{label} must be a JSON object")

    if not all(isinstance(key, str) for key in value):
        raise V2AnalysisError(f"{label} keys must be strings")

    return value


def _require_exact_keys(
    value: Mapping[str, object],
    *,
    expected: frozenset[str],
    label: str,
) -> None:
    actual = frozenset(value)

    if actual == expected:
        return

    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    details: list[str] = []

    if missing:
        details.append("missing " + ", ".join(missing))

    if extra:
        details.append("unexpected " + ", ".join(extra))

    raise V2AnalysisError(f"{label} has invalid fields: {'; '.join(details)}")


def _require_string(value: object, *, label: str) -> str:
    if not isinstance(value, str):
        raise V2AnalysisError(f"{label} must be a string")

    return _require_nonblank(value, label=label)


def _require_optional_string(value: object, *, label: str) -> str | None:
    if value is None:
        return None

    return _require_string(value, label=label)


def _require_integer(value: object, *, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise V2AnalysisError(f"{label} must be an integer")

    return value


def _require_sequence(value: object, *, label: str) -> Sequence[object]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise V2AnalysisError(f"{label} must be a JSON array")

    return value


@dataclass(frozen=True, slots=True)
class V2AnalysisValue:
    """Immutable canonical JSON value used by parameters and results."""

    canonical_json: str

    def __post_init__(self) -> None:
        parsed = _load_json(self.canonical_json, label="analysis value")
        canonical = canonical_json_bytes(parsed).decode("utf-8")

        if canonical != self.canonical_json:
            raise V2AnalysisError("analysis value JSON must already be canonical")

    @classmethod
    def from_python(cls, value: object) -> V2AnalysisValue:
        return cls(canonical_json_bytes(value).decode("utf-8"))

    def to_python(self) -> object:
        return _load_json(self.canonical_json, label="analysis value")


@dataclass(frozen=True, slots=True)
class V2AnalysisParameter:
    name: str
    value: V2AnalysisValue
    unit: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "name",
            _require_nonblank(self.name, label="parameter name"),
        )
        object.__setattr__(
            self,
            "unit",
            _require_optional_nonblank(self.unit, label="parameter unit"),
        )

    @classmethod
    def from_value(
        cls,
        name: str,
        value: object,
        *,
        unit: str | None = None,
    ) -> V2AnalysisParameter:
        return cls(name=name, value=V2AnalysisValue.from_python(value), unit=unit)


@dataclass(frozen=True, slots=True)
class V2AnalysisDerivedValue:
    name: str
    value: V2AnalysisValue
    unit: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "name",
            _require_nonblank(self.name, label="derived-value name"),
        )
        object.__setattr__(
            self,
            "unit",
            _require_optional_nonblank(self.unit, label="derived-value unit"),
        )

    @classmethod
    def from_value(
        cls,
        name: str,
        value: object,
        *,
        unit: str | None = None,
    ) -> V2AnalysisDerivedValue:
        return cls(name=name, value=V2AnalysisValue.from_python(value), unit=unit)


@dataclass(frozen=True, slots=True)
class V2AnalysisUncertainty:
    source: str
    statement: str
    value: V2AnalysisValue | None = None
    unit: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "source",
            _require_nonblank(self.source, label="uncertainty source"),
        )
        object.__setattr__(
            self,
            "statement",
            _require_nonblank(self.statement, label="uncertainty statement"),
        )
        object.__setattr__(
            self,
            "unit",
            _require_optional_nonblank(self.unit, label="uncertainty unit"),
        )

        if self.value is None and self.unit is not None:
            raise V2AnalysisError("uncertainty units require a quantified uncertainty value")

    @classmethod
    def quantified(
        cls,
        source: str,
        statement: str,
        value: object,
        *,
        unit: str | None = None,
    ) -> V2AnalysisUncertainty:
        return cls(
            source=source,
            statement=statement,
            value=V2AnalysisValue.from_python(value),
            unit=unit,
        )


@dataclass(frozen=True, slots=True)
class V2SoftwareVersion:
    name: str
    version: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "name",
            _require_nonblank(self.name, label="software name"),
        )
        object.__setattr__(
            self,
            "version",
            _require_nonblank(self.version, label="software version"),
        )


@dataclass(frozen=True, slots=True)
class V2AnalysisInput:
    dataset_id: str
    source_evidence_id: str
    content_hash: str
    byte_length: int
    media_type: str
    provenance: str
    preprocessing_steps: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "dataset_id",
            _require_nonblank(self.dataset_id, label="dataset ID"),
        )
        object.__setattr__(
            self,
            "source_evidence_id",
            _require_nonblank(
                self.source_evidence_id,
                label="source evidence ID",
            ),
        )
        object.__setattr__(
            self,
            "content_hash",
            _require_sha256(self.content_hash, label="dataset content hash"),
        )

        if self.byte_length < 0:
            raise V2AnalysisError("dataset byte length must not be negative")

        object.__setattr__(
            self,
            "media_type",
            _require_nonblank(self.media_type, label="dataset media type"),
        )
        object.__setattr__(
            self,
            "provenance",
            _require_nonblank(self.provenance, label="dataset provenance"),
        )

        steps = tuple(
            _require_nonblank(step, label="preprocessing step") for step in self.preprocessing_steps
        )

        if len(steps) != len(set(steps)):
            raise V2AnalysisError("preprocessing steps must not contain duplicates")

        object.__setattr__(self, "preprocessing_steps", steps)


@dataclass(frozen=True, slots=True)
class V2AnalysisMethod:
    method_id: str
    version: str
    implementation: str
    description: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "method_id",
            _require_nonblank(self.method_id, label="method ID"),
        )
        object.__setattr__(
            self,
            "version",
            _require_nonblank(self.version, label="method version"),
        )
        object.__setattr__(
            self,
            "implementation",
            _require_nonblank(
                self.implementation,
                label="method implementation",
            ),
        )
        object.__setattr__(
            self,
            "description",
            _require_nonblank(self.description, label="method description"),
        )


@dataclass(frozen=True, slots=True)
class V2AnalysisJob:
    job_id: str
    stream_id: str
    position_id: str
    requested_by_player_id: str
    method: V2AnalysisMethod
    inputs: tuple[V2AnalysisInput, ...]
    parameters: tuple[V2AnalysisParameter, ...]
    output_kind: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "job_id",
            _require_nonblank(self.job_id, label="analysis job ID"),
        )
        object.__setattr__(
            self,
            "stream_id",
            _require_nonblank(self.stream_id, label="stream ID"),
        )
        object.__setattr__(
            self,
            "position_id",
            _require_nonblank(self.position_id, label="position ID"),
        )
        object.__setattr__(
            self,
            "requested_by_player_id",
            _require_nonblank(
                self.requested_by_player_id,
                label="requesting player ID",
            ),
        )
        object.__setattr__(
            self,
            "output_kind",
            _require_nonblank(self.output_kind, label="analysis output kind"),
        )

        if not self.inputs:
            raise V2AnalysisError("analysis jobs require at least one input")

        _require_unique_names(
            self.inputs,
            attribute="dataset_id",
            label="analysis inputs",
        )
        _require_unique_names(
            self.parameters,
            attribute="name",
            label="analysis parameters",
        )

        object.__setattr__(
            self,
            "inputs",
            tuple(sorted(self.inputs, key=lambda value: value.dataset_id)),
        )
        object.__setattr__(
            self,
            "parameters",
            tuple(sorted(self.parameters, key=lambda value: value.name)),
        )


@dataclass(frozen=True, slots=True)
class V2AnalysisJobEnvelope:
    schema_version: int
    job: V2AnalysisJob
    job_hash: str

    def __post_init__(self) -> None:
        if self.schema_version != V2_ANALYSIS_JOB_SCHEMA_VERSION:
            raise V2AnalysisError(f"unsupported analysis-job schema version: {self.schema_version}")

        object.__setattr__(
            self,
            "job_hash",
            _require_sha256(self.job_hash, label="analysis job hash"),
        )


@dataclass(frozen=True, slots=True)
class V2AnalysisArtifact:
    artifact_id: str
    job_id: str
    job_hash: str
    input_manifest_hash: str
    method_id: str
    method_version: str
    parameters: tuple[V2AnalysisParameter, ...]
    result_kind: str
    derived_values: tuple[V2AnalysisDerivedValue, ...]
    uncertainties: tuple[V2AnalysisUncertainty, ...]
    limitations: tuple[str, ...]
    software_versions: tuple[V2SoftwareVersion, ...]
    provenance: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "artifact_id",
            _require_nonblank(self.artifact_id, label="artifact ID"),
        )
        object.__setattr__(
            self,
            "job_id",
            _require_nonblank(self.job_id, label="analysis job ID"),
        )
        object.__setattr__(
            self,
            "job_hash",
            _require_sha256(self.job_hash, label="analysis job hash"),
        )
        object.__setattr__(
            self,
            "input_manifest_hash",
            _require_sha256(
                self.input_manifest_hash,
                label="input manifest hash",
            ),
        )
        object.__setattr__(
            self,
            "method_id",
            _require_nonblank(self.method_id, label="method ID"),
        )
        object.__setattr__(
            self,
            "method_version",
            _require_nonblank(self.method_version, label="method version"),
        )
        object.__setattr__(
            self,
            "result_kind",
            _require_nonblank(self.result_kind, label="result kind"),
        )

        _require_unique_names(
            self.parameters,
            attribute="name",
            label="artifact parameters",
        )
        _require_unique_names(
            self.derived_values,
            attribute="name",
            label="derived values",
        )
        _require_unique_names(
            self.uncertainties,
            attribute="source",
            label="uncertainties",
        )
        _require_unique_names(
            self.software_versions,
            attribute="name",
            label="software versions",
        )

        object.__setattr__(
            self,
            "parameters",
            tuple(sorted(self.parameters, key=lambda value: value.name)),
        )
        object.__setattr__(
            self,
            "derived_values",
            tuple(sorted(self.derived_values, key=lambda value: value.name)),
        )
        object.__setattr__(
            self,
            "uncertainties",
            tuple(sorted(self.uncertainties, key=lambda value: value.source)),
        )
        object.__setattr__(
            self,
            "software_versions",
            tuple(sorted(self.software_versions, key=lambda value: value.name)),
        )
        object.__setattr__(
            self,
            "limitations",
            _require_nonempty_strings(
                self.limitations,
                label="artifact limitation",
            ),
        )
        object.__setattr__(
            self,
            "provenance",
            _require_nonempty_strings(
                self.provenance,
                label="artifact provenance",
            ),
        )

        if not self.derived_values:
            raise V2AnalysisError(
                "successful analysis artifacts require at least one derived value"
            )

        if not self.uncertainties:
            raise V2AnalysisError("successful analysis artifacts require uncertainty statements")

        if not self.software_versions:
            raise V2AnalysisError("successful analysis artifacts require software versions")


@dataclass(frozen=True, slots=True)
class V2AnalysisArtifactEnvelope:
    schema_version: int
    artifact: V2AnalysisArtifact
    artifact_hash: str

    def __post_init__(self) -> None:
        if self.schema_version != V2_ANALYSIS_ARTIFACT_SCHEMA_VERSION:
            raise V2AnalysisError(
                f"unsupported analysis-artifact schema version: {self.schema_version}"
            )

        object.__setattr__(
            self,
            "artifact_hash",
            _require_sha256(self.artifact_hash, label="analysis artifact hash"),
        )


def calculate_dataset_hash(data: bytes | bytearray | memoryview) -> str:
    return hashlib.sha256(bytes(data)).hexdigest()


def _analysis_value_to_record(value: V2AnalysisValue) -> object:
    return value.to_python()


def _analysis_value_from_record(value: object) -> V2AnalysisValue:
    return V2AnalysisValue.from_python(value)


def _parameter_to_record(parameter: V2AnalysisParameter) -> dict[str, object]:
    return {
        "name": parameter.name,
        "unit": parameter.unit,
        "value": _analysis_value_to_record(parameter.value),
    }


def _parameter_from_record(value: object) -> V2AnalysisParameter:
    record = _require_mapping(value, label="analysis parameter")
    _require_exact_keys(
        record,
        expected=frozenset({"name", "unit", "value"}),
        label="analysis parameter",
    )
    return V2AnalysisParameter(
        name=_require_string(record["name"], label="parameter name"),
        value=_analysis_value_from_record(record["value"]),
        unit=_require_optional_string(record["unit"], label="parameter unit"),
    )


def _derived_value_to_record(
    value: V2AnalysisDerivedValue,
) -> dict[str, object]:
    return {
        "name": value.name,
        "unit": value.unit,
        "value": _analysis_value_to_record(value.value),
    }


def _derived_value_from_record(value: object) -> V2AnalysisDerivedValue:
    record = _require_mapping(value, label="derived value")
    _require_exact_keys(
        record,
        expected=frozenset({"name", "unit", "value"}),
        label="derived value",
    )
    return V2AnalysisDerivedValue(
        name=_require_string(record["name"], label="derived-value name"),
        value=_analysis_value_from_record(record["value"]),
        unit=_require_optional_string(record["unit"], label="derived-value unit"),
    )


def _uncertainty_to_record(
    uncertainty: V2AnalysisUncertainty,
) -> dict[str, object]:
    return {
        "source": uncertainty.source,
        "statement": uncertainty.statement,
        "unit": uncertainty.unit,
        "value": (
            None if uncertainty.value is None else _analysis_value_to_record(uncertainty.value)
        ),
    }


def _uncertainty_from_record(value: object) -> V2AnalysisUncertainty:
    record = _require_mapping(value, label="analysis uncertainty")
    _require_exact_keys(
        record,
        expected=frozenset({"source", "statement", "unit", "value"}),
        label="analysis uncertainty",
    )
    quantified = record["value"]
    return V2AnalysisUncertainty(
        source=_require_string(record["source"], label="uncertainty source"),
        statement=_require_string(
            record["statement"],
            label="uncertainty statement",
        ),
        value=(None if quantified is None else _analysis_value_from_record(quantified)),
        unit=_require_optional_string(record["unit"], label="uncertainty unit"),
    )


def _software_version_to_record(
    value: V2SoftwareVersion,
) -> dict[str, object]:
    return {"name": value.name, "version": value.version}


def _software_version_from_record(value: object) -> V2SoftwareVersion:
    record = _require_mapping(value, label="software version")
    _require_exact_keys(
        record,
        expected=frozenset({"name", "version"}),
        label="software version",
    )
    return V2SoftwareVersion(
        name=_require_string(record["name"], label="software name"),
        version=_require_string(record["version"], label="software version"),
    )


def analysis_input_to_record(value: V2AnalysisInput) -> dict[str, object]:
    return {
        "byte_length": value.byte_length,
        "content_hash": value.content_hash,
        "dataset_id": value.dataset_id,
        "media_type": value.media_type,
        "preprocessing_steps": list(value.preprocessing_steps),
        "provenance": value.provenance,
        "source_evidence_id": value.source_evidence_id,
    }


def analysis_input_from_record(value: object) -> V2AnalysisInput:
    record = _require_mapping(value, label="analysis input")
    _require_exact_keys(
        record,
        expected=frozenset(
            {
                "byte_length",
                "content_hash",
                "dataset_id",
                "media_type",
                "preprocessing_steps",
                "provenance",
                "source_evidence_id",
            }
        ),
        label="analysis input",
    )
    steps = tuple(
        _require_string(item, label="preprocessing step")
        for item in _require_sequence(
            record["preprocessing_steps"],
            label="preprocessing steps",
        )
    )
    return V2AnalysisInput(
        dataset_id=_require_string(record["dataset_id"], label="dataset ID"),
        source_evidence_id=_require_string(
            record["source_evidence_id"],
            label="source evidence ID",
        ),
        content_hash=_require_string(
            record["content_hash"],
            label="dataset content hash",
        ),
        byte_length=_require_integer(
            record["byte_length"],
            label="dataset byte length",
        ),
        media_type=_require_string(
            record["media_type"],
            label="dataset media type",
        ),
        provenance=_require_string(
            record["provenance"],
            label="dataset provenance",
        ),
        preprocessing_steps=steps,
    )


def _method_to_record(value: V2AnalysisMethod) -> dict[str, object]:
    return {
        "description": value.description,
        "implementation": value.implementation,
        "method_id": value.method_id,
        "version": value.version,
    }


def _method_from_record(value: object) -> V2AnalysisMethod:
    record = _require_mapping(value, label="analysis method")
    _require_exact_keys(
        record,
        expected=frozenset({"description", "implementation", "method_id", "version"}),
        label="analysis method",
    )
    return V2AnalysisMethod(
        method_id=_require_string(record["method_id"], label="method ID"),
        version=_require_string(record["version"], label="method version"),
        implementation=_require_string(
            record["implementation"],
            label="method implementation",
        ),
        description=_require_string(
            record["description"],
            label="method description",
        ),
    )


def analysis_job_to_record(value: V2AnalysisJob) -> dict[str, object]:
    return {
        "inputs": [analysis_input_to_record(item) for item in value.inputs],
        "job_id": value.job_id,
        "method": _method_to_record(value.method),
        "output_kind": value.output_kind,
        "parameters": [_parameter_to_record(item) for item in value.parameters],
        "position_id": value.position_id,
        "requested_by_player_id": value.requested_by_player_id,
        "stream_id": value.stream_id,
    }


def analysis_job_from_record(value: object) -> V2AnalysisJob:
    record = _require_mapping(value, label="analysis job")
    _require_exact_keys(
        record,
        expected=frozenset(
            {
                "inputs",
                "job_id",
                "method",
                "output_kind",
                "parameters",
                "position_id",
                "requested_by_player_id",
                "stream_id",
            }
        ),
        label="analysis job",
    )
    return V2AnalysisJob(
        job_id=_require_string(record["job_id"], label="analysis job ID"),
        stream_id=_require_string(record["stream_id"], label="stream ID"),
        position_id=_require_string(record["position_id"], label="position ID"),
        requested_by_player_id=_require_string(
            record["requested_by_player_id"],
            label="requesting player ID",
        ),
        method=_method_from_record(record["method"]),
        inputs=tuple(
            analysis_input_from_record(item)
            for item in _require_sequence(
                record["inputs"],
                label="analysis inputs",
            )
        ),
        parameters=tuple(
            _parameter_from_record(item)
            for item in _require_sequence(
                record["parameters"],
                label="analysis parameters",
            )
        ),
        output_kind=_require_string(
            record["output_kind"],
            label="analysis output kind",
        ),
    )


def calculate_input_manifest_hash(
    inputs: Iterable[V2AnalysisInput],
) -> str:
    normalized = tuple(sorted(inputs, key=lambda value: value.dataset_id))

    if not normalized:
        raise V2AnalysisError("input manifests require at least one dataset")

    _require_unique_names(
        normalized,
        attribute="dataset_id",
        label="input manifest",
    )
    record = {
        "inputs": [analysis_input_to_record(item) for item in normalized],
        "schema_version": 1,
    }
    return hashlib.sha256(canonical_json_bytes(record)).hexdigest()


def calculate_analysis_job_hash(job: V2AnalysisJob) -> str:
    record = {
        "job": analysis_job_to_record(job),
        "schema_version": V2_ANALYSIS_JOB_SCHEMA_VERSION,
    }
    return hashlib.sha256(canonical_json_bytes(record)).hexdigest()


def create_analysis_job_envelope(
    job: V2AnalysisJob,
) -> V2AnalysisJobEnvelope:
    return V2AnalysisJobEnvelope(
        schema_version=V2_ANALYSIS_JOB_SCHEMA_VERSION,
        job=job,
        job_hash=calculate_analysis_job_hash(job),
    )


def verify_analysis_job_envelope(
    envelope: V2AnalysisJobEnvelope,
) -> V2AnalysisJob:
    expected = calculate_analysis_job_hash(envelope.job)

    if envelope.job_hash != expected:
        raise V2AnalysisIntegrityError("analysis job hash does not match its canonical job record")

    return envelope.job


def serialize_analysis_job_envelope(
    envelope: V2AnalysisJobEnvelope,
) -> bytes:
    verify_analysis_job_envelope(envelope)
    record = {
        "job": analysis_job_to_record(envelope.job),
        "job_hash": envelope.job_hash,
        "schema_version": envelope.schema_version,
    }
    return canonical_json_bytes(record)


def deserialize_analysis_job_envelope(
    data: bytes | bytearray | memoryview | str,
) -> V2AnalysisJobEnvelope:
    record = _require_mapping(
        _load_json(data, label="analysis job envelope"),
        label="analysis job envelope",
    )
    _require_exact_keys(
        record,
        expected=frozenset({"job", "job_hash", "schema_version"}),
        label="analysis job envelope",
    )
    envelope = V2AnalysisJobEnvelope(
        schema_version=_require_integer(
            record["schema_version"],
            label="analysis-job schema version",
        ),
        job=analysis_job_from_record(record["job"]),
        job_hash=_require_string(record["job_hash"], label="analysis job hash"),
    )
    verify_analysis_job_envelope(envelope)
    return envelope


def analysis_artifact_to_record(
    value: V2AnalysisArtifact,
) -> dict[str, object]:
    return {
        "artifact_id": value.artifact_id,
        "derived_values": [_derived_value_to_record(item) for item in value.derived_values],
        "input_manifest_hash": value.input_manifest_hash,
        "job_hash": value.job_hash,
        "job_id": value.job_id,
        "limitations": list(value.limitations),
        "method_id": value.method_id,
        "method_version": value.method_version,
        "parameters": [_parameter_to_record(item) for item in value.parameters],
        "provenance": list(value.provenance),
        "result_kind": value.result_kind,
        "software_versions": [
            _software_version_to_record(item) for item in value.software_versions
        ],
        "uncertainties": [_uncertainty_to_record(item) for item in value.uncertainties],
    }


def analysis_artifact_from_record(value: object) -> V2AnalysisArtifact:
    record = _require_mapping(value, label="analysis artifact")
    _require_exact_keys(
        record,
        expected=frozenset(
            {
                "artifact_id",
                "derived_values",
                "input_manifest_hash",
                "job_hash",
                "job_id",
                "limitations",
                "method_id",
                "method_version",
                "parameters",
                "provenance",
                "result_kind",
                "software_versions",
                "uncertainties",
            }
        ),
        label="analysis artifact",
    )
    return V2AnalysisArtifact(
        artifact_id=_require_string(record["artifact_id"], label="artifact ID"),
        job_id=_require_string(record["job_id"], label="analysis job ID"),
        job_hash=_require_string(record["job_hash"], label="analysis job hash"),
        input_manifest_hash=_require_string(
            record["input_manifest_hash"],
            label="input manifest hash",
        ),
        method_id=_require_string(record["method_id"], label="method ID"),
        method_version=_require_string(
            record["method_version"],
            label="method version",
        ),
        parameters=tuple(
            _parameter_from_record(item)
            for item in _require_sequence(
                record["parameters"],
                label="artifact parameters",
            )
        ),
        result_kind=_require_string(record["result_kind"], label="result kind"),
        derived_values=tuple(
            _derived_value_from_record(item)
            for item in _require_sequence(
                record["derived_values"],
                label="derived values",
            )
        ),
        uncertainties=tuple(
            _uncertainty_from_record(item)
            for item in _require_sequence(
                record["uncertainties"],
                label="analysis uncertainties",
            )
        ),
        limitations=tuple(
            _require_string(item, label="artifact limitation")
            for item in _require_sequence(
                record["limitations"],
                label="artifact limitations",
            )
        ),
        software_versions=tuple(
            _software_version_from_record(item)
            for item in _require_sequence(
                record["software_versions"],
                label="software versions",
            )
        ),
        provenance=tuple(
            _require_string(item, label="artifact provenance")
            for item in _require_sequence(
                record["provenance"],
                label="artifact provenance",
            )
        ),
    )


def calculate_analysis_artifact_hash(
    artifact: V2AnalysisArtifact,
) -> str:
    record = {
        "artifact": analysis_artifact_to_record(artifact),
        "schema_version": V2_ANALYSIS_ARTIFACT_SCHEMA_VERSION,
    }
    return hashlib.sha256(canonical_json_bytes(record)).hexdigest()


def create_analysis_artifact_envelope(
    job_envelope: V2AnalysisJobEnvelope,
    *,
    artifact_id: str,
    derived_values: Iterable[V2AnalysisDerivedValue],
    uncertainties: Iterable[V2AnalysisUncertainty],
    limitations: Iterable[str],
    software_versions: Iterable[V2SoftwareVersion],
    provenance: Iterable[str],
) -> V2AnalysisArtifactEnvelope:
    job = verify_analysis_job_envelope(job_envelope)
    artifact = V2AnalysisArtifact(
        artifact_id=artifact_id,
        job_id=job.job_id,
        job_hash=job_envelope.job_hash,
        input_manifest_hash=calculate_input_manifest_hash(job.inputs),
        method_id=job.method.method_id,
        method_version=job.method.version,
        parameters=job.parameters,
        result_kind=job.output_kind,
        derived_values=tuple(derived_values),
        uncertainties=tuple(uncertainties),
        limitations=tuple(limitations),
        software_versions=tuple(software_versions),
        provenance=tuple(provenance),
    )
    return V2AnalysisArtifactEnvelope(
        schema_version=V2_ANALYSIS_ARTIFACT_SCHEMA_VERSION,
        artifact=artifact,
        artifact_hash=calculate_analysis_artifact_hash(artifact),
    )


def verify_analysis_artifact_envelope(
    envelope: V2AnalysisArtifactEnvelope,
    *,
    job_envelope: V2AnalysisJobEnvelope | None = None,
) -> V2AnalysisArtifact:
    expected = calculate_analysis_artifact_hash(envelope.artifact)

    if envelope.artifact_hash != expected:
        raise V2AnalysisIntegrityError(
            "analysis artifact hash does not match its canonical artifact record"
        )

    if job_envelope is None:
        return envelope.artifact

    job = verify_analysis_job_envelope(job_envelope)
    artifact = envelope.artifact

    if artifact.job_id != job.job_id:
        raise V2AnalysisIntegrityError("analysis artifact belongs to a different job ID")

    if artifact.job_hash != job_envelope.job_hash:
        raise V2AnalysisIntegrityError("analysis artifact belongs to a different job hash")

    expected_manifest_hash = calculate_input_manifest_hash(job.inputs)

    if artifact.input_manifest_hash != expected_manifest_hash:
        raise V2AnalysisIntegrityError("analysis artifact input manifest does not match its job")

    if artifact.method_id != job.method.method_id:
        raise V2AnalysisIntegrityError("analysis artifact method ID does not match its job")

    if artifact.method_version != job.method.version:
        raise V2AnalysisIntegrityError("analysis artifact method version does not match its job")

    if artifact.parameters != job.parameters:
        raise V2AnalysisIntegrityError("analysis artifact parameters do not match its job")

    if artifact.result_kind != job.output_kind:
        raise V2AnalysisIntegrityError("analysis artifact result kind does not match its job")

    return artifact


def serialize_analysis_artifact_envelope(
    envelope: V2AnalysisArtifactEnvelope,
) -> bytes:
    verify_analysis_artifact_envelope(envelope)
    record = {
        "artifact": analysis_artifact_to_record(envelope.artifact),
        "artifact_hash": envelope.artifact_hash,
        "schema_version": envelope.schema_version,
    }
    return canonical_json_bytes(record)


def deserialize_analysis_artifact_envelope(
    data: bytes | bytearray | memoryview | str,
) -> V2AnalysisArtifactEnvelope:
    record = _require_mapping(
        _load_json(data, label="analysis artifact envelope"),
        label="analysis artifact envelope",
    )
    _require_exact_keys(
        record,
        expected=frozenset({"artifact", "artifact_hash", "schema_version"}),
        label="analysis artifact envelope",
    )
    envelope = V2AnalysisArtifactEnvelope(
        schema_version=_require_integer(
            record["schema_version"],
            label="analysis-artifact schema version",
        ),
        artifact=analysis_artifact_from_record(record["artifact"]),
        artifact_hash=_require_string(
            record["artifact_hash"],
            label="analysis artifact hash",
        ),
    )
    verify_analysis_artifact_envelope(envelope)
    return envelope
