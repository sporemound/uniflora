from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from importlib import import_module
from importlib.metadata import version as distribution_version
from pathlib import Path
from typing import Any

import holoviews as hv
import matplotlib
import pandas as pd
import resvg_py

from .activity_projection import (
    ACTIVITY_DATA_FILENAME,
    ACTIVITY_MANIFEST_FILENAME,
    ACTIVITY_SCHEMA_VERSION,
    ACTIVITY_VISUALIZATION_FILENAME,
    DEFAULT_MAX_SPECTROGRAM_FREQUENCY_BINS,
    DEFAULT_MAX_SPECTROGRAM_TIME_BINS,
    DEFAULT_MAX_WAVEFORM_POINTS,
    build_activity_dataset,
    build_activity_visualization_spec,
    canonical_json,
)
from .analysis import compute_phase_space, compute_spectrogram
from .models import AnalysisArtifact, file_sha256
from .views import build_static_publication_layout, initialize_holoviews

# Publication export is a headless operation. Select the non-interactive backend
# before importing pyplot so a workstation export never depends on Tcl/Tk.
matplotlib.use("Agg", force=True)
plt = import_module("matplotlib.pyplot")

SVG_NAMESPACE = "http://www.w3.org/2000/svg"
PNG_LONG_EDGE = 1800
SOFTWARE_DISTRIBUTIONS = {
    "numpy": "numpy",
    "pandas": "pandas",
    "scipy": "scipy",
    "xarray": "xarray",
    "colorcet": "colorcet",
    "holoviews": "holoviews",
    "matplotlib": "matplotlib",
    "resvg_py": "resvg_py",
}
ET.register_namespace("", SVG_NAMESPACE)


@dataclass(frozen=True)
class PublicationBundle:
    directory: Path
    svg_path: Path
    png_path: Path
    visualization_path: Path
    activity_data_path: Path
    activity_visualization_path: Path
    manifest_path: Path
    activity_publication_path: Path
    visualization_id: str


def build_visualization_spec(artifact: AnalysisArtifact) -> dict[str, Any]:
    return {
        "schemaVersion": "1.0.0",
        "artifactId": artifact.artifact_id,
        "environment": artifact.environment,
        "positionId": artifact.position_id,
        "institutionId": artifact.institution_id,
        "title": artifact.title,
        "renderer": "holoviews-matplotlib-resvg",
        "panels": [
            {
                "id": "waveform",
                "type": "timeseries",
                "series": ["raw_voltage_v", "calibrated_voltage_v", "uncertainty_v"],
                "x": "offset_seconds",
            },
            {
                "id": "spectrogram",
                "type": "spectrogram",
                "quantity": "calibrated_voltage_v",
                "colorMap": "CET_L17",
            },
            {
                "id": "calibration-residual",
                "type": "residual",
                "expression": "calibrated_voltage_v - raw_voltage_v",
            },
            {
                "id": "phase-space",
                "type": "phase-map",
                "x": "calibrated_voltage_v",
                "y": "slew_rate_v_per_s",
                "color": "offset_seconds",
                "qualityFilter": "valid",
            },
        ],
        "timeBasis": "UTC with seconds relative to verified receipt",
        "limitations": list(artifact.limitations),
        "artifactDefinitionHash": artifact.artifact_definition_hash(),
    }


