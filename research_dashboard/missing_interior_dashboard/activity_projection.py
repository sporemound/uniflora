from __future__ import annotations

import json
from collections.abc import Iterable
from itertools import pairwise
from typing import Any

import numpy as np
import pandas as pd

from .analysis import TIME_BASIS_TO_ZONE, compute_spectrogram
from .models import AnalysisArtifact

ACTIVITY_DATA_FILENAME = "activity-data.json"
ACTIVITY_VISUALIZATION_FILENAME = "activity-visualization.json"
ACTIVITY_MANIFEST_FILENAME = "manifest-phase3b.json"
ACTIVITY_SCHEMA_VERSION = "3.0.0"
DEFAULT_MAX_WAVEFORM_POINTS = 640
DEFAULT_MAX_SPECTROGRAM_TIME_BINS = 96
DEFAULT_MAX_SPECTROGRAM_FREQUENCY_BINS = 64


def canonical_json(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def build_activity_dataset(
    artifact: AnalysisArtifact,
    frame: pd.DataFrame,
    visualization_id: str,
    *,
    max_waveform_points: int = DEFAULT_MAX_WAVEFORM_POINTS,
    max_spectrogram_time_bins: int = DEFAULT_MAX_SPECTROGRAM_TIME_BINS,
    max_spectrogram_frequency_bins: int = DEFAULT_MAX_SPECTROGRAM_FREQUENCY_BINS,
) -> dict[str, Any]:
    if max_waveform_points < 16:
        raise ValueError("max_waveform_points must be at least 16")
    if max_spectrogram_time_bins < 8:
        raise ValueError("max_spectrogram_time_bins must be at least 8")
    if max_spectrogram_frequency_bins < 8:
        raise ValueError("max_spectrogram_frequency_bins must be at least 8")

    sample_indices = _envelope_sample_indices(
        frame["calibrated_voltage_v"].to_numpy(dtype=float),
        max_waveform_points,
    )
    selected = frame.iloc[sample_indices]
    samples = [
        {
            "sampleIndex": int(row.sample_index),
            "timeSeconds": _number(row.offset_seconds),
            "rawVoltageV": _number(row.raw_voltage_v),
            "calibratedVoltageV": _number(row.calibrated_voltage_v),
            "uncertaintyV": _number(row.uncertainty_v),
            "residualVoltageV": _number(row.calibrated_voltage_v - row.raw_voltage_v),
            "quality": str(row.quality),
        }
        for row in selected.itertuples(index=False)
    ]

    spectrogram = compute_spectrogram(frame, artifact.sample_rate_hz)
    time_indices = _even_indices(
        spectrogram.sizes["time_seconds"],
        max_spectrogram_time_bins,
    )
    frequency_indices = _even_indices(
        spectrogram.sizes["frequency_hz"],
        max_spectrogram_frequency_bins,
    )
    reduced_spectrogram = spectrogram.isel(
        time_seconds=time_indices,
        frequency_hz=frequency_indices,
    )

    time_values = np.asarray(
        reduced_spectrogram.coords["time_seconds"].to_numpy(),
        dtype=float,
    )
    frequency_values = np.asarray(
        reduced_spectrogram.coords["frequency_hz"].to_numpy(),
        dtype=float,
    )
    power_values = reduced_spectrogram.to_numpy().astype(float)

    power_min = float(np.nanmin(power_values))
    power_max = float(np.nanmax(power_values))

    return {
        "schemaVersion": ACTIVITY_SCHEMA_VERSION,
        "artifactId": artifact.artifact_id,
        "visualizationId": visualization_id,
        "environment": artifact.environment,
        "positionId": artifact.position_id,
        "institutionId": artifact.institution_id,
        "title": artifact.title,
        "stateHeadHash": artifact.state_head_hash,
        "artifactDefinitionHash": artifact.artifact_definition_hash(),
        "inputDatasetHash": artifact.data_sha256,
        "generatedAt": artifact.completed_at.isoformat().replace("+00:00", "Z"),
        "referenceTimeUtc": artifact.reference_time_utc.isoformat().replace("+00:00", "Z"),
        "sampleRateHz": _number(artifact.sample_rate_hz),
        "sourceClockId": artifact.source_clock_id,
        "timeZones": {
            "facility": artifact.facility_timezone,
            "source": artifact.source_timezone,
            "named": {
                name: zone
                for name, zone in TIME_BASIS_TO_ZONE.items()
                if zone is not None
            },
        },
        "waveform": {
            "fullSampleCount": len(frame),
            "publishedSampleCount": len(samples),
            "startSeconds": _number(frame["offset_seconds"].iloc[0]),
            "endSeconds": _number(frame["offset_seconds"].iloc[-1]),
            "samples": samples,
            "qualityIntervals": _quality_intervals(frame),
        },
        "spectrogram": {
            "timeSeconds": [_number(value) for value in time_values],
            "frequencyHz": [_number(value) for value in frequency_values],
            "powerDb": [
                [_number(value) for value in row]
                for row in power_values
            ],
            "minimumDb": _number(power_min),
            "maximumDb": _number(power_max),
            "units": "dB/Hz",
        },
        "events": [
            {
                "eventId": event.event_id,
                "label": event.label,
                "timeSeconds": _number(event.offset_seconds),
                "source": event.source,
                "uncertaintySeconds": _number(event.uncertainty_seconds),
            }
            for event in artifact.events
        ],
        "derivedValues": [
            {
                "valueId": value.value_id,
                "label": value.label,
                "value": _number(value.value),
                "unit": value.unit,
                "uncertainty": _number(value.uncertainty),
            }
            for value in artifact.derived_values
        ],
        "publicSummary": artifact.public_summary,
        "limitations": list(artifact.limitations),
    }


def build_activity_visualization_spec(
    artifact: AnalysisArtifact,
    visualization_id: str,
) -> dict[str, Any]:
    return {
        "schemaVersion": ACTIVITY_SCHEMA_VERSION,
        "visualizationId": visualization_id,
        "artifactId": artifact.artifact_id,
        "environment": artifact.environment,
        "title": artifact.title,
        "renderer": "missing-interior-native-svg-canvas",
        "datasetFilename": ACTIVITY_DATA_FILENAME,
        "fallbackFilename": "scientific-plate.png",
        "manifestFilename": ACTIVITY_MANIFEST_FILENAME,
        "views": [
            {
                "id": "waveform",
                "type": "linked-timeseries",
                "x": "timeSeconds",
                "series": [
                    {
                        "id": "rawVoltageV",
                        "label": "Raw voltage",
                        "unit": "V",
                        "defaultVisible": True,
                    },
                    {
                        "id": "calibratedVoltageV",
                        "label": "Calibrated voltage",
                        "unit": "V",
                        "defaultVisible": True,
                    },
                    {
                        "id": "residualVoltageV",
                        "label": "Calibration residual",
                        "unit": "V",
                        "defaultVisible": False,
                    },
                ],
                "uncertaintyField": "uncertaintyV",
                "eventField": "events",
            },
            {
                "id": "spectrogram",
                "type": "linked-spectrogram",
                "x": "timeSeconds",
                "y": "frequencyHz",
                "value": "powerDb",
                "units": "dB/Hz",
            },
        ],
        "interaction": {
            "linkedTimeWindow": True,
            "hoverReadout": True,
            "dragToSelect": True,
            "resetControl": True,
            "timeBases": [
                "Zulu",
                "Facility local",
                "Source original",
                "Pacific",
                "Mountain",
                "Central",
                "Eastern",
            ],
        },
        "provenance": {
            "stateHeadHash": artifact.state_head_hash,
            "artifactDefinitionHash": artifact.artifact_definition_hash(),
            "inputDatasetHash": artifact.data_sha256,
            "analysisMethod": artifact.method.method_id,
            "analysisMethodVersion": artifact.method.version,
        },
        "limitations": list(artifact.limitations),
    }


def _envelope_sample_indices(values: np.ndarray, limit: int) -> list[int]:
    count = len(values)
    if count <= limit:
        return list(range(count))

    interior_limit = limit - 2
    bucket_count = max(1, interior_limit // 2)
    boundaries = np.linspace(1, count - 1, bucket_count + 1, dtype=int)
    indices: set[int] = {0, count - 1}

    for start, end in pairwise(boundaries):
        if end <= start:
            continue
        bucket = values[start:end]
        if bucket.size == 0:
            continue
        indices.add(start + int(np.nanargmin(bucket)))
        indices.add(start + int(np.nanargmax(bucket)))

    ordered = sorted(indices)
    if len(ordered) <= limit:
        return ordered
    return [ordered[index] for index in _even_indices(len(ordered), limit)]


def _even_indices(count: int, limit: int) -> list[int]:
    if count <= 0:
        return []
    if count <= limit:
        return list(range(count))
    return sorted(set(np.linspace(0, count - 1, limit, dtype=int).tolist()))


def _quality_intervals(frame: pd.DataFrame) -> list[dict[str, Any]]:
    intervals: list[dict[str, Any]] = []
    start_index = 0
    qualities = frame["quality"].astype(str).tolist()
    times = frame["offset_seconds"].to_numpy(dtype=float)

    for index in range(1, len(qualities) + 1):
        is_boundary = index == len(qualities) or qualities[index] != qualities[start_index]
        if not is_boundary:
            continue
        intervals.append(
            {
                "startSeconds": _number(times[start_index]),
                "endSeconds": _number(times[index - 1]),
                "quality": qualities[start_index],
            }
        )
        start_index = index
    return intervals


def _number(value: Any) -> float:
    numeric = float(value)
    if not np.isfinite(numeric):
        raise ValueError("Activity projections cannot contain non-finite numbers")
    rounded = round(numeric, 8)
    return 0.0 if rounded == -0.0 else rounded


def iter_referenced_filenames(spec: dict[str, Any]) -> Iterable[str]:
    for key in ("datasetFilename", "fallbackFilename", "manifestFilename"):
        value = spec.get(key)
        if isinstance(value, str) and value:
            yield value
