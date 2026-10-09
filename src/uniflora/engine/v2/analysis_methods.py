from __future__ import annotations

import json
import platform
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from fractions import Fraction

from uniflora.engine.v2.analysis import (
    V2AnalysisDerivedValue,
    V2AnalysisInput,
    V2AnalysisJob,
    V2AnalysisJobEnvelope,
    V2AnalysisMethod,
    V2AnalysisParameter,
    V2AnalysisUncertainty,
    V2SoftwareVersion,
    create_analysis_job_envelope,
)
from uniflora.engine.v2.analysis_worker import (
    V2AnalysisExecutionRequest,
    V2AnalysisExecutionResult,
    V2AnalysisMethodExecutionError,
    V2AnalysisMethodRegistry,
)
from uniflora.engine.v2.serialization import canonical_json_bytes

V2_CLOCK_ALIGNMENT_METHOD_ID = "cross_source_clock_alignment"
V2_CLOCK_ALIGNMENT_METHOD_VERSION = "1.0.0"
V2_CLOCK_ALIGNMENT_OUTPUT_KIND = "cross_source_clock_alignment_report"
V2_CLOCK_OBSERVATION_MEDIA_TYPE = "application/vnd.uniflora.clock-observations+json"

V2_CLOCK_ALIGNMENT_METHOD = V2AnalysisMethod(
    method_id=V2_CLOCK_ALIGNMENT_METHOD_ID,
    version=V2_CLOCK_ALIGNMENT_METHOD_VERSION,
    implementation=("uniflora.engine.v2.analysis_methods:execute_cross_source_clock_alignment"),
    description=(
        "Estimate constant relative clock offsets from shared event identifiers "
        "while preserving declared timestamp uncertainty and residual mismatch."
    ),
)


class V2ClockAlignmentError(ValueError):
    """Raised when clock-observation data or parameters are invalid."""


