from __future__ import annotations

import re
from datetime import datetime, timezone

from .models import AprsObservation, AprsPacket, PacketKind
from .privacy import (
    cardinal_direction,
    coarse_range_band,
    daily_alias,
    haversine_km,
    initial_bearing_degrees,
    object_alias,
)


_TNC2_PATTERN = re.compile(
    r"^(?P<sender>[A-Za-z0-9-]{1,12})>"
    r"(?P<destination>[A-Za-z0-9-]{1,12})"
    r"(?P<path>(?:,[^:]+)?)"
    r":(?P<payload>.*)$"
)

_POSITION_PATTERN = re.compile(
    r"^(?P<lat_deg>\d{2})(?P<lat_min>\d{2}\.\d{2})(?P<lat_hemi>[NS])"
    r"(?P<table>[/\\])"
    r"(?P<lon_deg>\d{3})(?P<lon_min>\d{2}\.\d{2})(?P<lon_hemi>[EW])"
    r"(?P<symbol>.)"
    r"(?P<tail>.*)$"
)

_COURSE_SPEED_PATTERN = re.compile(r"^(?P<course>\d{3})/(?P<speed>\d{3})")
_WEATHER_TOKEN_PATTERNS: dict[str, re.Pattern[str]] = {
    "wind_course_degrees": re.compile(r"c(\d{3})"),
    "wind_speed_mph": re.compile(r"s(\d{3})"),
    "wind_gust_mph": re.compile(r"g(\d{3})"),
    "temperature_f": re.compile(r"t(-?\d{3})"),
    "humidity_percent": re.compile(r"h(\d{2})"),
    "pressure_hpa_tenths": re.compile(r"b(\d{5})"),
}


