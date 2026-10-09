from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import xarray as xr
from scipy import signal

from .models import AnalysisArtifact

TIME_BASIS_TO_ZONE = {
    "Zulu": "UTC",
    "Facility local": None,
    "Source original": None,
    "Pacific": "America/Los_Angeles",
    "Mountain": "America/Denver",
    "Central": "America/Chicago",
    "Eastern": "America/New_York",
}


@dataclass(frozen=True)
class WindowStatistics:
    start_seconds: float
    end_seconds: float
    sample_count: int
    minimum_voltage: float
    maximum_voltage: float
    rms_voltage: float
    excluded_count: int


@dataclass(frozen=True)
class PhaseSpaceStatistics:
    sample_count: int
    valid_count: int
    flagged_count: int
    rms_slew_v_per_s: float
    peak_absolute_slew_v_per_s: float
    percentile_99_absolute_slew_v_per_s: float


def subset_frame(frame: pd.DataFrame, x_range: tuple[float, float] | None) -> pd.DataFrame:
    if x_range is None or any(value is None for value in x_range):
        return frame
    start, end = sorted(x_range)
    selected = frame.loc[
        (frame["offset_seconds"] >= start) & (frame["offset_seconds"] <= end)
    ]
    return frame if len(selected) < 16 else selected


def window_statistics(
    frame: pd.DataFrame,
    x_range: tuple[float, float] | None = None,
) -> WindowStatistics:
    selected = subset_frame(frame, x_range)
    values = selected["calibrated_voltage_v"].to_numpy(dtype=float)
    return WindowStatistics(
        start_seconds=float(selected["offset_seconds"].iloc[0]),
        end_seconds=float(selected["offset_seconds"].iloc[-1]),
        sample_count=len(selected),
        minimum_voltage=float(np.min(values)),
        maximum_voltage=float(np.max(values)),
        rms_voltage=float(np.sqrt(np.mean(values**2))),
        excluded_count=int((selected["quality"] != "valid").sum()),
    )


def compute_phase_space(frame: pd.DataFrame, sample_rate_hz: float) -> pd.DataFrame:
    """Return calibrated voltage and its finite-difference slew rate.

    The derivative uses the artifact's declared uniform sample cadence. Central
    differences are used when at least three samples are available, with
    one-sided differences at the acquisition boundaries.
    """
    if sample_rate_hz <= 0:
        raise ValueError("sample_rate_hz must be positive")
    if len(frame) < 2:
        raise ValueError("phase-space analysis requires at least two samples")

    voltage = frame["calibrated_voltage_v"].to_numpy(dtype=float)
    edge_order = 2 if len(voltage) >= 3 else 1
    slew = np.gradient(voltage, 1.0 / sample_rate_hz, edge_order=edge_order)
    return pd.DataFrame(
        {
            "sample_index": frame["sample_index"].to_numpy(),
            "offset_seconds": frame["offset_seconds"].to_numpy(dtype=float),
            "calibrated_voltage_v": voltage,
            "slew_rate_v_per_s": slew,
            "quality": frame["quality"].astype(str).to_numpy(),
        }
    )


def phase_space_statistics(phase_frame: pd.DataFrame) -> PhaseSpaceStatistics:
    slew = phase_frame["slew_rate_v_per_s"].to_numpy(dtype=float)
    absolute_slew = np.abs(slew)
    valid_count = int((phase_frame["quality"] == "valid").sum())
    return PhaseSpaceStatistics(
        sample_count=len(phase_frame),
        valid_count=valid_count,
        flagged_count=len(phase_frame) - valid_count,
        rms_slew_v_per_s=float(np.sqrt(np.mean(slew**2))),
        peak_absolute_slew_v_per_s=float(np.max(absolute_slew)),
        percentile_99_absolute_slew_v_per_s=float(np.percentile(absolute_slew, 99)),
    )


def compute_spectrogram(
    frame: pd.DataFrame,
    sample_rate_hz: float,
    x_range: tuple[float, float] | None = None,
) -> xr.DataArray:
    selected = subset_frame(frame, x_range)
    values = selected["calibrated_voltage_v"].to_numpy(dtype=float)
    nperseg = min(256, 2 ** int(np.floor(np.log2(len(values)))))
    nperseg = max(8, nperseg)
    noverlap = min(nperseg - 1, int(nperseg * 0.75))
    frequencies, times, power = signal.spectrogram(
        values,
        fs=sample_rate_hz,
        window="hann",
        nperseg=nperseg,
        noverlap=noverlap,
        detrend="linear",
        scaling="density",
        mode="psd",
    )
    power_db = 10.0 * np.log10(np.maximum(power, np.finfo(float).tiny))
    absolute_times = times + float(selected["offset_seconds"].iloc[0])
    return xr.DataArray(
        power_db,
        dims=("frequency_hz", "time_seconds"),
        coords={"frequency_hz": frequencies, "time_seconds": absolute_times},
        name="power_db",
        attrs={
            "long_name": "Power spectral density",
            "units": "dB/Hz",
            "sample_rate_hz": sample_rate_hz,
            "window": "hann",
            "nperseg": nperseg,
            "noverlap": noverlap,
        },
    )


def format_timestamp(
    artifact: AnalysisArtifact,
    offset_seconds: float,
    time_basis: str,
) -> str:
    zone_name = TIME_BASIS_TO_ZONE.get(time_basis)
    if time_basis == "Facility local":
        zone_name = artifact.facility_timezone
    elif time_basis == "Source original":
        zone_name = artifact.source_timezone
    if zone_name is None:
        raise ValueError(f"Unknown time basis: {time_basis}")
    timestamp = artifact.reference_time_utc + timedelta(seconds=offset_seconds)
    localized = timestamp.astimezone(ZoneInfo(zone_name))
    zone_suffix = "Z" if zone_name == "UTC" else localized.tzname() or zone_name
    return localized.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3] + f" {zone_suffix}"


def nearest_sample(frame: pd.DataFrame, offset_seconds: float) -> pd.Series:
    index = (frame["offset_seconds"] - offset_seconds).abs().idxmin()
    return frame.loc[index]