def visualization_id_for(spec: dict[str, Any]) -> str:
    canonical = json.dumps(spec, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return "viz_" + hashlib.sha256(canonical.encode()).hexdigest()[:24]


def export_publication_bundle(
    artifact: AnalysisArtifact,
    frame: pd.DataFrame,
    output_root: Path,
) -> PublicationBundle:
    initialize_holoviews()
    spec = build_visualization_spec(artifact)
    visualization_id = visualization_id_for(spec)
    directory = output_root / artifact.environment / artifact.artifact_id / visualization_id
    directory.mkdir(parents=True, exist_ok=True)

    svg_path = directory / "scientific-plate.svg"
    png_path = directory / "scientific-plate.png"
    visualization_path = directory / "visualization.json"
    activity_data_path = directory / ACTIVITY_DATA_FILENAME
    activity_visualization_path = directory / ACTIVITY_VISUALIZATION_FILENAME
    manifest_path = directory / ACTIVITY_MANIFEST_FILENAME
    activity_publication_path = directory / "activity-publication.json"

    visualization_path.write_text(
        json.dumps(spec, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    activity_data = build_activity_dataset(artifact, frame, visualization_id)
    activity_visualization = build_activity_visualization_spec(
        artifact,
        visualization_id,
    )
    activity_data_path.write_text(canonical_json(activity_data), encoding="utf-8")
    activity_visualization_path.write_text(
        canonical_json(activity_visualization),
        encoding="utf-8",
    )

    spectrogram = compute_spectrogram(frame, artifact.sample_rate_hz)
    phase_frame = compute_phase_space(frame, artifact.sample_rate_hz)
    layout = build_static_publication_layout(artifact, frame, spectrogram, phase_frame)

    matplotlib.rcParams["svg.hashsalt"] = visualization_id
    matplotlib.rcParams["svg.fonttype"] = "none"
    figure = hv.render(layout, backend="matplotlib")
    figure.set_size_inches(14, 18)
    figure.patch.set_facecolor("#111518")
    figure.suptitle(
        f"{artifact.title}\n{artifact.institution_id} · {artifact.position_id}",
        color="#e9e3d7",
        fontsize=18,
        linespacing=1.25,
        y=0.985,
    )
    figure.subplots_adjust(
        bottom=0.07,
        hspace=0.58,
        left=0.09,
        right=0.91,
        top=0.85,
    )
    for axis in figure.axes:
        axis.set_facecolor("#111518")
        axis.tick_params(colors="#d9d3c8", labelsize=8)
        axis.xaxis.label.set_color("#e9e3d7")
        axis.yaxis.label.set_color("#e9e3d7")
        axis.title.set_color("#e9e3d7")
        for gridline in [*axis.get_xgridlines(), *axis.get_ygridlines()]:
            gridline.set_alpha(0.35)
            gridline.set_color("#748087")
            gridline.set_linewidth(0.6)
        legend = axis.get_legend()
        if legend is not None:
            legend.get_frame().set_alpha(0.92)
            legend.get_frame().set_edgecolor("#566168")
            legend.get_frame().set_facecolor("#181e22")
            for legend_text in legend.get_texts():
                legend_text.set_color("#e9e3d7")
        for spine in axis.spines.values():
            spine.set_color("#566168")

    try:
        _atomic_save_figure(
            figure,
            svg_path,
            metadata={
                "Date": artifact.completed_at.isoformat(),
                "Creator": "The Missing Interior Phase 3 dashboard",
                "Title": artifact.title,
                "Description": artifact.public_summary,
            },
        )
    finally:
        plt.close(figure)

    png_width, png_height = _add_accessible_svg_metadata(svg_path, artifact)
    svg_text = svg_path.read_text(encoding="utf-8")
    png_bytes = resvg_py.svg_to_bytes(
        svg_string=svg_text,
        width=png_width,
        height=png_height,
    )
    _atomic_write_bytes(png_path, png_bytes)

    software_versions = _software_versions()
    manifest = {
        "schemaVersion": "1.1.0",
        "artifactId": artifact.artifact_id,
        "visualizationId": visualization_id,
        "environment": artifact.environment,
        "positionId": artifact.position_id,
        "institutionId": artifact.institution_id,
        "stateHeadHash": artifact.state_head_hash,
        "inputDatasetHash": artifact.data_sha256,
        "artifactDefinitionHash": artifact.artifact_definition_hash(),
        "analysisMethod": artifact.method.method_id,
        "analysisMethodVersion": artifact.method.version,
        "renderer": "holoviews-matplotlib-resvg",
        "interactiveRenderer": "missing-interior-native-svg-canvas",
        "rendererVersions": {
            name: software_versions[name] for name in ("holoviews", "matplotlib", "resvg_py")
        },
        "softwareVersions": software_versions,
        "projectionProvenance": _projection_provenance(
            activity_data,
            spectrogram,
            png_width=png_width,
            png_height=png_height,
        ),
        "generatedAt": artifact.completed_at.isoformat().replace("+00:00", "Z"),
        "files": {
            "scientific-plate.svg": file_sha256(svg_path),
            "scientific-plate.png": file_sha256(png_path),
            "visualization.json": file_sha256(visualization_path),
            ACTIVITY_DATA_FILENAME: file_sha256(activity_data_path),
            ACTIVITY_VISUALIZATION_FILENAME: file_sha256(activity_visualization_path),
        },
        "limitations": list(artifact.limitations),
    }
    manifest_path.write_text(canonical_json(manifest), encoding="utf-8")

    publication = {
        "environment": artifact.environment,
        "publicationId": f"publication-phase3b-{visualization_id}",
        "artifactId": artifact.artifact_id,
        "stateHeadHash": artifact.state_head_hash,
        "evidenceStateHeadHash": artifact.state_head_hash,
        "title": artifact.title,
        "publicSummary": artifact.public_summary,
        "limitation": artifact.limitations[0],
        "primaryFilename": png_path.name,
        "manifestFilename": manifest_path.name,
        "visualizationFilename": activity_visualization_path.name,
        "dataFilename": activity_data_path.name,
        "publishedAt": artifact.completed_at.isoformat().replace("+00:00", "Z"),
    }
    activity_publication_path.write_text(
        canonical_json(publication),
        encoding="utf-8",
    )

    return PublicationBundle(
        directory=directory,
        svg_path=svg_path,
        png_path=png_path,
        visualization_path=visualization_path,
        activity_data_path=activity_data_path,
        activity_visualization_path=activity_visualization_path,
        manifest_path=manifest_path,
        activity_publication_path=activity_publication_path,
        visualization_id=visualization_id,
    )


def _software_versions() -> dict[str, str]:
    """Return installed distribution versions for every export-path dependency."""
    return {
        name: distribution_version(distribution)
        for name, distribution in SOFTWARE_DISTRIBUTIONS.items()
    }


def _projection_provenance(
    activity_data: dict[str, Any],
    spectrogram,
    *,
    png_width: int,
    png_height: int,
) -> dict[str, Any]:
    projected_spectrogram = activity_data["spectrogram"]
    waveform = activity_data["waveform"]
    return {
        "schemaVersion": ACTIVITY_SCHEMA_VERSION,
        "algorithms": {
            "waveformProjection": {
                "id": ("missing_interior_dashboard.activity_projection._envelope_sample_indices"),
                "maximumPoints": DEFAULT_MAX_WAVEFORM_POINTS,
                "fullSampleCount": int(waveform["fullSampleCount"]),
                "publishedSampleCount": int(waveform["publishedSampleCount"]),
            },
            "spectrogramAnalysis": {
                "id": "scipy.signal.spectrogram",
                "parameters": {
                    "window": str(spectrogram.attrs["window"]),
                    "nperseg": int(spectrogram.attrs["nperseg"]),
                    "noverlap": int(spectrogram.attrs["noverlap"]),
                    "detrend": "linear",
                    "scaling": "density",
                    "mode": "psd",
                    "decibelTransform": "10*log10(max(power,float64-tiny))",
                },
            },
            "spectrogramProjection": {
                "id": "missing_interior_dashboard.activity_projection._even_indices",
                "maximumTimeBins": DEFAULT_MAX_SPECTROGRAM_TIME_BINS,
                "maximumFrequencyBins": DEFAULT_MAX_SPECTROGRAM_FREQUENCY_BINS,
                "publishedTimeBins": len(projected_spectrogram["timeSeconds"]),
                "publishedFrequencyBins": len(projected_spectrogram["frequencyHz"]),
            },
            "staticVectorRendering": {
                "id": "holoviews.render",
                "backend": "matplotlib",
            },
            "svgRasterization": {
                "id": "resvg_py.svg_to_bytes",
                "width": png_width,
                "height": png_height,
                "longEdgePixels": PNG_LONG_EDGE,
            },
            "fileDigests": {
                "id": "sha256",
            },
        },
    }


def _atomic_save_figure(figure, path: Path, metadata: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="wb",
        suffix=".svg",
        dir=path.parent,
        delete=False,
    ) as temporary:
        temporary_path = Path(temporary.name)
    try:
        figure.savefig(
            temporary_path,
            format="svg",
            dpi=144,
            bbox_inches="tight",
            facecolor=figure.get_facecolor(),
            metadata=metadata,
        )
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    with tempfile.NamedTemporaryFile(
        mode="wb",
        suffix=path.suffix,
        dir=path.parent,
        delete=False,
    ) as temporary:
        temporary.write(data)
        temporary.flush()
        os.fsync(temporary.fileno())
        temporary_path = Path(temporary.name)
    try:
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _add_accessible_svg_metadata(
    path: Path,
    artifact: AnalysisArtifact,
) -> tuple[int, int]:
    tree = ET.parse(path)
    root = tree.getroot()

    view_box = root.get("viewBox")
    if not view_box:
        raise ValueError("Exported SVG does not contain a viewBox.")

    parts = view_box.replace(",", " ").split()
    if len(parts) != 4:
        raise ValueError(f"Exported SVG has an invalid viewBox: {view_box!r}")

    try:
        _, _, view_width, view_height = (float(value) for value in parts)
    except ValueError as exc:
        raise ValueError(f"Exported SVG contains non-numeric viewBox values: {view_box!r}") from exc

    if (
        not math.isfinite(view_width)
        or not math.isfinite(view_height)
        or view_width <= 0
        or view_height <= 0
    ):
        raise ValueError(f"Exported SVG has invalid dimensions: {view_width!r} x {view_height!r}")

    root.set("width", _format_svg_number(view_width))
    root.set("height", _format_svg_number(view_height))
    root.set("preserveAspectRatio", "xMidYMid meet")

    title = ET.Element(
        f"{{{SVG_NAMESPACE}}}title",
        {"id": "scientific-plate-title"},
    )
    title.text = artifact.title
    description = ET.Element(
        f"{{{SVG_NAMESPACE}}}desc",
        {"id": "scientific-plate-description"},
    )
    description.text = f"{artifact.public_summary} Limitation: {artifact.limitations[0]}"
    root.insert(0, description)
    root.insert(0, title)
    root.set("role", "img")
    root.set("aria-labelledby", "scientific-plate-title scientific-plate-description")
    tree.write(path, encoding="unicode", xml_declaration=True)

    scale = PNG_LONG_EDGE / max(view_width, view_height)
    png_width = max(1, round(view_width * scale))
    png_height = max(1, round(view_height * scale))
    return png_width, png_height


def _format_svg_number(value: float) -> str:
    return f"{value:.6f}".rstrip("0").rstrip(".")
