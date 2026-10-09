from __future__ import annotations

import json
from typing import cast

import pytest
from aiohttp import web

from uniflora.health import HealthService
from uniflora.runtime import Environment, RuntimeSessions


@pytest.mark.asyncio
async def test_health_reports_both_isolated_sessions() -> None:
    sessions = RuntimeSessions()
    await sessions.start(Environment.TEST)
    service = HealthService(sessions, "127.0.0.1", 8080)
    response = await service.health(cast(web.Request, None))
    payload = json.loads(response.body)
    assert payload["status"] == "ok"
    assert payload["sessions"]["live"]["mode"] == "locked"
    assert payload["sessions"]["test"]["mode"] == "running"


@pytest.mark.asyncio
async def test_readiness_tracks_discord_connection() -> None:
    service = HealthService(RuntimeSessions(), "127.0.0.1", 8080)
    unavailable = await service.ready(cast(web.Request, None))
    service.discord_connected = True
    available = await service.ready(cast(web.Request, None))
    assert unavailable.status == 503
    assert available.status == 200
