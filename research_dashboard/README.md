# The Missing Interior — Research Dashboard Phase 3B projection producer

This is an isolated local scientific workstation for **The Missing Interior**. It is deliberately separate from:

- `src/uniflora`;
- the authoritative game databases;
- the Discord bot process;
- the Cloudflare Activity project under `activity/`;
- the bare-bones v2 source work being finalized elsewhere.

Phase 3A made the HoloViz stack visibly testable. Phase 3B preserves that local workstation and adds a deterministic sanitized projection for the Discord Activity:

- Panel 1.9 dashboard shell;
- HoloViews interactive Bokeh views;
- a GeoViews Web Mercator facility map over CARTO/OpenStreetMap-derived tiles;
- Cartopy and PyProj coordinate transforms plus xyzservices provider metadata;
- Dask, SpatialPandas, and PyArrow support for out-of-core trajectory collections;
- linked waveform range and spectrogram recomputation;
- click-to-inspect retained samples;
- raw, calibrated, uncertainty, and degraded-sample layers;
- Zulu, facility-local, source-original, Pacific, Mountain, Central, and Eastern time displays;
- timing-event and calibration-residual workspaces;
- a calibrated-voltage/slew-rate phase-space diagnostic built from retained samples;
- adaptive hvPlot rendering that preserves per-sample hover below 50,000 valid
  samples and uses Datashader count rasterization above that density;
- Colorcet perceptual palettes for acquisition-time and occupancy encoding;
- provenance, method, dataset hash, limitations, and derived-value inspection;
- HoloViews → Matplotlib standalone SVG export;
- accessible SVG title and description;
- `resvg_py` SVG → PNG conversion;
- deterministic visualization IDs and byte-reproducible exports;
- a publication manifest and Phase 2 Activity registration payload;
- an optional helper that uploads a completed bundle through `activity/tools/publish_hypha.py`;
- extrema-preserving waveform reduction capped at 640 public samples;
- bounded spectrogram projection capped at 96 time bins by 64 frequency bins;
- browser-facing provenance, events, quality intervals, derived values, time zones, and limitations;
- deterministic `activity-data.json` and `activity-visualization.json` files.

The included SR-03 data is a deterministic synthetic fixture. It demonstrates the research and publication system; it is not represented as a real scientific observation.

## Directory layout

```text
research_dashboard/
    app.py
    pyproject.toml
    examples/
        sr03-artifact.json
        sr03-signal.csv
    missing_interior_dashboard/
        analysis.py
        cli.py
        dashboard.py
        export.py
        io.py
        models.py
        views.py
    tests/
    tools/
        check_environment.py
        generate_fixture.py
        publish_bundle.py
    data/rendered/
```

## Install in an isolated environment

### Recommended Miniforge/Conda route

From the repository root:

```powershell
Set-Location "C:\path\to\uniflora\research_dashboard"

conda env create -f ".\environment.yml"
conda activate "missing-interior-dashboard"
python -m pip install -e "." --no-deps --no-build-isolation
```

### Standard Python virtual-environment route

```powershell
Set-Location "C:\path\to\uniflora\research_dashboard"

python -m venv ".venv"

& ".\.venv\Scripts\Activate.ps1"

python -m pip install --upgrade pip
python -m pip install -r ".\requirements-dev.txt"
python -m pip install -e "." --no-deps --no-build-isolation
```

The dependency sets include `tsdownsample`. It is not required by the included 4,096-sample fixture, but it prepares hvPlot/HoloViews for much longer time series.

## Verify the research stack

```powershell
python ".\tools\check_environment.py"
```

Every listed module should report `"ok": true`.

Run Ruff only on Python files:

```powershell
python -m ruff check `
    ".\missing_interior_dashboard" `
    ".\tests" `
    ".\tools"
