from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

import discord

from .errors import AprsFiApiError
from .service import AprsFiExteriorService


logger = logging.getLogger(__name__)
VoiceBuilder = Callable[[str, int], Awaitable[discord.File | None]]


class AprsFiDiscordBridge:
    """Send an on-demand aprs.fi report as one Discord message."""

    def __init__(
        self,
        service: AprsFiExteriorService,
        *,
        voice_builder: VoiceBuilder | None = None,
    ) -> None:
        self.service = service
        self.voice_builder = voice_builder

    async def send_report(
        self,
        interaction: discord.Interaction,
        *,
        force_refresh: bool = False,
        attach_voice: bool = False,
    ) -> None:
        if not interaction.response.is_done():
            await interaction.response.defer()

        try:
            report = await self.service.report(
                force_refresh=force_refresh
            )
        except AprsFiApiError:
            logger.exception("aprs.fi exterior report failed")
            await interaction.followup.send(
                "The exterior register could not be reached. "
                "No game state changed.",
                ephemeral=True,
            )
            return

        options: dict[str, Any] = {
            "allowed_mentions": discord.AllowedMentions.none(),
        }

        if attach_voice and self.voice_builder is not None:
            voice_file = await self.voice_builder(
                report.text,
                interaction.id,
            )
            if voice_file is not None:
                options["file"] = voice_file

        await interaction.followup.send(
            report.text,
            **options,
        )
