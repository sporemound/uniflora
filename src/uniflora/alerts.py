from __future__ import annotations

import logging
from typing import Any

from uniflora.runtime import Environment

logger = logging.getLogger(__name__)


class DiagnosticAlertSink:
    def __init__(self, channel_id: int | None) -> None:
        self.channel_id = channel_id
        self.bot: Any | None = None

    def bind(self, bot: Any) -> None:
        self.bot = bot

    async def alert(self, environment: Environment | str, message: str) -> None:
        environment_name = (
            environment.value if isinstance(environment, Environment) else environment
        )
        logger.warning(
            "operational alert",
            extra={"environment": environment_name, "alert": message[:500]},
        )
        if self.channel_id is None or self.bot is None:
            return
        channel = self.bot.get_channel(self.channel_id)
        if channel is None:
            return
        try:
            await channel.send(f"[OPS:{environment_name.upper()}] {message[:1500]}")
        except Exception:
            logger.exception(
                "diagnostic alert delivery failed", extra={"environment": environment_name}
            )
