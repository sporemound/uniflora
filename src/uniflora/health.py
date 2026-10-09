from __future__ import annotations

from typing import Protocol

from aiohttp import web


class SessionHealthProvider(Protocol):
    async def all_snapshots(self) -> dict[str, dict[str, str]]: ...


class HealthService:
    def __init__(self, sessions: SessionHealthProvider, host: str, port: int) -> None:
        self.sessions = sessions
        self.host = host
        self.port = port
        self.discord_connected = False
        self.shutting_down = False
        self._runner: web.AppRunner | None = None

    async def health(self, request: web.Request) -> web.Response:
        del request
        return web.json_response(
            {
                "service": "the-missing-interior",
                "status": "stopping" if self.shutting_down else "ok",
                "discord_connected": self.discord_connected,
                "sessions": await self.sessions.all_snapshots(),
            }
        )

    async def ready(self, request: web.Request) -> web.Response:
        del request
        ready = self.discord_connected and not self.shutting_down
        return web.json_response({"ready": ready}, status=200 if ready else 503)

    def create_app(self) -> web.Application:
        app = web.Application()
        app.router.add_get("/healthz", self.health)
        app.router.add_get("/readyz", self.ready)
        return app

    async def start(self) -> None:
        self._runner = web.AppRunner(self.create_app(), access_log=None)
        await self._runner.setup()
        await web.TCPSite(self._runner, self.host, self.port).start()

    async def stop(self) -> None:
        self.shutting_down = True
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None
