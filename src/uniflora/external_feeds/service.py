from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from .aprs_client import AprsClient, AprsConfig
from .detector import AprsChangeDetector, DetectorConfig
from .formatter import render_bbs_event
from .models import AprsEvent
from .parser import AprsParser


logger = logging.getLogger(__name__)
EventCallback = Callable[[AprsEvent, str], Awaitable[None]]


class AprsFeedService:
    """Coordinate the APRS client, parser, detector, and public callback."""

    def __init__(
        self,
        *,
        config: AprsConfig,
        alias_secret: str,
        on_event: EventCallback,
        detector_config: DetectorConfig | None = None,
        field_name: str = "DEIR EL-MEDINA EXTERIOR FIELD",
    ) -> None:
        if not alias_secret:
            raise ValueError("alias_secret must not be empty")

        self.config = config
        self.client = AprsClient(config)
        self.parser = AprsParser(
            center_latitude=config.center_latitude,
            center_longitude=config.center_longitude,
            alias_secret=alias_secret,
        )
        self.detector = AprsChangeDetector(detector_config)
        self.on_event = on_event
        self.field_name = field_name

    async def run(self) -> None:
        async for line in self.client.lines():
            try:
                observation = self.parser.parse_line(line)
                if observation is None:
                    continue

                event = self.detector.consider(observation)
                if event is None:
                    continue

                rendered = render_bbs_event(
                    event,
                    field_name=self.field_name,
                )
                await self.on_event(event, rendered)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("APRS packet processing failed")

    async def close(self) -> None:
        await self.client.close()
