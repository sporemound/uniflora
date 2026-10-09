from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = ROOT / "examples"


def gaussian(t: np.ndarray, center: float, width: float, amplitude: float) -> np.ndarray:
    return amplitude * np.exp(-0.5 * ((t - center) / width) ** 2)


def main() -> int:
    sample_rate = 256.0
    sample_count = 4096
    offsets = np.arange(sample_count, dtype=float) / sample_rate - 4.0
    rng = np.random.default_rng(73103)

    drift = 0.018 * np.sin(2 * np.pi * 0.07 * offsets) + 0.0015 * offsets
    carrier = 0.022 * np.sin(2 * np.pi * 17.5 * offsets)
    response = gaussian(offsets, -3.0, 0.055, 0.46)
    receipt = gaussian(offsets, 0.0, 0.08, 0.29)
    declared = gaussian(offsets, 3.0, 0.05, 0.18)
    ringing = 0.035 * np.exp(-np.maximum(offsets + 3.0, 0) / 1.2) * np.sin(
        2 * np.pi * 31.0 * np.maximum(offsets + 3.0, 0)
    )
    noise = rng.normal(0.0, 0.008, sample_count)

    calibrated = carrier + response + receipt + declared + ringing + noise
    raw = calibrated + drift
    uncertainty = 0.011 + 0.004 * np.abs(np.sin(2 * np.pi * 0.11 * offsets))
    quality = np.full(sample_count, "valid", dtype=object)
    quality[(offsets >= 1.44) & (offsets <= 1.49)] = "degraded"
    quality[(offsets >= 6.70) & (offsets <= 6.73)] = "excluded"

    frame = pd.DataFrame(
        {
            "sample_index": np.arange(sample_count),
            "offset_seconds": offsets,
            "raw_voltage_v": raw,
            "calibrated_voltage_v": calibrated,
            "uncertainty_v": uncertainty,
            "quality": quality,
        }
    )
    data_path = EXAMPLES / "sr03-signal.csv"
    frame.to_csv(data_path, index=False, float_format="%.9f", lineterminator="\n")
    data_hash = hashlib.sha256(data_path.read_bytes()).hexdigest()

    artifact = {
        "schema_version": "1.0.0",
        "artifact_id": "artifact-phase3-sr03",
        "environment": "test",
        "position_id": "position-0",
        "institution_id": "interfacility-intake",
        "title": "SR-03 line-voltage and timing study",
        "completed_at": "2026-07-24T03:17:15Z",
        "state_head_hash": "531225e7d753e51510ba9b2bd0898853e71492e41433a708cba758a829636bcb",
        "reference_time_utc": "2026-07-24T03:17:09Z",
        "facility_timezone": "America/Los_Angeles",
        "source_timezone": "America/Los_Angeles",
        "source_clock_id": "sr03-retired-source-clock",
        "data_file": "sr03-signal.csv",
        "data_sha256": data_hash,
        "sample_rate_hz": sample_rate,
        "method": {
            "method_id": "line-voltage-timing-study",
            "version": "1.0.0",
            "parameters": {
                "reference_event": "intake-receipt",
                "calibration": "low-order drift removal",
                "spectrogram_window": "hann",
                "fixture_seed": 73103
            }
        },
        "events": [
            {
                "event_id": "boundary-response",
                "label": "Boundary response",
                "offset_seconds": -3.0,
                "source": "Boundary Array relay",
                "uncertainty_seconds": 0.02
            },
            {
                "event_id": "intake-receipt",
                "label": "Verified intake receipt",
                "offset_seconds": 0.0,
                "source": "Interfacility Intake clock",
                "uncertainty_seconds": 0.02
            },
            {
                "event_id": "declared-transmission",
                "label": "Declared transmission",
                "offset_seconds": 3.0,
                "source": "SR-03 packet header",
                "uncertainty_seconds": 0.05
            }
        ],
        "derived_values": [
            {
                "value_id": "declared-minus-receipt",
                "label": "Declared transmission minus verified receipt",
                "value": 3.0,
                "unit": "s",
                "uncertainty": 0.07
            },
            {
                "value_id": "response-minus-receipt",
                "label": "Boundary response minus verified receipt",
                "value": -3.0,
                "unit": "s",
                "uncertainty": 0.04
            }
        ],
        "limitations": [
            (
                "This deterministic Phase 3 fixture demonstrates the dashboard and "
                "publication path; it is not a production scientific observation."
            ),
            (
                "A misconfigured source clock remains a viable ordinary explanation "
                "for the declared transmission offset."
            ),
            (
                "The synthetic line-voltage waveform cannot establish the physical "
                "origin of the packet."
            ),
        ],
        "public_summary": (
            "The verified intake receipt falls three seconds before the packet's declared "
            "transmission time; the retained voltage record also contains a response "
            "three seconds before receipt."
        ),
    }
    artifact_path = EXAMPLES / "sr03-artifact.json"
    artifact_path.write_text(json.dumps(artifact, indent=2) + "\n", encoding="utf-8")
    print(artifact_path)
    print(data_path)
    print(data_hash)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
