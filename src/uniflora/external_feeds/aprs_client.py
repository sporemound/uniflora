from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass


logger = logging.getLogger(__name__)
_LOGIN_PATTERN = re.compile(r"^[A-Za-z0-9]{3,9}(?:-[A-Za-z0-9]{1,2})?$")


@dataclass(frozen=True, slots=True)
class AprsConfig:
    """Receive-only APRS-IS connection settings."""

    login_call: str
    center_latitude: float = 25.728333
    center_longitude: float = 32.601389
    radius_km: int = 200
    host: str = "euro.aprs2.net"
    port: int = 14580
    passcode: str = "-1"
    software_name: str = "uniflora"
    software_version: str = "0.1"
    connect_timeout_seconds: float = 20.0
    read_timeout_seconds: float = 180.0
    reconnect_min_seconds: float = 5.0
    reconnect_max_seconds: float = 300.0

    def __post_init__(self) -> None:
        if not _LOGIN_PATTERN.fullmatch(self.login_call):
            raise ValueError(
                "login_call must be a 3–9 character APRS-IS identifier, "
                "optionally followed by a one- or two-character SSID"
            )
        if not -90.0 <= self.center_latitude <= 90.0:
            raise ValueError("center_latitude must be between -90 and 90")
        if not -180.0 <= self.center_longitude <= 180.0:
            raise ValueError("center_longitude must be between -180 and 180")
        if not 1 <= self.radius_km <= 9999:
            raise ValueError("radius_km must be between 1 and 9999")
        if self.passcode != "-1":
            raise ValueError(
                "This client is intentionally receive-only; passcode must remain -1"
            )

    @property
    def range_filter(self) -> str:
        return (
            f"r/{self.center_latitude:.6f}/"
            f"{self.center_longitude:.6f}/"
            f"{self.radius_km}"
        )

    @property
    def login_line(self) -> str:
        return (
            f"user {self.login_call} "
            f"pass -1 "
            f"vers {self.software_name} {self.software_version} "
            f"filter {self.range_filter}"
        )


class AprsClient:
    """Receive-only APRS-IS TCP client with reconnect handling.

    There is deliberately no packet-transmission method.
    """

    def __init__(self, config: AprsConfig) -> None:
        self.config = config
        self._closed = asyncio.Event()
        self._writer: asyncio.StreamWriter | None = None

    async def close(self) -> None:
        self._closed.set()
        writer = self._writer
        self._writer = None
        if writer is not None:
            writer.close()
            try:
                await writer.wait_closed()
            except (ConnectionError, OSError):
                pass

    async def lines(self) -> AsyncIterator[str]:
        delay = self.config.reconnect_min_seconds

        while not self._closed.is_set():
            try:
                async for line in self._connection_lines():
                    delay = self.config.reconnect_min_seconds
                    yield line
            except asyncio.CancelledError:
                raise
            except (ConnectionError, OSError, asyncio.TimeoutError) as exc:
                logger.warning(
                    "APRS-IS connection interrupted",
                    extra={
                        "host": self.config.host,
                        "port": self.config.port,
                        "error": str(exc),
                    },
                )

            if self._closed.is_set():
                return

            try:
                await asyncio.wait_for(self._closed.wait(), timeout=delay)
                return
            except asyncio.TimeoutError:
                delay = min(delay * 2.0, self.config.reconnect_max_seconds)

    async def _connection_lines(self) -> AsyncIterator[str]:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(self.config.host, self.config.port),
            timeout=self.config.connect_timeout_seconds,
        )
        self._writer = writer

        try:
            greeting = await asyncio.wait_for(
                reader.readline(),
                timeout=self.config.connect_timeout_seconds,
            )
            if not greeting:
                raise ConnectionError("APRS-IS closed before greeting")

            writer.write((self.config.login_line + "\r\n").encode("ascii"))
            await writer.drain()

            login_response_seen = False

            while not self._closed.is_set():
                raw = await asyncio.wait_for(
                    reader.readline(),
                    timeout=self.config.read_timeout_seconds,
                )
                if not raw:
                    raise ConnectionError("APRS-IS connection closed")

                line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
                if not line:
                    continue

                if line.startswith("#"):
                    if "logresp" in line.lower():
                        login_response_seen = True
                        logger.info(
                            "APRS-IS login acknowledged",
                            extra={
                                "response": line,
                                "filter": self.config.range_filter,
                            },
                        )
                    continue

                if not login_response_seen:
                    logger.debug("APRS packet arrived before explicit login response")

                # APRS-IS limits TNC2 lines to 512 bytes. Reject larger input.
                if len(raw) > 512:
                    logger.warning("oversized APRS line discarded")
                    continue

                yield line
        finally:
            if self._writer is writer:
                self._writer = None
            writer.close()
            try:
                await writer.wait_closed()
            except (ConnectionError, OSError):
                pass
