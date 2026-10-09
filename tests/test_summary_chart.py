from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
_SRC_ROOT = _ROOT / "src"

for path in (_ROOT, _SRC_ROOT):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

import asyncio
import copy
import struct
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

_root = Path(__file__).resolve().parents[1]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import pytest

from uniflora.content.loader import PuzzleRegistry
from uniflora.engine.actions import SummarizeAction
from uniflora.engine.core import EngineOutcome
from uniflora.game_service import GameService
from uniflora.narration import FallbackNarrator
from uniflora.runtime import Environment
from uniflora.storage.repository import SessionRef
from uniflora.summary_chart import (
    PNG_SCALE,
    SVG_MIN_HEIGHT,
    SVG_WIDTH,
    RenderedSummaryChart,
    SummarySnapshot,
    attachment_filename,
    convert_svg_to_png,
    normalize_chart_state,
    render_summary_chart,
    render_summary_svg,
)
from uniflora.summary_fixture import build_fixture_snapshot

def _recapture(
    snapshot: SummarySnapshot,
    *,
    data_update: dict[str, Any] | None = None,
    resource_lines: tuple[str, ...] | None = None,
    version: int | None = None,
) -> SummarySnapshot:
    state = snapshot.session_state()
    if data_update:
        state["data"].update(copy.deepcopy(data_update))
    if version is not None:
        state["version"] = version
    return SummarySnapshot.capture(
        environment=snapshot.environment,
        session_state=state,
        definition=snapshot.definition(),
        public_resource_lines=(
            snapshot.public_resource_lines if resource_lines is None else resource_lines
        ),
    )


def _png_dimensions(png: bytes) -> tuple[int, int]:
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    assert png[12:16] == b"IHDR"
    return struct.unpack(">II", png[16:24])


def test_generated_svg_is_valid_standalone_xml_with_accessible_text() -> None:
    svg = render_summary_svg(normalize_chart_state(build_fixture_snapshot()))

    root = ET.fromstring(svg)

    assert root.tag == "{http://www.w3.org/2000/svg}svg"
    assert root.find("{http://www.w3.org/2000/svg}title") is not None
    assert root.find("{http://www.w3.org/2000/svg}desc") is not None
    assert root.find("{http://www.w3.org/2000/svg}rect").attrib["class"] == "background"


def test_generated_png_has_signature_and_two_x_dimensions() -> None:
    svg = render_summary_svg(normalize_chart_state(build_fixture_snapshot()))

    png = convert_svg_to_png(svg)
    width, height = _png_dimensions(png)

    root = ET.fromstring(svg)
    assert width == SVG_WIDTH * PNG_SCALE
    assert height == int(root.attrib["height"]) * PNG_SCALE
    assert len(png) > 1000


def test_unicode_state_text_remains_valid_and_renderable() -> None:
    snapshot = _recapture(
        build_fixture_snapshot(),
        data_update={
            "prior_position_summary": (
                "Workers’ archive — confirmed; water ≤ 7, fungal relation ↔ civic memory."
            )
        },
    )

    svg = render_summary_svg(normalize_chart_state(snapshot))
    png = convert_svg_to_png(svg)

    ET.fromstring(svg)
    assert "Workers’ archive — confirmed" in svg
    assert _png_dimensions(png)[0] == SVG_WIDTH * PNG_SCALE


def test_layout_sections_do_not_overlap_within_either_column() -> None:
    root = ET.fromstring(
        render_summary_svg(normalize_chart_state(build_fixture_snapshot()))
    )
    namespace = {"svg": "http://www.w3.org/2000/svg"}
    sections = {
        group.attrib["data-section"]: (
            float(group.attrib["data-top"]),
            float(group.attrib["data-bottom"]),
        )
        for group in root.findall("svg:g", namespace)
        if "data-section" in group.attrib
    }

    for sequence in (
        ("participation", "inherited", "conditions", "resources"),
        ("participation", "inherited", "requirements", "actions", "counters"),
    ):
        present = [sections[name] for name in sequence if name in sections]
        assert all(
            first[1] <= second[0]
            for first, second in zip(present, present[1:], strict=False)
        )


def test_observations_do_not_fill_primary_participation_segments() -> None:
    snapshot = build_fixture_snapshot()
    chart = normalize_chart_state(snapshot)

    assert chart.participation.primary == 2
    assert chart.participation.observations == 3
    assert chart.participation.remaining == 1


def test_resource_headroom_and_conditional_output_are_normalized_explicitly() -> None:
    chart = normalize_chart_state(build_fixture_snapshot())
    resources = {item.name: item for item in chart.resources}

    archive = resources["Lower Archive"]
    assert archive.current == 7
    assert archive.threshold == 5
    assert archive.headroom == 2

    veil = resources["Condensation Veil"]
    assert veil.current == 9
    assert veil.conditional
    assert veil.status == "action required"
    assert "before using its output" in str(veil.requirement)
    assert veil.status != "available"


