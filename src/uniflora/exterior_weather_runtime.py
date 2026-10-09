from __future__ import annotations

"""
Mutable runtime state for applying exterior weather multipliers.

Drop-in destination:
    src/uniflora/exterior_weather_runtime.py

This class gives GameService a deterministic way to replace active weather,
query current multipliers, and apply fractional effects to integer resources.
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from math import floor
from typing import Any

from uniflora.exterior_weather_rules import (
    ExteriorCondition,
    ExteriorWeatherObservation,
    ExteriorWeatherOutcome,
    WaterSystemInfluence,
    WeatherRuleConfig,
    evaluate_exterior_weather,
)


class WaterSystem(StrEnum):
    CONDENSATION_VEIL = "condensation_veil"
    SOLAR_DISTILLATION = "solar_distillation"
    CISTERN_RETENTION = "cistern_retention"
    CAPILLARY_TRANSFER = "capillary_transfer"
    WIND_TOWER = "wind_tower"
    THERMAL_STORAGE = "thermal_storage"
    WATER_PURITY = "water_purity"
    EVAPORATION_BURDEN = "evaporation_burden"


_SYSTEM_FIELDS: dict[WaterSystem, str] = {
    WaterSystem.CONDENSATION_VEIL: (
        "condensation_veil_multiplier"
    ),
    WaterSystem.SOLAR_DISTILLATION: (
        "solar_distillation_multiplier"
    ),
    WaterSystem.CISTERN_RETENTION: (
        "cistern_retention_multiplier"
    ),
    WaterSystem.CAPILLARY_TRANSFER: (
        "capillary_transfer_multiplier"
    ),
    WaterSystem.WIND_TOWER: "wind_tower_multiplier",
    WaterSystem.THERMAL_STORAGE: "thermal_storage_multiplier",
    WaterSystem.WATER_PURITY: "water_purity_multiplier",
    WaterSystem.EVAPORATION_BURDEN: (
        "evaporation_burden_multiplier"
    ),
}


@dataclass(frozen=True, slots=True)
class AppliedWeatherAmount:
    system: WaterSystem
    base_units: int
    multiplier: float
    exact_units: float
    whole_units: int
    residual_before: float
    residual_after: float
    weather_active: bool


@dataclass(slots=True)
class ExteriorWeatherRuntimeState:
    latest_observation: ExteriorWeatherObservation | None = None
    latest_outcome: ExteriorWeatherOutcome | None = None
    known_observation_keys: set[str] = field(default_factory=set)
    residuals: dict[str, float] = field(default_factory=dict)

    def evaluate(
        self,
        current: ExteriorWeatherObservation,
        *,
        config: WeatherRuleConfig = WeatherRuleConfig(),
    ) -> ExteriorWeatherOutcome:
        previous_outcome = self.latest_outcome
        return evaluate_exterior_weather(
            current=current,
            previous=self.latest_observation,
            previous_modifiers=(
                previous_outcome.modifiers
                if previous_outcome is not None
                else None
            ),
            previous_conditions=(
                previous_outcome.conditions
                if previous_outcome is not None
                else frozenset()
            ),
            known_observation_keys=frozenset(
                self.known_observation_keys
            ),
            config=config,
        )

    def accept(self, outcome: ExteriorWeatherOutcome) -> bool:
        if outcome.duplicate:
            return False

        self.latest_observation = outcome.current
        self.latest_outcome = outcome
        self.known_observation_keys.add(
            outcome.current.observation_key
        )
        return True

    def active_influence(
        self,
        at: datetime | None = None,
    ) -> WaterSystemInfluence:
        if self.latest_outcome is None:
            return WaterSystemInfluence()

        moment = at or datetime.now(timezone.utc)
        if self.latest_outcome.window.is_active(moment):
            return self.latest_outcome.modifiers
        return WaterSystemInfluence()

    def multiplier_for(
        self,
        system: WaterSystem,
        *,
        at: datetime | None = None,
    ) -> float:
        influence = self.active_influence(at)
        return float(getattr(influence, _SYSTEM_FIELDS[system]))

    def apply_units(
        self,
        system: WaterSystem,
        base_units: int,
        *,
        at: datetime | None = None,
        residual_key: str | None = None,
    ) -> AppliedWeatherAmount:
        if base_units < 0:
            raise ValueError("base_units cannot be negative")

        influence = self.active_influence(at)
        multiplier = float(
            getattr(influence, _SYSTEM_FIELDS[system])
        )
        weather_active = self.latest_outcome is not None and (
            self.latest_outcome.window.is_active(
                at or datetime.now(timezone.utc)
            )
        )

        key = residual_key or system.value
        residual_before = self.residuals.get(key, 0.0)
        exact_units = base_units * multiplier + residual_before
        whole_units = floor(exact_units)
        residual_after = exact_units - whole_units
        self.residuals[key] = residual_after

        return AppliedWeatherAmount(
            system=system,
            base_units=base_units,
            multiplier=multiplier,
            exact_units=round(exact_units, 6),
            whole_units=whole_units,
            residual_before=round(residual_before, 6),
            residual_after=round(residual_after, 6),
            weather_active=weather_active,
        )

    def snapshot(self) -> dict[str, Any]:
        return {
            "latest_observation_key": (
                self.latest_observation.observation_key
                if self.latest_observation is not None
                else None
            ),
            "known_observation_keys": sorted(
                self.known_observation_keys
            ),
            "residuals": dict(self.residuals),
            "active_phase": (
                self.latest_outcome.window.phase.value
                if self.latest_outcome is not None
                else None
            ),
            "active_until": (
                self.latest_outcome.window.expires_at_utc.isoformat()
                if self.latest_outcome is not None
                else None
            ),
            "active_influence": asdict(
                self.latest_outcome.modifiers
                if self.latest_outcome is not None
                else WaterSystemInfluence()
            ),
            "conditions": (
                sorted(
                    condition.value
                    for condition in self.latest_outcome.conditions
                )
                if self.latest_outcome is not None
                else [ExteriorCondition.NOMINAL.value]
            ),
        }


__all__ = [
    "AppliedWeatherAmount",
    "ExteriorWeatherRuntimeState",
    "WaterSystem",
]
