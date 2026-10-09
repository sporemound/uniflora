from __future__ import annotations

from pathlib import Path

import pytest

from missing_interior_dashboard.analysis import (
    compute_phase_space,
    compute_spectrogram,
    format_timestamp,
    nearest_sample,
    phase_space_statistics,
    window_statistics,
)
from missing_interior_dashboard.io import load_signal_frame
from missing_interior_dashboard.models import load_artifact

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_PATH = ROOT / "examples" / "sr03-artifact.json"


@pytest.fixture(scope="module")
def loaded():
    artifact = load_artifact(ARTIFACT_PATH)
    return artifact, load_signal_frame(ARTIFACT_PATH, artifact)


def test_spectrogram_has_units_and_ordered_coordinates(loaded) -> None:
    artifact, frame = loaded
    result = compute_spectrogram(frame, artifact.sample_rate_hz, (-3.5, 0.5))

    assert result.dims == ("frequency_hz", "time_seconds")
    assert result.attrs["units"] == "dB/Hz"
    assert result.sizes["frequency_hz"] > 10
    assert result.sizes["time_seconds"] > 2
    assert float(result.time_seconds.min()) >= -3.5
    assert float(result.time_seconds.max()) <= 0.5


def test_time_basis_conversion_preserves_instant(loaded) -> None:
    artifact, _frame = loaded

    assert format_timestamp(artifact, 0, "Zulu").endswith("Z")
    assert "PDT" in format_timestamp(artifact, 0, "Pacific")
    assert "EDT" in format_timestamp(artifact, 0, "Eastern")


def test_range_statistics_and_nearest_sample(loaded) -> None:
    _artifact, frame = loaded
    stats = window_statistics(frame, (-0.1, 0.1))
    sample = nearest_sample(frame, 0.0)

    assert 40 <= stats.sample_count <= 60
    assert stats.rms_voltage > 0
    assert float(sample["offset_seconds"]) == pytest.approx(0.0)


def test_phase_space_uses_declared_sample_cadence(loaded) -> None:
    artifact, frame = loaded
    phase = compute_phase_space(frame, artifact.sample_rate_hz)
    expected = (
        frame["calibrated_voltage_v"].iloc[2] - frame["calibrated_voltage_v"].iloc[0]
    ) * artifact.sample_rate_hz / 2

    assert list(phase.columns) == [
        "sample_index",
        "offset_seconds",
        "calibrated_voltage_v",
        "slew_rate_v_per_s",
        "quality",
    ]
    assert len(phase) == len(frame)
    assert phase["slew_rate_v_per_s"].iloc[1] == pytest.approx(expected)


def test_phase_space_statistics_preserve_quality_flags(loaded) -> None:
    artifact, frame = loaded
    phase = compute_phase_space(frame, artifact.sample_rate_hz)
    stats = phase_space_statistics(phase)

    assert stats.sample_count == 4096
    assert stats.valid_count == int((frame["quality"] == "valid").sum())
    assert stats.flagged_count == int((frame["quality"] != "valid").sum())
    assert stats.peak_absolute_slew_v_per_s >= stats.percentile_99_absolute_slew_v_per_s
    assert stats.rms_slew_v_per_s > 0
