"""Integration example; copy the relevant parts into discord_adapter.py.

This file is not imported automatically.
"""

from __future__ import annotations

import os

import discord

from uniflora.external_feeds import AprsConfig, AprsFeedService
from uniflora.runtime import Environment


def build_aprs_service(bot: object) -> AprsFeedService:
    """Build a receive-only service bound to Hypha's live channel."""

    async def on_event(event: object, rendered: str) -> None:
        channel_id = bot.routing.current.live_channel_id  # type: ignore[attr-defined]
        channel = bot.get_channel(channel_id)  # type: ignore[attr-defined]
        if channel is None:
            return

        options: dict[str, object] = {
            "allowed_mentions": discord.AllowedMentions.none(),
        }

        # Optional: attach Hypha's voice rendering only for rare event types.
        if getattr(event, "voice", False):
            voice_file = await bot._build_voice_file(  # type: ignore[attr-defined]
                rendered,
                Environment.LIVE,
                source_message_id=int(event.occurred_at.timestamp()),
            )
            if voice_file is not None:
                options["file"] = voice_file

        await channel.send(rendered, **options)  # type: ignore[attr-defined]

    login_call = os.environ["UNIFLORA_APRS_LOGIN_CALL"]
    alias_secret = os.environ["UNIFLORA_APRS_ALIAS_SECRET"]

    config = AprsConfig(
        login_call=login_call,
        center_latitude=25.728333,
        center_longitude=32.601389,
        radius_km=int(os.getenv("UNIFLORA_APRS_RADIUS_KM", "200")),
        host=os.getenv("UNIFLORA_APRS_HOST", "euro.aprs2.net"),
    )

    return AprsFeedService(
        config=config,
        alias_secret=alias_secret,
        on_event=on_event,
        field_name="DEIR EL-MEDINA EXTERIOR FIELD",
    )


# InteriorBot.__init__:
#
#     self._aprs_feed = build_aprs_service(self)
#     self._aprs_task: asyncio.Task[None] | None = None
#
# InteriorBot.setup_hook:
#
#     if self._aprs_task is None:
#         self._aprs_task = asyncio.create_task(
#             self._aprs_feed.run(),
#             name="aprs-exterior-feed",
#         )
#
# InteriorBot.close:
#
#     await self._aprs_feed.close()
#     if self._aprs_task is not None:
#         self._aprs_task.cancel()
#         try:
#             await self._aprs_task
#         except asyncio.CancelledError:
#             pass
#         self._aprs_task = None
