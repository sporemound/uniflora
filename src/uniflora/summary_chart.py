from __future__ import annotations

"""
SVG/PNG state-chart renderer for The Missing Interior.

Drop-in destination:
    src/uniflora/summary_chart.py

The renderer consumes only a captured SummarySnapshot. It never rereads the
repository, performs network requests, or mutates game state. The latest
persisted exterior-weather payload is rendered as a temporary operational
layer over the canonical settlement state.
"""

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime
from html import escape
import json
import re
import textwrap
import xml.etree.ElementTree as ET
from typing import Any, Iterable, Mapping

import resvg_py


SVG_WIDTH = 1400
SVG_MIN_HEIGHT = 1120
PNG_SCALE = 2

_PREPARATION_ACTIVITIES = {
    "orientation",
    "coordination",
    "calculation",
}

_SYSTEM_LABELS: tuple[tuple[str, str], ...] = (
    ("condensation_veil_multiplier", "Condensation Veil"),
    ("solar_distillation_multiplier", "Solar Still Courts"),
    ("cistern_retention_multiplier", "Thermal Cistern Retention"),
    ("capillary_transfer_multiplier", "Capillary Galleries"),
    ("wind_tower_multiplier", "Wind-Tower Response"),
    ("thermal_storage_multiplier", "Thermal Storage"),
    ("water_purity_multiplier", "Water Purification"),
    ("evaporation_burden_multiplier", "Evaporation Burden"),
)


