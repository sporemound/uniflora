from __future__ import annotations

from collections.abc import Iterable

import colorcet as cc
import holoviews as hv
import numpy as np
import pandas as pd
import xarray as xr
from holoviews import opts

from .models import AnalysisArtifact

BACKGROUND = "#111518"
PANEL = "#171d21"
TEXT = "#e9e3d7"
MUTED = "#98a2a8"
RAW = "#8b9499"
CALIBRATED = "#72bcc8"
UNCERTAINTY = "#315c64"
EVENT = "#d1a45f"
RESIDUAL = "#a98dc5"
EXCLUDED = "#b7685e"
PHASE_DENSITY_RASTERIZE_THRESHOLD = 50_000


def initialize_holoviews() -> None:
    hv.extension("bokeh", "matplotlib")


def build_facility_map_view(facilities: pd.DataFrame):
    """Render WGS84 facility records over live OpenStreetMap tiles."""
    import cartopy.crs as ccrs
    import geoviews as gv

    required = {"longitude", "latitude", "name", "sector", "status"}
    missing = required.difference(facilities.columns)
    if missing:
        raise ValueError(f"facility map is missing columns: {', '.join(sorted(missing))}")

    points = gv.Points(
        facilities,
        kdims=["longitude", "latitude"],
        vdims=["name", "sector", "status"],
        crs=ccrs.PlateCarree(),
        label="Facility sites",
    ).opts(
        color="status",
        cmap={"focus": EVENT, "available": CALIBRATED, "locked": MUTED},
        size=11,
        line_color=BACKGROUND,
        line_width=2,
        alpha=0.92,
        tools=["hover"],
        responsive=True,
        height=610,
        xlim=(-128, -66),
        ylim=(24, 51),
        show_legend=True,
        legend_position="bottom_left",
    )
    labels = gv.Labels(
        facilities,
        kdims=["longitude", "latitude"],
        vdims=["name"],
        crs=ccrs.PlateCarree(),
    ).opts(
        text_color=TEXT,
        text_font_size="8pt",
        xoffset=10,
        yoffset=8,
    )
    return (gv.tile_sources.CartoDark * points * labels).opts(
        bgcolor=BACKGROUND,
        title="Persistent institutional network",
        toolbar="above",
    )


def build_waveform(
    artifact: AnalysisArtifact,
    frame: pd.DataFrame,
    *,
    show_raw: bool,
    show_uncertainty: bool,
) -> tuple[hv.Overlay, hv.Curve]:
    del artifact
    x = frame["offset_seconds"].to_numpy(dtype=float)
    calibrated_values = frame["calibrated_voltage_v"].to_numpy(dtype=float)
    calibrated = hv.Curve(
        (x, calibrated_values),
        kdims=["Seconds from receipt"],
        vdims=["Calibrated voltage (V)"],
        label="Calibrated",
    )
    calibrated = calibrated.opts(
        opts.Curve(
            color=CALIBRATED,
            line_width=2,
            tools=["hover", "xpan", "xwheel_zoom", "box_zoom", "reset"],
            active_tools=["xwheel_zoom"],
            responsive=True,
            height=310,
            bgcolor=BACKGROUND,
            show_grid=True,
            toolbar="above",
        )
    )

    layers: list[hv.Element] = []
    if show_uncertainty:
        uncertainty = frame["uncertainty_v"].to_numpy(dtype=float)
        spread = hv.Area(
            (x, calibrated_values - uncertainty, calibrated_values + uncertainty),
            kdims=["Seconds from receipt"],
            vdims=["Lower", "Upper"],
            label="Measurement uncertainty",
        ).opts(color=UNCERTAINTY, alpha=0.35, line_alpha=0)
        layers.append(spread)
    if show_raw:
        raw = hv.Curve(
            (x, frame["raw_voltage_v"].to_numpy(dtype=float)),
            kdims=["Seconds from receipt"],
            vdims=["Raw voltage (V)"],
            label="Raw",
        ).opts(color=RAW, line_width=1, line_dash="dashed", alpha=0.75)
        layers.append(raw)
    layers.append(calibrated)

    invalid = frame.loc[frame["quality"] != "valid"]
    if not invalid.empty:
        excluded = hv.Scatter(
            (invalid["offset_seconds"], invalid["calibrated_voltage_v"]),
            kdims=["Seconds from receipt"],
            vdims=["Excluded sample voltage (V)"],
            label="Excluded or degraded",
        ).opts(color=EXCLUDED, marker="x", size=7, line_width=2)
        layers.append(excluded)

    overlay = hv.Overlay(layers).opts(
        opts.Overlay(
            legend_position="top_left",
            show_legend=True,
            bgcolor=BACKGROUND,
        )
    )
    return overlay, calibrated


def add_event_markers(plot: hv.Overlay, events: Iterable) -> hv.Overlay:
    result: hv.Overlay = plot
    for event in events:
        line = hv.VLine(event.offset_seconds).opts(
            color=EVENT,
            line_dash="dotted",
            line_width=1.5,
            alpha=0.9,
        )
        result *= line
    return result


