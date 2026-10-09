from __future__ import annotations

from datetime import datetime, timezone

from .config import AprsFiSettings
from .models import AprsFiLocationRecord, AprsFiWeatherRecord
from .privacy import (
    cardinal_direction,
    coarse_range_band,
    daily_alias,
    haversine_km,
    initial_bearing_degrees,
)


def _age_text(observed_at: datetime | None, now: datetime) -> str:
    if observed_at is None:
        return "report time unavailable"

    delta_seconds = max(0, int((now - observed_at).total_seconds()))
    if delta_seconds < 120:
        return "reported within the last two minutes"
    if delta_seconds < 3600:
        return f"reported {delta_seconds // 60} minutes ago"
    if delta_seconds < 172800:
        return f"reported {delta_seconds // 3600} hours ago"
    return f"reported {delta_seconds // 86400} days ago"


def _location_lines(
    record: AprsFiLocationRecord,
    settings: AprsFiSettings,
    now: datetime,
) -> list[str]:
    alias = daily_alias(record.name, settings.alias_secret, now.date())
    lines = [alias]

    if record.latitude is not None and record.longitude is not None:
        distance = haversine_km(
            settings.center_latitude,
            settings.center_longitude,
            record.latitude,
            record.longitude,
        )
        bearing = initial_bearing_degrees(
            settings.center_latitude,
            settings.center_longitude,
            record.latitude,
            record.longitude,
        )
        lines.append(f"bearing: {cardinal_direction(bearing)}")
        lines.append(f"range: {coarse_range_band(distance)}")
    else:
        lines.append("position: withheld or unavailable")

    lines.append(_age_text(record.last_reported_at, now))

    if record.speed_kph is not None:
        movement = "moving" if record.speed_kph >= 5.0 else "stationary"
        lines.append(f"movement account: {movement}")

    return lines


def _weather_lines(
    record: AprsFiWeatherRecord,
    settings: AprsFiSettings,
    now: datetime,
) -> list[str]:
    alias = daily_alias(record.name, settings.alias_secret, now.date())
    lines = [alias, _age_text(record.reported_at, now)]

    if record.temperature_c is not None:
        lines.append(f"temperature: {record.temperature_c:.1f} °C")
    if record.pressure_mbar is not None:
        lines.append(f"pressure: {record.pressure_mbar:.1f} mbar")
    if record.humidity_percent is not None:
        lines.append(f"humidity: {record.humidity_percent:.0f}%")
    if record.wind_speed_mps is not None:
        lines.append(f"wind: {record.wind_speed_mps:.1f} m/s")
    if record.wind_gust_mps is not None:
        lines.append(f"gust: {record.wind_gust_mps:.1f} m/s")
    if record.rain_1h_mm is not None:
        lines.append(f"rain / 1h: {record.rain_1h_mm:.1f} mm")

    if len(lines) == 2:
        lines.append("weather fields unavailable")

    return lines


def render_exterior_report(
    locations: tuple[AprsFiLocationRecord, ...],
    weather: tuple[AprsFiWeatherRecord, ...],
    settings: AprsFiSettings,
    *,
    now: datetime | None = None,
    from_cache: bool = False,
) -> str:
    now = now or datetime.now(timezone.utc)
    sections: list[str] = []

    for record in locations[: settings.max_public_entries]:
        sections.append("\n".join(_location_lines(record, settings, now)))

    remaining = max(0, settings.max_public_entries - len(sections))
    for record in weather[:remaining]:
        sections.append("\n".join(_weather_lines(record, settings, now)))

    cache_label = "cached observation" if from_cache else "new observation"
    timestamp = now.strftime("%Y-%m-%d %H:%M:%SZ")

    if not sections:
        body = (
            "no configured exterior station returned a usable observation.\n\n"
            "the register remains open."
        )
    else:
        body = "\n\n────────────────────────\n\n".join(sections)

    return (
        "```text\n"
        "DEIR EL-MEDINA EXTERIOR REGISTER\n"
        f"{cache_label.upper()} // {timestamp}\n"
        "════════════════════════════════\n"
        f"{body}\n"
        "```\n"
        "*external observation only — settlement state unchanged*\n"
        "Data source: <https://aprs.fi/>"
    )
