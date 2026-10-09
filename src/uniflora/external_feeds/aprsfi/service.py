from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from .client import AprsFiClient
from .config import AprsFiSettings
from .formatter import render_exterior_report
from .models import ExteriorReport


class AprsFiExteriorService:
    """User-triggered exterior reports with a short shared cache."""

    def __init__(
        self,
        settings: AprsFiSettings,
        *,
        client: AprsFiClient | None = None,
    ) -> None:
        self.settings = settings
        self.client = client or AprsFiClient(settings)
        self._cache: ExteriorReport | None = None
        self._lock = asyncio.Lock()

    async def close(self) -> None:
        await self.client.close()

    async def report(self, *, force_refresh: bool = False) -> ExteriorReport:
        async with self._lock:
            now = datetime.now(timezone.utc)
            if (
                not force_refresh
                and self._cache is not None
                and now - self._cache.fetched_at
                < timedelta(seconds=self.settings.cache_ttl_seconds)
            ):
                cached_text = self._cache.text.replace(
                    "NEW OBSERVATION",
                    "CACHED OBSERVATION",
                    1,
                )
                return ExteriorReport(
                    text=cached_text,
                    fetched_at=self._cache.fetched_at,
                    from_cache=True,
                    location_count=self._cache.location_count,
                    weather_count=self._cache.weather_count,
                )

            enabled = tuple(
                target for target in self.settings.targets if target.enabled
            )
            location_names = tuple(
                target.name for target in enabled if target.location
            )
            weather_names = tuple(
                target.name for target in enabled if target.weather
            )

            locations = (
                await self.client.query_locations(location_names)
                if location_names
                else ()
            )
            weather = (
                await self.client.query_weather(weather_names)
                if weather_names
                else ()
            )

            text = render_exterior_report(
                locations,
                weather,
                self.settings,
                now=now,
                from_cache=False,
            )
            report = ExteriorReport(
                text=text,
                fetched_at=now,
                from_cache=False,
                location_count=len(locations),
                weather_count=len(weather),
            )
            self._cache = report
            return report
