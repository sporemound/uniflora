from __future__ import annotations

from pathlib import Path

import panel as pn

from missing_interior_dashboard.analysis import compute_phase_space
from missing_interior_dashboard.dashboard import FACILITY_SITES, ResearchDashboard
from missing_interior_dashboard.views import (
    PHASE_DENSITY_RASTERIZE_THRESHOLD,
    build_facility_map_view,
    build_phase_density_view,
    phase_density_uses_rasterization,
)

ROOT = Path(__file__).resolve().parents[1]


def test_dashboard_constructs_with_verified_fixture() -> None:
    dashboard = ResearchDashboard(ROOT / "examples" / "sr03-artifact.json")
    template = dashboard.template()

    assert isinstance(template, pn.template.FastListTemplate)
    assert dashboard.artifact.artifact_id == "artifact-phase3-sr03"
    assert len(dashboard.frame) == 4096


def test_phase_diagnostic_preserves_hover_until_density_requires_rasterization() -> None:
    dashboard = ResearchDashboard(ROOT / "examples" / "sr03-artifact.json")
    phase = compute_phase_space(dashboard.frame, dashboard.artifact.sample_rate_hz)

    assert len(phase) < PHASE_DENSITY_RASTERIZE_THRESHOLD
    assert phase_density_uses_rasterization(phase) is False
    assert phase_density_uses_rasterization(phase, threshold=1) is True
    assert build_phase_density_view(phase) is not None


def test_facility_map_uses_projected_tiles_and_wgs84_sites() -> None:
    view = build_facility_map_view(FACILITY_SITES)

    assert len(FACILITY_SITES) == 6
    assert view.get(0).group == "WMTS"
    assert view.get(1).group == "Points"
