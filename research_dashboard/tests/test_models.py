from __future__ import annotations

from pathlib import Path

import pytest

from missing_interior_dashboard.io import load_signal_frame
from missing_interior_dashboard.models import ArtifactValidationError, load_artifact

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "examples" / "sr03-artifact.json"


def test_fixture_loads_and_dataset_hash_verifies() -> None:
    artifact = load_artifact(ARTIFACT)
    frame = load_signal_frame(ARTIFACT, artifact)

    assert artifact.artifact_id == "artifact-phase3-sr03"
    assert artifact.environment == "test"
    assert artifact.sample_rate_hz == 256.0
    assert len(frame) == 4096
    assert frame["offset_seconds"].iloc[0] == pytest.approx(-4.0)


def test_changed_dataset_is_rejected(tmp_path: Path) -> None:
    artifact_copy = tmp_path / ARTIFACT.name
    data_copy = tmp_path / "sr03-signal.csv"
    artifact_copy.write_bytes(ARTIFACT.read_bytes())
    data_copy.write_bytes((ROOT / "examples" / "sr03-signal.csv").read_bytes() + b"\n")

    artifact = load_artifact(artifact_copy)
    with pytest.raises(ArtifactValidationError, match="hash mismatch"):
        load_signal_frame(artifact_copy, artifact)