def test_unknown_counter_direction_remains_neutral() -> None:
    chart = normalize_chart_state(build_fixture_snapshot())

    assert chart.counters
    assert all(counter.direction == "neutral" for counter in chart.counters)


def test_state_change_produces_changed_svg_and_png() -> None:
    original = build_fixture_snapshot()
    changed_data = copy.deepcopy(original.session_state()["data"])
    changed_data["counters"]["containment"] = 8
    changed = _recapture(original, data_update=changed_data, version=2)

    original_render = render_summary_chart(original)
    changed_render = render_summary_chart(changed)

    assert original_render.svg != changed_render.svg
    assert original_render.png_bytes != changed_render.png_bytes


def test_rendering_uses_no_temporary_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    monkeypatch.setenv("TEMP", str(tmp_path))
    monkeypatch.setenv("TMP", str(tmp_path))

    render_summary_chart(build_fixture_snapshot())

    assert list(tmp_path.iterdir()) == []


def test_attachment_filename_uses_snapshot_position_and_cycle() -> None:
    assert (
        attachment_filename(build_fixture_snapshot())
        == "missing-interior-position-1-cycle-1.png"
    )


def test_dense_summary_expands_or_displays_explicit_overflow_note() -> None:
    snapshot = build_fixture_snapshot()
    facts = [
        {
            "public_text": (
                f"Confirmed condition {index}: the maintained civic system retains a long "
                "public operating rule without hiding its threshold or provenance."
            ),
            "classification": "confirmed",
        }
        for index in range(30)
    ]
    dense = _recapture(snapshot, data_update={"confirmed_facts": facts})

    svg = render_summary_svg(normalize_chart_state(dense))
    root = ET.fromstring(svg)

    assert int(root.attrib["height"]) > SVG_MIN_HEIGHT or (
        "Full details remain in the accompanying text summary." in svg
    )


class _SnapshotRepository:
    def __init__(self) -> None:
        self.state_calls = 0

    async def resolve_participant(self, ref: SessionRef, discord_user_id: int) -> str:
        del ref
        return f"discord:{discord_user_id}"

    async def runtime_control(self, ref: SessionRef) -> dict[str, Any]:
        del ref
        return {"feature_flags": {}}

    async def state(self, ref: SessionRef) -> dict[str, Any]:
        del ref
        self.state_calls += 1
        raise AssertionError("a committed summary snapshot must not be reread")


class _SnapshotEngine:
    def __init__(self, base_state: dict[str, Any]) -> None:
        self.base_state = base_state

    async def process(
        self,
        ref: SessionRef,
        *,
        participant_id: str,
        action: SummarizeAction,
        idempotency_key: str,
    ) -> EngineOutcome:
        del ref, action, idempotency_key
        state = copy.deepcopy(self.base_state)
        user_id = int(participant_id.rsplit(":", 1)[-1])
        state["version"] = user_id
        return EngineOutcome(
            True,
            "accepted",
            event_id=f"event-{user_id}",
            event_type="summary.recorded",
            public_data={"public_text": f"Summary from committed version {user_id}."},
            state_after=state,
        )


def _summary_game() -> tuple[GameService, _SnapshotRepository]:
    registry = PuzzleRegistry.load_packaged()
    definition = registry.get(1)
    state = {
        "mode": "running",
        "current_position": 1,
        "response_profile": "surface_noise",
        "data": definition.initial_state(),
        "modified_by_force": False,
        "version": 0,
    }
    repository = _SnapshotRepository()
    ref = SessionRef("test", Environment.TEST)
    game = GameService(
        repository,  # type: ignore[arg-type]
        {Environment.TEST: ref},
        registry,
        _SnapshotEngine(state),  # type: ignore[arg-type]
        FallbackNarrator(),
    )
    return game, repository


