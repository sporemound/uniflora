from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from importlib.metadata import version as distribution_version
from pathlib import Path

import matplotlib

from missing_interior_dashboard.export import export_publication_bundle
from missing_interior_dashboard.io import load_signal_frame
from missing_interior_dashboard.models import file_sha256, load_artifact

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_PATH = ROOT / "examples" / "sr03-artifact.json"


def test_export_selects_headless_matplotlib_backend() -> None:
    assert str(matplotlib.get_backend()).casefold() == "agg"


def test_export_creates_svg_png_and_activity_metadata(tmp_path: Path) -> None:
    artifact = load_artifact(ARTIFACT_PATH)
    frame = load_signal_frame(ARTIFACT_PATH, artifact)
    bundle = export_publication_bundle(artifact, frame, tmp_path)

    assert bundle.svg_path.is_file()
    assert bundle.png_path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    root = ET.parse(bundle.svg_path).getroot()
    assert root.attrib["role"] == "img"
    assert root.attrib["aria-labelledby"]

    activity_data = json.loads(bundle.activity_data_path.read_text(encoding="utf-8"))
    activity_visualization = json.loads(
        bundle.activity_visualization_path.read_text(encoding="utf-8")
    )
    manifest = json.loads(bundle.manifest_path.read_text(encoding="utf-8"))
    publication = json.loads(bundle.activity_publication_path.read_text(encoding="utf-8"))
    visualization = json.loads(bundle.visualization_path.read_text(encoding="utf-8"))

    assert activity_data["visualizationId"] == bundle.visualization_id
    assert {panel["id"] for panel in visualization["panels"]} == {
        "waveform",
        "spectrogram",
        "calibration-residual",
        "phase-space",
    }
    assert activity_visualization["datasetFilename"] == "activity-data.json"
    assert manifest["visualizationId"] == bundle.visualization_id
    assert manifest["files"]["scientific-plate.svg"] == file_sha256(bundle.svg_path)
    assert manifest["files"]["scientific-plate.png"] == file_sha256(bundle.png_path)
    assert manifest["files"]["activity-data.json"] == file_sha256(bundle.activity_data_path)
    assert manifest["files"]["activity-visualization.json"] == file_sha256(
        bundle.activity_visualization_path
    )
    expected_versions = {
        name: distribution_version(name)
        for name in (
            "numpy",
            "pandas",
            "scipy",
            "xarray",
            "colorcet",
            "holoviews",
            "matplotlib",
            "resvg_py",
        )
    }
    assert manifest["softwareVersions"] == expected_versions
    assert manifest["rendererVersions"] == {
        name: expected_versions[name] for name in ("holoviews", "matplotlib", "resvg_py")
    }

    projection = manifest["projectionProvenance"]
    assert projection["schemaVersion"] == activity_data["schemaVersion"]
    assert (
        projection["algorithms"]["waveformProjection"]["id"]
        == "missing_interior_dashboard.activity_projection._envelope_sample_indices"
    )
    assert projection["algorithms"]["waveformProjection"]["fullSampleCount"] == len(frame)
    assert (
        projection["algorithms"]["waveformProjection"]["publishedSampleCount"]
        == activity_data["waveform"]["publishedSampleCount"]
    )
    assert projection["algorithms"]["spectrogramAnalysis"]["id"] == "scipy.signal.spectrogram"
    assert projection["algorithms"]["spectrogramProjection"]["publishedFrequencyBins"] == len(
        activity_data["spectrogram"]["frequencyHz"]
    )
    assert projection["algorithms"]["spectrogramProjection"]["publishedTimeBins"] == len(
        activity_data["spectrogram"]["timeSeconds"]
    )
    assert projection["algorithms"]["staticVectorRendering"] == {
        "id": "holoviews.render",
        "backend": "matplotlib",
    }
    assert projection["algorithms"]["svgRasterization"]["id"] == "resvg_py.svg_to_bytes"
    assert projection["algorithms"]["fileDigests"]["id"] == "sha256"
    assert publication["primaryFilename"] == "scientific-plate.png"
    assert publication["manifestFilename"] == "manifest-phase3b.json"
    assert publication["visualizationFilename"] == "activity-visualization.json"
    assert publication["dataFilename"] == "activity-data.json"


def test_repeated_export_is_byte_reproducible(tmp_path: Path) -> None:
    artifact = load_artifact(ARTIFACT_PATH)
    frame = load_signal_frame(ARTIFACT_PATH, artifact)
    first = export_publication_bundle(artifact, frame, tmp_path / "first")
    second = export_publication_bundle(artifact, frame, tmp_path / "second")

    assert first.visualization_id == second.visualization_id
    assert first.svg_path.read_bytes() == second.svg_path.read_bytes()
    assert first.png_path.read_bytes() == second.png_path.read_bytes()
    assert first.visualization_path.read_bytes() == second.visualization_path.read_bytes()
    assert first.activity_data_path.read_bytes() == second.activity_data_path.read_bytes()
    assert (
        first.activity_visualization_path.read_bytes()
        == second.activity_visualization_path.read_bytes()
    )
    assert first.manifest_path.read_bytes() == second.manifest_path.read_bytes()
