from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable
from typing import Any

import aiohttp

from .config import AprsFiSettings
from .errors import AprsFiApiError
from .models import AprsFiLocationRecord, AprsFiWeatherRecord


logger = logging.getLogger(__name__)


def _unique_names(names: Iterable[str]) -> tuple[str, ...]:
    ordered: dict[str, None] = {}
    for name in names:
        cleaned = name.strip().upper()
        if cleaned:
            ordered.setdefault(cleaned, None)
    values = tuple(ordered)
    if not values:
        raise ValueError("At least one aprs.fi target is required")
    if len(values) > 20:
        raise ValueError("aprs.fi accepts at most 20 named targets per request")
    return values


class AprsFiClient:
    """Small async client for aprs.fi's named-target API.

    It intentionally implements only `loc` and `wx`. Text-message retrieval is
    omitted to avoid relaying personal radio traffic into Discord.
    """

    def __init__(
        self,
        settings: AprsFiSettings,
        *,
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        self.settings = settings
        self._session = session
        self._owns_session = session is None

    async def close(self) -> None:
        if self._owns_session and self._session is not None:
            await self._session.close()
        self._session = None

    async def query_locations(
        self,
        names: Iterable[str],
    ) -> tuple[AprsFiLocationRecord, ...]:
        payload = await self._request("loc", _unique_names(names))
        entries = payload.get("entries", [])
        if not isinstance(entries, list):
            raise AprsFiApiError("aprs.fi returned a malformed location response")
        return tuple(
            record
            for entry in entries
            if isinstance(entry, dict)
            and (record := AprsFiLocationRecord.from_api(entry)).name
        )

    async def query_weather(
        self,
        names: Iterable[str],
    ) -> tuple[AprsFiWeatherRecord, ...]:
        payload = await self._request("wx", _unique_names(names))
        entries = payload.get("entries", [])
        if not isinstance(entries, list):
            raise AprsFiApiError("aprs.fi returned a malformed weather response")
        return tuple(
            record
            for entry in entries
            if isinstance(entry, dict)
            and (record := AprsFiWeatherRecord.from_api(entry)).name
        )

    async def _request(
        self,
        what: str,
        names: tuple[str, ...],
    ) -> dict[str, Any]:
        if what not in {"loc", "wx"}:
            raise ValueError("Only loc and wx queries are supported")

        session = await self._get_session()
        params = {
            "name": ",".join(names),
            "what": what,
            "apikey": self.settings.api_key,
            "format": "json",
        }
        headers = {
            "User-Agent": self.settings.user_agent,
            "Accept": "application/json",
        }

        try:
            async with session.get(
                self.settings.endpoint,
                params=params,
                headers=headers,
            ) as response:
                if response.status != 200:
                    snippet = (await response.text())[:300]
                    raise AprsFiApiError(
                        f"aprs.fi HTTP {response.status}: {snippet}"
                    )

                try:
                    payload = await response.json(content_type=None)
                except (aiohttp.ContentTypeError, ValueError) as exc:
                    raise AprsFiApiError(
                        "aprs.fi returned invalid JSON"
                    ) from exc
        except asyncio.TimeoutError as exc:
            raise AprsFiApiError("aprs.fi request timed out") from exc
        except aiohttp.ClientError as exc:
            raise AprsFiApiError(
                f"aprs.fi request failed: {exc}"
            ) from exc

        if not isinstance(payload, dict):
            raise AprsFiApiError("aprs.fi returned a non-object response")

        if payload.get("result") != "ok":
            description = str(
                payload.get("description", "unknown aprs.fi API failure")
            )
            raise AprsFiApiError(description)

        return payload

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(
                total=self.settings.timeout_seconds
            )
            self._session = aiohttp.ClientSession(timeout=timeout)
            self._owns_session = True
        return self._session
