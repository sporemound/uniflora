from datetime import timedelta

from uniflora.exterior_weather_rules import (
    StationScope,
    outcome_from_mapping,
)
from uniflora.exterior_weather_runtime import (
    ExteriorWeatherRuntimeState,
    WaterSystem,
)


def _night_outcome():
    return outcome_from_mapping(
        {
            "station": "HECA",
            "observed_at": "2026-07-22T20:13:22Z",
            "temperature_c": 30.6,
            "pressure_mbar": 1009.0,
            "humidity_percent": 52.0,
            "wind_speed_mps": 4.9,
        },
        scope=StationScope.REGIONAL_RELAY,
    )


def test_runtime_replaces_active_weather():
    state = ExteriorWeatherRuntimeState()
    outcome = _night_outcome()

    assert state.accept(outcome)
    assert not state.accept(
        state.evaluate(outcome.current)
    )
    assert state.latest_outcome == outcome


def test_fractional_multiplier_accumulates_deterministically():
    state = ExteriorWeatherRuntimeState()
    outcome = _night_outcome()
    state.accept(outcome)

    first = state.apply_units(
        WaterSystem.CONDENSATION_VEIL,
        9,
        at=outcome.current.observed_at,
    )
    second = state.apply_units(
        WaterSystem.CONDENSATION_VEIL,
        9,
        at=outcome.current.observed_at,
    )

    assert first.multiplier > 1.0
    assert second.residual_before == first.residual_after
    assert second.whole_units >= first.whole_units


def test_weather_expires_to_neutral():
    state = ExteriorWeatherRuntimeState()
    outcome = _night_outcome()
    state.accept(outcome)

    expired_at = outcome.window.expires_at_utc + timedelta(seconds=1)
    assert (
        state.multiplier_for(
            WaterSystem.CONDENSATION_VEIL,
            at=expired_at,
        )
        == 1.0
    )