```

Run the test suite:

```powershell
python -m pytest -q
```

The export tests create SVG and PNG files only inside pytest temporary directories.

Run the end-to-end HoloViz smoke test:

```powershell
python ".\tools\holoviz_smoke.py"
```

This renders the fixture through HoloViews/Bokeh, aggregates a 250,000-point line with Datashader, and creates a real HoloViews → Matplotlib → SVG → `resvg_py` → PNG publication bundle.

## Start the local HoloViews dashboard

```powershell
missing-interior-dashboard serve --dev
```

The default address is:

```text
http://127.0.0.1:8765/app
```

The command binds only to `127.0.0.1`. It does not expose the dashboard to your LAN or the internet.

The dashboard should display:

- the SR-03 scientific artifact as verified;
- a **Geographic field** tab with pan, zoom, hover, and six WGS84 facility sites;
- 4,096 retained samples at 256 Hz;
- an interactive waveform;
- a spectrogram that recomputes when the waveform range changes;
- a **Phase-space diagnostics** tab plotting calibrated voltage against its
  finite-difference slew rate;
- sample details after clicking the calibrated trace;
- timing events at -3, 0, and +3 seconds relative to receipt;
- provenance and limitations;
- a publication export control.

Use the mouse wheel over the waveform to zoom the x-axis. The linked spectrogram updates to the selected interval. Click the calibrated line to inspect the nearest retained sample.

The phase-space view uses the artifact's declared sample rate to compute the
calibrated-voltage derivative. For ordinary artifacts, every valid sample remains
hoverable and Colorcet encodes its time relative to receipt. Quality-flagged samples
are overlaid as red crosses instead of being silently removed. Once an artifact
contains more than 50,000 valid samples, the view switches to Datashader count
rasterization; at that density a pixel-wise occupancy field is more faithful and
usable than tens of thousands of overlapping browser glyphs. The same full-dataset
phase map is included in the static HoloViews publication plate. The interactive
dashboard retains per-sample hover and zoom behavior; the immutable plate preserves
the mapped diagnostic for Activity delivery.

## Export without starting the dashboard

```powershell
missing-interior-dashboard export
```

The output is written under:

```text
data/rendered/test/artifact-phase3-sr03/<visualization-id>/
```

A bundle contains:

```text
scientific-plate.svg
scientific-plate.png
visualization.json
activity-data.json
activity-visualization.json
manifest-phase3b.json
activity-publication.json
```

The PNG is generated from the complete SVG using `resvg_py`; it is not a screenshot of the Panel interface.

The export uses the artifact completion time and a fixed Matplotlib SVG hash salt. Repeating the export with the same artifact, data, method, and renderer versions should produce the same SVG and PNG bytes.

## Publish a bundle to the local Phase 3B Activity

Keep the Activity development server running in a separate PowerShell window. Set the same HMAC secret used by `activity\.dev.vars`:

```powershell
$env:HYPHA_ACTIVITY_SECRET = "your-real-64-character-secret"
```

Then publish a completed bundle:

```powershell
python ".\tools\publish_bundle.py" `
    ".\data\rendered\test\artifact-phase3-sr03\<visualization-id>" `
    --activity-root "..\activity" `
    --base-url "http://127.0.0.1:5173"
```

The helper uploads the SVG, PNG, local visualization specification, reduced Activity dataset, Activity visualization specification, and manifest through the signed endpoint, then registers `activity-publication.json`. Before registration it reads the current public state head from the Activity and uses that as the publication state while preserving the artifact's evidence state separately. The registered publication ID is suffixed with that state-head prefix, so the same evidence may be published again after a later state revision without violating append-only publication IDs.

The Activity discovers the latest publication directly and renders the reduced dataset as linked browser-native scientific views. The authoritative 4,096-sample fixture and all HoloViews processing remain local.

## Load another artifact

Use the dashboard's **Artifact JSON** field, or launch with:

```powershell
missing-interior-dashboard serve `
    --artifact "V:\path\to\another-artifact.json"
```

The artifact JSON must identify a CSV in the same directory and include its exact SHA-256. The dashboard rejects a missing file, path traversal, altered data, missing required columns, invalid environment, or malformed hashes.

Required CSV columns:

```text
sample_index
offset_seconds
raw_voltage_v
calibrated_voltage_v
uncertainty_v
quality
```

## Phase boundary

Phase 3A does not read the v2 SQLite analysis store directly. That connection should be added only after the bare-bones engine and analysis-store interfaces are finalized. The current fixture boundary allows HoloViews, Panel, Datashader, export, and publication behavior to be tested without creating merge conflicts or coupling the dashboard to unfinished engine code.


## Phase 3B projection acceptance

Run the projection tests inside the dashboard environment:

```powershell
conda activate "missing-interior-dashboard"
Set-Location "C:\path\to\uniflora\research_dashboard"
python -m pytest --basetemp ".\.pytest-tmp"
```

The projection tests verify deterministic JSON, waveform and spectrogram bounds, event retention, provenance retention, and export-manifest hashes.
