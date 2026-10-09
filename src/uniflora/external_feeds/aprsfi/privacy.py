from __future__ import annotations

import hashlib
import math
from datetime import date


EARTH_RADIUS_KM = 6371.0088
_CARDINALS = (
    "north",
    "northeast",
    "east",
    "southeast",
    "south",
    "southwest",
    "west",
    "northwest",
)


def daily_alias(identifier: str, secret: str, day: date) -> str:
    material = f"{day.isoformat()}|{secret}|{identifier.upper()}".encode("utf-8")
    digest = hashlib.blake2s(material, digest_size=4).digest()
    number = int.from_bytes(digest, "big") % 1000
    return f"exterior station {number:03d}"


def haversine_km(
    latitude_a: float,
    longitude_a: float,
    latitude_b: float,
    longitude_b: float,
) -> float:
    lat1 = math.radians(latitude_a)
    lat2 = math.radians(latitude_b)
    dlat = math.radians(latitude_b - latitude_a)
    dlon = math.radians(longitude_b - longitude_a)

    value = (
        math.sin(dlat / 2.0) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2.0) ** 2
    )
    return EARTH_RADIUS_KM * 2.0 * math.atan2(
        math.sqrt(value),
        math.sqrt(max(0.0, 1.0 - value)),
    )


def initial_bearing_degrees(
    latitude_a: float,
    longitude_a: float,
    latitude_b: float,
    longitude_b: float,
) -> float:
    lat1 = math.radians(latitude_a)
    lat2 = math.radians(latitude_b)
    dlon = math.radians(longitude_b - longitude_a)

    y = math.sin(dlon) * math.cos(lat2)
    x = (
        math.cos(lat1) * math.sin(lat2)
        - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    )
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def cardinal_direction(degrees: float) -> str:
    index = int((degrees + 22.5) // 45.0) % len(_CARDINALS)
    return _CARDINALS[index]


def coarse_range_band(distance_km: float) -> str:
    if distance_km < 10:
        return "within 10 km"
    if distance_km < 25:
        return "10–25 km"
    if distance_km < 50:
        return "25–50 km"
    if distance_km < 100:
        return "50–100 km"
    if distance_km < 200:
        return "100–200 km"
    if distance_km < 400:
        return "200–400 km"
    if distance_km < 800:
        return "400–800 km"
    return "beyond 800 km"