@dataclass(frozen=True, slots=True)
class SummarySnapshot:
    environment: str
    session_json: str
    definition_json: str
    public_resource_lines: tuple[str, ...]
    position: int
    cycle: int
    phase: str
    activity: str | None

    @classmethod
    def capture(
        cls,
        *,
        environment: str,
        session_state: Mapping[str, Any],
        definition: Mapping[str, Any],
        public_resource_lines: tuple[str, ...] = (),
    ) -> "SummarySnapshot":
        state = json.loads(
            json.dumps(
                session_state,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        definition_copy = json.loads(
            json.dumps(
                definition,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        position = int(state.get("current_position", 0))
        data = state.get("data", {})
        cycle_data = data.get("cycle", {}) if isinstance(data, dict) else {}
        cycle = int(cycle_data.get("index", 1))
        phase, activity = _public_cycle_phase(cycle_data)

        return cls(
            environment=str(environment),
            session_json=json.dumps(
                state,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
            definition_json=json.dumps(
                definition_copy,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
            public_resource_lines=tuple(
                str(line) for line in public_resource_lines
            ),
            position=position,
            cycle=cycle,
            phase=phase,
            activity=activity,
        )

    def session_state(self) -> dict[str, Any]:
        return json.loads(self.session_json)

    def definition(self) -> dict[str, Any]:
        return json.loads(self.definition_json)


@dataclass(frozen=True, slots=True)
class ParticipationSummary:
    primary: int
    minimum: int
    observations: int
    remaining: int


@dataclass(frozen=True, slots=True)
class ResourceSummary:
    name: str
    current: float | None
    threshold: float | None
    headroom: float | None
    conditional: bool
    status: str
    requirement: str | None
    detail: str


@dataclass(frozen=True, slots=True)
class CounterSummary:
    name: str
    target: str | None
    value: float
    direction: str = "neutral"


@dataclass(frozen=True, slots=True)
class WeatherMeasurement:
    label: str
    value: str


@dataclass(frozen=True, slots=True)
class WeatherSystemSummary:
    key: str
    name: str
    multiplier: float
    percent_change: float
    status: str
    base_value: float | None = None
    effective_value: float | None = None
    unit: str | None = None


@dataclass(frozen=True, slots=True)
class WeatherSummary:
    station: str
    scope: str
    phase: str
    phase_lore: str | None
    observed_at: str
    local_observed_at: str | None
    expires_at: str | None
    measurements: tuple[WeatherMeasurement, ...]
    systems: tuple[WeatherSystemSummary, ...]
    conditions: tuple[str, ...]
    triggers: tuple[str, ...]
    exterior_pressure_score: float | None


@dataclass(frozen=True, slots=True)
class NormalizedSummaryChart:
    environment: str
    position: int
    position_title: str
    cycle: int
    phase: str
    activity: str | None
    participation: ParticipationSummary
    inherited: tuple[str, ...]
    conditions: tuple[str, ...]
    requirements: tuple[str, ...]
    actions: tuple[str, ...]
    resources: tuple[ResourceSummary, ...]
    counters: tuple[CounterSummary, ...]
    weather: WeatherSummary | None
    state_version: int


@dataclass(frozen=True, slots=True)
class RenderedSummaryChart:
    svg: str
    png_bytes: bytes
    filename: str
    alt_text: str


def normalize_chart_state(
    snapshot: SummarySnapshot,
) -> NormalizedSummaryChart:
    state = snapshot.session_state()
    definition = snapshot.definition()
    data = state.get("data", {})
    if not isinstance(data, dict):
        data = {}

    cycle = data.get("cycle", {})
    if not isinstance(cycle, dict):
        cycle = {}

    primary_contributors = cycle.get("primary_contributors", {})
    primary = (
        len(primary_contributors)
        if isinstance(primary_contributors, dict)
        else 0
    )
    minimum = int(cycle.get("primary_minimum", 3))
    observations = int(cycle.get("observation_count", 0))
    participation = ParticipationSummary(
        primary=primary,
        minimum=minimum,
        observations=observations,
        remaining=max(0, minimum - primary),
    )

    inherited_text = str(
        data.get("prior_position_summary")
        or data.get("inherited_summary")
        or "No inherited settlement summary has been recorded."
    )
    inherited = tuple(
        part.strip()
        for part in re.split(r"(?<=[.;])\s+", inherited_text)
        if part.strip()
    )

    conditions = _public_conditions(data)
    resources = tuple(
        _parse_resource_line(line)
        for line in snapshot.public_resource_lines
        if str(line).strip()
    )
    counters = _normalize_counters(data.get("counters", {}))

    requirements: list[str] = []
    if participation.remaining:
        requirements.append(
            f"{participation.remaining} more primary contribution"
            + ("" if participation.remaining == 1 else "s")
            + " required."
        )
    else:
        requirements.append("Primary contributor minimum is met.")

    for resource in resources:
        if resource.conditional and resource.requirement:
            requirements.append(f"{resource.name}: {resource.requirement}")

    reactions = data.get("triggered_reactions", [])
    if isinstance(reactions, list):
        active_reactions = [
            item
            for item in reactions
            if isinstance(item, dict) and not item.get("consumed", False)
        ]
        if active_reactions:
            requirements.append(
                f"{len(active_reactions)} public reaction"
                + ("" if len(active_reactions) == 1 else "s")
                + " remain available."
            )

    allowed_actions = definition.get("allowed_actions", [])
    if not isinstance(allowed_actions, list):
        allowed_actions = []
    actions = tuple(
        str(item).replace("_", " ").replace("-", " ").title()
        for item in allowed_actions
    )
    if not actions:
        actions = (
            "Use /interior next for currently valid actions.",
        )

    weather = _normalize_weather(data.get("exterior_weather"), resources)

    return NormalizedSummaryChart(
        environment=snapshot.environment,
        position=snapshot.position,
        position_title=str(
            definition.get("title", f"Position {snapshot.position}")
        ),
        cycle=snapshot.cycle,
        phase=snapshot.phase,
        activity=snapshot.activity,
        participation=participation,
        inherited=inherited,
        conditions=conditions,
        requirements=tuple(requirements),
        actions=actions,
        resources=resources,
        counters=counters,
        weather=weather,
        state_version=int(state.get("version", 0)),
    )


def attachment_filename(snapshot: SummarySnapshot) -> str:
    return (
        f"missing-interior-position-{snapshot.position}"
        f"-cycle-{snapshot.cycle}.png"
    )


def render_summary_svg(chart: NormalizedSummaryChart) -> str:
    margin = 42
    gap = 24
    content_width = SVG_WIDTH - margin * 2
    column_width = (content_width - gap) / 2

    header_top = 32.0
    header_bottom = 142.0

    participation_lines = (
        f"Primary contributors: {chart.participation.primary}/"
        f"{chart.participation.minimum}",
        f"Observational contributions: {chart.participation.observations}",
        (
            "Contributor gate met."
            if chart.participation.remaining == 0
            else f"Remaining primary accounts: "
            f"{chart.participation.remaining}"
        ),
    )
    participation_top = header_bottom + 18
    participation_height = _section_height(
        participation_lines,
        chars=110,
        minimum=142,
    )
    participation_bottom = participation_top + participation_height

    inherited_lines = chart.inherited or (
        "No inherited conditions are currently public.",
    )
    inherited_top = participation_bottom + gap
    inherited_height = _section_height(
        inherited_lines,
        chars=118,
        minimum=130,
    )
    inherited_bottom = inherited_top + inherited_height

    left_y = inherited_bottom + gap
    right_y = inherited_bottom + gap

    condition_lines = chart.conditions or (
        "No confirmed current-position condition is public yet.",
    )
    conditions_height = _section_height(
        condition_lines,
        chars=56,
        minimum=170,
    )
    conditions_top = left_y
    conditions_bottom = conditions_top + conditions_height
    left_y = conditions_bottom + gap

    resource_lines = _resource_display_lines(chart.resources)
    resources_height = _section_height(
        resource_lines,
        chars=56,
        minimum=210,
    )
    resources_top = left_y
    resources_bottom = resources_top + resources_height
    left_y = resources_bottom

    requirements_height = _section_height(
        chart.requirements,
        chars=56,
        minimum=170,
    )
    requirements_top = right_y
    requirements_bottom = requirements_top + requirements_height
    right_y = requirements_bottom + gap

    actions_height = _section_height(
        chart.actions,
        chars=56,
        minimum=150,
    )
    actions_top = right_y
    actions_bottom = actions_top + actions_height
    right_y = actions_bottom + gap

    counter_lines = _counter_display_lines(chart.counters)
    counters_height = _section_height(
        counter_lines,
        chars=56,
        minimum=190,
    )
    counters_top = right_y
    counters_bottom = counters_top + counters_height
    right_y = counters_bottom

    main_bottom = max(left_y, right_y)
    weather_top = main_bottom + gap
    weather_height = (
        _weather_section_height(chart.weather)
        if chart.weather is not None
        else 0
    )
    weather_bottom = weather_top + weather_height

    footer_top = (
        weather_bottom + 26
        if chart.weather is not None
        else main_bottom + 26
    )
    svg_height = max(SVG_MIN_HEIGHT, int(footer_top + 72))

    title = (
        f"The Missing Interior state chart — Position {chart.position}, "
        f"Cycle {chart.cycle}"
    )
    description = (
        f"Public settlement state for {chart.position_title}. "
        f"{chart.participation.primary} of "
        f"{chart.participation.minimum} primary contributors recorded."
    )
    if chart.weather is not None:
        description += (
            f" Exterior weather phase {chart.weather.phase}; "
            f"{len(chart.weather.systems)} temporary system multipliers shown."
        )

    parts: list[str] = [
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" '
            f'width="{SVG_WIDTH}" height="{svg_height}" '
            f'viewBox="0 0 {SVG_WIDTH} {svg_height}" '
            f'role="img" aria-labelledby="chart-title chart-desc">'
        ),
        f"<title id=\"chart-title\">{escape(title)}</title>",
        f"<desc id=\"chart-desc\">{escape(description)}</desc>",
        _style_block(),
        (
            f'<rect class="background" x="0" y="0" '
            f'width="{SVG_WIDTH}" height="{svg_height}" rx="0"/>'
        ),
        _header_svg(chart, margin, header_top, content_width),
        _section_svg(
            "participation",
            "Participation",
            margin,
            participation_top,
            content_width,
            participation_height,
            participation_lines,
            chars=110,
            accent=True,
        ),
        _section_svg(
            "inherited",
            "Inherited Settlement State",
            margin,
            inherited_top,
            content_width,
            inherited_height,
            inherited_lines,
            chars=118,
        ),
        _section_svg(
            "conditions",
            "Confirmed Conditions",
            margin,
            conditions_top,
            column_width,
            conditions_height,
            condition_lines,
            chars=56,
        ),
        _section_svg(
            "resources",
            "Resources & Operating Margins",
            margin,
            resources_top,
            column_width,
            resources_height,
            resource_lines,
            chars=56,
        ),
        _section_svg(
            "requirements",
            "Current Requirements",
            margin + column_width + gap,
            requirements_top,
            column_width,
            requirements_height,
            chart.requirements,
            chars=56,
        ),
        _section_svg(
            "actions",
            "Available Action Families",
            margin + column_width + gap,
            actions_top,
            column_width,
            actions_height,
            chart.actions,
            chars=56,
        ),
        _section_svg(
            "counters",
            "Counters & Pressure",
            margin + column_width + gap,
            counters_top,
            column_width,
            counters_height,
            counter_lines,
            chars=56,
        ),
    ]

    if chart.weather is not None:
        parts.append(
            _weather_section_svg(
                chart.weather,
                margin,
                weather_top,
                content_width,
                weather_height,
            )
        )

    parts.extend(
        (
            (
                f'<text class="footer" x="{margin}" y="{footer_top}">'
                f'Snapshot version {chart.state_version} · '
                f'{escape(chart.environment)} environment · '
                f'weather is temporary and does not overwrite canonical values'
                f"</text>"
            ),
            "</svg>",
        )
    )
    return "\n".join(parts)


def convert_svg_to_png(svg: str) -> bytes:
    root = ET.fromstring(svg)
    width = int(float(root.attrib["width"]))
    height = int(float(root.attrib["height"]))
    return resvg_py.svg_to_bytes(
        svg_string=svg,
        width=width * PNG_SCALE,
        height=height * PNG_SCALE,
    )


def render_summary_chart(
    snapshot: SummarySnapshot,
) -> RenderedSummaryChart:
    chart = normalize_chart_state(snapshot)
    svg = render_summary_svg(chart)
    png = convert_svg_to_png(svg)
    weather_phrase = ""
    if chart.weather is not None:
        weather_phrase = (
            f" Exterior phase {chart.weather.phase}; temporary multipliers "
            f"for {len(chart.weather.systems)} water systems are included."
        )
    return RenderedSummaryChart(
        svg=svg,
        png_bytes=png,
        filename=attachment_filename(snapshot),
        alt_text=(
            f"State chart for Position {chart.position}, Cycle {chart.cycle}, "
            f"{chart.phase}. {chart.participation.primary} of "
            f"{chart.participation.minimum} primary contributors recorded."
            f"{weather_phrase}"
        ),
    )


def _public_cycle_phase(
    cycle: Mapping[str, Any],
) -> tuple[str, str | None]:
    raw = str(cycle.get("phase", "orientation"))
    label = raw.replace("_", " ").title()
    if raw in _PREPARATION_ACTIVITIES:
        return "Preparation", label
    return label, None


def _public_conditions(data: Mapping[str, Any]) -> tuple[str, ...]:
    records: list[Any] = []
    for key in (
        "confirmed_facts",
        "prior_confirmed_facts",
    ):
        value = data.get(key, [])
        if isinstance(value, list):
            records.extend(value)

    lines: list[str] = []
    for record in records:
        if isinstance(record, dict):
            text = (
                record.get("public_text")
                or record.get("text")
                or record.get("summary")
            )
        else:
            text = record
        if text:
            normalized = " ".join(str(text).split())
            if normalized not in lines:
                lines.append(normalized)
    return tuple(lines)


def _parse_resource_line(line: str) -> ResourceSummary:
    normalized = " ".join(str(line).split())
    name, separator, detail = normalized.partition(":")
    if not separator:
        name = "Resource"
        detail = normalized

    current = _first_number(
        detail,
        (
            r"current-cycle output\s+(-?\d+(?:\.\d+)?)",
            r"current\s+(-?\d+(?:\.\d+)?)",
            r"output\s+(-?\d+(?:\.\d+)?)",
        ),
    )
    threshold = _first_number(
        detail,
        (
            r"coherence floor\s+(-?\d+(?:\.\d+)?)",
            r"required reserve\s+(-?\d+(?:\.\d+)?)",
            r"required minimum\s+(-?\d+(?:\.\d+)?)",
            r"threshold\s+(-?\d+(?:\.\d+)?)",
        ),
    )
    headroom = _first_number(
        detail,
        (
            r"donation headroom\s+(-?\d+(?:\.\d+)?)",
            r"transferable headroom\s+(-?\d+(?:\.\d+)?)",
            r"headroom\s+(-?\d+(?:\.\d+)?)",
        ),
    )

    lower = detail.casefold()
    conditional = any(
        phrase in lower
        for phrase in (
            "maintenance required",
            "required before use",
            "if maintained",
            "action required",
        )
    )
    if conditional:
        status = "action required"
        requirement = "maintenance required before using its output"
    elif "maintenance satisfied" in lower:
        status = "available"
        requirement = None
    elif "deficit" in lower:
        status = "deficit"
        requirement = None
    else:
        status = "recorded"
        requirement = None

    return ResourceSummary(
        name=name.strip(),
        current=current,
        threshold=threshold,
        headroom=headroom,
        conditional=conditional,
        status=status,
        requirement=requirement,
        detail=detail.strip(),
    )


def _first_number(
    text: str,
    patterns: Iterable[str],
) -> float | None:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return float(match.group(1))
    return None


def _normalize_counters(value: Any) -> tuple[CounterSummary, ...]:
    if not isinstance(value, dict):
        return ()
    counters: list[CounterSummary] = []
    for name, raw in value.items():
        if isinstance(raw, dict):
            for target, amount in raw.items():
                number = _coerce_float(amount)
                if number is not None:
                    counters.append(
                        CounterSummary(
                            name=str(name),
                            target=str(target),
                            value=number,
                        )
                    )
        else:
            number = _coerce_float(raw)
            if number is not None:
                counters.append(
                    CounterSummary(
                        name=str(name),
                        target=None,
                        value=number,
                    )
                )
    return tuple(counters)


def _normalize_weather(
    value: Any,
    resources: tuple[ResourceSummary, ...],
) -> WeatherSummary | None:
    if not isinstance(value, dict):
        return None

    readings = value.get("readings", {})
    if not isinstance(readings, dict):
        readings = {}

    observed_at = str(
        value.get("observed_at")
        or value.get("local_observed_at")
        or "unavailable"
    )
    local_observed = value.get("local_observed_at")
    expires = (
        value.get("window_expires_at")
        or value.get("local_window_expires_at")
    )

    measurements: list[WeatherMeasurement] = [
        WeatherMeasurement(
            "Observed",
            _format_timestamp(observed_at),
        )
    ]
    for label, key, unit, precision in (
        ("Temperature", "temperature_c", "°C", 1),
        ("Pressure", "pressure_mbar", "mbar", 1),
        ("Humidity", "humidity_percent", "%", 0),
        ("Wind direction", "wind_direction_degrees", "°", 0),
        ("Wind speed", "wind_speed_mps", "m/s", 1),
        ("Wind gust", "wind_gust_mps", "m/s", 1),
        ("Rain / 1h", "rain_1h_mm", "mm", 1),
        ("Rain / 24h", "rain_24h_mm", "mm", 1),
        (
            "Rain since midnight",
            "rain_since_midnight_mm",
            "mm",
            1,
        ),
        ("Luminosity", "luminosity_wm2", "W/m²", 1),
    ):
        number = _coerce_float(readings.get(key))
        if number is not None:
            measurements.append(
                WeatherMeasurement(
                    label,
                    f"{number:.{precision}f} {unit}",
                )
            )

    influence = (
        value.get("water_system_multipliers")
        or value.get("continuous_influence")
        or value.get("modifiers")
        or {}
    )
    if not isinstance(influence, dict):
        influence = {}

    resource_by_name = {item.name.casefold(): item for item in resources}
    veil_resource = resource_by_name.get("condensation veil")

    systems: list[WeatherSystemSummary] = []
    for key, name in _SYSTEM_LABELS:
        multiplier = _coerce_float(influence.get(key))
        if multiplier is None:
            continue
        base_value: float | None = None
        effective_value: float | None = None
        unit: str | None = None
        if (
            key == "condensation_veil_multiplier"
            and veil_resource is not None
            and veil_resource.current is not None
        ):
            base_value = veil_resource.current
            effective_value = base_value * multiplier
            unit = "water"

        systems.append(
            WeatherSystemSummary(
                key=key,
                name=name,
                multiplier=multiplier,
                percent_change=(multiplier - 1.0) * 100.0,
                status=_system_status(
                    multiplier,
                    burden=(
                        key == "evaporation_burden_multiplier"
                    ),
                ),
                base_value=base_value,
                effective_value=effective_value,
                unit=unit,
            )
        )

    conditions_raw = value.get("conditions", [])
    conditions = (
        tuple(str(item) for item in conditions_raw)
        if isinstance(conditions_raw, list)
        else ()
    )
    triggers_raw = value.get("eligible_triggers", [])
    triggers: list[str] = []
    if isinstance(triggers_raw, list):
        for item in triggers_raw:
            if isinstance(item, dict):
                trigger = item.get("kind")
            else:
                trigger = item
            if trigger:
                triggers.append(str(trigger))

    pressure = _coerce_float(
        influence.get("exterior_pressure_score")
    )
    if pressure is None:
        signals = value.get("signal_scores", {})
        if isinstance(signals, dict):
            pressure = _coerce_float(
                signals.get("exterior_pressure")
            )

    return WeatherSummary(
        station=str(value.get("station", "unknown")),
        scope=str(value.get("station_scope", "regional_relay")),
        phase=str(value.get("phase", "unclassified")),
        phase_lore=(
            str(value["phase_lore"])
            if value.get("phase_lore")
            else None
        ),
        observed_at=_format_timestamp(observed_at),
        local_observed_at=(
            _format_timestamp(str(local_observed))
            if local_observed
            else None
        ),
        expires_at=(
            _format_timestamp(str(expires))
            if expires
            else None
        ),
        measurements=tuple(measurements),
        systems=tuple(systems),
        conditions=conditions,
        triggers=tuple(triggers),
        exterior_pressure_score=pressure,
    )


def _format_multiplier_percent(multiplier: float) -> str:
    """Format a multiplier as a half-up rounded percent change."""

    change = (
        Decimal(str(multiplier)) - Decimal("1")
    ) * Decimal("100")
    rounded = change.quantize(
        Decimal("0.1"),
        rounding=ROUND_HALF_UP,
    )
    return f"{rounded:+.1f}"


def _system_status(multiplier: float, *, burden: bool) -> str:
    if burden:
        if multiplier < 0.95:
            return "reduced"
        if multiplier <= 1.05:
            return "stable"
        if multiplier <= 1.15:
            return "elevated"
        return "severe"
    if multiplier < 0.72:
        return "dormant"
    if multiplier < 0.95:
        return "strained"
    if multiplier <= 1.03:
        return "balanced"
    if multiplier <= 1.15:
        return "favored"
    return "surge"


def _format_timestamp(value: str) -> str:
    text = value.strip()
    if not text:
        return "unavailable"
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text
    if parsed.tzinfo is None:
        return parsed.strftime("%Y-%m-%d %H:%M:%S")
    return parsed.strftime("%Y-%m-%d %H:%M:%S %Z").strip()


def _coerce_float(value: Any) -> float | None:
    try:
        if value is None or isinstance(value, bool):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _resource_display_lines(
    resources: tuple[ResourceSummary, ...],
) -> tuple[str, ...]:
    if not resources:
        return ("No public resource margin has been established.",)
    lines: list[str] = []
    for item in resources:
        line = f"{item.name}: {item.detail}"
        if item.conditional and item.requirement:
            line += f" · {item.status}"
        lines.append(line)
    return tuple(lines)


def _counter_display_lines(
    counters: tuple[CounterSummary, ...],
) -> tuple[str, ...]:
    if not counters:
        return ("No active public counter is recorded.",)
    lines: list[str] = []
    for counter in counters:
        name = counter.name.replace("_", " ").title()
        target = (
            " · "
            + counter.target.replace("_", " ").replace("-", " ").title()
            if counter.target
            else ""
        )
        lines.append(f"{name}{target}: {counter.value:g}")
    return tuple(lines)


def _weather_section_height(
    weather: WeatherSummary | None,
) -> float:
    if weather is None:
        return 0
    measurement_rows = max(3, len(weather.measurements))
    system_rows = max(1, (len(weather.systems) + 1) // 2)
    metadata_rows = 3
    return max(
        430.0,
        118.0
        + measurement_rows * 29.0
        + system_rows * 58.0
        + metadata_rows * 24.0,
    )


def _section_height(
    lines: Iterable[str],
    *,
    chars: int,
    minimum: float,
) -> float:
    content_height = 0.0

    for line in lines:
        wrapped = _wrap(str(line), chars)
        content_height += len(wrapped) * 26.0
        content_height += 5.0

    return max(minimum, 74.0 + content_height)


def _wrap(text: str, chars: int) -> tuple[str, ...]:
    normalized = " ".join(str(text).split())
    return tuple(
        textwrap.wrap(
            normalized,
            width=max(12, chars),
            break_long_words=False,
            break_on_hyphens=False,
        )
        or [""]
    )


def _style_block() -> str:
    return """
<style>
  .background { fill: #111713; }
  .panel { fill: #18211b; stroke: #45604d; stroke-width: 1.5; }
  .panel-accent { fill: #1c2b21; stroke: #7fa287; stroke-width: 1.8; }
  .weather-panel { fill: #17231f; stroke: #89ad98; stroke-width: 2; }
  .title { fill: #edf3ed; font: 700 34px "Segoe UI", sans-serif; }
  .subtitle { fill: #b9c8bc; font: 18px "Segoe UI", sans-serif; }
  .section-title { fill: #dfe9e1; font: 700 20px "Segoe UI", sans-serif; }
  .body { fill: #cbd7cd; font: 16px "Segoe UI", sans-serif; }
  .body-strong { fill: #f1f5f1; font: 700 17px "Segoe UI", sans-serif; }
  .muted { fill: #9eafa2; font: 14px "Segoe UI", sans-serif; }
  .positive { fill: #b9deb9; font: 700 16px "Segoe UI", sans-serif; }
  .negative { fill: #e4c2a5; font: 700 16px "Segoe UI", sans-serif; }
  .neutral { fill: #cbd7cd; font: 700 16px "Segoe UI", sans-serif; }
  .divider { stroke: #3d5344; stroke-width: 1; }
  .bar-track { fill: #26342b; }
  .bar-fill { fill: #7fa287; }
  .footer { fill: #849589; font: 13px "Segoe UI", sans-serif; }
</style>
""".strip()


def _header_svg(
    chart: NormalizedSummaryChart,
    x: float,
    y: float,
    width: float,
) -> str:
    activity = (
        f" · latest activity {chart.activity}"
        if chart.activity is not None
        else ""
    )
    return "\n".join(
        (
            (
                f'<text class="title" x="{x}" y="{y + 36}">'
                f'{escape(chart.position_title)}</text>'
            ),
            (
                f'<text class="subtitle" x="{x}" y="{y + 72}">'
                f'Position {chart.position} · Cycle {chart.cycle} · '
                f'{escape(chart.phase + activity)}</text>'
            ),
            (
                f'<line class="divider" x1="{x}" y1="{y + 96}" '
                f'x2="{x + width}" y2="{y + 96}"/>'
            ),
        )
    )


def _section_svg(
    name: str,
    title: str,
    x: float,
    y: float,
    width: float,
    height: float,
    lines: Iterable[str],
    *,
    chars: int,
    accent: bool = False,
) -> str:
    panel_class = "panel-accent" if accent else "panel"
    parts = [
        (
            f'<g data-section="{escape(name)}" data-top="{y:.1f}" '
            f'data-bottom="{y + height:.1f}">'
        ),
        (
            f'<rect class="{panel_class}" x="{x:.1f}" y="{y:.1f}" '
            f'width="{width:.1f}" height="{height:.1f}" rx="16"/>'
        ),
        (
            f'<text class="section-title" x="{x + 22:.1f}" '
            f'y="{y + 34:.1f}">{escape(title)}</text>'
        ),
    ]
    cursor = y + 67
    for line in lines:
        wrapped = _wrap(str(line), chars)
        for index, segment in enumerate(wrapped):
            prefix = "• " if index == 0 else "  "
            parts.append(
                (
                    f'<text class="body" x="{x + 24:.1f}" '
                    f'y="{cursor:.1f}">{escape(prefix + segment)}</text>'
                )
            )
            cursor += 26
        cursor += 5
    parts.append("</g>")
    return "\n".join(parts)


def _weather_section_svg(
    weather: WeatherSummary,
    x: float,
    y: float,
    width: float,
    height: float,
) -> str:
    half = (width - 32) / 2
    left_x = x + 24
    right_x = x + half + 40
    parts = [
        (
            f'<g data-section="weather" data-top="{y:.1f}" '
            f'data-bottom="{y + height:.1f}">'
        ),
        (
            f'<rect class="weather-panel" x="{x:.1f}" y="{y:.1f}" '
            f'width="{width:.1f}" height="{height:.1f}" rx="18"/>'
        ),
        (
            f'<text class="section-title" x="{x + 22:.1f}" '
            f'y="{y + 35:.1f}">Exterior Weather &amp; Water Systems</text>'
        ),
        (
            f'<text class="body-strong" x="{x + 22:.1f}" '
            f'y="{y + 68:.1f}">{escape(weather.phase.title())} phase'
            f' · station {escape(weather.station)}'
            f' · {escape(weather.scope.replace("_", " "))}</text>'
        ),
    ]

    if weather.phase_lore:
        parts.append(
            (
                f'<text class="muted" x="{x + 22:.1f}" '
                f'y="{y + 94:.1f}">{escape(weather.phase_lore)}</text>'
            )
        )

    cursor = y + 128
    parts.append(
        (
            f'<text class="section-title" x="{left_x:.1f}" '
            f'y="{cursor:.1f}">Measurements</text>'
        )
    )
    cursor += 30
    for measurement in weather.measurements:
        parts.append(
            (
                f'<text class="body" x="{left_x:.1f}" '
                f'y="{cursor:.1f}">{escape(measurement.label)}: '
                f'{escape(measurement.value)}</text>'
            )
        )
        cursor += 27

    weather_meta_y = cursor + 10
    if weather.expires_at:
        parts.append(
            (
                f'<text class="muted" x="{left_x:.1f}" '
                f'y="{weather_meta_y:.1f}">Window through: '
                f'{escape(weather.expires_at)}</text>'
            )
        )
        weather_meta_y += 23
    if weather.conditions:
        parts.append(
            (
                f'<text class="muted" x="{left_x:.1f}" '
                f'y="{weather_meta_y:.1f}">Threshold state: '
                f'{escape(", ".join(weather.conditions))}</text>'
            )
        )
        weather_meta_y += 23
    if weather.triggers:
        parts.append(
            (
                f'<text class="muted" x="{left_x:.1f}" '
                f'y="{weather_meta_y:.1f}">Eligible: '
                f'{escape(", ".join(weather.triggers))}</text>'
            )
        )

    system_title_y = y + 128
    parts.append(
        (
            f'<text class="section-title" x="{right_x:.1f}" '
            f'y="{system_title_y:.1f}">Location Multipliers</text>'
        )
    )

    systems = list(weather.systems)
    row_y = system_title_y + 36
    system_col_width = (half - 18) / 2
    for index, system in enumerate(systems):
        col = index % 2
        row = index // 2
        sx = right_x + col * (system_col_width + 18)
        sy = row_y + row * 86
        cls = (
            "positive"
            if system.percent_change > 3
            else "negative"
            if system.percent_change < -3
            else "neutral"
        )
        parts.append(
            (
                f'<text class="body-strong" x="{sx:.1f}" '
                f'y="{sy:.1f}">{escape(system.name)}</text>'
            )
        )
        parts.append(
            (
                f'<text class="{cls}" x="{sx:.1f}" '
                f'y="{sy + 25:.1f}">'
                f'{_format_multiplier_percent(system.multiplier)}% '
                f'· ×{system.multiplier:.4f} · '
                f'{escape(system.status)}</text>'
            )
        )
        if (
            system.base_value is not None
            and system.effective_value is not None
        ):
            parts.append(
                (
                    f'<text class="muted" x="{sx:.1f}" '
                    f'y="{sy + 48:.1f}">base '
                    f'{system.base_value:g} → effective '
                    f'{system.effective_value:.2f} '
                    f'{escape(system.unit or "")}</text>'
                )
            )
        else:
            bar_width = min(
                system_col_width - 8,
                max(0.0, system.multiplier / 1.6)
                * (system_col_width - 8),
            )
            parts.append(
                (
                    f'<rect class="bar-track" x="{sx:.1f}" '
                    f'y="{sy + 38:.1f}" width="{system_col_width - 8:.1f}" '
                    f'height="9" rx="4.5"/>'
                )
            )
            parts.append(
                (
                    f'<rect class="bar-fill" x="{sx:.1f}" '
                    f'y="{sy + 38:.1f}" width="{bar_width:.1f}" '
                    f'height="9" rx="4.5"/>'
                )
            )

    if weather.exterior_pressure_score is not None:
        parts.append(
            (
                f'<text class="muted" x="{right_x:.1f}" '
                f'y="{y + height - 25:.1f}">Exterior pressure index: '
                f'{weather.exterior_pressure_score * 100:.1f}%</text>'
            )
        )
    parts.append("</g>")
    return "\n".join(parts)


__all__ = [
    "PNG_SCALE",
    "SVG_MIN_HEIGHT",
    "SVG_WIDTH",
    "CounterSummary",
    "NormalizedSummaryChart",
    "ParticipationSummary",
    "RenderedSummaryChart",
    "ResourceSummary",
    "SummarySnapshot",
    "WeatherMeasurement",
    "WeatherSummary",
    "WeatherSystemSummary",
    "attachment_filename",
    "convert_svg_to_png",
    "normalize_chart_state",
    "render_summary_chart",
    "render_summary_svg",
]
