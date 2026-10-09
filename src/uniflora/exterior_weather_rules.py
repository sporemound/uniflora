from __future__ import annotations

"""
Diurnal weather-to-gameplay rules for The Missing Interior.

Drop-in destination:
    src/uniflora/exterior_weather_rules.py

Design principles:
- Every usable observation changes system multipliers.
- A new observation replaces the active influence; it never stacks.
- The station's Egyptian local time selects an operating phase.
- HECA is treated as a regional relay, so effects are restrained.
- Thresholds create named conditions and event eligibility.
- Hysteresis prevents hazards from flickering near boundaries.
- No randomness, network calls, Discord calls, storage, or mutation occurs here.
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime, time, timedelta, timezone
from enum import StrEnum
from hashlib import sha256
from math import log
from typing import Any, Mapping, Protocol
from zoneinfo import ZoneInfo


class ExteriorPhase(StrEnum):
    NIGHT = "night"
    DAWN = "dawn"
    DAY = "day"
    DUSK = "dusk"


class ExteriorCondition(StrEnum):
    NOMINAL = "nominal"
    WARM = "warm"
    EXTREME_HEAT = "extreme_heat"
    DRY_AIR = "dry_air"
    COOL_HUMID = "cool_humid"
    STRONG_WIND = "strong_wind"
    PRESSURE_LOW = "pressure_low"
    PRESSURE_FALLING = "pressure_falling"
    PRESSURE_RISING = "pressure_rising"
    CONDENSATION_FAVORED = "condensation_favored"


class StationScope(StrEnum):
    REGIONAL_RELAY = "regional_relay"
    LOCAL_PROXY = "local_proxy"


class ExteriorTriggerKind(StrEnum):
    HEAT_LOAD = "heat_load"
    DRY_VEIL = "dry_veil"
    EXTERIOR_FRONT = "exterior_front"
    WIND_EXPOSURE = "wind_exposure"
    CONDENSATION_WINDOW = "condensation_window"
    SOLAR_STILL_WINDOW = "solar_still_window"
    THERMAL_RELEASE_WINDOW = "thermal_release_window"
    EVAPORATION_STRESS = "evaporation_stress"


class SystemBand(StrEnum):
    DORMANT = "dormant"
    STRAINED = "strained"
    BALANCED = "balanced"
    FAVORED = "favored"
    SURGE = "surge"


@dataclass(frozen=True, slots=True)
class PhaseProfile:
    condensation_veil: float
    solar_distillation: float
    cistern_retention: float
    capillary_transfer: float
    wind_tower: float
    thermal_storage: float
    water_purity: float
    evaporation_burden: float
    lore: str


def _default_phase_profiles() -> dict[ExteriorPhase, PhaseProfile]:
    return {
        ExteriorPhase.NIGHT: PhaseProfile(
            condensation_veil=1.30,
            solar_distillation=0.20,
            cistern_retention=1.12,
            capillary_transfer=1.06,
            wind_tower=0.92,
            thermal_storage=1.08,
            water_purity=0.98,
            evaporation_burden=0.72,
            lore="cold-sky collection and protected storage",
        ),
        ExteriorPhase.DAWN: PhaseProfile(
            condensation_veil=1.18,
            solar_distillation=0.62,
            cistern_retention=1.08,
            capillary_transfer=1.15,
            wind_tower=1.00,
            thermal_storage=1.04,
            water_purity=1.03,
            evaporation_burden=0.84,
            lore="dew transfer and capillary distribution",
        ),
        ExteriorPhase.DAY: PhaseProfile(
            condensation_veil=0.62,
            solar_distillation=1.30,
            cistern_retention=0.88,
            capillary_transfer=0.92,
            wind_tower=1.05,
            thermal_storage=1.18,
            water_purity=1.12,
            evaporation_burden=1.30,
            lore="solar distillation, purification, and thermal charging",
        ),
        ExteriorPhase.DUSK: PhaseProfile(
            condensation_veil=0.95,
            solar_distillation=0.45,
            cistern_retention=1.02,
            capillary_transfer=1.00,
            wind_tower=1.12,
            thermal_storage=1.15,
            water_purity=1.00,
            evaporation_burden=0.95,
            lore="thermal release, balancing, and wind routing",
        ),
    }


@dataclass(frozen=True, slots=True)
class WeatherRuleConfig:
    timezone_name: str = "Africa/Cairo"

    dawn_start_hour: int = 5
    day_start_hour: int = 8
    dusk_start_hour: int = 17
    night_start_hour: int = 20
    maximum_window_hours: float = 2.0

    reference_temperature_c: float = 24.0
    heat_span_c: float = 16.0
    standard_pressure_mbar: float = 1013.25
    pressure_span_mbar: float = 20.0
    wind_span_mps: float = 15.0
    condensation_neutral_spread_c: float = 12.0

    regional_scope_weight: float = 0.35
    local_scope_weight: float = 1.0
    smoothing_new_weight: float = 0.35
    phase_transition_new_weight: float = 0.65

    minimum_multiplier: float = 0.55
    maximum_multiplier: float = 1.60

    warm_enter_c: float = 32.0
    warm_exit_c: float = 30.0
    extreme_heat_enter_c: float = 38.0
    extreme_heat_exit_c: float = 36.0
    dry_air_enter_temperature_c: float = 35.0
    dry_air_enter_humidity_percent: float = 25.0
    dry_air_exit_temperature_c: float = 33.0
    dry_air_exit_humidity_percent: float = 30.0
    cool_humid_enter_temperature_c: float = 26.0
    cool_humid_enter_humidity_percent: float = 65.0
    cool_humid_exit_temperature_c: float = 28.0
    cool_humid_exit_humidity_percent: float = 60.0
    strong_wind_enter_mps: float = 10.0
    strong_wind_exit_mps: float = 8.5
    low_pressure_enter_mbar: float = 1003.0
    low_pressure_exit_mbar: float = 1006.0
    pressure_change_trigger_mbar: float = 5.0

    phase_profiles: Mapping[ExteriorPhase, PhaseProfile] = field(
        default_factory=_default_phase_profiles
    )


@dataclass(frozen=True, slots=True)
class ExteriorWeatherObservation:
    station: str
    observed_at: datetime
    scope: StationScope = StationScope.REGIONAL_RELAY

    temperature_c: float | None = None
    pressure_mbar: float | None = None
    humidity_percent: float | None = None
    wind_direction_degrees: float | None = None
    wind_speed_mps: float | None = None
    wind_gust_mps: float | None = None
    rain_1h_mm: float | None = None
    rain_24h_mm: float | None = None
    rain_since_midnight_mm: float | None = None
    luminosity_wm2: float | None = None
    source: str = "aprs.fi"

    def __post_init__(self) -> None:
        station = self.station.strip().upper()
        if not station:
            raise ValueError("station cannot be empty")
        object.__setattr__(self, "station", station)

        observed_at = self.observed_at
        if observed_at.tzinfo is None:
            observed_at = observed_at.replace(tzinfo=timezone.utc)
        else:
            observed_at = observed_at.astimezone(timezone.utc)
        object.__setattr__(self, "observed_at", observed_at)

        _validate_range(
            "humidity_percent",
            self.humidity_percent,
            0.0,
            100.0,
        )
        _validate_range(
            "wind_direction_degrees",
            self.wind_direction_degrees,
            0.0,
            360.0,
        )

    @property
    def observation_key(self) -> str:
        identity = (
            f"{self.source}|{self.station}|"
            f"{self.observed_at.isoformat(timespec='seconds')}"
        )
        return sha256(identity.encode("utf-8")).hexdigest()[:24]


@dataclass(frozen=True, slots=True)
class WeatherDelta:
    elapsed_seconds: float | None = None
    temperature_c: float | None = None
    pressure_mbar: float | None = None
    humidity_percent: float | None = None
    wind_speed_mps: float | None = None


@dataclass(frozen=True, slots=True)
class WeatherSignalScores:
    heat: float = 0.0
    humidity: float = 0.0
    dryness: float = 0.0
    condensation: float = 0.0
    wind: float = 0.0
    pressure_load: float = 0.0
    exterior_pressure: float = 0.0
    dew_point_c: float | None = None
    dew_point_spread_c: float | None = None


@dataclass(frozen=True, slots=True)
class WaterSystemInfluence:
    condensation_veil_multiplier: float = 1.0
    solar_distillation_multiplier: float = 1.0
    cistern_retention_multiplier: float = 1.0
    capillary_transfer_multiplier: float = 1.0
    wind_tower_multiplier: float = 1.0
    thermal_storage_multiplier: float = 1.0
    water_purity_multiplier: float = 1.0
    evaporation_burden_multiplier: float = 1.0
    exterior_pressure_score: float = 0.0

    def is_neutral(self) -> bool:
        values = asdict(self)
        pressure = values.pop("exterior_pressure_score")
        return (
            all(abs(value - 1.0) < 1e-9 for value in values.values())
            and abs(pressure) < 1e-9
        )


ExteriorModifiers = WaterSystemInfluence
ContinuousWeatherInfluence = WaterSystemInfluence


@dataclass(frozen=True, slots=True)
class WeatherWindow:
    phase: ExteriorPhase
    phase_lore: str
    observed_at_utc: datetime
    observed_at_local: datetime
    expires_at_utc: datetime
    expires_at_local: datetime

    def is_active(self, at: datetime | None = None) -> bool:
        moment = at or datetime.now(timezone.utc)
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        return moment.astimezone(timezone.utc) < self.expires_at_utc


@dataclass(frozen=True, slots=True)
class ExteriorTriggerCandidate:
    kind: ExteriorTriggerKind
    severity: int
    reason: str
    requires_player_action: bool = True
    once_per_cycle: bool = True


@dataclass(frozen=True, slots=True)
class ExteriorWeatherOutcome:
    current: ExteriorWeatherObservation
    previous: ExteriorWeatherObservation | None
    delta: WeatherDelta
    signal_scores: WeatherSignalScores
    window: WeatherWindow
    conditions: frozenset[ExteriorCondition]
    modifiers: WaterSystemInfluence
    triggers: tuple[ExteriorTriggerCandidate, ...]
    duplicate: bool = False
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def influence(self) -> WaterSystemInfluence:
        return self.modifiers

    def to_event_payload(self, *, environment: str) -> dict[str, Any]:
        influence = asdict(self.modifiers)
        return {
            "type": "exterior_weather_observed",
            "environment": environment,
            "deduplication_key": self.current.observation_key,
            "station": self.current.station,
            "station_scope": self.current.scope.value,
            "source": self.current.source,
            "observed_at": self.current.observed_at.isoformat(),
            "phase": self.window.phase.value,
            "phase_lore": self.window.phase_lore,
            "local_observed_at": self.window.observed_at_local.isoformat(),
            "window_expires_at": self.window.expires_at_utc.isoformat(),
            "local_window_expires_at": (
                self.window.expires_at_local.isoformat()
            ),
            "readings": {
                "temperature_c": self.current.temperature_c,
                "pressure_mbar": self.current.pressure_mbar,
                "humidity_percent": self.current.humidity_percent,
                "wind_direction_degrees": (
                    self.current.wind_direction_degrees
                ),
                "wind_speed_mps": self.current.wind_speed_mps,
                "wind_gust_mps": self.current.wind_gust_mps,
                "rain_1h_mm": self.current.rain_1h_mm,
                "rain_24h_mm": self.current.rain_24h_mm,
                "rain_since_midnight_mm": (
                    self.current.rain_since_midnight_mm
                ),
                "luminosity_wm2": self.current.luminosity_wm2,
            },
            "delta": asdict(self.delta),
            "signal_scores": asdict(self.signal_scores),
            "conditions": sorted(
                condition.value for condition in self.conditions
            ),
            "water_system_multipliers": influence,
            "continuous_influence": influence,
            "modifiers": influence,
            "eligible_triggers": [
                {
                    "kind": trigger.kind.value,
                    "severity": trigger.severity,
                    "reason": trigger.reason,
                    "requires_player_action": (
                        trigger.requires_player_action
                    ),
                    "once_per_cycle": trigger.once_per_cycle,
                }
                for trigger in self.triggers
            ],
            "replacement_semantics": (
                "replace active weather influence; never stack"
            ),
            "duplicate": self.duplicate,
            "notes": list(self.notes),
        }


class AprsFiWeatherRecordLike(Protocol):
    name: str
    reported_at: datetime
    temperature_c: float | None
    pressure_mbar: float | None
    humidity_percent: float | None
    wind_direction_degrees: float | None
    wind_speed_mps: float | None
    wind_gust_mps: float | None
    rain_1h_mm: float | None
    rain_24h_mm: float | None
    rain_since_midnight_mm: float | None
    luminosity_wm2: float | None


def observation_from_aprsfi(
    record: AprsFiWeatherRecordLike,
    *,
    scope: StationScope = StationScope.REGIONAL_RELAY,
) -> ExteriorWeatherObservation:
    return ExteriorWeatherObservation(
        station=record.name,
        observed_at=record.reported_at,
        scope=scope,
        temperature_c=record.temperature_c,
        pressure_mbar=record.pressure_mbar,
        humidity_percent=record.humidity_percent,
        wind_direction_degrees=record.wind_direction_degrees,
        wind_speed_mps=record.wind_speed_mps,
        wind_gust_mps=record.wind_gust_mps,
        rain_1h_mm=record.rain_1h_mm,
        rain_24h_mm=record.rain_24h_mm,
        rain_since_midnight_mm=record.rain_since_midnight_mm,
        luminosity_wm2=record.luminosity_wm2,
    )


def classify_phase(
    observed_at: datetime,
    *,
    config: WeatherRuleConfig = WeatherRuleConfig(),
) -> ExteriorPhase:
    local = _to_local(observed_at, config)
    hour = local.hour
    if config.dawn_start_hour <= hour < config.day_start_hour:
        return ExteriorPhase.DAWN
    if config.day_start_hour <= hour < config.dusk_start_hour:
        return ExteriorPhase.DAY
    if config.dusk_start_hour <= hour < config.night_start_hour:
        return ExteriorPhase.DUSK
    return ExteriorPhase.NIGHT


def calculate_weather_window(
    observation: ExteriorWeatherObservation,
    *,
    config: WeatherRuleConfig = WeatherRuleConfig(),
) -> WeatherWindow:
    local_observed = _to_local(observation.observed_at, config)
    phase = classify_phase(observation.observed_at, config=config)
    boundary = _next_phase_boundary(local_observed, phase, config)
    duration_expiry = local_observed + timedelta(
        hours=config.maximum_window_hours
    )
    local_expiry = min(boundary, duration_expiry)
    profile = config.phase_profiles[phase]

    return WeatherWindow(
        phase=phase,
        phase_lore=profile.lore,
        observed_at_utc=observation.observed_at,
        observed_at_local=local_observed,
        expires_at_utc=local_expiry.astimezone(timezone.utc),
        expires_at_local=local_expiry,
    )


def calculate_delta(
    current: ExteriorWeatherObservation,
    previous: ExteriorWeatherObservation | None,
) -> WeatherDelta:
    if previous is None:
        return WeatherDelta()

    return WeatherDelta(
        elapsed_seconds=(
            current.observed_at - previous.observed_at
        ).total_seconds(),
        temperature_c=_subtract_optional(
            current.temperature_c,
            previous.temperature_c,
        ),
        pressure_mbar=_subtract_optional(
            current.pressure_mbar,
            previous.pressure_mbar,
        ),
        humidity_percent=_subtract_optional(
            current.humidity_percent,
            previous.humidity_percent,
        ),
        wind_speed_mps=_subtract_optional(
            current.wind_speed_mps,
            previous.wind_speed_mps,
        ),
    )


def calculate_signal_scores(
    observation: ExteriorWeatherObservation,
    *,
    config: WeatherRuleConfig = WeatherRuleConfig(),
) -> WeatherSignalScores:
    temperature = observation.temperature_c
    humidity_percent = observation.humidity_percent
    pressure = observation.pressure_mbar
    wind = observation.wind_speed_mps

    humidity = (
        _clamp(humidity_percent / 100.0, 0.0, 1.0)
        if humidity_percent is not None
        else 0.0
    )
    dryness = 1.0 - humidity

    heat = (
        _clamp(
            (temperature - config.reference_temperature_c)
            / config.heat_span_c,
            0.0,
            1.0,
        )
        if temperature is not None
        else 0.0
    )
    wind_score = (
        _clamp(wind / config.wind_span_mps, 0.0, 1.0)
        if wind is not None
        else 0.0
    )
    pressure_load = (
        _clamp(
            (config.standard_pressure_mbar - pressure)
            / config.pressure_span_mbar,
            0.0,
            1.0,
        )
        if pressure is not None
        else 0.0
    )

    dew_point = _dew_point_c(temperature, humidity_percent)
    dew_spread = (
        temperature - dew_point
        if temperature is not None and dew_point is not None
        else None
    )
    condensation = (
        _clamp(
            (
                config.condensation_neutral_spread_c
                - dew_spread
            )
            / config.condensation_neutral_spread_c,
            -1.0,
            1.0,
        )
        if dew_spread is not None
        else 0.0
    )

    scope_weight = _scope_weight(observation.scope, config)
    exterior_pressure = _clamp(
        scope_weight
        * (
            0.45 * heat
            + 0.35 * wind_score
            + 0.20 * pressure_load
        ),
        0.0,
        1.0,
    )

    return WeatherSignalScores(
        heat=round(heat, 6),
        humidity=round(humidity, 6),
        dryness=round(dryness, 6),
        condensation=round(condensation, 6),
        wind=round(wind_score, 6),
        pressure_load=round(pressure_load, 6),
        exterior_pressure=round(exterior_pressure, 6),
        dew_point_c=(
            round(dew_point, 3) if dew_point is not None else None
        ),
        dew_point_spread_c=(
            round(dew_spread, 3) if dew_spread is not None else None
        ),
    )


def classify_conditions(
    current: ExteriorWeatherObservation,
    delta: WeatherDelta,
    *,
    previous_conditions: frozenset[ExteriorCondition] = frozenset(),
    config: WeatherRuleConfig = WeatherRuleConfig(),
) -> frozenset[ExteriorCondition]:
    conditions: set[ExteriorCondition] = set()
    temperature = current.temperature_c
    humidity = current.humidity_percent
    pressure = current.pressure_mbar
    wind = current.wind_speed_mps

    extreme = _entered_or_held_high(
        temperature,
        enter=config.extreme_heat_enter_c,
        exit=config.extreme_heat_exit_c,
        previously_active=(
            ExteriorCondition.EXTREME_HEAT in previous_conditions
        ),
    )
    warm = _entered_or_held_high(
        temperature,
        enter=config.warm_enter_c,
        exit=config.warm_exit_c,
        previously_active=ExteriorCondition.WARM in previous_conditions,
    )
    if extreme:
        conditions.add(ExteriorCondition.EXTREME_HEAT)
    elif warm:
        conditions.add(ExteriorCondition.WARM)

    dry_entered = (
        temperature is not None
        and humidity is not None
        and temperature >= config.dry_air_enter_temperature_c
        and humidity <= config.dry_air_enter_humidity_percent
    )
    dry_held = (
        ExteriorCondition.DRY_AIR in previous_conditions
        and temperature is not None
        and humidity is not None
        and temperature >= config.dry_air_exit_temperature_c
        and humidity <= config.dry_air_exit_humidity_percent
    )
    if dry_entered or dry_held:
        conditions.add(ExteriorCondition.DRY_AIR)

    cool_entered = (
        temperature is not None
        and humidity is not None
        and temperature <= config.cool_humid_enter_temperature_c
        and humidity >= config.cool_humid_enter_humidity_percent
    )
    cool_held = (
        ExteriorCondition.COOL_HUMID in previous_conditions
        and temperature is not None
        and humidity is not None
        and temperature <= config.cool_humid_exit_temperature_c
        and humidity >= config.cool_humid_exit_humidity_percent
    )
    if cool_entered or cool_held:
        conditions.add(ExteriorCondition.COOL_HUMID)
        conditions.add(ExteriorCondition.CONDENSATION_FAVORED)

    if _entered_or_held_high(
        wind,
        enter=config.strong_wind_enter_mps,
        exit=config.strong_wind_exit_mps,
        previously_active=(
            ExteriorCondition.STRONG_WIND in previous_conditions
        ),
    ):
        conditions.add(ExteriorCondition.STRONG_WIND)

    if _entered_or_held_low(
        pressure,
        enter=config.low_pressure_enter_mbar,
        exit=config.low_pressure_exit_mbar,
        previously_active=(
            ExteriorCondition.PRESSURE_LOW in previous_conditions
        ),
    ):
        conditions.add(ExteriorCondition.PRESSURE_LOW)

    if delta.pressure_mbar is not None:
        if delta.pressure_mbar <= -config.pressure_change_trigger_mbar:
            conditions.add(ExteriorCondition.PRESSURE_FALLING)
        elif delta.pressure_mbar >= config.pressure_change_trigger_mbar:
            conditions.add(ExteriorCondition.PRESSURE_RISING)

    if not conditions:
        conditions.add(ExteriorCondition.NOMINAL)

    return frozenset(conditions)


def calculate_water_system_influence(
    current: ExteriorWeatherObservation,
    *,
    phase: ExteriorPhase | None = None,
    signal_scores: WeatherSignalScores | None = None,
    previous_influence: WaterSystemInfluence | None = None,
    previous_phase: ExteriorPhase | None = None,
    config: WeatherRuleConfig = WeatherRuleConfig(),
) -> WaterSystemInfluence:
    selected_phase = phase or classify_phase(
        current.observed_at,
        config=config,
    )
    scores = signal_scores or calculate_signal_scores(
        current,
        config=config,
    )
    profile = config.phase_profiles[selected_phase]

    moderate_wind_capture = (
        1.0
        + 0.08 * min(scores.wind, 0.45)
        - 0.18 * max(scores.wind - 0.65, 0.0)
    )

    raw = WaterSystemInfluence(
        condensation_veil_multiplier=(
            profile.condensation_veil
            * (1.0 + 0.28 * scores.condensation)
            * (1.0 + 0.06 * scores.humidity)
            * moderate_wind_capture
        ),
        solar_distillation_multiplier=(
            profile.solar_distillation
            * (
                1.0
                + 0.20 * scores.heat
                + 0.08 * scores.dryness
            )
        ),
        cistern_retention_multiplier=(
            profile.cistern_retention
            * (
                1.0
                - 0.10 * scores.heat
                - 0.05 * scores.wind
                + 0.08 * scores.humidity
            )
        ),
        capillary_transfer_multiplier=(
            profile.capillary_transfer
            * (
                1.0
                + 0.14 * scores.humidity
                - 0.08 * scores.heat
                - 0.04 * scores.wind
            )
        ),
        wind_tower_multiplier=(
            profile.wind_tower
            * (
                1.0
                + 0.28 * scores.wind
                - 0.05 * scores.pressure_load
            )
        ),
        thermal_storage_multiplier=(
            profile.thermal_storage
            * (
                1.0
                + (
                    0.16 * scores.heat
                    if selected_phase
                    in {ExteriorPhase.DAY, ExteriorPhase.DUSK}
                    else 0.08 * (1.0 - scores.heat)
                )
            )
        ),
        water_purity_multiplier=(
            profile.water_purity
            * (
                1.0
                + (
                    0.14 * scores.heat
                    if selected_phase is ExteriorPhase.DAY
                    else 0.03 * scores.humidity
                )
            )
        ),
        evaporation_burden_multiplier=(
            profile.evaporation_burden
            * (
                1.0
                + 0.24 * scores.heat
                + 0.14 * scores.wind
                - 0.12 * scores.humidity
            )
        ),
        exterior_pressure_score=scores.exterior_pressure,
    )

    weight = _scope_weight(current.scope, config)
    scaled = WaterSystemInfluence(
        condensation_veil_multiplier=_scale_from_neutral(
            raw.condensation_veil_multiplier,
            weight,
            config,
        ),
        solar_distillation_multiplier=_scale_from_neutral(
            raw.solar_distillation_multiplier,
            weight,
            config,
        ),
        cistern_retention_multiplier=_scale_from_neutral(
            raw.cistern_retention_multiplier,
            weight,
            config,
        ),
        capillary_transfer_multiplier=_scale_from_neutral(
            raw.capillary_transfer_multiplier,
            weight,
            config,
        ),
        wind_tower_multiplier=_scale_from_neutral(
            raw.wind_tower_multiplier,
            weight,
            config,
        ),
        thermal_storage_multiplier=_scale_from_neutral(
            raw.thermal_storage_multiplier,
            weight,
            config,
        ),
        water_purity_multiplier=_scale_from_neutral(
            raw.water_purity_multiplier,
            weight,
            config,
        ),
        evaporation_burden_multiplier=_scale_from_neutral(
            raw.evaporation_burden_multiplier,
            weight,
            config,
        ),
        exterior_pressure_score=scores.exterior_pressure,
    )

    if previous_influence is None:
        return _rounded_influence(scaled)

    alpha = (
        config.phase_transition_new_weight
        if previous_phase is not None and previous_phase != selected_phase
        else config.smoothing_new_weight
    )
    alpha = _clamp(alpha, 0.0, 1.0)

    return _rounded_influence(
        WaterSystemInfluence(
            condensation_veil_multiplier=_smooth(
                previous_influence.condensation_veil_multiplier,
                scaled.condensation_veil_multiplier,
                alpha,
            ),
            solar_distillation_multiplier=_smooth(
                previous_influence.solar_distillation_multiplier,
                scaled.solar_distillation_multiplier,
                alpha,
            ),
            cistern_retention_multiplier=_smooth(
                previous_influence.cistern_retention_multiplier,
                scaled.cistern_retention_multiplier,
                alpha,
            ),
            capillary_transfer_multiplier=_smooth(
                previous_influence.capillary_transfer_multiplier,
                scaled.capillary_transfer_multiplier,
                alpha,
            ),
            wind_tower_multiplier=_smooth(
                previous_influence.wind_tower_multiplier,
                scaled.wind_tower_multiplier,
                alpha,
            ),
            thermal_storage_multiplier=_smooth(
                previous_influence.thermal_storage_multiplier,
                scaled.thermal_storage_multiplier,
                alpha,
            ),
            water_purity_multiplier=_smooth(
                previous_influence.water_purity_multiplier,
                scaled.water_purity_multiplier,
                alpha,
            ),
            evaporation_burden_multiplier=_smooth(
                previous_influence.evaporation_burden_multiplier,
                scaled.evaporation_burden_multiplier,
                alpha,
            ),
            exterior_pressure_score=_smooth(
                previous_influence.exterior_pressure_score,
                scaled.exterior_pressure_score,
                alpha,
            ),
        )
    )


calculate_modifiers = calculate_water_system_influence
calculate_continuous_influence = calculate_water_system_influence


def build_trigger_candidates(
    conditions: frozenset[ExteriorCondition],
    influence: WaterSystemInfluence,
    *,
    phase: ExteriorPhase,
    scope: StationScope,
) -> tuple[ExteriorTriggerCandidate, ...]:
    candidates: list[ExteriorTriggerCandidate] = []
    severity = 2 if scope is StationScope.LOCAL_PROXY else 1

    if ExteriorCondition.EXTREME_HEAT in conditions:
        candidates.append(
            ExteriorTriggerCandidate(
                kind=ExteriorTriggerKind.HEAT_LOAD,
                severity=severity,
                reason=(
                    "exterior heat raises water loss and storage burden"
                ),
            )
        )
    if ExteriorCondition.DRY_AIR in conditions:
        candidates.append(
            ExteriorTriggerCandidate(
                kind=ExteriorTriggerKind.DRY_VEIL,
                severity=severity,
                reason="dry air suppresses atmospheric collection",
            )
        )
    if ExteriorCondition.PRESSURE_FALLING in conditions:
        candidates.append(
            ExteriorTriggerCandidate(
                kind=ExteriorTriggerKind.EXTERIOR_FRONT,
                severity=severity,
                reason=(
                    "rapid pressure loss marks an approaching exterior front"
                ),
            )
        )
    if ExteriorCondition.STRONG_WIND in conditions:
        candidates.append(
            ExteriorTriggerCandidate(
                kind=ExteriorTriggerKind.WIND_EXPOSURE,
                severity=severity,
                reason=(
                    "strong wind increases exposed-route maintenance"
                ),
            )
        )
    if (
        phase in {ExteriorPhase.NIGHT, ExteriorPhase.DAWN}
        and influence.condensation_veil_multiplier >= 1.08
    ):
        candidates.append(
            ExteriorTriggerCandidate(
                kind=ExteriorTriggerKind.CONDENSATION_WINDOW,
                severity=1,
                reason=(
                    "the cold-sky veil has entered a favorable collection window"
                ),
                requires_player_action=False,
            )
        )
    if (
        phase is ExteriorPhase.DAY
        and influence.solar_distillation_multiplier >= 1.08
    ):
        candidates.append(
            ExteriorTriggerCandidate(
                kind=ExteriorTriggerKind.SOLAR_STILL_WINDOW,
                severity=1,
                reason=(
                    "the solar still courts have entered a favorable cycle"
                ),
                requires_player_action=False,
            )
        )
    if (
        phase is ExteriorPhase.DUSK
        and influence.thermal_storage_multiplier >= 1.08
    ):
        candidates.append(
            ExteriorTriggerCandidate(
                kind=ExteriorTriggerKind.THERMAL_RELEASE_WINDOW,
                severity=1,
                reason=(
                    "stored daytime heat can be redirected before night cooling"
                ),
                requires_player_action=False,
            )
        )
    if influence.evaporation_burden_multiplier >= 1.10:
        candidates.append(
            ExteriorTriggerCandidate(
                kind=ExteriorTriggerKind.EVAPORATION_STRESS,
                severity=severity,
                reason=(
                    "open water and channels are losing moisture faster than baseline"
                ),
            )
        )

    return tuple(candidates)


def evaluate_exterior_weather(
    *,
    current: ExteriorWeatherObservation,
    previous: ExteriorWeatherObservation | None = None,
    previous_modifiers: WaterSystemInfluence | None = None,
    previous_conditions: frozenset[ExteriorCondition] = frozenset(),
    known_observation_keys: frozenset[str] = frozenset(),
    config: WeatherRuleConfig = WeatherRuleConfig(),
) -> ExteriorWeatherOutcome:
    duplicate = current.observation_key in known_observation_keys
    delta = calculate_delta(current, previous)
    scores = calculate_signal_scores(current, config=config)
    window = calculate_weather_window(current, config=config)
    conditions = classify_conditions(
        current,
        delta,
        previous_conditions=previous_conditions,
        config=config,
    )
    previous_phase = (
        classify_phase(previous.observed_at, config=config)
        if previous is not None
        else None
    )

    influence = (
        previous_modifiers
        if duplicate and previous_modifiers is not None
        else calculate_water_system_influence(
            current,
            phase=window.phase,
            signal_scores=scores,
            previous_influence=previous_modifiers,
            previous_phase=previous_phase,
            config=config,
        )
    )

    notes: list[str] = []
    if previous is None:
        notes.append("pressure and trend baseline established")
    elif delta.elapsed_seconds is not None and delta.elapsed_seconds <= 0:
        notes.append("observation is not newer than the previous baseline")
    if duplicate:
        notes.append(
            "duplicate observation; active water-system influence unchanged"
        )

    triggers = (
        ()
        if duplicate
        else build_trigger_candidates(
            conditions,
            influence,
            phase=window.phase,
            scope=current.scope,
        )
    )

    return ExteriorWeatherOutcome(
        current=current,
        previous=previous,
        delta=delta,
        signal_scores=scores,
        window=window,
        conditions=conditions,
        modifiers=influence,
        triggers=triggers,
        duplicate=duplicate,
        notes=tuple(notes),
    )


def render_settlement_effects(outcome: ExteriorWeatherOutcome) -> str:
    influence = outcome.modifiers
    window = outcome.window

    lines = [
        "WATER SYSTEM RESPONSE",
        (
            f"• operating phase: {window.phase.value} — "
            f"{window.phase_lore}"
        ),
        (
            "• window valid until: "
            f"{window.expires_at_utc.strftime('%Y-%m-%d %H:%M:%S UTC')}"
        ),
    ]

    if outcome.duplicate:
        lines.append(
            "• observation already recorded; active multipliers unchanged"
        )

    lines.extend(
        (
            _render_output_multiplier(
                "Condensation Veil",
                influence.condensation_veil_multiplier,
            ),
            _render_output_multiplier(
                "solar still courts",
                influence.solar_distillation_multiplier,
            ),
            _render_output_multiplier(
                "thermal cistern retention",
                influence.cistern_retention_multiplier,
            ),
            _render_output_multiplier(
                "capillary galleries",
                influence.capillary_transfer_multiplier,
            ),
            _render_output_multiplier(
                "wind-tower response",
                influence.wind_tower_multiplier,
            ),
            _render_output_multiplier(
                "thermal storage",
                influence.thermal_storage_multiplier,
            ),
            _render_output_multiplier(
                "water purification",
                influence.water_purity_multiplier,
            ),
            _render_burden_multiplier(
                "evaporation burden",
                influence.evaporation_burden_multiplier,
            ),
            (
                "• exterior pressure index: "
                f"{influence.exterior_pressure_score * 100:.1f}%"
            ),
        )
    )

    threshold_names = sorted(
        condition.value for condition in outcome.conditions
    )
    lines.append("• threshold state: " + ", ".join(threshold_names))

    if outcome.triggers:
        lines.append(
            "• eligible triggers: "
            + ", ".join(
                trigger.kind.value for trigger in outcome.triggers
            )
        )
    else:
        lines.append("• no categorical trigger crossed")

    for note in outcome.notes:
        lines.append(f"• {note}")

    return "\n".join(lines)


def outcome_from_mapping(
    payload: Mapping[str, Any],
    *,
    scope: StationScope = StationScope.REGIONAL_RELAY,
    previous: ExteriorWeatherObservation | None = None,
    previous_modifiers: WaterSystemInfluence | None = None,
    previous_conditions: frozenset[ExteriorCondition] = frozenset(),
    known_observation_keys: frozenset[str] = frozenset(),
    config: WeatherRuleConfig = WeatherRuleConfig(),
) -> ExteriorWeatherOutcome:
    observed_at_raw = payload["observed_at"]
    if isinstance(observed_at_raw, datetime):
        observed_at = observed_at_raw
    elif isinstance(observed_at_raw, str):
        observed_at = datetime.fromisoformat(
            observed_at_raw.replace("Z", "+00:00")
        )
    else:
        raise TypeError(
            "observed_at must be a datetime or ISO-8601 string"
        )

    observation = ExteriorWeatherObservation(
        station=str(payload["station"]),
        observed_at=observed_at,
        scope=scope,
        temperature_c=_optional_float(payload.get("temperature_c")),
        pressure_mbar=_optional_float(payload.get("pressure_mbar")),
        humidity_percent=_optional_float(
            payload.get("humidity_percent")
        ),
        wind_direction_degrees=_optional_float(
            payload.get("wind_direction_degrees")
        ),
        wind_speed_mps=_optional_float(payload.get("wind_speed_mps")),
        wind_gust_mps=_optional_float(payload.get("wind_gust_mps")),
        rain_1h_mm=_optional_float(payload.get("rain_1h_mm")),
        rain_24h_mm=_optional_float(payload.get("rain_24h_mm")),
        rain_since_midnight_mm=_optional_float(
            payload.get("rain_since_midnight_mm")
        ),
        luminosity_wm2=_optional_float(
            payload.get("luminosity_wm2")
        ),
        source=str(payload.get("source", "external")),
    )

    return evaluate_exterior_weather(
        current=observation,
        previous=previous,
        previous_modifiers=previous_modifiers,
        previous_conditions=previous_conditions,
        known_observation_keys=known_observation_keys,
        config=config,
    )


def system_band(multiplier: float) -> SystemBand:
    if multiplier < 0.72:
        return SystemBand.DORMANT
    if multiplier < 0.95:
        return SystemBand.STRAINED
    if multiplier <= 1.03:
        return SystemBand.BALANCED
    if multiplier <= 1.15:
        return SystemBand.FAVORED
    return SystemBand.SURGE


def _render_output_multiplier(label: str, multiplier: float) -> str:
    change = (multiplier - 1.0) * 100.0
    return (
        f"• {label}: {change:+.1f}% "
        f"(×{multiplier:.4f}) — {system_band(multiplier).value}"
    )


def _render_burden_multiplier(label: str, multiplier: float) -> str:
    change = (multiplier - 1.0) * 100.0
    if multiplier < 0.95:
        status = "reduced"
    elif multiplier <= 1.05:
        status = "stable"
    elif multiplier <= 1.15:
        status = "elevated"
    else:
        status = "severe"
    return (
        f"• {label}: {change:+.1f}% "
        f"(×{multiplier:.4f}) — {status}"
    )


def _to_local(
    moment: datetime,
    config: WeatherRuleConfig,
) -> datetime:
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(ZoneInfo(config.timezone_name))


def _next_phase_boundary(
    local: datetime,
    phase: ExteriorPhase,
    config: WeatherRuleConfig,
) -> datetime:
    if phase is ExteriorPhase.NIGHT:
        if local.hour < config.dawn_start_hour:
            boundary_date = local.date()
        else:
            boundary_date = local.date() + timedelta(days=1)
        boundary_hour = config.dawn_start_hour
    elif phase is ExteriorPhase.DAWN:
        boundary_date = local.date()
        boundary_hour = config.day_start_hour
    elif phase is ExteriorPhase.DAY:
        boundary_date = local.date()
        boundary_hour = config.dusk_start_hour
    else:
        boundary_date = local.date()
        boundary_hour = config.night_start_hour

    return datetime.combine(
        boundary_date,
        time(hour=boundary_hour),
        tzinfo=local.tzinfo,
    )


def _dew_point_c(
    temperature_c: float | None,
    humidity_percent: float | None,
) -> float | None:
    if (
        temperature_c is None
        or humidity_percent is None
        or humidity_percent <= 0.0
    ):
        return None

    a = 17.625
    b = 243.04
    gamma = (
        log(humidity_percent / 100.0)
        + (a * temperature_c) / (b + temperature_c)
    )
    return (b * gamma) / (a - gamma)


def _scope_weight(
    scope: StationScope,
    config: WeatherRuleConfig,
) -> float:
    return (
        config.local_scope_weight
        if scope is StationScope.LOCAL_PROXY
        else config.regional_scope_weight
    )


def _scale_from_neutral(
    raw: float,
    scope_weight: float,
    config: WeatherRuleConfig,
) -> float:
    scaled = 1.0 + scope_weight * (raw - 1.0)
    return _clamp(
        scaled,
        config.minimum_multiplier,
        config.maximum_multiplier,
    )


def _entered_or_held_high(
    value: float | None,
    *,
    enter: float,
    exit: float,
    previously_active: bool,
) -> bool:
    if value is None:
        return False
    return value >= (exit if previously_active else enter)


def _entered_or_held_low(
    value: float | None,
    *,
    enter: float,
    exit: float,
    previously_active: bool,
) -> bool:
    if value is None:
        return False
    return value <= (exit if previously_active else enter)


def _rounded_influence(
    value: WaterSystemInfluence,
) -> WaterSystemInfluence:
    return WaterSystemInfluence(
        condensation_veil_multiplier=round(
            value.condensation_veil_multiplier,
            6,
        ),
        solar_distillation_multiplier=round(
            value.solar_distillation_multiplier,
            6,
        ),
        cistern_retention_multiplier=round(
            value.cistern_retention_multiplier,
            6,
        ),
        capillary_transfer_multiplier=round(
            value.capillary_transfer_multiplier,
            6,
        ),
        wind_tower_multiplier=round(
            value.wind_tower_multiplier,
            6,
        ),
        thermal_storage_multiplier=round(
            value.thermal_storage_multiplier,
            6,
        ),
        water_purity_multiplier=round(
            value.water_purity_multiplier,
            6,
        ),
        evaporation_burden_multiplier=round(
            value.evaporation_burden_multiplier,
            6,
        ),
        exterior_pressure_score=round(
            value.exterior_pressure_score,
            6,
        ),
    )


def _smooth(previous: float, current: float, alpha: float) -> float:
    return previous * (1.0 - alpha) + current * alpha


def _optional_float(value: Any) -> float | None:
    return None if value is None else float(value)


def _subtract_optional(
    current: float | None,
    previous: float | None,
) -> float | None:
    if current is None or previous is None:
        return None
    return round(current - previous, 3)


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _validate_range(
    name: str,
    value: float | None,
    lower: float,
    upper: float,
) -> None:
    if value is not None and not lower <= value <= upper:
        raise ValueError(
            f"{name} must be between {lower} and {upper}"
        )


__all__ = [
    "ContinuousWeatherInfluence",
    "ExteriorCondition",
    "ExteriorModifiers",
    "ExteriorPhase",
    "ExteriorTriggerCandidate",
    "ExteriorTriggerKind",
    "ExteriorWeatherObservation",
    "ExteriorWeatherOutcome",
    "PhaseProfile",
    "StationScope",
    "SystemBand",
    "WaterSystemInfluence",
    "WeatherDelta",
    "WeatherRuleConfig",
    "WeatherSignalScores",
    "WeatherWindow",
    "build_trigger_candidates",
    "calculate_continuous_influence",
    "calculate_delta",
    "calculate_modifiers",
    "calculate_signal_scores",
    "calculate_water_system_influence",
    "calculate_weather_window",
    "classify_conditions",
    "classify_phase",
    "evaluate_exterior_weather",
    "observation_from_aprsfi",
    "outcome_from_mapping",
    "render_settlement_effects",
    "system_band",
]
