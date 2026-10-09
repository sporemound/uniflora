from __future__ import annotations

from pathlib import Path

from missing_interior_dashboard.activity_projection import (
    ACTIVITY_DATA_FILENAME,
    ACTIVITY_MANIFEST_FILENAME,
    build_activity_dataset,
    build_activity_visualization_spec,
    canonical_json,
)
from missing_interior_dashboard.io import load_signal_frame
from missing_interior_dashboard.models import load_artifact

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_PATH = ROOT / "examples" / "sr03-artifact.json"


def _projection():
    artifact = load_artifact(ARTIFACT_PATH)
    frame = load_signal_frame(ARTIFACT_PATH, artifact)
    visualization_id = "viz_test_projection"
    return artifact, frame, visualization_id


def test_activity_dataset_is_deterministic_and_bounded() -> None:
    artifact, frame, visualization_id = _projection()

    first = build_activity_dataset(artifact, frame, visualization_id)
    second = build_activity_dataset(artifact, frame, visualization_id)

    assert canonical_json(first) == canonical_json(second)
    assert first["waveform"]["fullSampleCount"] == 4096
    assert 16 <= first["waveform"]["publishedSampleCount"] <= 640
    assert len(first["spectrogram"]["timeSeconds"]) <= 96
    assert len(first["spectrogram"]["frequencyHz"]) <= 64
    assert len(first["spectrogram"]["powerDb"]) == len(
        first["spectrogram"]["frequencyHz"]
    )


def test_activity_dataset_preserves_public_provenance() -> None:
    artifact, frame, visualization_id = _projection()
    dataset = build_activity_dataset(artifact, frame, visualization_id)

    assert dataset["stateHeadHash"] == artifact.state_head_hash
    assert dataset["inputDatasetHash"] == artifact.data_sha256
    assert dataset["timeZones"]["facility"] == artifact.facility_timezone
    assert dataset["timeZones"]["source"] == artifact.source_timezone
    assert [event["eventId"] for event in dataset["events"]] == [
        event.event_id for event in artifact.events
    ]
    assert dataset["limitations"] == list(artifact.limitations)


def test_activity_visualization_references_reduced_dataset() -> None:
    artifact, _, visualization_id = _projection()
    spec = build_activity_visualization_spec(artifact, visualization_id)

    assert spec["schemaVersion"] == "3.0.0"
    assert spec["datasetFilename"] == ACTIVITY_DATA_FILENAME
    assert spec["manifestFilename"] == ACTIVITY_MANIFEST_FILENAME
    assert spec["interaction"]["linkedTimeWindow"] is True
    assert {view["id"] for view in spec["views"]} == {"waveform", "spectrogram"}