class AprsParser:
    """Parse a safe subset of APRS used by the ambient observation prototype.

    Supported:
    - TNC2 headers
    - uncompressed position packets
    - timestamped uncompressed position packets
    - APRS objects with uncompressed positions
    - status and telemetry classification
    - common weather tokens

    Compressed positions and Mic-E packets are deliberately ignored rather
    than guessed.
    """

    def __init__(
        self,
        *,
        center_latitude: float,
        center_longitude: float,
        alias_secret: str,
    ) -> None:
        self.center_latitude = center_latitude
        self.center_longitude = center_longitude
        self.alias_secret = alias_secret

    def parse_line(
        self,
        line: str,
        *,
        received_at: datetime | None = None,
    ) -> AprsObservation | None:
        packet = self.parse_packet(line, received_at=received_at)
        if packet is None:
            return None
        return self.to_observation(packet)

    @staticmethod
    def parse_packet(
        line: str,
        *,
        received_at: datetime | None = None,
    ) -> AprsPacket | None:
        line = line.strip("\r\n")
        if not line or line.startswith("#") or len(line.encode("utf-8", errors="ignore")) > 512:
            return None

        match = _TNC2_PATTERN.match(line)
        if match is None:
            return None

        path_text = match.group("path").lstrip(",")
        path = tuple(part.strip() for part in path_text.split(",") if part.strip())
        return AprsPacket(
            sender=match.group("sender").upper(),
            destination=match.group("destination").upper(),
            path=path,
            payload=match.group("payload"),
            received_at=received_at or datetime.now(timezone.utc),
        )

    def to_observation(self, packet: AprsPacket) -> AprsObservation | None:
        payload = packet.payload
        if not payload:
            return None

        station_alias = daily_alias(
            packet.sender,
            self.alias_secret,
            packet.received_at.date(),
        )
        base = {
            "station_key": packet.sender,
            "station_alias": station_alias,
            "received_at": packet.received_at,
        }

        data_type = payload[0]

        if data_type in ("!", "="):
            return self._position_observation(payload[1:], PacketKind.POSITION, base)

        if data_type in ("/", "@"):
            if len(payload) < 9:
                return None
            # Timestamped position packets carry a seven-character timestamp.
            return self._position_observation(payload[8:], PacketKind.POSITION, base)

        if data_type == ";":
            return self._object_observation(payload, base)

        if data_type == ">":
            return AprsObservation(
                **base,
                kind=PacketKind.STATUS,
                status_present=True,
            )

        if payload.startswith("T#"):
            return AprsObservation(
                **base,
                kind=PacketKind.TELEMETRY,
            )

        if data_type == "_":
            weather = self._parse_weather(payload[1:])
            return AprsObservation(
                **base,
                kind=PacketKind.WEATHER,
                weather=weather,
            )

        return AprsObservation(
            **base,
            kind=PacketKind.OTHER,
        )

    def _object_observation(
        self,
        payload: str,
        base: dict[str, object],
    ) -> AprsObservation | None:
        # ;OBJECTNAM*DDHHMMzDDMM.mmN/DDDMM.mmE...
        if len(payload) < 19:
            return None

        name = payload[1:10].strip() or "unnamed"
        alive_marker = payload[10]
        if alive_marker not in ("*", "_"):
            return None

        position_payload = payload[18:]
        observation = self._position_observation(
            position_payload,
            PacketKind.OBJECT,
            base,
        )
        if observation is None:
            return None

        return AprsObservation(
            station_key=observation.station_key,
            station_alias=observation.station_alias,
            kind=PacketKind.OBJECT,
            received_at=observation.received_at,
            latitude=observation.latitude,
            longitude=observation.longitude,
            bearing=observation.bearing,
            range_km=observation.range_km,
            range_band=observation.range_band,
            moving=observation.moving,
            speed_kph=observation.speed_kph,
            course_degrees=observation.course_degrees,
            object_alias=object_alias(
                name,
                self.alias_secret,
                observation.received_at.date(),
            ),
            weather=observation.weather,
        )

    def _position_observation(
        self,
        text: str,
        kind: PacketKind,
        base: dict[str, object],
    ) -> AprsObservation | None:
        match = _POSITION_PATTERN.match(text)
        if match is None:
            return None

        latitude = self._coordinate(
            int(match.group("lat_deg")),
            float(match.group("lat_min")),
            match.group("lat_hemi"),
        )
        longitude = self._coordinate(
            int(match.group("lon_deg")),
            float(match.group("lon_min")),
            match.group("lon_hemi"),
        )

        distance = haversine_km(
            self.center_latitude,
            self.center_longitude,
            latitude,
            longitude,
        )
        bearing_degrees = initial_bearing_degrees(
            self.center_latitude,
            self.center_longitude,
            latitude,
            longitude,
        )

        tail = match.group("tail")
        course_degrees: int | None = None
        speed_kph: float | None = None
        moving: bool | None = None

        course_speed = _COURSE_SPEED_PATTERN.match(tail)
        if course_speed is not None:
            course_degrees = int(course_speed.group("course"))
            speed_knots = int(course_speed.group("speed"))
            speed_kph = round(speed_knots * 1.852, 1)
            moving = speed_kph >= 5.0

        weather = self._parse_weather(tail)
        observed_kind = PacketKind.WEATHER if weather else kind

        return AprsObservation(
            **base,
            kind=observed_kind,
            latitude=latitude,
            longitude=longitude,
            bearing=cardinal_direction(bearing_degrees),
            range_km=round(distance, 1),
            range_band=coarse_range_band(distance),
            moving=moving,
            speed_kph=speed_kph,
            course_degrees=course_degrees,
            weather=weather,
        )

    @staticmethod
    def _coordinate(degrees: int, minutes: float, hemisphere: str) -> float:
        value = degrees + minutes / 60.0
        return -value if hemisphere in ("S", "W") else value

    @staticmethod
    def _parse_weather(text: str) -> dict[str, float]:
        values: dict[str, float] = {}

        for name, pattern in _WEATHER_TOKEN_PATTERNS.items():
            match = pattern.search(text)
            if match is None:
                continue
            raw = int(match.group(1))

            if name == "pressure_hpa_tenths":
                values["pressure_hpa"] = raw / 10.0
            elif name == "humidity_percent":
                values["humidity_percent"] = 100.0 if raw == 0 else float(raw)
            else:
                values[name] = float(raw)

        return values
