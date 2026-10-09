from __future__ import annotations

import os
from pathlib import Path

import holoviews as hv
import pandas as pd
import panel as pn
import param

from .analysis import (
    TIME_BASIS_TO_ZONE,
    compute_phase_space,
    compute_spectrogram,
    format_timestamp,
    nearest_sample,
    phase_space_statistics,
    window_statistics,
)
from .export import export_publication_bundle
from .io import load_signal_frame
from .models import AnalysisArtifact, ArtifactValidationError, load_artifact
from .views import (
    BACKGROUND,
    CALIBRATED,
    PANEL,
    TEXT,
    add_event_markers,
    build_facility_map_view,
    build_phase_density_view,
    build_residual_view,
    build_spectrogram_view,
    build_timing_view,
    build_waveform,
    initialize_holoviews,
    phase_density_uses_rasterization,
)

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ARTIFACT = ROOT / "examples" / "sr03-artifact.json"
DEFAULT_OUTPUT = ROOT / "data" / "rendered"

FACILITY_SITES = pd.DataFrame(
    [
        (-119.05, 40.88, "Boundary Array", "Black Rock Sector, Nevada", "focus"),
        (
            -80.21,
            38.73,
            "Aeronautical Incident Center",
            "Allegheny Sector, West Virginia",
            "locked",
        ),
        (-90.88, 43.25, "Aerial Phenomena Archive", "Driftless Sector, Wisconsin", "locked"),
        (-105.91, 37.73, "Holography Laboratory", "San Luis Sector, Colorado", "locked"),
        (-123.53, 47.45, "Subsurface Resonance Station", "Cascadia Sector, Washington", "locked"),
        (-74.31, 44.12, "Quantum State Institute", "Adirondack Sector, New York", "locked"),
    ],
    columns=["longitude", "latitude", "name", "sector", "status"],
)


class DashboardState(param.Parameterized):
    revision = param.Integer(default=0)


