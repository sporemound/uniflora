from __future__ import annotations

from pathlib import Path

import pandas as pd

from .models import REQUIRED_SIGNAL_COLUMNS, AnalysisArtifact, ArtifactValidationError, file_sha256


def resolve_data_path(artifact_path: Path, artifact: AnalysisArtifact) -> Path:
    candidate = (artifact_path.parent / artifact.data_file).resolve()
    parent = artifact_path.parent.resolve()
    if parent not in candidate.parents:
        raise ArtifactValidationError("data_file must stay within the artifact directory")
    return candidate


def load_signal_frame(artifact_path: Path, artifact: AnalysisArtifact) -> pd.DataFrame:
    data_path = resolve_data_path(artifact_path, artifact)
    if not data_path.is_file():
        raise ArtifactValidationError(f"Signal data file does not exist: {data_path}")
    actual_hash = file_sha256(data_path)
    if actual_hash != artifact.data_sha256:
        raise ArtifactValidationError(
            f"Signal data hash mismatch: expected {artifact.data_sha256}, received {actual_hash}"
        )

    frame = pd.read_csv(data_path)
    missing = [column for column in REQUIRED_SIGNAL_COLUMNS if column not in frame.columns]
    if missing:
        raise ArtifactValidationError(f"Signal data is missing columns: {', '.join(missing)}")
    if frame.empty:
        raise ArtifactValidationError("Signal data cannot be empty")
    if not frame["offset_seconds"].is_monotonic_increasing:
        raise ArtifactValidationError("offset_seconds must be monotonically increasing")
    if frame["sample_index"].duplicated().any():
        raise ArtifactValidationError("sample_index values must be unique")
    return frame
