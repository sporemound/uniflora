from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


def _optional_float(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _optional_int(value: object) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _unix_datetime(value: object) -> datetime | None:
    parsed = _optional_int(value)
    if parsed is None:
        return None
    try:
        return datetime.fromtimestamp(parsed, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


@dataclass(frozen=True, slots=True)
class AprsFiLocationRecord:
    """Location record with free-text and packet path fields discarded."""

    name: str
    target_type: str | None
    first_at_position: datetime | None
    last_reported_at: datetime | None
    latitude: float | None
    longitude: float | None
    course_degrees: float | None
    speed_kph: float | None
    altitude_m: float | None

    @classmethod
    def from_api(cls, entry: dict[str, Any]) -> "AprsFiLocationRecord":
        # Deliberately ignore showname, srccall, dstcall, comment, path,
        # PHG, status, MMSI and other identifying/free-text fields.
        return cls(
            name=str(entry.get("name", "")).strip(),
            target_type=(
                str(entry["type"]).strip()
                if entry.get("type") is not None
                else None
            ),
            first_at_position=_unix_datetime(entry.get("time")),
            last_reported_at=_unix_datetime(entry.get("lasttime")),
            latitude=_optional_float(entry.get("lat")),
            longitude=_optional_float(entry.get("lng")),
            course_degrees=_optional_float(entry.get("course")),
            speed_kph=_optional_float(entry.get("speed")),
            altitude_m=_optional_float(entry.get("altitude")),
        )


@dataclass(frozen=True, slots=True)
class AprsFiWeatherRecord:
    """Metric weather observation returned by aprs.fi."""

    name: str
    reported_at: datetime | None
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

    @classmethod
    def from_api(cls, entry: dict[str, Any]) -> "AprsFiWeatherRecord":
        return cls(
            name=str(entry.get("name", "")).strip(),
            reported_at=_unix_datetime(entry.get("time")),
            temperature_c=_optional_float(entry.get("temp")),
            pressure_mbar=_optional_float(entry.get("pressure")),
            humidity_percent=_optional_float(entry.get("humidity")),
            wind_direction_degrees=_optional_float(entry.get("wind_direction")),
            wind_speed_mps=_optional_float(entry.get("wind_speed")),
            wind_gust_mps=_optional_float(entry.get("wind_gust")),
            rain_1h_mm=_optional_float(entry.get("rain_1h")),
            rain_24h_mm=_optional_float(entry.get("rain_24h")),
            rain_since_midnight_mm=_optional_float(entry.get("rain_mn")),
            luminosity_wm2=_optional_float(entry.get("luminosity")),
        )


@dataclass(frozen=True, slots=True)
class ExteriorReport:
    text: str
    fetched_at: datetime
    from_cache: bool
    location_count: int
    weather_count: int
