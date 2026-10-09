from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class PacketKind(StrEnum):
    POSITION = "position"
    WEATHER = "weather"
    OBJECT = "object"
    STATUS = "status"
    TELEMETRY = "telemetry"
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class AprsPacket:
    """A conservatively parsed APRS-IS TNC2 packet."""

    sender: str
    destination: str
    path: tuple[str, ...]
    payload: str
    received_at: datetime


@dataclass(frozen=True, slots=True)
class AprsObservation:
    """A privacy-reduced observation suitable for change detection."""

    station_key: str
    station_alias: str
    kind: PacketKind
    received_at: datetime
    latitude: float | None = None
    longitude: float | None = None
    bearing: str | None = None
    range_km: float | None = None
    range_band: str | None = None
    moving: bool | None = None
    speed_kph: float | None = None
    course_degrees: int | None = None
    object_alias: str | None = None
    weather: dict[str, float] = field(default_factory=dict)
    status_present: bool = False


@dataclass(frozen=True, slots=True)
class AprsEvent:
    """A public, non-canonical observation rendered for Discord."""

    event_id: str
    event_type: str
    occurred_at: datetime
    station_alias: str
    body: str
    voice: bool = False
    severity: str = "ordinary"
