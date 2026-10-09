from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .models import AprsEvent, AprsObservation, PacketKind


@dataclass(frozen=True, slots=True)
class DetectorConfig:
    global_cooldown: timedelta = timedelta(hours=2)
    resume_after: timedelta = timedelta(hours=3)
    pressure_change_hpa: float = 4.0
    movement_threshold_kph: float = 5.0
    announce_new_stations: bool = True


@dataclass(slots=True)
class _StationState:
    last_seen_at: datetime
    last_pressure_hpa: float | None
    moving: bool | None
    reports: int = 1


class AprsChangeDetector:
    """Convert packet observations into sparse public events.

    State is kept in memory and keyed by the private station key. Public events
    contain only daily aliases and coarse directional/range information.
    """

    def __init__(self, config: DetectorConfig | None = None) -> None:
        self.config = config or DetectorConfig()
        self._stations: dict[str, _StationState] = {}
        self._last_public_event_at: datetime | None = None

    def consider(self, observation: AprsObservation) -> AprsEvent | None:
        now = observation.received_at
        previous = self._stations.get(observation.station_key)
        pressure = observation.weather.get("pressure_hpa")

        candidate: AprsEvent | None = None

        if previous is None:
            self._stations[observation.station_key] = _StationState(
                last_seen_at=now,
                last_pressure_hpa=pressure,
                moving=observation.moving,
            )
            if self.config.announce_new_stations and observation.kind is not PacketKind.OTHER:
                candidate = self._new_station_event(observation)
        else:
            silence = now - previous.last_seen_at
            previous.reports += 1

            if silence >= self.config.resume_after:
                candidate = self._resumed_event(observation, silence)
            elif (
                pressure is not None
                and previous.last_pressure_hpa is not None
                and abs(pressure - previous.last_pressure_hpa)
                >= self.config.pressure_change_hpa
            ):
                candidate = self._pressure_event(
                    observation,
                    previous.last_pressure_hpa,
                    pressure,
                )
            elif (
                observation.moving is not None
                and previous.moving is not None
                and observation.moving != previous.moving
            ):
                candidate = self._movement_event(observation)

            previous.last_seen_at = now
            previous.last_pressure_hpa = pressure
            previous.moving = observation.moving

        if candidate is None:
            return None

        if (
            self._last_public_event_at is not None
            and now - self._last_public_event_at < self.config.global_cooldown
        ):
            return None

        self._last_public_event_at = now
        return candidate

    @staticmethod
    def _field_text(observation: AprsObservation) -> str:
        details: list[str] = []
        if observation.bearing:
            details.append(f"bearing: {observation.bearing}")
        if observation.range_band:
            details.append(f"range: {observation.range_band}")
        if not details:
            details.append("position: withheld")
        return "\n".join(details)

    def _new_station_event(self, observation: AprsObservation) -> AprsEvent:
        noun = "object" if observation.kind is PacketKind.OBJECT else "station"
        public_alias = observation.object_alias or observation.station_alias
        body = (
            f"{public_alias} has entered the exterior register.\n\n"
            f"{self._field_text(observation)}\n\n"
            f"the {noun} may have been present before the archive began listening."
        )
        return AprsEvent(
            event_id=f"aprs:new:{observation.station_alias}:{int(observation.received_at.timestamp())}",
            event_type="new_station",
            occurred_at=observation.received_at,
            station_alias=public_alias,
            body=body,
        )

    def _resumed_event(
        self,
        observation: AprsObservation,
        silence: timedelta,
    ) -> AprsEvent:
        hours = max(1, round(silence.total_seconds() / 3600.0))
        body = (
            f"{observation.station_alias} has resumed after {hours} hours of silence.\n\n"
            f"{self._field_text(observation)}\n\n"
            "the previous position had remained on record."
        )
        return AprsEvent(
            event_id=f"aprs:resumed:{observation.station_alias}:{int(observation.received_at.timestamp())}",
            event_type="station_resumed",
            occurred_at=observation.received_at,
            station_alias=observation.station_alias,
            body=body,
            voice=True,
        )

    def _pressure_event(
        self,
        observation: AprsObservation,
        old_pressure: float,
        new_pressure: float,
    ) -> AprsEvent:
        tendency = "rising" if new_pressure > old_pressure else "falling"
        delta = abs(new_pressure - old_pressure)
        body = (
            f"{observation.station_alias} reports atmospheric pressure {tendency}.\n\n"
            f"change: {delta:.1f} hPa\n"
            f"{self._field_text(observation)}\n\n"
            "the exterior instrument has recorded the correction."
        )
        return AprsEvent(
            event_id=f"aprs:pressure:{observation.station_alias}:{int(observation.received_at.timestamp())}",
            event_type="pressure_change",
            occurred_at=observation.received_at,
            station_alias=observation.station_alias,
            body=body,
        )

    def _movement_event(self, observation: AprsObservation) -> AprsEvent:
        state = "moving" if observation.moving else "stationary"
        body = (
            f"{observation.station_alias} now reports itself as {state}.\n\n"
            f"{self._field_text(observation)}\n\n"
            "the register has retained both accounts."
        )
        return AprsEvent(
            event_id=f"aprs:movement:{observation.station_alias}:{int(observation.received_at.timestamp())}",
            event_type="movement_change",
            occurred_at=observation.received_at,
            station_alias=observation.station_alias,
            body=body,
        )