@pytest.mark.asyncio
async def test_successful_summary_invokes_fresh_renderer_from_committed_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    game, repository = _summary_game()
    snapshots: list[SummarySnapshot] = []

    def fake_render(snapshot: SummarySnapshot) -> RenderedSummaryChart:
        snapshots.append(snapshot)
        version = snapshot.session_state()["version"]
        return RenderedSummaryChart(
            svg=f"<svg data-version='{version}'/>",
            png_bytes=b"\x89PNG\r\n\x1a\n" + str(version).encode(),
            filename=attachment_filename(snapshot),
            alt_text="fixture alt text",
        )

    monkeypatch.setattr("uniflora.game_service.render_summary_chart", fake_render)
    action = SummarizeAction(action="summarize")

    first = await game.act(Environment.TEST, 7, action, "summary-1")
    second = await game.act(Environment.TEST, 7, action, "summary-2")

    assert len(snapshots) == 2
    assert snapshots[0] is not snapshots[1]
    assert snapshots[0].session_json == snapshots[1].session_json
    assert first.attachment is not None
    assert second.attachment is not None
    assert first.attachment is not second.attachment
    assert (
        "Current state chart generated from Position 1 · Cycle 1 · Preparation "
        "· latest activity Orientation." in first.text
    )
    assert "Recorded: A confirmed public summary was archived." in first.text
    assert "Cost: Free information action; no primary action consumed." in first.text
    assert "0/3 primary contributors" in first.text
    assert "Available next: `/interior next`" in first.text
    assert "Full public ledger: `/interior recall`" in first.text
    assert "Summary from committed version 7." not in first.text
    assert snapshots[0].session_state()["version"] == 7
    assert repository.state_calls == 0


@pytest.mark.asyncio
async def test_simultaneous_summary_renders_remain_request_local(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    game, _ = _summary_game()

    def fake_render(snapshot: SummarySnapshot) -> RenderedSummaryChart:
        version = snapshot.session_state()["version"]
        return RenderedSummaryChart(
            svg=f"<svg>{version}</svg>",
            png_bytes=b"\x89PNG\r\n\x1a\n" + str(version).encode(),
            filename=attachment_filename(snapshot),
            alt_text=f"version {version}",
        )

    monkeypatch.setattr("uniflora.game_service.render_summary_chart", fake_render)
    action = SummarizeAction(action="summarize")

    first, second = await asyncio.gather(
        game.act(Environment.TEST, 7, action, "summary-7"),
        game.act(Environment.TEST, 9, action, "summary-9"),
    )

    assert first.attachment is not None
    assert second.attachment is not None
    assert first.attachment.image_bytes.endswith(b"7")
    assert second.attachment.image_bytes.endswith(b"9")
    assert first.attachment.image_bytes != second.attachment.image_bytes


@pytest.mark.asyncio
async def test_image_failure_keeps_successful_text_summary(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    game, repository = _summary_game()

    def broken_render(snapshot: SummarySnapshot) -> RenderedSummaryChart:
        del snapshot
        raise RuntimeError("renderer fixture failure")

    monkeypatch.setattr("uniflora.game_service.render_summary_chart", broken_render)

    result = await game.act(
        Environment.TEST,
        7,
        SummarizeAction(action="summarize"),
        "summary-failure",
    )

    assert result.accepted
    assert "Summary from committed version 7." in result.text
    assert "The visual state chart could not be generated for this summary." in result.text
    assert result.attachment is None
    assert result.phase_footer is not None
    assert repository.state_calls == 0
    assert "summary state chart rendering failed" in caplog.text



def test_weather_snapshot_normalizes_measurements_and_location_multipliers() -> None:
    chart = normalize_chart_state(build_fixture_snapshot())

    assert chart.weather is not None
    assert chart.weather.station == "HECA"
    assert chart.weather.phase == "night"

    measurements = {
        item.label: item.value
        for item in chart.weather.measurements
    }
    assert measurements["Temperature"] == "30.6 °C"
    assert measurements["Pressure"] == "1009.0 mbar"
    assert measurements["Humidity"] == "52 %"
    assert measurements["Wind direction"] == "310 °"
    assert measurements["Wind speed"] == "4.9 m/s"

    systems = {
        item.name: item
        for item in chart.weather.systems
    }
    veil = systems["Condensation Veil"]
    assert veil.multiplier == pytest.approx(1.1430)
    assert veil.base_value == 9
    assert veil.effective_value == pytest.approx(10.287)
    assert veil.status == "favored"

    solar = systems["Solar Still Courts"]
    assert solar.multiplier == pytest.approx(0.7285)
    assert solar.status == "strained"


def test_weather_measurements_and_multipliers_are_rendered_in_svg_and_png() -> None:
    snapshot = build_fixture_snapshot()
    svg = render_summary_svg(normalize_chart_state(snapshot))
    png = convert_svg_to_png(svg)

    assert "Exterior Weather &amp; Water Systems" in svg
    assert "30.6 °C" in svg
    assert "1009.0 mbar" in svg
    assert "52 %" in svg
    assert "310 °" in svg
    assert "4.9 m/s" in svg
    assert "Condensation Veil" in svg
    assert "+14.3%" in svg
    assert "effective 10.29 water" in svg
    assert "Solar Still Courts" in svg
    assert "-27.2%" in svg
    assert _png_dimensions(png)[0] == SVG_WIDTH * PNG_SCALE
