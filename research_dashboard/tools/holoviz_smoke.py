from __future__ import annotations

import json
from pathlib import Path

import datashader as ds
import holoviews as hv
import numpy as np
import pandas as pd

from missing_interior_dashboard.export import export_publication_bundle
from missing_interior_dashboard.io import load_signal_frame
from missing_interior_dashboard.models import load_artifact
from missing_interior_dashboard.views import build_waveform, initialize_holoviews

ROOT = Path(__file__).resolve().parent.parent
ARTIFACT_PATH = ROOT / "examples" / "sr03-artifact.json"
OUTPUT = ROOT / "data" / "rendered" / "smoke"


def main() -> int:
    initialize_holoviews()
    artifact = load_artifact(ARTIFACT_PATH)
    frame = load_signal_frame(ARTIFACT_PATH, artifact)

    waveform, _primary = build_waveform(
        artifact,
        frame,
        show_raw=True,
        show_uncertainty=True,
    )
    bokeh_plot = hv.render(waveform, backend="bokeh")

    dense_x = np.linspace(0.0, 100.0, 250_000)
    dense_frame = pd.DataFrame(
        {
            "x": dense_x,
            "y": np.sin(dense_x) + 0.15 * np.sin(41.0 * dense_x),
        }
    )
    canvas = ds.Canvas(plot_width=800, plot_height=300)
    aggregate = canvas.line(dense_frame, "x", "y")

    bundle = export_publication_bundle(artifact, frame, OUTPUT)
    result = {
        "holoviews_bokeh_model": type(bokeh_plot).__name__,
        "datashader_aggregate_shape": list(aggregate.shape),
        "visualization_id": bundle.visualization_id,
        "svg": str(bundle.svg_path),
        "png": str(bundle.png_path),
    }
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