def build_spectrogram_view(data: xr.DataArray) -> hv.Image:
    image = hv.Image(
        data,
        kdims=["time_seconds", "frequency_hz"],
        vdims=["power_db"],
    )
    return image.opts(
        opts.Image(
            cmap=cc.CET_L17,
            colorbar=True,
            clabel="Power (dB/Hz)",
            xlabel="Seconds from receipt",
            ylabel="Frequency (Hz)",
            responsive=True,
            height=310,
            tools=["hover", "xpan", "xwheel_zoom", "box_zoom", "reset"],
            active_tools=["xwheel_zoom"],
            bgcolor=BACKGROUND,
        )
    )


def build_residual_view(frame: pd.DataFrame) -> hv.Overlay:
    residual = frame["calibrated_voltage_v"] - frame["raw_voltage_v"]
    curve = hv.Curve(
        (frame["offset_seconds"], residual),
        kdims=["Seconds from receipt"],
        vdims=["Calibration correction (V)"],
        label="Applied correction",
    ).opts(
        color=RESIDUAL,
        line_width=2,
        responsive=True,
        height=270,
        tools=["hover", "xwheel_zoom", "reset"],
        active_tools=["xwheel_zoom"],
        bgcolor=BACKGROUND,
        show_grid=True,
    )
    zero = hv.HLine(0).opts(color=MUTED, line_dash="dotted", alpha=0.7)
    return (curve * zero).opts(legend_position="top_left")


def phase_density_uses_rasterization(
    phase_frame: pd.DataFrame,
    *,
    threshold: int = PHASE_DENSITY_RASTERIZE_THRESHOLD,
) -> bool:
    """Use Datashader only when valid points exceed the vector-hover budget."""
    if threshold < 1:
        raise ValueError("threshold must be positive")
    return int((phase_frame["quality"] == "valid").sum()) > threshold


def build_phase_density_view(
    phase_frame: pd.DataFrame,
    *,
    rasterize_threshold: int = PHASE_DENSITY_RASTERIZE_THRESHOLD,
):
    """Build a voltage/slew-rate phase portrait from retained artifact samples."""
    import hvplot.pandas  # noqa: F401  # registers the pandas .hvplot accessor

    valid = phase_frame.loc[phase_frame["quality"] == "valid"]
    flagged = phase_frame.loc[phase_frame["quality"] != "valid"]
    rasterized = phase_density_uses_rasterization(
        phase_frame,
        threshold=rasterize_threshold,
    )

    common = {
        "x": "calibrated_voltage_v",
        "y": "slew_rate_v_per_s",
        "xlabel": "Calibrated voltage (V)",
        "ylabel": "Slew rate (V/s)",
        "title": "Calibrated voltage / slew-rate phase portrait",
        "responsive": True,
        "height": 520,
        "bgcolor": BACKGROUND,
        "show_grid": True,
    }
    if rasterized:
        import datashader as ds

        phase = valid.hvplot.points(
            **common,
            rasterize=True,
            aggregator=ds.count(),
            cmap=cc.CET_L17,
            cnorm="eq_hist",
            colorbar=True,
            clabel="Valid-sample occupancy",
            tools=["hover", "box_zoom", "wheel_zoom", "reset"],
        )
    else:
        phase = valid.hvplot.points(
            **common,
            color="offset_seconds",
            cmap=cc.CET_L17,
            colorbar=True,
            clabel="Seconds from receipt",
            alpha=0.58,
            size=5,
            hover_cols=["sample_index", "offset_seconds", "quality"],
            tools=["hover", "box_zoom", "wheel_zoom", "reset"],
        )

    if not flagged.empty:
        flagged_points = hv.Points(
            flagged,
            kdims=["calibrated_voltage_v", "slew_rate_v_per_s"],
            vdims=["sample_index", "offset_seconds", "quality"],
            label="Degraded or excluded",
        ).opts(
            color=EXCLUDED,
            marker="x",
            size=8,
            line_width=2,
            tools=["hover"],
        )
        phase *= flagged_points

    zero_slew = hv.HLine(0).opts(color=MUTED, line_dash="dotted", alpha=0.6)
    zero_voltage = hv.VLine(0).opts(color=MUTED, line_dash="dotted", alpha=0.6)
    return (phase * zero_slew * zero_voltage).opts(
        legend_position="top_left",
        show_legend=not flagged.empty,
    )