class ResearchDashboard:
    def __init__(self, artifact_path: Path) -> None:
        initialize_holoviews()
        pn.extension(
            "tabulator",
            notifications=True,
            sizing_mode="stretch_width",
        )

        self.state = DashboardState()
        self.artifact: AnalysisArtifact
        self.frame = None
        self.loaded_path = artifact_path

        self.artifact_path = pn.widgets.TextInput(
            label="Artifact JSON",
            value=str(artifact_path),
            placeholder="Path to an analysis artifact JSON file",
        )
        self.load_button = pn.widgets.Button(
            label="Load and verify",
            color="primary",
        )
        self.time_basis = pn.widgets.Select(
            label="Time basis",
            options=list(TIME_BASIS_TO_ZONE),
            value="Zulu",
        )
        self.show_raw = pn.widgets.Checkbox(
            label="Show raw measurement",
            value=True,
        )
        self.show_uncertainty = pn.widgets.Checkbox(
            label="Show uncertainty",
            value=True,
        )
        self.output_path = pn.widgets.TextInput(
            label="Publication output root",
            value=str(DEFAULT_OUTPUT),
        )
        self.export_button = pn.widgets.Button(
            label="Create publication artifact",
            color="success",
        )
        self.status = pn.pane.Alert("Loading fixture…", alert_type="info")
        self.export_status = pn.pane.Markdown("No publication bundle created in this session.")
        self.preview = pn.pane.PNG(height=360, sizing_mode="stretch_width", visible=False)

        self.load_button.on_click(self._load_from_widget)
        self.export_button.on_click(self._export)
        self._load(artifact_path)

    def _load_from_widget(self, _event) -> None:
        self._load(Path(self.artifact_path.value).expanduser())

    def _load(self, path: Path) -> None:
        try:
            artifact = load_artifact(path)
            frame = load_signal_frame(path, artifact)
        except ArtifactValidationError as exc:
            self.status.object = str(exc)
            self.status.alert_type = "danger"
            return
        self.artifact = artifact
        self.frame = frame
        self.loaded_path = path
        self.status.object = (
            f"Verified **{artifact.artifact_id}** against dataset `{artifact.data_sha256[:12]}…` "
            f"({len(frame):,} samples at {artifact.sample_rate_hz:g} Hz)."
        )
        self.status.alert_type = "success"
        self.state.revision += 1

    def _export(self, _event) -> None:
        try:
            bundle = export_publication_bundle(
                self.artifact,
                self.frame,
                Path(self.output_path.value).expanduser(),
            )
        except Exception as exc:  # surfaced in the local operator UI
            self.export_status.object = f"**Export failed:** `{type(exc).__name__}: {exc}`"
            if pn.state.notifications:
                pn.state.notifications.error(f"Export failed: {exc}", duration=8000)
            return
        self.preview.object = str(bundle.png_path)
        self.preview.visible = True
        self.export_status.object = (
            f"**Publication bundle created**\n\n"
            f"- Visualization: `{bundle.visualization_id}`\n"
            f"- Directory: `{bundle.directory}`\n"
            f"- SVG: `{bundle.svg_path.name}`\n"
            f"- PNG: `{bundle.png_path.name}`\n"
            f"- Manifest: `{bundle.manifest_path.name}`\n"
            f"- Activity registration: `{bundle.activity_publication_path.name}`"
        )
        if pn.state.notifications:
            pn.state.notifications.success("Publication bundle created.", duration=5000)

    def signals_workspace(self, revision: int, show_raw: bool, show_uncertainty: bool):
        del revision
        waveform, primary = build_waveform(
            self.artifact,
            self.frame,
            show_raw=show_raw,
            show_uncertainty=show_uncertainty,
        )
        waveform = add_event_markers(waveform, self.artifact.events)
        range_stream = hv.streams.RangeX(source=primary, x_range=None)
        tap_stream = hv.streams.Tap(source=primary, x=None, y=None)

        def spectrogram_for_range(x_range):
            data = compute_spectrogram(
                self.frame,
                self.artifact.sample_rate_hz,
                x_range=x_range,
            )
            return build_spectrogram_view(data)

        dynamic_spectrogram = hv.DynamicMap(
            spectrogram_for_range,
            streams=[range_stream],
        )
        inspector = pn.bind(
            self.sample_inspector,
            x=tap_stream.param.x,
            time_basis=self.time_basis.param.value,
        )
        selected_stats = pn.bind(
            self.range_summary,
            x_range=range_stream.param.x_range,
        )
        plots = pn.pane.HoloViews(
            (waveform + dynamic_spectrogram).cols(1),
            sizing_mode="stretch_width",
        )
        return pn.Column(
            plots,
            pn.Row(selected_stats, inspector, sizing_mode="stretch_width"),
            sizing_mode="stretch_width",
        )

    def timing_workspace(self, revision: int, time_basis: str):
        del revision
        event_rows = []
        for event in sorted(self.artifact.events, key=lambda item: item.offset_seconds):
            event_rows.append(
                {
                    "event": event.label,
                    "source": event.source,
                    "offset_seconds": event.offset_seconds,
                    "uncertainty_seconds": event.uncertainty_seconds,
                    "selected_time": format_timestamp(
                        self.artifact,
                        event.offset_seconds,
                        time_basis,
                    ),
                    "zulu": format_timestamp(self.artifact, event.offset_seconds, "Zulu"),
                }
            )
        table = pn.widgets.Tabulator(
            pd.DataFrame(event_rows),
            pagination=None,
            disabled=True,
            sizing_mode="stretch_width",
            height=220,
        )
        return pn.Column(
            pn.pane.HoloViews(build_timing_view(self.artifact), sizing_mode="stretch_width"),
            table,
            pn.pane.HoloViews(build_residual_view(self.frame), sizing_mode="stretch_width"),
        )

    def diagnostics_workspace(self, revision: int):
        del revision
        phase_frame = compute_phase_space(self.frame, self.artifact.sample_rate_hz)
        stats = phase_space_statistics(phase_frame)
        rasterized = phase_density_uses_rasterization(phase_frame)
        render_note = (
            "Datashader count rasterization is active because this artifact exceeds "
            "the 50,000-valid-sample interactive vector budget. Color encodes "
            "equalized valid-sample occupancy."
            if rasterized
            else (
                "Vector inspection is active for this artifact. Each valid sample is "
                "hoverable, and color encodes seconds from verified receipt. Artifacts "
                "above 50,000 valid samples switch to Datashader count rasterization."
            )
        )
        metrics = pn.FlexBox(
            _metric("Valid samples", f"{stats.valid_count:,}", "phase-density input"),
            _metric("Flagged", f"{stats.flagged_count:,}", "marked, not hidden"),
            _metric("RMS slew", f"{stats.rms_slew_v_per_s:.3f} V/s", "central difference"),
            _metric(
                "99th percentile |slew|",
                f"{stats.percentile_99_absolute_slew_v_per_s:.3f} V/s",
                "tail-resistant scale",
            ),
            sizing_mode="stretch_width",
        )
        explanation = pn.pane.Markdown(
            "\n".join(
                [
                    "### How to read this diagnostic",
                    (
                        "The phase portrait plots calibrated voltage against its time "
                        "derivative, computed at the artifact's declared sample cadence. "
                        "Closed or repeated traces indicate recurring waveform dynamics; "
                        "vertical excursions identify rapid transitions; dense horizontal "
                        "bands can indicate sustained levels or clipping."
                    ),
                    (
                        "Quality-flagged samples remain visible as red crosses but do not "
                        "contribute to the valid-sample density."
                    ),
                ]
            ),
            styles={"background": PANEL, "padding": "12px"},
            sizing_mode="stretch_width",
        )
        return pn.Column(
            pn.pane.Alert(render_note, alert_type="info"),
            metrics,
            pn.pane.HoloViews(
                build_phase_density_view(phase_frame),
                sizing_mode="stretch_width",
            ),
            explanation,
            sizing_mode="stretch_width",
        )

    def geography_workspace(self):
        return pn.Column(
            pn.pane.Alert(
                (
                    "Live Web Mercator tiles with WGS84 facility records. Pan and zoom "
                    "to inspect sectors; published trajectory and density collections "
                    "can be overlaid through the same GeoViews/Datashader pipeline."
                ),
                alert_type="info",
            ),
            pn.pane.HoloViews(
                build_facility_map_view(FACILITY_SITES),
                sizing_mode="stretch_width",
            ),
            sizing_mode="stretch_width",
        )

    def provenance_workspace(self, revision: int, time_basis: str):
        del revision
        derived = [
            {
                "quantity": item.label,
                "value": item.value,
                "unit": item.unit,
                "uncertainty": item.uncertainty,
            }
            for item in self.artifact.derived_values
        ]
        method = pn.pane.JSON(
            {
                "method_id": self.artifact.method.method_id,
                "version": self.artifact.method.version,
                "parameters": self.artifact.method.parameters,
                "dataset_sha256": self.artifact.data_sha256,
                "artifact_definition_sha256": self.artifact.artifact_definition_hash(),
                "state_head_hash": self.artifact.state_head_hash,
                "reference_time": format_timestamp(self.artifact, 0, time_basis),
            },
            depth=3,
            sizing_mode="stretch_width",
        )
        return pn.Column(
            "### Derived values",
            pn.widgets.Tabulator(
                pd.DataFrame(derived),
                disabled=True,
                height=220,
                sizing_mode="stretch_width",
            ),
            "### Method and provenance",
            method,
            "### Limitations",
            pn.pane.Markdown("\n".join(f"- {item}" for item in self.artifact.limitations)),
        )

    def overview_metrics(self, revision: int):
        del revision
        stats = window_statistics(self.frame)
        duration = stats.end_seconds - stats.start_seconds
        return pn.FlexBox(
            _metric("Samples", f"{stats.sample_count:,}", "retained rows"),
            _metric("Duration", f"{duration:.3f} s", "full acquisition"),
            _metric("Sample rate", f"{self.artifact.sample_rate_hz:g} Hz", "declared cadence"),
            _metric("Degraded", str(stats.excluded_count), "visibly marked"),
            sizing_mode="stretch_width",
        )

    def sample_inspector(self, x: float | None, time_basis: str):
        if x is None:
            return pn.pane.Markdown(
                "### Sample inspector\nClick the calibrated waveform to inspect a retained sample.",
                styles={"background": PANEL, "padding": "12px"},
                sizing_mode="stretch_width",
            )
        sample = nearest_sample(self.frame, x)
        timestamp = format_timestamp(
            self.artifact,
            float(sample["offset_seconds"]),
            time_basis,
        )
        return pn.pane.Markdown(
            "\n".join(
                [
                    "### Sample inspector",
                    f"**Time:** {timestamp}",
                    f"**Offset:** {float(sample['offset_seconds']):.6f} s",
                    f"**Raw:** {float(sample['raw_voltage_v']):.6f} V",
                    f"**Calibrated:** {float(sample['calibrated_voltage_v']):.6f} V",
                    f"**Uncertainty:** ±{float(sample['uncertainty_v']):.6f} V",
                    f"**Quality:** {sample['quality']}",
                ]
            ),
            styles={"background": PANEL, "padding": "12px"},
            sizing_mode="stretch_width",
        )

    def range_summary(self, x_range):
        stats = window_statistics(self.frame, x_range)
        return pn.pane.Markdown(
            "\n".join(
                [
                    "### Selected interval",
                    f"**Range:** {stats.start_seconds:.3f} to {stats.end_seconds:.3f} s",
                    f"**Samples:** {stats.sample_count:,}",
                    f"**RMS:** {stats.rms_voltage:.5f} V",
                    (
                        "**Minimum / maximum:** "
                        f"{stats.minimum_voltage:.5f} / {stats.maximum_voltage:.5f} V"
                    ),
                    f"**Degraded samples:** {stats.excluded_count}",
                ]
            ),
            styles={"background": PANEL, "padding": "12px"},
            sizing_mode="stretch_width",
        )

    def template(self):
        sidebar = pn.Column(
            "## Artifact",
            self.artifact_path,
            self.load_button,
            self.status,
            "## Display",
            self.time_basis,
            self.show_raw,
            self.show_uncertainty,
            "## Publication",
            self.output_path,
            self.export_button,
            self.export_status,
            width=330,
        )
        signals = pn.bind(
            self.signals_workspace,
            revision=self.state.param.revision,
            show_raw=self.show_raw.param.value,
            show_uncertainty=self.show_uncertainty.param.value,
        )
        timing = pn.bind(
            self.timing_workspace,
            revision=self.state.param.revision,
            time_basis=self.time_basis.param.value,
        )
        provenance = pn.bind(
            self.provenance_workspace,
            revision=self.state.param.revision,
            time_basis=self.time_basis.param.value,
        )
        diagnostics = pn.bind(
            self.diagnostics_workspace,
            revision=self.state.param.revision,
        )
        metrics = pn.bind(self.overview_metrics, revision=self.state.param.revision)
        tabs = pn.Tabs(
            ("Geographic field", self.geography_workspace()),
            ("Signals", signals),
            ("Phase-space diagnostics", diagnostics),
            ("Timing", timing),
            ("Provenance", provenance),
            ("Publication preview", pn.Column(self.preview, self.export_status)),
            dynamic=True,
            sizing_mode="stretch_width",
        )
        right_sidebar = pn.Column(
            "## Current artifact",
            pn.bind(self.artifact_context, revision=self.state.param.revision),
            "## Interpretation rule",
            pn.pane.Alert(
                (
                    "Computed results are evidence. The dashboard does not convert "
                    "them into a narrative conclusion."
                ),
                alert_type="warning",
            ),
            width=330,
        )
        return pn.template.FastListTemplate(
            site="The Missing Interior",
            title="Distributed Analysis Console — Phase 3A",
            theme="dark",
            theme_toggle=True,
            accent_base_color=CALIBRATED,
            header_background=BACKGROUND,
            main_layout=None,
            main_max_width="1600px",
            sidebar=[sidebar],
            right_sidebar=[right_sidebar],
            main=[
                metrics,
                tabs,
            ],
            raw_css=[
                f"body {{ background: {BACKGROUND}; color: {TEXT}; }}",
                ".bk-root { font-family: Inter, Segoe UI, sans-serif; }",
            ],
        )

    def artifact_context(self, revision: int):
        del revision
        return pn.pane.Markdown(
            "\n".join(
                [
                    f"**{self.artifact.title}**",
                    f"Environment: `{self.artifact.environment}`",
                    f"Position: `{self.artifact.position_id}`",
                    f"Institution: `{self.artifact.institution_id}`",
                    f"Method: `{self.artifact.method.method_id} {self.artifact.method.version}`",
                    f"Dataset: `{self.artifact.data_sha256[:16]}…`",
                    f"State: `{self.artifact.state_head_hash[:16]}…`",
                ]
            )
        )


def _metric(label: str, value: str, detail: str):
    return pn.Card(
        pn.pane.Markdown(f"**{label}**\n\n# {value}\n\n{detail}"),
        width=250,
        height=145,
        styles={"background": PANEL, "border": "1px solid #38444a"},
        hide_header=True,
    )


def build_app() -> pn.template.FastListTemplate:
    artifact_value = os.environ.get("MI_DASHBOARD_ARTIFACT", str(DEFAULT_ARTIFACT))
    return ResearchDashboard(Path(artifact_value)).template()
