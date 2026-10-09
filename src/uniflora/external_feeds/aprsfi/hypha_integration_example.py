"""Copy the relevant sections into discord_adapter.py.

This example deliberately leaves player authorization in Hypha's existing
command framework. The aprs.fi service itself never mutates game state.
"""

from __future__ import annotations

from pathlib import Path

from uniflora.external_feeds.aprsfi import (
    AprsFiExteriorService,
    AprsFiSettings,
)
from uniflora.external_feeds.aprsfi.discord_bridge import AprsFiDiscordBridge
from uniflora.runtime import Environment


# InteriorBot.__init__
#
# settings_path = (
#     Path(__file__).resolve().parent
#     / "external_feeds"
#     / "aprsfi"
#     / "targets.json"
# )
#
# self._aprsfi_service = AprsFiExteriorService(
#     AprsFiSettings.from_environment(settings_path)
# )
#
# async def build_aprsfi_voice(text: str, source_message_id: int):
#     return await self._build_voice_file(
#         text,
#         Environment.LIVE,
#         source_message_id=source_message_id,
#     )
#
# self._aprsfi_bridge = AprsFiDiscordBridge(
#     self._aprsfi_service,
#     voice_builder=build_aprsfi_voice,
# )


# Inside InteriorBot._build_command_group(), after `group` is created:
#
# @group.command(
#     name="exterior",
#     description="Read the exterior station register",
# )
# async def exterior(interaction: discord.Interaction) -> None:
#     environment = await self._authorize_player(interaction)
#     if environment is None:
#         return
#
#     # Keep the public source tied to the live game unless you explicitly
#     # want isolated test-channel previews.
#     if environment is not Environment.LIVE:
#         await interaction.response.send_message(
#             "The exterior register is attached to the live surface.",
#             ephemeral=True,
#         )
#         return
#
#     await self._aprsfi_bridge.send_report(
#         interaction,
#         attach_voice=False,
#     )
#
#
# If your adapter does not have `_authorize_player`, use the same authorization
# block as another ordinary live player command and call `send_report` only
# after AccessResult.ALLOWED.


# InteriorBot.close(), before `await super().close()`:
#
# await self._aprsfi_service.close()
