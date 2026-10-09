from uniflora.exterior_weather_rules import (
    ExteriorCondition,
    ExteriorPhase,
    StationScope,
    evaluate_exterior_weather,
    outcome_from_mapping,
)


def _weather(observed_at: str, **updates):
    payload = {
        "station": "HECA",
        "observed_at": observed_at,
        "temperature_c": 30.6,
        "pressure_mbar": 1009.0,
        "humidity_percent": 52.0,
        "wind_direction_degrees": 310.0,
        "wind_speed_mps": 4.9,
        "source": "aprs.fi",
    }
    payload.update(updates)
    return outcome_from_mapping(
        payload,
        scope=StationScope.REGIONAL_RELAY,
    )


def test_heca_evening_utc_is_night_in_egypt():
    outcome = _weather("2026-07-22T20:13:22Z")

    assert outcome.window.phase is ExteriorPhase.NIGHT
    assert outcome.modifiers.condensation_veil_multiplier > 1.08
    assert outcome.modifiers.solar_distillation_multiplier < 0.85
    assert outcome.modifiers.evaporation_burden_multiplier < 1.0


def test_day_favors_solar_and_night_favors_condensation():
    night = _weather("2026-07-22T23:00:00Z")
    day = _weather("2026-07-22T10:00:00Z")

    assert (
        night.modifiers.condensation_veil_multiplier
        > day.modifiers.condensation_veil_multiplier
    )
    assert (
        day.modifiers.solar_distillation_multiplier
        > night.modifiers.solar_distillation_multiplier
    )


def test_duplicate_never_stacks():
    first = _weather("2026-07-22T20:13:22Z")
    duplicate = evaluate_exterior_weather(
        current=first.current,
        previous=first.current,
        previous_modifiers=first.modifiers,
        previous_conditions=first.conditions,
        known_observation_keys=frozenset(
            {first.current.observation_key}
        ),
    )

    assert duplicate.duplicate
    assert duplicate.modifiers == first.modifiers
    assert duplicate.triggers == ()


def test_strong_wind_hysteresis_holds_then_clears():
    first = _weather(
        "2026-07-22T20:13:22Z",
        wind_speed_mps=10.2,
    )
    assert ExteriorCondition.STRONG_WIND in first.conditions

    held = outcome_from_mapping(
        {
            "station": "HECA",
            "observed_at": "2026-07-22T21:13:22Z",
            "temperature_c": 30.6,
            "pressure_mbar": 1009.0,
            "humidity_percent": 52.0,
            "wind_speed_mps": 9.0,
        },
        scope=StationScope.REGIONAL_RELAY,
        previous=first.current,
        previous_modifiers=first.modifiers,
        previous_conditions=first.conditions,
    )
    assert ExteriorCondition.STRONG_WIND in held.conditions

    cleared = outcome_from_mapping(
        {
            "station": "HECA",
            "observed_at": "2026-07-22T22:13:22Z",
            "temperature_c": 30.6,
            "pressure_mbar": 1009.0,
            "humidity_percent": 52.0,
            "wind_speed_mps": 8.0,
        },
        scope=StationScope.REGIONAL_RELAY,
        previous=held.current,
        previous_modifiers=held.modifiers,
        previous_conditions=held.conditions,
    )
    assert ExteriorCondition.STRONG_WIND not in cleared.conditions