def _require_nonblank(value: str, *, label: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise V2ClockAlignmentError(f"{label} must not be blank")
    return normalized


def _require_integer(value: object, *, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise V2ClockAlignmentError(f"{label} must be an integer")
    return value


def _require_nonnegative_integer(value: object, *, label: str) -> int:
    parsed = _require_integer(value, label=label)
    if parsed < 0:
        raise V2ClockAlignmentError(f"{label} must not be negative")
    return parsed


def _require_mapping(value: object, *, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise V2ClockAlignmentError(f"{label} must be a JSON object")
    if not all(isinstance(key, str) for key in value):
        raise V2ClockAlignmentError(f"{label} keys must be strings")
    return value


def _require_sequence(value: object, *, label: str) -> Sequence[object]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise V2ClockAlignmentError(f"{label} must be a JSON array")
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
    raise V2ClockAlignmentError(f"{label} has invalid fields: {'; '.join(details)}")


def _fraction_record(value: Fraction) -> dict[str, int]:
    return {
        "denominator": value.denominator,
        "numerator": value.numerator,
    }


def _median(values: Sequence[int | Fraction]) -> Fraction:
    if not values:
        raise V2ClockAlignmentError("cannot calculate a median without values")

    ordered = sorted(Fraction(value) for value in values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def _parameter_map(
    parameters: Iterable[V2AnalysisParameter],
) -> dict[str, V2AnalysisParameter]:
    return {parameter.name: parameter for parameter in parameters}


@dataclass(frozen=True, slots=True)
class V2ClockObservation:
    event_id: str
    timestamp_us: int
    uncertainty_us: int

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "event_id",
            _require_nonblank(self.event_id, label="event ID"),
        )
        object.__setattr__(
            self,
            "timestamp_us",
            _require_integer(self.timestamp_us, label="timestamp"),
        )
        object.__setattr__(
            self,
            "uncertainty_us",
            _require_nonnegative_integer(
                self.uncertainty_us,
                label="timestamp uncertainty",
            ),
        )


@dataclass(frozen=True, slots=True)
class V2ClockObservationDataset:
    clock_id: str
    observations: tuple[V2ClockObservation, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "clock_id",
            _require_nonblank(self.clock_id, label="clock ID"),
        )
        normalized = tuple(sorted(self.observations, key=lambda item: item.event_id))
        if not normalized:
            raise V2ClockAlignmentError(
                "clock-observation datasets require at least one observation"
            )
        event_ids = tuple(item.event_id for item in normalized)
        if len(event_ids) != len(set(event_ids)):
            raise V2ClockAlignmentError("clock-observation datasets must not repeat event IDs")
        object.__setattr__(self, "observations", normalized)

    def observation_map(self) -> dict[str, V2ClockObservation]:
        return {item.event_id: item for item in self.observations}


def serialize_clock_observation_dataset(
    dataset: V2ClockObservationDataset,
) -> bytes:
    return canonical_json_bytes(
        {
            "clock_id": dataset.clock_id,
            "observations": [
                {
                    "event_id": observation.event_id,
                    "timestamp_us": observation.timestamp_us,
                    "uncertainty_us": observation.uncertainty_us,
                }
                for observation in dataset.observations
            ],
        }
    )


def deserialize_clock_observation_dataset(
    data: bytes | bytearray | memoryview | str,
) -> V2ClockObservationDataset:
    try:
        if isinstance(data, str):
            parsed = json.loads(data)
        else:
            parsed = json.loads(bytes(data).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise V2ClockAlignmentError(f"invalid clock-observation JSON: {exc}") from exc

    record = _require_mapping(parsed, label="clock-observation dataset")
    _require_exact_keys(
        record,
        expected=frozenset({"clock_id", "observations"}),
        label="clock-observation dataset",
    )

    clock_id_value = record["clock_id"]
    if not isinstance(clock_id_value, str):
        raise V2ClockAlignmentError("clock ID must be a string")

    observations: list[V2ClockObservation] = []
    for index, value in enumerate(_require_sequence(record["observations"], label="observations")):
        observation = _require_mapping(
            value,
            label=f"observation {index}",
        )
        _require_exact_keys(
            observation,
            expected=frozenset({"event_id", "timestamp_us", "uncertainty_us"}),
            label=f"observation {index}",
        )
        event_id_value = observation["event_id"]
        if not isinstance(event_id_value, str):
            raise V2ClockAlignmentError(f"observation {index} event ID must be a string")
        observations.append(
            V2ClockObservation(
                event_id=event_id_value,
                timestamp_us=_require_integer(
                    observation["timestamp_us"],
                    label=f"observation {index} timestamp",
                ),
                uncertainty_us=_require_nonnegative_integer(
                    observation["uncertainty_us"],
                    label=f"observation {index} timestamp uncertainty",
                ),
            )
        )

    return V2ClockObservationDataset(
        clock_id=clock_id_value,
        observations=tuple(observations),
    )


def create_cross_source_clock_alignment_job(
    *,
    job_id: str,
    stream_id: str,
    position_id: str,
    requested_by_player_id: str,
    inputs: tuple[V2AnalysisInput, ...],
    reference_dataset_id: str,
    minimum_shared_events: int = 2,
    tolerance_us: int | None = None,
) -> V2AnalysisJobEnvelope:
    if len(inputs) < 2:
        raise V2ClockAlignmentError("clock alignment requires at least two retained datasets")

    normalized_reference = _require_nonblank(
        reference_dataset_id,
        label="reference dataset ID",
    )
    input_ids = {item.dataset_id for item in inputs}
    if normalized_reference not in input_ids:
        raise V2ClockAlignmentError("reference dataset ID must identify one supplied input")

    if minimum_shared_events < 1:
        raise V2ClockAlignmentError("minimum shared events must be at least one")

    parameters = [
        V2AnalysisParameter.from_value(
            "minimum_shared_events",
            minimum_shared_events,
            unit="events",
        ),
        V2AnalysisParameter.from_value(
            "reference_dataset_id",
            normalized_reference,
        ),
    ]
    if tolerance_us is not None:
        if tolerance_us < 0:
            raise V2ClockAlignmentError("alignment tolerance must not be negative")
        parameters.append(
            V2AnalysisParameter.from_value(
                "tolerance_us",
                tolerance_us,
                unit="microseconds",
            )
        )

    return create_analysis_job_envelope(
        V2AnalysisJob(
            job_id=job_id,
            stream_id=stream_id,
            position_id=position_id,
            requested_by_player_id=requested_by_player_id,
            method=V2_CLOCK_ALIGNMENT_METHOD,
            inputs=inputs,
            parameters=tuple(parameters),
            output_kind=V2_CLOCK_ALIGNMENT_OUTPUT_KIND,
        )
    )


def _read_parameters(
    request: V2AnalysisExecutionRequest,
) -> tuple[str, int, int | None]:
    parameters = _parameter_map(request.job_envelope.job.parameters)
    allowed = {
        "minimum_shared_events",
        "reference_dataset_id",
        "tolerance_us",
    }
    unknown = sorted(set(parameters) - allowed)
    if unknown:
        raise V2ClockAlignmentError("unsupported clock-alignment parameters: " + ", ".join(unknown))

    reference_parameter = parameters.get("reference_dataset_id")
    minimum_parameter = parameters.get("minimum_shared_events")
    if reference_parameter is None or minimum_parameter is None:
        raise V2ClockAlignmentError(
            "clock alignment requires reference_dataset_id and minimum_shared_events parameters"
        )

    if reference_parameter.unit is not None:
        raise V2ClockAlignmentError("reference_dataset_id must not declare a unit")
    if minimum_parameter.unit != "events":
        raise V2ClockAlignmentError("minimum_shared_events must use the 'events' unit")

    reference_value = reference_parameter.value.to_python()
    if not isinstance(reference_value, str):
        raise V2ClockAlignmentError("reference_dataset_id must be a string")
    reference_dataset_id = _require_nonblank(
        reference_value,
        label="reference dataset ID",
    )

    minimum_shared_events = _require_integer(
        minimum_parameter.value.to_python(),
        label="minimum shared events",
    )
    if minimum_shared_events < 1:
        raise V2ClockAlignmentError("minimum shared events must be at least one")

    tolerance_parameter = parameters.get("tolerance_us")
    tolerance_us: int | None = None
    if tolerance_parameter is not None:
        if tolerance_parameter.unit != "microseconds":
            raise V2ClockAlignmentError("tolerance_us must use the 'microseconds' unit")
        tolerance_us = _require_nonnegative_integer(
            tolerance_parameter.value.to_python(),
            label="alignment tolerance",
        )

    return reference_dataset_id, minimum_shared_events, tolerance_us


def _load_datasets(
    request: V2AnalysisExecutionRequest,
) -> dict[str, V2ClockObservationDataset]:
    loaded: dict[str, V2ClockObservationDataset] = {}
    clock_ids: set[str] = set()

    for resolved in request.inputs:
        if resolved.descriptor.media_type not in {
            "application/json",
            V2_CLOCK_OBSERVATION_MEDIA_TYPE,
        }:
            raise V2ClockAlignmentError(
                f"dataset {resolved.dataset_id!r} must use JSON clock-observation media type"
            )
        dataset = deserialize_clock_observation_dataset(resolved.data)
        if dataset.clock_id in clock_ids:
            raise V2ClockAlignmentError(
                f"clock ID {dataset.clock_id!r} is repeated across datasets"
            )
        loaded[resolved.dataset_id] = dataset
        clock_ids.add(dataset.clock_id)

    if len(loaded) < 2:
        raise V2ClockAlignmentError("clock alignment requires at least two resolved datasets")
    return loaded


def _execute_cross_source_clock_alignment(
    request: V2AnalysisExecutionRequest,
) -> V2AnalysisExecutionResult:
    job = request.job_envelope.job
    if job.output_kind != V2_CLOCK_ALIGNMENT_OUTPUT_KIND:
        raise V2ClockAlignmentError("clock-alignment job has an incompatible output kind")

    reference_dataset_id, minimum_shared_events, tolerance_us = _read_parameters(request)
    datasets = _load_datasets(request)
    reference = datasets.get(reference_dataset_id)
    if reference is None:
        raise V2ClockAlignmentError("reference dataset is not present in the resolved input set")

    reference_observations = reference.observation_map()
    offsets: dict[str, dict[str, int]] = {reference_dataset_id: _fraction_record(Fraction(0))}
    shared_counts: dict[str, int] = {}
    residual_summary: dict[str, dict[str, dict[str, int]]] = {}
    declared_uncertainty: dict[str, int] = {}
    residual_uncertainty: dict[str, dict[str, int]] = {}
    maximum_absolute_residual = Fraction(0)

    for dataset_id, dataset in sorted(datasets.items()):
        if dataset_id == reference_dataset_id:
            continue

        observations = dataset.observation_map()
        shared_event_ids = sorted(set(reference_observations) & set(observations))
        if len(shared_event_ids) < minimum_shared_events:
            raise V2ClockAlignmentError(
                f"dataset {dataset_id!r} shares {len(shared_event_ids)} events; "
                f"at least {minimum_shared_events} are required"
            )

        deltas = [
            reference_observations[event_id].timestamp_us - observations[event_id].timestamp_us
            for event_id in shared_event_ids
        ]
        offset = _median(deltas)
        residuals = [
            Fraction(observations[event_id].timestamp_us)
            + offset
            - reference_observations[event_id].timestamp_us
            for event_id in shared_event_ids
        ]
        absolute_residuals = [abs(value) for value in residuals]
        maximum_residual = max(absolute_residuals)
        median_residual = _median(absolute_residuals)
        maximum_declared_pair_uncertainty = max(
            reference_observations[event_id].uncertainty_us + observations[event_id].uncertainty_us
            for event_id in shared_event_ids
        )

        offsets[dataset_id] = _fraction_record(offset)
        shared_counts[dataset_id] = len(shared_event_ids)
        residual_summary[dataset_id] = {
            "maximum_absolute_residual_us": _fraction_record(maximum_residual),
            "median_absolute_residual_us": _fraction_record(median_residual),
        }
        declared_uncertainty[dataset_id] = maximum_declared_pair_uncertainty
        residual_uncertainty[dataset_id] = _fraction_record(maximum_residual)
        maximum_absolute_residual = max(
            maximum_absolute_residual,
            maximum_residual,
        )

    derived_values = [
        V2AnalysisDerivedValue.from_value(
            "alignment_offsets",
            offsets,
            unit="microseconds",
        ),
        V2AnalysisDerivedValue.from_value(
            "maximum_absolute_residual",
            _fraction_record(maximum_absolute_residual),
            unit="microseconds",
        ),
        V2AnalysisDerivedValue.from_value(
            "reference_clock_id",
            reference.clock_id,
        ),
        V2AnalysisDerivedValue.from_value(
            "reference_dataset_id",
            reference_dataset_id,
        ),
        V2AnalysisDerivedValue.from_value(
            "residual_summary",
            residual_summary,
            unit="microseconds",
        ),
        V2AnalysisDerivedValue.from_value(
            "shared_event_counts",
            shared_counts,
            unit="events",
        ),
    ]
    if tolerance_us is not None:
        derived_values.extend(
            (
                V2AnalysisDerivedValue.from_value(
                    "all_sources_within_tolerance",
                    maximum_absolute_residual <= tolerance_us,
                ),
                V2AnalysisDerivedValue.from_value(
                    "tolerance",
                    tolerance_us,
                    unit="microseconds",
                ),
            )
        )

    provenance = [
        (
            f"Dataset {resolved.descriptor.dataset_id} retained from evidence "
            f"{resolved.descriptor.source_evidence_id} with SHA-256 "
            f"{resolved.descriptor.content_hash}."
        )
        for resolved in request.inputs
    ]
    provenance.append(
        "Constant-offset alignment used exact shared event identifiers and "
        "retained integer microsecond timestamps."
    )

    return V2AnalysisExecutionResult(
        derived_values=tuple(derived_values),
        uncertainties=(
            V2AnalysisUncertainty.quantified(
                "alignment_residual_dispersion",
                ("Maximum post-alignment residual for each non-reference dataset."),
                residual_uncertainty,
                unit="microseconds",
            ),
            V2AnalysisUncertainty.quantified(
                "declared_timestamp_uncertainty",
                (
                    "Maximum summed timestamp uncertainty across shared event "
                    "pairs for each non-reference dataset."
                ),
                declared_uncertainty,
                unit="microseconds",
            ),
            V2AnalysisUncertainty(
                source="event_correspondence_assumption",
                statement=(
                    "The method assumes equal event IDs identify the same "
                    "physical occurrence across sources."
                ),
            ),
        ),
        limitations=(
            "A constant offset does not estimate clock drift or nonlinear timing error.",
            "Alignment does not establish that differently mediated records share one cause.",
            "Event matching is inherited from dataset preparation rather than inferred here.",
            "Sparse shared events can conceal local timing departures between matched events.",
        ),
        software_versions=(
            V2SoftwareVersion(
                name="python",
                version=platform.python_version(),
            ),
            V2SoftwareVersion(
                name="uniflora-clock-alignment",
                version=V2_CLOCK_ALIGNMENT_METHOD_VERSION,
            ),
        ),
        provenance=tuple(provenance),
    )


def execute_cross_source_clock_alignment(
    request: V2AnalysisExecutionRequest,
) -> V2AnalysisExecutionResult:
    try:
        return _execute_cross_source_clock_alignment(request)
    except V2AnalysisMethodExecutionError:
        raise
    except (TypeError, ValueError) as exc:
        raise V2AnalysisMethodExecutionError(
            f"invalid cross-source clock-alignment input: {exc}",
            retryable=False,
        ) from exc


def create_registry() -> V2AnalysisMethodRegistry:
    registry = V2AnalysisMethodRegistry()
    registry.register(
        V2_CLOCK_ALIGNMENT_METHOD,
        execute_cross_source_clock_alignment,
    )
    return registry