def build_timing_view(artifact: AnalysisArtifact) -> hv.Overlay:
    sorted_events = sorted(artifact.events, key=lambda item: item.offset_seconds)
    x = np.asarray([event.offset_seconds for event in sorted_events], dtype=float)
    y = np.arange(len(sorted_events), 0, -1, dtype=float)
    labels = [event.label for event in sorted_events]
    sources = [event.source for event in sorted_events]
    points = hv.Points(
        (x, y, labels, sources),
        kdims=["Seconds from receipt", "Lane"],
        vdims=["Event", "Source"],
    ).opts(
        color=EVENT,
        size=12,
        marker="diamond",
        tools=["hover"],
        responsive=True,
        height=260,
        xaxis="bottom",
        yaxis=None,
        bgcolor=BACKGROUND,
        show_grid=True,
    )
    stems = hv.Segments((x, np.zeros_like(y), x, y)).opts(color=MUTED, line_dash="dotted")
    text = hv.Labels(
        (x, y + 0.18, labels),
        kdims=["Seconds from receipt", "Lane"],
        vdims="Event",
    ).opts(
        text_color=TEXT,
        text_font_size="10pt",
        text_align="center",
    )
    receipt = hv.VLine(0).opts(color=CALIBRATED, line_width=2, alpha=0.8)
    return (stems * points * text * receipt).opts(show_legend=False)


def build_static_publication_layout(
    artifact: AnalysisArtifact,
    frame: pd.DataFrame,
    spectrogram: xr.DataArray,
    phase_frame: pd.DataFrame,
) -> hv.Layout:
    x = frame["offset_seconds"].to_numpy(dtype=float)
    raw = hv.Curve(
        (x, frame["raw_voltage_v"].to_numpy(dtype=float)),
        "Seconds from receipt",
        "Voltage (V)",
        label="Raw",
    ).opts(
        opts.Curve(
            backend="matplotlib",
            color=RAW,
            linewidth=0.8,
            linestyle="--",
            alpha=0.75,
            show_grid=True,
            show_legend=True,
        )
    )
    calibrated = hv.Curve(
        (x, frame["calibrated_voltage_v"].to_numpy(dtype=float)),
        "Seconds from receipt",
        "Voltage (V)",
        label="Calibrated",
    ).opts(
        opts.Curve(
            backend="matplotlib",
            color=CALIBRATED,
            linewidth=1.5,
            show_grid=True,
            show_legend=True,
        )
    )
    uncertainty = frame["uncertainty_v"].to_numpy(dtype=float)
    spread = hv.Area(
        (
            x,
            frame["calibrated_voltage_v"].to_numpy(dtype=float) - uncertainty,
            frame["calibrated_voltage_v"].to_numpy(dtype=float) + uncertainty,
        ),
        kdims=["Seconds from receipt"],
        vdims=["Lower", "Upper"],
    ).opts(
        opts.Area(
            backend="matplotlib",
            color=UNCERTAINTY,
            alpha=0.28,
            linewidth=0,
        )
    )
    waveform: hv.Overlay = raw * spread * calibrated
    for event in artifact.events:
        waveform *= hv.VLine(event.offset_seconds).opts(
            opts.VLine(
                backend="matplotlib",
                color=EVENT,
                linestyle=":",
                linewidth=1,
            )
        )
    waveform = waveform.opts(
        opts.Overlay(
            backend="matplotlib",
            title="A. Retained line-voltage record",
            show_legend=True,
            legend_position="top_left",
            bgcolor=BACKGROUND,
            aspect=2.5,
        )
    )

    image = hv.Image(
        spectrogram,
        kdims=["time_seconds", "frequency_hz"],
        vdims=["power_db"],
    ).opts(
        opts.Image(
            backend="matplotlib",
            title="B. Time-frequency representation",
            cmap=cc.cm.CET_L17,
            colorbar=True,
            xlabel="Seconds from receipt",
            ylabel="Frequency (Hz)",
            bgcolor=BACKGROUND,
            aspect=2.5,
        )
    )

    correction = frame["calibrated_voltage_v"] - frame["raw_voltage_v"]
    residual = hv.Curve(
        (x, correction),
        "Seconds from receipt",
        "Correction (V)",
    ).opts(
        opts.Curve(
            backend="matplotlib",
            title="C. Applied calibration correction",
            color=RESIDUAL,
            linewidth=1.4,
            show_grid=True,
            bgcolor=BACKGROUND,
            aspect=2.5,
        )
    )

    valid_phase = phase_frame.loc[phase_frame["quality"] == "valid"]
    phase_map = hv.Points(
        valid_phase,
        kdims=["calibrated_voltage_v", "slew_rate_v_per_s"],
        vdims=["offset_seconds"],
    ).opts(
        opts.Points(
            backend="matplotlib",
            title="D. Calibrated voltage / slew-rate phase map",
            color="offset_seconds",
            cmap=cc.cm.CET_L17,
            colorbar=True,
            xlabel="Calibrated voltage (V)",
            ylabel="Slew rate (V/s)",
            alpha=0.58,
            show_grid=True,
            bgcolor=BACKGROUND,
            aspect=2.5,
        )
    )

    return (waveform + image + residual + phase_map).cols(1).opts(
        opts.Layout(
            backend="matplotlib",
            sublabel_format="",
            tight=True,
            tight_padding=3,
            vspace=0.55,
        )
    )
