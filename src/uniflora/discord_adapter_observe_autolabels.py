from __future__ import annotations

import asyncio
import io
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from uniflora.access import AccessPolicy, AccessResult, RequestContext
from uniflora.alerts import DiagnosticAlertSink
from uniflora.announcements import SCHEDULED_ANNOUNCEMENTS, ScheduledAnnouncement
from uniflora.config import Settings
from uniflora.engine.actions import (
    AddProposalKickerAction,
    AnnotateDifferenceAction,
    AuditAction,
    AwakenVesselAction,
    BeginStackAction,
    BranchProposalAction,
    CalculateFlowAction,
    CandidateAction,
    ClarifyRecordAction,
    ClassifyContradictionAction,
    CompareRecordsAction,
    ConfirmReconstructionAction,
    ConnectAction,
    ContainAction,
    DocumentAction,
    InoculateAction,
    InspectAction,
    MitigateAction,
    ObserveAction,
    OfferAction,
    OrientLocalAction,
    ProposeCirculationAction,
    ProposeMemoryArchiveAction,
    ProposeProductionReformAction,
    ProposeReciprocityAction,
    ProposeReconstructionAction,
    ProposeRemediationProtocolAction,
    ProposeTranslationAction,
    ReactToStackAction,
    RedesignAction,
    ReduceAction,
    RefuseAction,
    RelayAction,
    RelayRecordAction,
    ReplaceAction,
    RequestSupportAction,
    ResolveStackAction,
    RestAction,
    SampleAction,
    SeparateAction,
    SlowAction,
    SummarizeAction,
    SustainAction,
    UseTriggeredReactionAction,
)
from uniflora.game_service import GameService, PublicResult
from uniflora.health import HealthService
from uniflora.interpretation import MessageSignals, NaturalLanguageInterpreter
from uniflora.openai_privacy import (
    DiscordPrivacyMetadata,
    ParticipantIdentity,
)
from uniflora.operations import OperationsService
from uniflora.runtime import (
    Environment,
    InvalidTransition,
    RoutingSnapshot,
    RuntimeRouting,
    RuntimeSessions,
)
from uniflora.storage.repository import GameRepository, SessionRef, StorageError

logger = logging.getLogger(__name__)


_CIRCULATION_REVISION_PLANS: dict[str, dict[str, str]] = {
    "change": {
        "maintenance": "maintain the Condensation Veil collection surface",
        "reassessment": "reassess Nursery demand and Veil output before the next cycle",
        "branch_condition": "if Nursery demand or Veil output changes",
        "branch_action": "revise delivery to the confirmed need and release unused condensation",
    },
}


def _circulation_revision_plan(trigger: str) -> dict[str, str]:
    """Expand one player-facing choice into the validator's canonical proposal fields."""

    return _CIRCULATION_REVISION_PLANS[trigger]


class SettlementInterventionView(discord.ui.View):
    """Persistent, no-catalogue response controls for an active settlement event."""

    def __init__(self, bot: InteriorBot, labels: dict[str, str] | None = None) -> None:
        super().__init__(timeout=None)
        self.bot = bot
        if labels:
            self.brace.label = labels.get("brace", self.brace.label)[:80]
            self.divert.label = labels.get("divert", self.divert.label)[:80]
            self.release.label = labels.get("release", self.release.label)[:80]

    @discord.ui.button(
        label="Brace (+strain)",
        style=discord.ButtonStyle.primary,
        custom_id="interior:settlement:brace",
    )
    async def brace(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button[SettlementInterventionView],
    ) -> None:
        del button
        await self.bot._perform_settlement_intervention(interaction, "brace")

    @discord.ui.button(
        label="Divert (+burden)",
        style=discord.ButtonStyle.primary,
        custom_id="interior:settlement:divert",
    )
    async def divert(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button[SettlementInterventionView],
    ) -> None:
        del button
        await self.bot._perform_settlement_intervention(interaction, "divert")

    @discord.ui.button(
        label="Release (-escalation, -capacity)",
        style=discord.ButtonStyle.danger,
        custom_id="interior:settlement:release",
    )
    async def release(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button[SettlementInterventionView],
    ) -> None:
        del button
        await self.bot._perform_settlement_intervention(interaction, "release")


def _request_context(interaction: discord.Interaction) -> RequestContext:
    roles = getattr(interaction.user, "roles", ())
    return RequestContext(
        guild_id=interaction.guild_id,
        channel_id=interaction.channel_id,
        user_id=interaction.user.id,
        role_ids=frozenset(role.id for role in roles),
        is_dm=interaction.guild_id is None,
    )


def _message_request_context(message: discord.Message) -> RequestContext:
    roles = getattr(message.author, "roles", ())
    return RequestContext(
        guild_id=message.guild.id if message.guild else None,
        channel_id=message.channel.id,
        user_id=message.author.id,
        role_ids=frozenset(role.id for role in roles),
        is_dm=message.guild is None,
    )


def _participant_identity(user: object) -> ParticipantIdentity:
    names = tuple(
        dict.fromkeys(
            str(value)
            for value in (
                getattr(user, "name", None),
                getattr(user, "display_name", None),
                getattr(user, "global_name", None),
            )
            if value
        )
    )
    return ParticipantIdentity(discord_user_id=int(user.id), names=names)


def _privacy_metadata(message: discord.Message) -> DiscordPrivacyMetadata:
    referenced: list[ParticipantIdentity] = []
    seen = {message.author.id}
    for user in getattr(message, "mentions", ()):
        if user.id not in seen:
            referenced.append(_participant_identity(user))
            seen.add(user.id)
    reply = getattr(getattr(message, "reference", None), "resolved", None)
    if isinstance(reply, discord.Message) and reply.author.id not in seen:
        referenced.append(_participant_identity(reply.author))

    sensitive: list[str] = [
        str(message.id),
        str(message.channel.id),
        str(message.guild.id) if message.guild else "",
    ]
    for value in (
        getattr(message, "created_at", None),
        getattr(message, "edited_at", None),
        getattr(message, "jump_url", None),
        getattr(message.author, "avatar", None),
        getattr(message.author, "display_avatar", None),
    ):
        if value is not None:
            sensitive.append(str(getattr(value, "url", value)))
    reference = getattr(message, "reference", None)
    for field in ("message_id", "channel_id", "guild_id"):
        value = getattr(reference, field, None)
        if value is not None:
            sensitive.append(str(value))
    return DiscordPrivacyMetadata(
        current_participant=_participant_identity(message.author),
        referenced_participants=tuple(referenced),
        sensitive_values=tuple(sensitive),
    )


class InteriorBot(commands.Bot):
    """Discord boundary. It contains no puzzle or progression logic."""

    def __init__(
        self,
        settings: Settings,
        sessions: RuntimeSessions,
        routing: RuntimeRouting,
        health: HealthService,
        repository: GameRepository | None = None,
        session_refs: dict[Environment, SessionRef] | None = None,
        game: GameService | None = None,
        natural_language: NaturalLanguageInterpreter | None = None,
        operations: OperationsService | None = None,
        alerts: DiagnosticAlertSink | None = None,
    ) -> None:
        intents = discord.Intents.none()
        intents.guilds = True
        intents.messages = True
        intents.message_content = True
        super().__init__(command_prefix=commands.when_mentioned, intents=intents)
        self.settings = settings
        self.sessions = sessions
        self.routing = routing
        self.health = health
        self.policy = AccessPolicy()
        self.repository = repository
        self.session_refs = session_refs
        self.game = game
        self.natural_language = natural_language
        self.operations = operations
        self.alerts = alerts
        self._commands_synced = False
        self._settlement_expiry_task: asyncio.Task[None] | None = None
        self._scheduled_announcement_task: asyncio.Task[None] | None = None
        self._position_announcement_locks = {
            environment: asyncio.Lock() for environment in Environment
        }
        self.tree.add_command(self._build_command_group())

    async def setup_hook(self) -> None:
        self.add_view(SettlementInterventionView(self))
        if (
            self.settings.feature_settlement_events
            and self.game is not None
            and self._settlement_expiry_task is None
        ):
            self._settlement_expiry_task = asyncio.create_task(
                self._settlement_expiry_loop(), name="settlement-event-expiry"
            )
        if self.game is not None and self._scheduled_announcement_task is None:
            self._scheduled_announcement_task = asyncio.create_task(
                self._scheduled_announcement_loop(), name="scheduled-announcements"
            )
        guild = discord.Object(id=self.settings.discord_guild_id)
        self.tree.copy_global_to(guild=guild)
        synced = await self.tree.sync(guild=guild)
        self._commands_synced = True
        logger.info(
            "application commands synchronized",
            extra={"guild_id": guild.id, "command_count": len(synced), "environment": "system"},
        )

    async def on_ready(self) -> None:
        self.health.discord_connected = True
        logger.info(
            "discord client ready",
            extra={
                "user_id": self.user.id if self.user else None,
                "guild_id": self.settings.discord_guild_id,
                "environment": "system",
            },
        )
        routing = self.routing.current
        for environment, channel_id in (
            (Environment.LIVE, routing.live_channel_id),
            (Environment.TEST, routing.test_channel_id),
        ):
            channel = self.get_channel(channel_id)
            if channel is not None:
                await self._announce_current_position(environment, channel)

    async def on_disconnect(self) -> None:
        self.health.discord_connected = False
        logger.warning("discord client disconnected", extra={"environment": "system"})

    async def on_raw_message_delete(self, payload: discord.RawMessageDeleteEvent) -> None:
        routing = self.routing.current
        if payload.guild_id != routing.guild_id:
            return
        environment = (
            Environment.LIVE
            if payload.channel_id == routing.live_channel_id
            else Environment.TEST
            if payload.channel_id == routing.test_channel_id
            else None
        )
        if environment is None:
            return
        logger.info(
            "public Discord message deleted; durable game events remain unchanged",
            extra={
                "environment": environment.value,
                "message_id": payload.message_id,
                "channel_id": payload.channel_id,
            },
        )
        if self.alerts is not None:
            await self.alerts.alert(
                environment,
                f"Discord message {payload.message_id} was deleted; no durable event was removed.",
            )

    async def on_message(self, message: discord.Message) -> None:
        if message.guild is None or message.author.bot:
            return
        modes = {
            environment: (await self.sessions.snapshot(environment)).mode
            for environment in Environment
        }
        decision = self.policy.authorize_player(
            _message_request_context(message), self.routing.current, modes
        )
        if decision.result is not AccessResult.ALLOWED or decision.environment is None:
            return
        if self.natural_language is None:
            return
        bot_user_id = self.user.id if self.user else None
        replied = getattr(getattr(message, "reference", None), "resolved", None)
        signals = MessageSignals(
            mentions_bot=bool(
                bot_user_id is not None
                and any(user.id == bot_user_id for user in getattr(message, "mentions", ()))
            ),
            replies_to_bot=bool(
                bot_user_id is not None
                and isinstance(replied, discord.Message)
                and replied.author.id == bot_user_id
            ),
        )
        result = await self.natural_language.handle(
            decision.environment,
            message.author.id,
            message.content,
            signals,
            idempotency_key=f"discord-message:{message.id}",
            privacy_metadata=_privacy_metadata(message),
        )
        if result.should_respond:
            marker = ""
            if (
                decision.environment is Environment.TEST
                and self.settings.test_surface_marker_enabled
            ):
                marker = "[TEST SURFACE]\n"
            rendered = await self._with_phase_footer(result.text, decision.environment)
            await message.channel.send(f"{marker}{rendered}")
            await self._announce_current_position(decision.environment, message.channel)

    async def on_error(self, event_method: str, *args: object, **kwargs: object) -> None:
        del args, kwargs
        logger.exception(
            "unhandled discord event error",
            extra={"event": event_method, "environment": "system"},
        )

    async def close(self) -> None:
        if self._scheduled_announcement_task is not None:
            self._scheduled_announcement_task.cancel()
            try:
                await self._scheduled_announcement_task
            except asyncio.CancelledError:
                pass
            self._scheduled_announcement_task = None
        if self._settlement_expiry_task is not None:
            self._settlement_expiry_task.cancel()
            try:
                await self._settlement_expiry_task
            except asyncio.CancelledError:
                pass
            self._settlement_expiry_task = None
        self.health.discord_connected = False
        await super().close()

    async def _scheduled_announcement_loop(self) -> None:
        await self.wait_until_ready()
        for announcement in sorted(SCHEDULED_ANNOUNCEMENTS, key=lambda item: item.send_at):
            if self.is_closed():
                return
            if self.game is None or await self.game.scheduled_announcement_delivered(
                announcement.announcement_id
            ):
                continue
            delay = max(0.0, (announcement.send_at - discord.utils.utcnow()).total_seconds())
            if delay:
                await asyncio.sleep(delay)
            await self._deliver_scheduled_announcement(announcement)

    async def _deliver_scheduled_announcement(self, announcement: ScheduledAnnouncement) -> None:
        if discord.utils.utcnow() > announcement.expires_at:
            logger.warning(
                "stale scheduled announcement skipped",
                extra={
                    "environment": Environment.LIVE.value,
                    "announcement_id": announcement.announcement_id,
                },
            )
            return
        if self.game is None or await self.game.scheduled_announcement_delivered(
            announcement.announcement_id
        ):
            return
        guild = self.get_guild(self.routing.current.guild_id)
        channel = (
            discord.utils.get(guild.text_channels, name=announcement.channel_name)
            if guild is not None
            else None
        )
        if channel is None:
            logger.error(
                "scheduled announcement channel unavailable",
                extra={
                    "environment": Environment.LIVE.value,
                    "announcement_id": announcement.announcement_id,
                    "channel_name": announcement.channel_name,
                },
            )
            return
        message = await channel.send(
            announcement.text,
            allowed_mentions=discord.AllowedMentions.none(),
        )
        await self.game.mark_scheduled_announcement_delivered(
            announcement.announcement_id, channel.id, message.id
        )

    async def _settlement_expiry_loop(self) -> None:
        await self.wait_until_ready()
        while not self.is_closed():
            await asyncio.sleep(self.settings.settlement_event_poll_seconds)
            try:
                await self._expire_settlement_event_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "settlement event expiry check failed",
                    extra={"environment": Environment.LIVE.value},
                )

    async def _expire_settlement_event_once(self) -> None:
        if self.game is None:
            return
        result = await self.game.expire_settlement_event(Environment.LIVE)
        if not result.accepted:
            return
        channel = self.get_channel(self.routing.current.live_channel_id)
        if channel is None:
            logger.warning(
                "expired settlement event could not be posted; live channel unavailable",
                extra={"environment": Environment.LIVE.value},
            )
            return
        await channel.send(  # type: ignore[attr-defined]
            await self._with_phase_footer(result.text, Environment.LIVE),
            allowed_mentions=discord.AllowedMentions.none(),
        )
        await self._announce_current_position(Environment.LIVE, channel)

    async def _authorize_admin(
        self,
        interaction: discord.Interaction,
        required_environment: Environment | None = None,
    ) -> Environment | None:
        decision = self.policy.authorize_admin(
            _request_context(interaction), self.routing.current, required_environment
        )
        if decision.result is AccessResult.ALLOWED:
            return decision.environment
        # Discord requires an acknowledgement for slash commands. This is an
        # operational denial only; no clue or game fact is sent privately.
        await interaction.response.send_message(
            "The interface is inactive for this request.", ephemeral=True
        )
        logger.warning(
            "discord command rejected",
            extra={
                "environment": decision.environment.value if decision.environment else "outside",
                "reason": decision.reason,
                "guild_id": interaction.guild_id,
                "channel_id": interaction.channel_id,
                "user_id": interaction.user.id,
            },
        )
        return None

    async def _authorize_player(
        self, interaction: discord.Interaction
    ) -> Environment | None:
        modes = {
            environment: (await self.sessions.snapshot(environment)).mode
            for environment in Environment
        }
        decision = self.policy.authorize_player(
            _request_context(interaction), self.routing.current, modes
        )
        if decision.result is AccessResult.ALLOWED:
            return decision.environment
        await interaction.response.send_message(
            "The interface is inactive for this request.", ephemeral=True
        )
        return None

    async def _authorize_diagnostic(
        self, interaction: discord.Interaction
    ) -> bool:
        decision = self.policy.authorize_diagnostic(
            _request_context(interaction), self.routing.current
        )
        if decision.result is AccessResult.ALLOWED:
            return True
        await interaction.response.send_message(
            "The diagnostic interface is inactive for this request.", ephemeral=True
        )
        return False

    async def _send(
        self,
        interaction: discord.Interaction,
        message: str,
        environment: Environment,
        view: discord.ui.View | None = None,
    ) -> None:
        marker = ""
        if environment is Environment.TEST and self.settings.test_surface_marker_enabled:
            marker = "[TEST SURFACE]\n"
        rendered = await self._with_phase_footer(message, environment)
        chunks = self._discord_chunks(rendered, marker)
        if view is None:
            await interaction.response.send_message(chunks[0])
        else:
            await interaction.response.send_message(
                chunks[0],
                view=view,
                allowed_mentions=discord.AllowedMentions.none(),
            )
        for chunk in chunks[1:]:
            await interaction.followup.send(chunk)

    async def _send_deferred_action(
        self,
        interaction: discord.Interaction,
        result: PublicResult,
        environment: Environment,
        view: discord.ui.View | None = None,
    ) -> None:
        message = result.text
        phase_footer = result.phase_footer
        rendered = (
            f"{message}\n\n{phase_footer}"
            if phase_footer
            else await self._with_phase_footer(message, environment)
        )
        marker = ""
        if environment is Environment.TEST and self.settings.test_surface_marker_enabled:
            marker = "[TEST SURFACE]\n"
        chunks = self._discord_chunks(rendered, marker)
        attachment = result.attachment
        file = (
            discord.File(
                io.BytesIO(attachment.image_bytes),
                filename=attachment.image_filename,
                description=attachment.image_alt_text,
            )
            if attachment is not None
            else None
        )
        send_options: dict[str, Any] = {"allowed_mentions": discord.AllowedMentions.none()}
        if file is not None:
            send_options["file"] = file
        if view is not None:
            send_options["view"] = view
        await interaction.followup.send(chunks[0], **send_options)
        for chunk in chunks[1:]:
            await interaction.followup.send(
                chunk,
                allowed_mentions=discord.AllowedMentions.none(),
            )

    async def _with_phase_footer(self, message: str, environment: Environment) -> str:
        if self.game is None:
            return message
        try:
            footer = await self.game.current_phase_footer(environment)
        except StorageError:
            logger.warning(
                "current phase unavailable for Discord reply",
                extra={"environment": environment.value},
            )
            return message
        return f"{message}\n\n{footer}"

    @staticmethod
    def _discord_chunks(message: str, marker: str = "") -> list[str]:
        limit = 2000 - len(marker)
        remaining = message
        chunks: list[str] = []
        while remaining:
            if len(remaining) <= limit:
                chunks.append(f"{marker}{remaining}")
                break
            split_at = remaining.rfind("\n", 0, limit + 1)
            if split_at <= 0:
                split_at = remaining.rfind(" ", 0, limit + 1)
            if split_at <= 0:
                split_at = limit
            chunks.append(f"{marker}{remaining[:split_at].rstrip()}")
            remaining = remaining[split_at:].lstrip()
        return chunks or [marker.rstrip()]

    async def _announce_current_position(self, environment: Environment, channel: object) -> None:
        if self.game is None:
            return
        async with self._position_announcement_locks[environment]:
            try:
                marker = ""
                if environment is Environment.TEST and self.settings.test_surface_marker_enabled:
                    marker = "[TEST SURFACE]\n"
                reveal = await self.game.pending_artifact_reveal(environment)
                if reveal is not None:
                    reveal_attachment = discord.File(
                        io.BytesIO(reveal.image_bytes),
                        filename=reveal.image_filename,
                        description=reveal.image_alt_text,
                    )
                    reveal_message = await channel.send(  # type: ignore[attr-defined]
                        f"{marker}{reveal.introduction}", file=reveal_attachment
                    )
                    recorded = await self.game.mark_artifact_reveal_delivered(
                        environment, reveal.reveal_id, int(reveal_message.id)
                    )
                    if not recorded:
                        logger.warning(
                            "artifact reveal was posted but its delivery was not recorded",
                            extra={
                                "environment": environment.value,
                                "reveal_id": reveal.reveal_id,
                                "message_id": int(reveal_message.id),
                            },
                        )
                        return

                announcement = await self.game.pending_position_announcement(environment)
                message = None
                if announcement is not None:
                    attachments = [
                        discord.File(
                            io.BytesIO(image.image_bytes),
                            filename=image.image_filename,
                            description=image.image_alt_text,
                        )
                        for image in (announcement, *announcement.additional_images)
                    ]
                    message = await channel.send(  # type: ignore[attr-defined]
                        f"{marker}{announcement.introduction}", files=attachments
                    )
                    recorded = await self.game.mark_position_announcement_delivered(
                        environment, announcement.position, int(message.id)
                    )
                    if not recorded:
                        logger.warning(
                            "position introduction was posted but its delivery was not recorded",
                            extra={
                                "environment": environment.value,
                                "position": announcement.position,
                                "message_id": int(message.id),
                            },
                        )
                        return

                pending_pin = await self.game.pending_position_pin(environment)
                if pending_pin is None:
                    return
                position, message_id = pending_pin
                if message is None or int(message.id) != message_id:
                    try:
                        message = await channel.fetch_message(message_id)  # type: ignore[attr-defined]
                    except discord.NotFound:
                        await self.game.mark_position_announcement_missing(
                            environment, position, message_id
                        )
                        logger.info(
                            "deleted position announcement retired without reposting",
                            extra={
                                "environment": environment.value,
                                "position": position,
                                "message_id": message_id,
                            },
                        )
                        return
                try:
                    await message.pin(reason=f"The Missing Interior Position {position} reference")
                except discord.NotFound:
                    await self.game.mark_position_announcement_missing(
                        environment, position, message_id
                    )
                    return
                await self.game.mark_position_announcement_pinned(environment, position, message_id)
            except discord.HTTPException as exc:
                logger.warning(
                    "artifact or position presentation delivery failed",
                    exc_info=(type(exc), exc, exc.__traceback__),
                    extra={"environment": environment.value},
                )
                if self.alerts is not None:
                    await self.alerts.alert(
                        environment,
                        "A public image could not be posted or pinned; Hypha will retry.",
                    )
            except Exception:
                logger.exception(
                    "public presentation processing failed",
                    extra={"environment": environment.value},
                )

    @staticmethod
    def _environment(value: str) -> Environment | None:
        try:
            return Environment(value.casefold())
        except ValueError:
            return None

    async def _perform_action(
        self, interaction: discord.Interaction, action: CandidateAction
    ) -> None:
        environment = await self._authorize_player(interaction)
        if environment is None:
            return
        if self.game is None:
            await self._send(interaction, "Deterministic game content is unavailable.", environment)
            return
        summary_requested = isinstance(action, SummarizeAction)
        if summary_requested:
            await interaction.response.defer()
        result = await self.game.act(
            environment,
            interaction.user.id,
            action,
            idempotency_key=f"discord-interaction:{interaction.id}",
        )
        view = None
        if await self.game.has_active_settlement_event(environment):
            view = await self._settlement_intervention_view(environment)
        if summary_requested:
            await self._send_deferred_action(
                interaction,
                result,
                environment,
                view=view,
            )
        else:
            await self._send(interaction, result.text, environment, view=view)
        if result.accepted and interaction.channel is not None:
            await self._announce_current_position(environment, interaction.channel)

    async def _perform_settlement_intervention(
        self, interaction: discord.Interaction, method: str
    ) -> None:
        context = _request_context(interaction)
        environment = await self._authorize_player(interaction)
        if environment is None:
            return
        if environment is Environment.LIVE and (
            self.routing.current.mycotroph_role_id not in context.role_ids
        ):
            await self._send(
                interaction,
                "A live Mycotroph role is required for settlement intervention.",
                environment,
            )
            return
        if self.game is None:
            await self._send(interaction, "Settlement events are unavailable.", environment)
            return
        label = getattr(interaction.user, "display_name", None) or getattr(
            interaction.user, "name", "A Mycotroph"
        )
        result = await self.game.intervene_settlement_event(
            environment,
            interaction.user.id,
            str(label),
            method,
            idempotency_key=f"discord-interaction:{interaction.id}",
        )
        view = None
        if result.accepted and await self.game.has_active_settlement_event(environment):
            view = await self._settlement_intervention_view(environment)
        await self._send(interaction, result.text, environment, view=view)

    async def _settlement_intervention_view(
        self, environment: Environment
    ) -> SettlementInterventionView:
        labels = None
        if self.game is not None:
            label_loader = getattr(self.game, "settlement_intervention_labels", None)
            if label_loader is not None:
                labels = await label_loader(environment)
        return SettlementInterventionView(self, labels)

    async def _transition(
        self,
        interaction: discord.Interaction,
        environment: Environment,
        action: str,
        operation: Callable[[Environment, str | None], Awaitable[object]],
    ) -> None:
        authorized = await self._authorize_admin(interaction, environment)
        if authorized is None:
            return
        try:
            snapshot = await operation(environment, f"discord:{interaction.user.id}")
        except InvalidTransition as exc:
            await self._send(interaction, str(exc), environment)
            return
        mode = snapshot.mode.value
        logger.info(
            "session mode changed",
            extra={
                "environment": environment.value,
                "action": action,
                "mode": mode,
                "admin_user_id": interaction.user.id,
            },
        )
        await self._send(
            interaction, f"{environment.value.title()} session is {mode}.", environment
        )

    def _build_command_group(self) -> app_commands.Group:
        group = app_commands.Group(name="interior", description="Controls")
        test_tools = app_commands.Group(name="test", description="Isolated test utilities")
        ops_tools = app_commands.Group(name="ops", description="Routing and features")

        async def entity_id_autocomplete(
            interaction: discord.Interaction, current: str
        ) -> list[app_commands.Choice[str]]:
            if self.game is None:
                return []
            modes = {
                environment: (await self.sessions.snapshot(environment)).mode
                for environment in Environment
            }
            decision = self.policy.authorize_player(
                _request_context(interaction), self.routing.current, modes
            )
            if decision.result is not AccessResult.ALLOWED or decision.environment is None:
                return []
            choices = await self.game.entity_choices(decision.environment, current)
            return [
                app_commands.Choice(name=label[:100], value=value)
                for label, value in choices[:25]
                if len(value) <= 100
            ]

        async def maintenance_target_autocomplete(
            interaction: discord.Interaction, current: str
        ) -> list[app_commands.Choice[str]]:
            if self.game is None:
                return []
            modes = {
                environment: (await self.sessions.snapshot(environment)).mode
                for environment in Environment
            }
            decision = self.policy.authorize_player(
                _request_context(interaction), self.routing.current, modes
            )
            if decision.result is not AccessResult.ALLOWED or decision.environment is None:
                return []
            choices = await self.game.maintenance_target_choices(
                decision.environment, current
            )
            return [
                app_commands.Choice(name=label[:100], value=value)
                for label, value in choices[:25]
                if len(value) <= 100
            ]

        async def observable_entity_autocomplete(
            interaction: discord.Interaction, current: str
        ) -> list[app_commands.Choice[str]]:
            print(
                "OBS CALLBACK FIRED",
                {
                    "user_id": interaction.user.id,
                    "guild_id": interaction.guild_id,
                    "channel_id": interaction.channel_id,
                    "current": current,
                },
                flush=True,
            )

            if self.game is None:
                print("OBS FAILURE: self.game is None", flush=True)
                return []

            try:
                modes = {
                    environment: (await self.sessions.snapshot(environment)).mode
                    for environment in Environment
                }
                print(
                    "OBS SESSION MODES",
                    {environment.value: mode.value for environment, mode in modes.items()},
                    flush=True,
                )

                context = _request_context(interaction)
                print(
                    "OBS REQUEST CONTEXT",
                    {
                        "guild_id": context.guild_id,
                        "channel_id": context.channel_id,
                        "user_id": context.user_id,
                        "role_ids": sorted(context.role_ids),
                        "is_dm": context.is_dm,
                    },
                    flush=True,
                )

                routing = self.routing.current
                print(
                    "OBS ROUTING",
                    {
                        "guild_id": routing.guild_id,
                        "live_channel_id": routing.live_channel_id,
                        "test_channel_id": routing.test_channel_id,
                        "mycotroph_role_id": routing.mycotroph_role_id,
                        "admin_user_ids": sorted(routing.admin_user_ids),
                    },
                    flush=True,
                )

                decision = self.policy.authorize_player(context, routing, modes)
                print(
                    "OBS AUTHORIZATION",
                    {
                        "result": decision.result.value,
                        "environment": (
                            decision.environment.value if decision.environment is not None else None
                        ),
                        "reason": decision.reason,
                    },
                    flush=True,
                )

                if (
                    decision.result is not AccessResult.ALLOWED
                    or decision.environment is None
                ):
                    print("OBS FAILURE: authorization denied", flush=True)
                    return []

                # Observe needs both kinds of spoiler-safe labels:
                # 1. discovery cues that are still available to inspect; and
                # 2. entities already made public by unlocked observations.
                #
                # The discovery catalogue can legitimately become empty after
                # all current cues have been inspected.  Using it alone makes
                # Discord's selector look broken even though known entities
                # remain valid Observe inputs.
                discovery_choices = await self.game.observable_entity_choices(
                    decision.environment
                )
                known_choices = await self.game.entity_choices(
                    decision.environment, current
                )

                print(
                    "OBS DISCOVERY CHOICES",
                    {
                        "count": len(discovery_choices),
                        "choices": discovery_choices,
                    },
                    flush=True,
                )
                print(
                    "OBS KNOWN ENTITY CHOICES",
                    {
                        "count": len(known_choices),
                        "choices": known_choices,
                    },
                    flush=True,
                )

                choices: list[tuple[str, str]] = []
                seen_values: set[str] = set()
                for label, value in (*discovery_choices, *known_choices):
                    normalized_value = value.casefold()
                    if normalized_value in seen_values:
                        continue
                    seen_values.add(normalized_value)
                    choices.append((label, value))

                print(
                    "OBS MERGED CHOICES",
                    {"count": len(choices), "choices": choices},
                    flush=True,
                )

                query = current.strip().casefold()
                rendered = [
                    app_commands.Choice(name=label[:100], value=value)
                    for label, value in choices
                    if len(value) <= 100
                    and (
                        not query
                        or query in label.casefold()
                        or query in value.casefold()
                    )
                ][:25]
                print(
                    "OBS RENDERED CHOICES",
                    {
                        "count": len(rendered),
                        "choices": [(choice.name, choice.value) for choice in rendered],
                    },
                    flush=True,
                )
                return rendered

            except Exception as exc:
                print(
                    "OBS EXCEPTION",
                    {"type": type(exc).__name__, "message": str(exc)},
                    flush=True,
                )
                logger.exception("observe autocomplete failed")
                return []

        async def inspectable_entity_autocomplete(
            interaction: discord.Interaction, current: str
        ) -> list[app_commands.Choice[str]]:
            if self.game is None:
                return []
            modes = {
                environment: (await self.sessions.snapshot(environment)).mode
                for environment in Environment
            }
            decision = self.policy.authorize_player(
                _request_context(interaction), self.routing.current, modes
            )
            if decision.result is not AccessResult.ALLOWED or decision.environment is None:
                return []
            choices = await self.game.inspectable_entity_choices(
                decision.environment, current
            )
            return [
                app_commands.Choice(name=label[:100], value=value)
                for label, value in choices
                if len(value) <= 100
            ]

        def attach_entity_autocomplete(
            command: app_commands.Command[Any, ..., Any], *parameters: str
        ) -> None:
            for parameter in parameters:
                command.autocomplete(parameter)(entity_id_autocomplete)

        def attach_configured_autocomplete(
            command: app_commands.Command[Any, ..., Any], parameter: str, field: str
        ) -> None:
            async def configured_autocomplete(
                interaction: discord.Interaction, current: str
            ) -> list[app_commands.Choice[str]]:
                if self.game is None:
                    return []
                modes = {
                    environment: (await self.sessions.snapshot(environment)).mode
                    for environment in Environment
                }
                decision = self.policy.authorize_player(
                    _request_context(interaction), self.routing.current, modes
                )
                if (
                    decision.result is not AccessResult.ALLOWED
                    or decision.environment is None
                ):
                    return []
                choices = await self.game.configured_choices(
                    decision.environment, field, current
                )
                return [
                    app_commands.Choice(name=label[:100], value=value)
                    for label, value in choices
                    if len(value) <= 100
                ]

            command.autocomplete(parameter)(configured_autocomplete)

        @ops_tools.command(name="setup", description="Validate Discord surfaces")
        async def setup(interaction: discord.Interaction) -> None:
            environment = await self._authorize_admin(interaction)
            if environment is None:
                return
            routing = self.routing.current
            await self._send(
                interaction,
                (
                    "Configuration is valid. "
                    f"Live: <#{routing.live_channel_id}>; test: <#{routing.test_channel_id}>; "
                    f"diagnostic: "
                    + (
                        f"<#{routing.diagnostic_channel_id}>"
                        if routing.diagnostic_channel_id is not None
                        else "not configured"
                    )
                    + f"; role: <@&{routing.mycotroph_role_id}>."
                ),
                environment,
            )

        @ops_tools.command(name="status", description="Live mode")
        async def status(interaction: discord.Interaction) -> None:
            environment = await self._authorize_admin(interaction, Environment.LIVE)
            if environment is None:
                return
            snapshot = await self.sessions.snapshot(Environment.LIVE)
            await self._send(interaction, f"Live session: {snapshot.mode.value}.", environment)

        @group.command(name="pause", description="Pause the live session")
        async def pause(interaction: discord.Interaction) -> None:
            await self._transition(interaction, Environment.LIVE, "pause", self.sessions.pause)

        @group.command(name="resume", description="Resume the live session")
        async def resume(interaction: discord.Interaction) -> None:
            await self._transition(interaction, Environment.LIVE, "resume", self.sessions.resume)

        @group.command(name="intervene", description="Event response")
        @app_commands.choices(
            method=[
                app_commands.Choice(name="brace", value="brace"),
                app_commands.Choice(name="divert", value="divert"),
                app_commands.Choice(name="release", value="release"),
            ]
        )
        async def intervene(
            interaction: discord.Interaction, method: app_commands.Choice[str]
        ) -> None:
            await self._perform_settlement_intervention(interaction, method.value)

        @ops_tools.command(name="set-live-channel", description="Persist the live puzzle channel")
        @app_commands.describe(channel="The exact live puzzle text channel")
        async def set_live_channel(
            interaction: discord.Interaction, channel: discord.TextChannel
        ) -> None:
            environment = await self._authorize_admin(interaction)
            if environment is None:
                return
            if channel.guild.id != self.routing.current.guild_id:
                await self._send(
                    interaction, "Channel must belong to the configured guild.", environment
                )
                return
            try:
                await self.routing.set_live_channel(channel.id)
            except ValueError as exc:
                await self._send(interaction, str(exc), environment)
                return
            logger.info(
                "live channel override set",
                extra={
                    "environment": "live",
                    "channel_id": channel.id,
                    "admin_user_id": interaction.user.id,
                },
            )
            await self._send(
                interaction,
                f"Live channel persisted as {channel.mention}.",
                environment,
            )

        @ops_tools.command(name="set-test-channel", description="Persist the test puzzle channel")
        @app_commands.describe(channel="The exact administrator-only test text channel")
        async def set_test_channel(
            interaction: discord.Interaction, channel: discord.TextChannel
        ) -> None:
            environment = await self._authorize_admin(interaction)
            if environment is None:
                return
            if channel.guild.id != self.routing.current.guild_id:
                await self._send(
                    interaction, "Channel must belong to the configured guild.", environment
                )
                return
            try:
                await self.routing.set_test_channel(channel.id)
            except ValueError as exc:
                await self._send(interaction, str(exc), environment)
                return
            logger.info(
                "test channel override set",
                extra={
                    "environment": "test",
                    "channel_id": channel.id,
                    "admin_user_id": interaction.user.id,
                },
            )
            await self._send(
                interaction,
                f"Test channel persisted as {channel.mention}.",
                environment,
            )

        @ops_tools.command(name="set-role", description="Persist the live mycotroph role")
        @app_commands.describe(role="The role authorized for live play")
        async def set_role(interaction: discord.Interaction, role: discord.Role) -> None:
            environment = await self._authorize_admin(interaction)
            if environment is None:
                return
            if role.guild.id != self.routing.current.guild_id:
                await self._send(
                    interaction, "Role must belong to the configured guild.", environment
                )
                return
            await self.routing.set_role(role.id)
            logger.info(
                "mycotroph role override set",
                extra={
                    "environment": "live",
                    "role_id": role.id,
                    "admin_user_id": interaction.user.id,
                },
            )
            await self._send(
                interaction,
                f"Live player role persisted as {role.mention}.",
                environment,
            )

        @ops_tools.command(
            name="set-diagnostic-channel", description="Persist the administrator diagnostics"
        )
        async def set_diagnostic_channel(
            interaction: discord.Interaction, channel: discord.TextChannel
        ) -> None:
            environment = await self._authorize_admin(interaction)
            if environment is None:
                return
            if channel.guild.id != self.routing.current.guild_id:
                await self._send(
                    interaction, "Channel must belong to the configured guild.", environment
                )
                return
            try:
                await self.routing.set_diagnostic_channel(channel.id)
            except (ValueError, StorageError) as exc:
                await self._send(interaction, str(exc), environment)
                return
            if self.alerts is not None:
                self.alerts.channel_id = channel.id
            await self._send(
                interaction,
                f"Diagnostic channel persisted as {channel.mention}.",
                environment,
            )

        @ops_tools.command(name="feature", description="Enable or disable a major mechanic")
        async def set_feature(
            interaction: discord.Interaction, environment: str, feature: str, enabled: bool
        ) -> None:
            selected = self._environment(environment)
            if selected is None:
                await interaction.response.send_message("Environment must be live or test.")
                return
            authorized = await self._authorize_admin(interaction, selected)
            if authorized is None:
                return
            if self.operations is None:
                await self._send(interaction, "Operational controls are unavailable.", selected)
                return
            try:
                result = await self.operations.set_feature(
                    selected, feature, enabled, interaction.user.id
                )
            except StorageError as exc:
                await self._send(interaction, str(exc), selected)
                return
            await self._send(interaction, result.text, selected)

        @ops_tools.command(name="cycle-close", description="Emergency recovery")
        async def cycle_close(
            interaction: discord.Interaction, environment: str, reason: str, confirm: bool
        ) -> None:
            selected = self._environment(environment)
            if selected is None:
                await interaction.response.send_message("Environment must be live or test.")
                return
            authorized = await self._authorize_admin(interaction, selected)
            if authorized is None:
                return
            if not confirm:
                await self._send(
                    interaction, "Cycle close cancelled; set confirm to true.", selected
                )
                return
            if self.game is None:
                await self._send(
                    interaction, "Deterministic game content is unavailable.", selected
                )
                return
            result = await self.game.close_cycle(selected, interaction.user.id, reason)
            await self._send(interaction, result.text, selected)

        @test_tools.command(name="status", description="Show the isolated test session status")
        async def test_status(interaction: discord.Interaction) -> None:
            environment = await self._authorize_admin(interaction, Environment.TEST)
            if environment is None:
                return
            snapshot = await self.sessions.snapshot(Environment.TEST)
            await self._send(interaction, f"Test session: {snapshot.mode.value}.", environment)

        @test_tools.command(name="settlement-event", description="Open test event")
        async def test_settlement_event(interaction: discord.Interaction) -> None:
            environment = await self._authorize_admin(interaction, Environment.TEST)
            if environment is None:
                return
            if self.game is None:
                await self._send(interaction, "Settlement events are unavailable.", environment)
                return
            result = await self.game.open_test_settlement_event(
                interaction.user.id,
                idempotency_key=f"discord-interaction:{interaction.id}",
            )
            view = (
                await self._settlement_intervention_view(environment) if result.accepted else None
            )
            await self._send(interaction, result.text, environment, view=view)

        @test_tools.command(name="start", description="Start the isolated test session")
        async def test_start(interaction: discord.Interaction) -> None:
            await self._transition(interaction, Environment.TEST, "test-start", self.sessions.start)

        @test_tools.command(name="pause", description="Pause the isolated test session")
        async def test_pause(interaction: discord.Interaction) -> None:
            await self._transition(interaction, Environment.TEST, "test-pause", self.sessions.pause)

        @test_tools.command(name="resume", description="Resume the isolated test session")
        async def test_resume(interaction: discord.Interaction) -> None:
            await self._transition(
                interaction, Environment.TEST, "test-resume", self.sessions.resume
            )

        @test_tools.command(name="as", description="Select a simulated test participant")
        @app_commands.describe(identity="Identity slug, or self")
        async def test_as(interaction: discord.Interaction, identity: str) -> None:
            environment = await self._authorize_admin(interaction, Environment.TEST)
            if environment is None:
                return
            if self.repository is None or self.session_refs is None:
                await self._send(
                    interaction, "Persistent test identities are unavailable.", environment
                )
                return
            try:
                participant_id = await self.repository.select_test_identity(
                    self.session_refs[Environment.TEST], identity, interaction.user.id
                )
            except StorageError as exc:
                await self._send(interaction, str(exc), environment)
                return
            await self._send(interaction, f"Active participant: `{participant_id}`.", environment)

        @test_tools.command(name="list-identities", description="List test participants")
        async def test_list_identities(interaction: discord.Interaction) -> None:
            environment = await self._authorize_admin(interaction, Environment.TEST)
            if environment is None:
                return
            if self.repository is None or self.session_refs is None:
                await self._send(
                    interaction, "Persistent test identities are unavailable.", environment
                )
                return
            identities = await self.repository.list_test_identities(
                self.session_refs[Environment.TEST]
            )
            slugs = ", ".join(item["slug"] for item in identities)
            await self._send(interaction, f"Available identities: {slugs}; self.", environment)

        @test_tools.command(name="create-identity", description="Create a test-only identity")
        @app_commands.describe(identity="Lowercase identity slug")
        async def test_create_identity(interaction: discord.Interaction, identity: str) -> None:
            environment = await self._authorize_admin(interaction, Environment.TEST)
            if environment is None:
                return
            if self.repository is None or self.session_refs is None:
                await self._send(
                    interaction, "Persistent test identities are unavailable.", environment
                )
                return
            try:
                participant_id = await self.repository.create_test_identity(
                    self.session_refs[Environment.TEST], identity, interaction.user.id
                )
            except StorageError as exc:
                await self._send(interaction, str(exc), environment)
                return
            await self._send(interaction, f"Created `{participant_id}`.", environment)

        @test_tools.command(name="remove-identity", description="Remove a test-only identity")
        @app_commands.describe(identity="Identity slug", confirm="Confirm destructive removal")
        async def test_remove_identity(
            interaction: discord.Interaction, identity: str, confirm: bool
        ) -> None:
            environment = await self._authorize_admin(interaction, Environment.TEST)
            if environment is None:
                return
            if not confirm:
                await self._send(
                    interaction, "Removal cancelled; set confirm to true.", environment
                )
                return
            if self.repository is None or self.session_refs is None:
                await self._send(
                    interaction, "Persistent test identities are unavailable.", environment
                )
                return
            try:
                await self.repository.remove_test_identity(
                    self.session_refs[Environment.TEST], identity, interaction.user.id
                )
            except StorageError as exc:
                await self._send(interaction, str(exc), environment)
                return
            await self._send(interaction, f"Removed test identity `{identity}`.", environment)

        @group.command(name="position", description="Current public position")
        async def position(interaction: discord.Interaction) -> None:
            environment = await self._authorize_player(interaction)
            if environment is None:
                return
            if self.game is None:
                await self._send(
                    interaction, "Deterministic game content is unavailable.", environment
                )
                return
            await self._send(
                interaction,
                await self.game.position(environment, interaction.user.id),
                environment,
            )

        @group.command(name="next", description="Useful actions now")
        async def next_steps(interaction: discord.Interaction) -> None:
            environment = await self._authorize_player(interaction)
            if environment is None:
                return
            if self.game is None:
                await self._send(
                    interaction, "Deterministic game content is unavailable.", environment
                )
                return
            await self._send(
                interaction,
                await self.game.next_steps(environment, interaction.user.id),
                environment,
            )

        @group.command(name="map", description="Public map")
        async def current_map(interaction: discord.Interaction) -> None:
            environment = await self._authorize_player(interaction)
            if environment is None:
                return
            if self.game is None:
                await self._send(
                    interaction, "Deterministic game content is unavailable.", environment
                )
                return
            await interaction.response.defer()
            map_image = await self.game.current_map(environment)
            if map_image is None:
                marker = (
                    "[TEST SURFACE]\n"
                    if environment is Environment.TEST and self.settings.test_surface_marker_enabled
                    else ""
                )
                await interaction.followup.send(
                    f"{marker}No public map has been recorded for the current position yet.",
                    allowed_mentions=discord.AllowedMentions.none(),
                )
                return
            marker = (
                "[TEST SURFACE]\n"
                if environment is Environment.TEST and self.settings.test_surface_marker_enabled
                else ""
            )
            attachment = discord.File(
                io.BytesIO(map_image.image_bytes),
                filename=map_image.image_filename,
                description=map_image.image_alt_text,
            )
            await interaction.followup.send(
                f"{marker}Current public-awareness map.",
                file=attachment,
                allowed_mentions=discord.AllowedMentions.none(),
            )

        @group.command(name="chart", description="Command chart")
        async def current_chart(interaction: discord.Interaction) -> None:
            environment = await self._authorize_player(interaction)
            if environment is None:
                return
            if self.game is None:
                await self._send(
                    interaction, "Deterministic game content is unavailable.", environment
                )
                return
            await interaction.response.defer()
            chart = await self.game.current_cycle_chart(environment)
            marker = (
                "[TEST SURFACE]\n"
                if environment is Environment.TEST and self.settings.test_surface_marker_enabled
                else ""
            )
            if chart is None:
                await interaction.followup.send(
                    f"{marker}No command chart has been recorded for the current position yet.",
                    allowed_mentions=discord.AllowedMentions.none(),
                )
                return
            attachment = discord.File(
                io.BytesIO(chart.image_bytes),
                filename=chart.image_filename,
                description=chart.image_alt_text,
            )
            await interaction.followup.send(
                f"{marker}Current position command chart.",
                file=attachment,
                allowed_mentions=discord.AllowedMentions.none(),
            )

        @group.command(name="recall", description="Recall confirmed public discoveries only")
        async def recall(interaction: discord.Interaction) -> None:
            environment = await self._authorize_player(interaction)
            if environment is None:
                return
            if self.game is None:
                await self._send(
                    interaction, "Deterministic game content is unavailable.", environment
                )
                return
            view = None
            if await self.game.has_active_settlement_event(environment):
                view = await self._settlement_intervention_view(environment)
            await self._send(
                interaction,
                await self.game.recall(environment),
                environment,
                view=view,
            )

        @group.command(name="accessibility", description="Show explicit public play alternatives")
        async def accessibility(interaction: discord.Interaction) -> None:
            environment = await self._authorize_player(interaction)
            if environment is None:
                return
            if self.game is None:
                await self._send(
                    interaction, "Deterministic game content is unavailable.", environment
                )
                return
            await self._send(interaction, await self.game.accessibility(environment), environment)

        actions = app_commands.Group(name="act", description="Actions")

        @actions.command(name="orient", description="Take only a narrow local bearing")
        async def act_orient(interaction: discord.Interaction, atmospheric_text: str = "") -> None:
            await self._perform_action(
                interaction,
                OrientLocalAction(action="orient_local", atmospheric_text=atmospheric_text),
            )

        @actions.command(name="awaken", description="Set rootglass fate")
        @app_commands.choices(
            fate=[
                app_commands.Choice(name="plant", value="plant"),
                app_commands.Choice(name="open", value="open"),
                app_commands.Choice(name="keep", value="keep"),
            ]
        )
        async def act_awaken(
            interaction: discord.Interaction,
            name: str,
            fate: app_commands.Choice[str],
        ) -> None:
            await self._perform_action(
                interaction,
                AwakenVesselAction(action="awaken_vessel", name=name, fate=fate.value),
            )

        @actions.command(
            name="observe", description="Observe a known entity or an inspectable map cue"
        )
        async def act_observe(interaction: discord.Interaction, entity: str) -> None:
            await self._perform_action(
                interaction, ObserveAction(action="observe", entity_id=entity)
            )

        @actions.command(name="connect", description="Contribute a public connection or repair")
        async def act_connect(interaction: discord.Interaction, source: str, target: str) -> None:
            await self._perform_action(
                interaction,
                ConnectAction(action="connect", source_entity_id=source, target_entity_id=target),
            )

        @actions.command(name="offer", description="Record a public sustainable resource offer")
        async def act_offer(
            interaction: discord.Interaction,
            resource: str,
            amount: app_commands.Range[float, 0.01, 100000.0],
            target: str,
        ) -> None:
            await self._perform_action(
                interaction,
                OfferAction(
                    action="offer",
                    resource_id=resource,
                    amount=float(amount),
                    target_entity_id=target,
                ),
            )

        @actions.command(name="request-support", description="Name a confirmed public need")
        async def act_request_support(
            interaction: discord.Interaction,
            need: str,
            amount: app_commands.Range[float, 0.01, 100000.0] | None = None,
        ) -> None:
            await self._perform_action(
                interaction,
                RequestSupportAction(
                    action="request_support",
                    need_id=need,
                    amount=float(amount) if amount is not None else None,
                ),
            )

        @actions.command(name="summarize", description="Summarize confirmed public discoveries")
        async def act_summarize(interaction: discord.Interaction, focus: str | None = None) -> None:
            await self._perform_action(
                interaction, SummarizeAction(action="summarize", focus=focus)
            )

        @actions.command(name="sustain", description="Maintain a source, route, or condition")
        async def act_sustain(
            interaction: discord.Interaction, target: str, condition: str
        ) -> None:
            await self._perform_action(
                interaction,
                SustainAction(action="sustain", target_entity_id=target, condition=condition),
            )

        @actions.command(name="relay", description="Record a routed public resource flow")
        async def act_relay(
            interaction: discord.Interaction,
            source: str,
            via: str,
            target: str,
            resource: str,
            amount: app_commands.Range[float, 0.01, 100000.0],
        ) -> None:
            await self._perform_action(
                interaction,
                RelayAction(
                    action="relay",
                    source_entity_id=source,
                    via_entity_id=via,
                    target_entity_id=target,
                    resource_id=resource,
                    amount=float(amount),
                ),
            )

        @actions.command(name="mitigate", description="Protect against a confirmed public burden")
        async def act_mitigate(
            interaction: discord.Interaction,
            target: str,
            risk: str,
            detail: str = "",
        ) -> None:
            await self._perform_action(
                interaction,
                MitigateAction(
                    action="mitigate", target_entity_id=target, risk=risk, detail=detail
                ),
            )

        @actions.command(name="calculate", description="Calculate delivery over a public pathway")
        @app_commands.describe(support_amount="Optional protected amount injected at Central Relay")
        async def act_calculate(
            interaction: discord.Interaction,
            source_amount: app_commands.Range[float, 0.01, 100000.0],
            pathway: str,
            support_amount: app_commands.Range[float, 0.0, 100000.0] = 0,
        ) -> None:
            await self._perform_action(
                interaction,
                CalculateFlowAction(
                    action="calculate_flow",
                    source_amount=float(source_amount),
                    pathway_entity_id=pathway,
                    support_amount=float(support_amount),
                ),
            )

        @actions.command(name="branch", description="Add a conditional branch to a proposal")
        async def act_branch(
            interaction: discord.Interaction,
            proposal_id: str,
            condition: str,
            action: str,
        ) -> None:
            await self._perform_action(
                interaction,
                BranchProposalAction(
                    action="branch_proposal",
                    proposal_id=proposal_id,
                    condition=condition,
                    branch_action=action,
                ),
            )

        @actions.command(name="compare", description="Compare two observed public records")
        async def act_compare(
            interaction: discord.Interaction, record_a: str, record_b: str
        ) -> None:
            await self._perform_action(
                interaction,
                CompareRecordsAction(
                    action="compare_records", record_a=record_a, record_b=record_b
                ),
            )

        @actions.command(name="clarify", description="Map a record to its stage term")
        async def act_clarify(interaction: discord.Interaction, record: str, term: str) -> None:
            await self._perform_action(
                interaction,
                ClarifyRecordAction(action="clarify_record", record_id=record, term=term),
            )

        @actions.command(name="classify", description="Classify a public record difference")
        async def act_classify(
            interaction: discord.Interaction,
            record_a: str,
            record_b: str,
            classification: str,
        ) -> None:
            await self._perform_action(
                interaction,
                ClassifyContradictionAction(
                    action="classify_contradiction",
                    record_a=record_a,
                    record_b=record_b,
                    classification=classification,
                ),
            )

        @actions.command(name="relay-record", description="Accurately relay one public record")
        async def act_relay_record(
            interaction: discord.Interaction, record: str, summary: str
        ) -> None:
            await self._perform_action(
                interaction,
                RelayRecordAction(action="relay_record", record_id=record, summary=summary),
            )

        @actions.command(name="annotate", description="Preserve a public record difference")
        async def act_annotate(interaction: discord.Interaction, record: str, note: str) -> None:
            await self._perform_action(
                interaction,
                AnnotateDifferenceAction(action="annotate_difference", record_id=record, note=note),
            )

        @actions.command(name="reconstruct", description="Submit the Position 0 reconstruction")
        @app_commands.describe(
            donor="Position 0 donor alias (use north)",
            recipient="Position 0 recipient alias (use east)",
            resource="Resource being transferred (use water)",
            amount="Transfer amount needed for viability (use 5)",
            pathway="Position 0 pathway alias (use path)",
            pathway_action="Choose how the damaged pathway is handled",
            maintenance="Maintenance; no sentence is needed",
        )
        @app_commands.choices(
            pathway_action=[
                app_commands.Choice(name="Repair the pathway", value="repair"),
                app_commands.Choice(name="Account for the pathway", value="account"),
            ],
            maintenance=[
                app_commands.Choice(name="Monitor", value="monitor"),
                app_commands.Choice(name="Reassess", value="reassess"),
                app_commands.Choice(name="Check", value="check"),
                app_commands.Choice(name="Review", value="review"),
                app_commands.Choice(name="Measure", value="measure"),
                app_commands.Choice(name="Revisit", value="revisit"),
                app_commands.Choice(name="Maintain", value="maintain"),
            ],
        )
        async def act_reconstruct(
            interaction: discord.Interaction,
            donor: str,
            recipient: str,
            resource: str,
            amount: app_commands.Range[float, 0.01, 100000.0],
            pathway: str,
            pathway_action: str,
            maintenance: str,
        ) -> None:
            await self._perform_action(
                interaction,
                ProposeReconstructionAction(
                    action="propose_reconstruction",
                    proposal={
                        "donor_id": donor,
                        "recipient_id": recipient,
                        "resource_id": resource,
                        "amount": float(amount),
                        "pathway_id": pathway,
                        "pathway_action": pathway_action,
                        "maintenance_condition": maintenance,
                    },
                ),
            )

        @actions.command(name="confirm", description="Confirm another participant's proposal")
        async def act_confirm(interaction: discord.Interaction, proposal_id: str) -> None:
            await self._perform_action(
                interaction,
                ConfirmReconstructionAction(
                    action="confirm_reconstruction", proposal_id=proposal_id
                ),
            )

        @actions.command(name="stack-open", description="Open a bounded public response stack")
        async def act_stack_open(
            interaction: discord.Interaction,
            donor: str,
            recipient: str,
            resource: str,
            amount: app_commands.Range[float, 0.01, 100000.0],
            pathway: str,
            maintenance: str = "",
        ) -> None:
            await self._perform_action(
                interaction,
                BeginStackAction(
                    action="begin_stack",
                    proposal={
                        "donor_id": donor,
                        "recipient_id": recipient,
                        "resource_id": resource,
                        "amount": float(amount),
                        "pathway_id": pathway,
                        "pathway_action": "repair",
                        "maintenance_condition": maintenance,
                    },
                ),
            )

        @actions.command(name="stack-react", description="Add one public response to a stack")
        async def act_stack_react(
            interaction: discord.Interaction, stack_id: str, reaction: str, detail: str = ""
        ) -> None:
            allowed = {
                "object_pathway",
                "repair_pathway",
                "reassess_pathway",
                "sustain",
                "mitigate_donor",
                "object_loss",
                "reassess_demand",
                "stabilize_relay",
                "protect_archive",
                "mitigate_north",
                "challenge_mapping",
                "request_provenance",
                "preserve_difference",
                "clarify_scale",
                "relay_summary",
                "object_compatibility",
                "object_evidence",
                "reduce_source",
                "slow_flow",
                "protect_workers",
                "contain_substrate",
                "audit_return",
                "cap_throughput",
                "reassess_viability",
                "preserve_archive",
            }
            if reaction not in allowed:
                await interaction.response.send_message(
                    "Use a reaction listed by the current position's accessibility command."
                )
                return
            await self._perform_action(
                interaction,
                ReactToStackAction(
                    action="react_to_stack",
                    stack_id=stack_id,
                    reaction=reaction,
                    detail=detail,
                ),
            )

        @actions.command(name="stack-resolve", description="Resolve a public stack in reverse")
        async def act_stack_resolve(interaction: discord.Interaction, stack_id: str) -> None:
            await self._perform_action(
                interaction,
                ResolveStackAction(action="resolve_stack", stack_id=stack_id),
            )

        @actions.command(name="kicker", description="Add an optional safeguard to a proposal")
        async def act_kicker(
            interaction: discord.Interaction,
            proposal_id: str,
            kicker: str,
            detail: str = "",
        ) -> None:
            allowed = {
                "monitoring",
                "protect_donor",
                "document",
                "document_flow",
                "adaptive_branch",
                "cite_provenance",
                "preserve_minority",
                "accessibility_glossary",
                "upstream_sampling",
                "downstream_sampling",
                "source_reduction",
                "worker_protection",
                "spent_substrate_plan",
                "public_disclosure",
                "long_term_monitoring",
                "repairability_standard",
                "seasonal_shutdown",
                "archive_failure",
            }
            if kicker not in allowed:
                await interaction.response.send_message(
                    "Use a kicker listed by the current position's accessibility command."
                )
                return
            await self._perform_action(
                interaction,
                AddProposalKickerAction(
                    action="add_proposal_kicker",
                    proposal_id=proposal_id,
                    kicker=kicker,
                    detail=detail,
                ),
            )

        @actions.command(name="trigger", description="Use an available public reaction trigger")
        async def act_trigger(interaction: discord.Interaction, trigger_id: str) -> None:
            await self._perform_action(
                interaction,
                UseTriggeredReactionAction(action="use_triggered_reaction", trigger_id=trigger_id),
            )

        @act_trigger.autocomplete("trigger_id")
        async def trigger_id_autocomplete(
            interaction: discord.Interaction, current: str
        ) -> list[app_commands.Choice[str]]:
            if self.game is None:
                return []
            modes = {
                environment: (await self.sessions.snapshot(environment)).mode
                for environment in Environment
            }
            decision = self.policy.authorize_player(
                _request_context(interaction), self.routing.current, modes
            )
            if decision.result is not AccessResult.ALLOWED or decision.environment is None:
                return []
            choices = await self.game.trigger_choices(decision.environment, interaction.user.id)
            query = current.strip().casefold()
            return [
                app_commands.Choice(name=label[:100], value=value)
                for label, value in choices
                if len(value) <= 100
                and (not query or query in label.casefold() or query in value.casefold())
            ][:25]

        act_observe.autocomplete("entity")(observable_entity_autocomplete)
        act_sustain.autocomplete("target")(maintenance_target_autocomplete)
        for command, parameters in (
            (act_connect, ("source", "target")),
            (act_offer, ("target",)),
            (act_relay, ("source", "via", "target")),
            (act_mitigate, ("target",)),
            (act_calculate, ("pathway",)),
            (act_compare, ("record_a", "record_b")),
            (act_clarify, ("record",)),
            (act_classify, ("record_a", "record_b")),
            (act_relay_record, ("record",)),
            (act_annotate, ("record",)),
            (act_reconstruct, ("donor", "recipient", "pathway")),
            (act_stack_open, ("donor", "recipient", "pathway")),
        ):
            attach_entity_autocomplete(command, *parameters)
        attach_configured_autocomplete(act_sustain, "condition", "maintenance_condition")
        attach_configured_autocomplete(act_mitigate, "risk", "mitigation_risk")

        group.add_command(actions)

        works = app_commands.Group(
            name="works", description="Provision Works and remediation actions"
        )

        @works.command(name="inspect", description="Inspect a known entity or public cue")
        async def works_inspect(interaction: discord.Interaction, target: str) -> None:
            await self._perform_action(
                interaction, InspectAction(action="inspect", target_entity_id=target)
            )

        @works.command(name="sample", description="Compare two public sampling points")
        async def works_sample(
            interaction: discord.Interaction, source: str, comparison: str, measure: str
        ) -> None:
            await self._perform_action(
                interaction,
                SampleAction(
                    action="sample",
                    source_entity_id=source,
                    comparison_entity_id=comparison,
                    measure=measure,
                ),
            )

        @works.command(name="separate", description="Separate clean and contaminated flows")
        async def works_separate(
            interaction: discord.Interaction,
            source: str,
            clean_target: str,
            contaminated_target: str,
        ) -> None:
            await self._perform_action(
                interaction,
                SeparateAction(
                    action="separate",
                    source_entity_id=source,
                    clean_target_entity_id=clean_target,
                    contaminated_target_entity_id=contaminated_target,
                ),
            )

        @works.command(name="inoculate", description="Renew a compatible treatment bed")
        async def works_inoculate(
            interaction: discord.Interaction, target: str, culture: str, substrate: str
        ) -> None:
            await self._perform_action(
                interaction,
                InoculateAction(
                    action="inoculate",
                    target_entity_id=target,
                    culture_id=culture,
                    substrate=substrate,
                ),
            )

        @works.command(name="slow", description="Conditionally slow a public flow")
        async def works_slow(interaction: discord.Interaction, target: str, condition: str) -> None:
            await self._perform_action(
                interaction,
                SlowAction(action="slow", target_entity_id=target, condition=condition),
            )

        @works.command(name="contain", description="Route material to public containment")
        async def works_contain(
            interaction: discord.Interaction, target: str, destination: str, condition: str
        ) -> None:
            await self._perform_action(
                interaction,
                ContainAction(
                    action="contain",
                    target_entity_id=target,
                    destination_entity_id=destination,
                    condition=condition,
                ),
            )

        @works.command(name="rest", description="Take an overloaded bed offline")
        async def works_rest(
            interaction: discord.Interaction, target: str, reassessment: str
        ) -> None:
            await self._perform_action(
                interaction,
                RestAction(action="rest", target_entity_id=target, reassessment=reassessment),
            )

        @works.command(name="replace", description="Replace and contain saturated substrate")
        async def works_replace(
            interaction: discord.Interaction,
            target: str,
            destination: str,
            replacement: str,
        ) -> None:
            await self._perform_action(
                interaction,
                ReplaceAction(
                    action="replace",
                    target_entity_id=target,
                    destination_entity_id=destination,
                    replacement=replacement,
                ),
            )

        @works.command(name="refuse", description="Refuse a flow above a public limit")
        async def works_refuse(interaction: discord.Interaction, target: str, basis: str) -> None:
            await self._perform_action(
                interaction,
                RefuseAction(action="refuse", target_entity_id=target, basis=basis),
            )

        @works.command(name="reduce", description="Reduce throughput or harmful input at source")
        async def works_reduce(
            interaction: discord.Interaction,
            target: str,
            measure: str,
            amount: app_commands.Range[float, 0.01, 100000.0] | None = None,
            condition: str = "",
        ) -> None:
            await self._perform_action(
                interaction,
                ReduceAction(
                    action="reduce",
                    target_entity_id=target,
                    measure=measure,
                    amount=float(amount) if amount is not None else None,
                    condition=condition,
                ),
            )

        @works.command(name="redesign", description="Connect production redesign to public need")
        async def works_redesign(
            interaction: discord.Interaction, target: str, change: str, public_need: str
        ) -> None:
            await self._perform_action(
                interaction,
                RedesignAction(
                    action="redesign",
                    target_entity_id=target,
                    change=change,
                    public_need=public_need,
                ),
            )

        @works.command(name="document", description="Version an existing public record")
        async def works_document(
            interaction: discord.Interaction,
            subject: str,
            record_type: str,
            reference: str,
        ) -> None:
            await self._perform_action(
                interaction,
                DocumentAction(
                    action="document",
                    subject_entity_id=subject,
                    record_type=record_type,
                    text=reference,
                ),
            )

        @works.command(name="audit", description="Compare a public claim with public evidence")
        async def works_audit(
            interaction: discord.Interaction, target: str, claim: str, comparison: str
        ) -> None:
            await self._perform_action(
                interaction,
                AuditAction(
                    action="audit",
                    target_entity_id=target,
                    claim=claim,
                    comparison=comparison,
                ),
            )

        works_inspect.autocomplete("target")(inspectable_entity_autocomplete)
        for command, parameters in (
            (works_sample, ("source", "comparison")),
            (works_separate, ("source", "clean_target", "contaminated_target")),
            (works_inoculate, ("target",)),
            (works_slow, ("target",)),
            (works_contain, ("target", "destination")),
            (works_rest, ("target",)),
            (works_replace, ("target", "destination")),
            (works_refuse, ("target",)),
            (works_reduce, ("target",)),
            (works_redesign, ("target",)),
            (works_document, ("subject",)),
            (works_audit, ("target",)),
        ):
            attach_entity_autocomplete(command, *parameters)
        for command, parameter, field in (
            (works_sample, "measure", "sample_measure"),
            (works_inoculate, "culture", "culture"),
            (works_inoculate, "substrate", "substrate"),
            (works_slow, "condition", "maintenance_condition"),
            (works_reduce, "measure", "reduction_measure"),
            (works_redesign, "change", "redesign_change"),
        ):
            attach_configured_autocomplete(command, parameter, field)

        group.add_command(works)

        proposals = app_commands.Group(
            name="propose", description="Position-specific public proposals"
        )

        @proposals.command(name="circulation", description="Propose the known circulation path")
        @app_commands.describe(
            source_amount="Input from calculate",
            delivered_amount="Total from calculate",
            revision_trigger="Required revision condition",
            support_source="Blank if none",
            support_amount="0 if none",
        )
        @app_commands.choices(
            revision_trigger=[
                app_commands.Choice(
                    name="Nursery demand or Veil output changes",
                    value="change",
                )
            ]
        )
        async def propose_circulation(
            interaction: discord.Interaction,
            source_amount: app_commands.Range[float, 0.01, 100000.0],
            delivered_amount: app_commands.Range[float, 0.01, 100000.0],
            revision_trigger: app_commands.Choice[str],
            support_source: str = "",
            support_amount: app_commands.Range[float, 0.0, 100000.0] = 0,
        ) -> None:
            revision = _circulation_revision_plan(revision_trigger.value)
            await self._perform_action(
                interaction,
                ProposeCirculationAction(
                    action="propose_circulation",
                    source_entity_id="condensation_veil",
                    recipient_entity_id="pale_nursery",
                    resource_id="water",
                    source_amount=float(source_amount),
                    pathway_entity_id="route_07",
                    relay_entity_id="central_relay",
                    delivered_amount=float(delivered_amount),
                    maintenance=revision["maintenance"],
                    reassessment=revision["reassessment"],
                    branch_condition=revision["branch_condition"],
                    branch_action=revision["branch_action"],
                    support_source_entity_id=support_source,
                    support_amount=float(support_amount),
                ),
            )

        @proposals.command(
            name="circulation-stack", description="Open a stack on the known circulation path"
        )
        @app_commands.describe(
            source_amount="Input from calculate",
            delivered_amount="Total from calculate",
            revision_trigger="Required revision condition",
            support_source="Blank if none",
            support_amount="0 if none",
        )
        @app_commands.choices(
            revision_trigger=[
                app_commands.Choice(
                    name="Nursery demand or Veil output changes",
                    value="change",
                )
            ]
        )
        async def propose_circulation_stack(
            interaction: discord.Interaction,
            source_amount: app_commands.Range[float, 0.01, 100000.0],
            delivered_amount: app_commands.Range[float, 0.01, 100000.0],
            revision_trigger: app_commands.Choice[str],
            support_source: str = "",
            support_amount: app_commands.Range[float, 0.0, 100000.0] = 0,
        ) -> None:
            revision = _circulation_revision_plan(revision_trigger.value)
            await self._perform_action(
                interaction,
                BeginStackAction(
                    action="begin_stack",
                    proposal={
                        "kind": "circulation",
                        "source_entity_id": "condensation_veil",
                        "recipient_entity_id": "pale_nursery",
                        "resource_id": "water",
                        "source_amount": float(source_amount),
                        "pathway_entity_id": "route_07",
                        "relay_entity_id": "central_relay",
                        "delivered_amount": float(delivered_amount),
                        "maintenance": revision["maintenance"],
                        "reassessment": revision["reassessment"],
                        "branch_condition": revision["branch_condition"],
                        "branch_action": revision["branch_action"],
                        "support_source_entity_id": support_source,
                        "support_amount": float(support_amount),
                    },
                ),
            )

        @proposals.command(name="translation", description="Propose a plural record concordance")
        async def propose_translation(
            interaction: discord.Interaction,
            record_a: str,
            record_b: str,
            record_c: str,
            classification: str,
            mapping: str,
            shared_summary: str,
            preserved_difference: str,
        ) -> None:
            await self._perform_action(
                interaction,
                ProposeTranslationAction(
                    action="propose_translation",
                    record_a=record_a,
                    record_b=record_b,
                    record_c=record_c,
                    classification=classification,
                    mapping=mapping,
                    shared_summary=shared_summary,
                    preserved_difference=preserved_difference,
                ),
            )

        @proposals.command(
            name="translation-stack", description="Open a response stack around translation"
        )
        async def propose_translation_stack(
            interaction: discord.Interaction,
            record_a: str,
            record_b: str,
            record_c: str,
            classification: str,
            mapping: str,
            shared_summary: str,
            preserved_difference: str,
        ) -> None:
            await self._perform_action(
                interaction,
                BeginStackAction(
                    action="begin_stack",
                    proposal={
                        "kind": "translation",
                        "record_a": record_a,
                        "record_b": record_b,
                        "record_c": record_c,
                        "classification": classification,
                        "mapping": mapping,
                        "shared_summary": shared_summary,
                        "preserved_difference": preserved_difference,
                    },
                ),
            )

        @proposals.command(name="reciprocity", description="Propose producer obligations")
        @app_commands.describe(open_stack="Open responses before filing")
        async def propose_reciprocity(
            interaction: discord.Interaction,
            producer: str,
            public_benefit: str,
            local_burden: str,
            source_reduction_action: str,
            material_disclosure: str,
            maintenance_obligation: str,
            containment_plan: str,
            worker_protection: str,
            shutdown_condition: str,
            open_stack: bool = False,
        ) -> None:
            proposal_action = ProposeReciprocityAction(
                action="propose_reciprocity",
                producer=producer,
                public_benefit=public_benefit,
                local_burden=local_burden,
                source_reduction_action=source_reduction_action,
                material_disclosure=material_disclosure,
                maintenance_obligation=maintenance_obligation,
                containment_plan=containment_plan,
                worker_protection=worker_protection,
                shutdown_condition=shutdown_condition,
            )
            candidate: CandidateAction = proposal_action
            if open_stack:
                candidate = BeginStackAction(
                    action="begin_stack",
                    proposal={
                        "kind": "reciprocity",
                        **proposal_action.model_dump(exclude={"action"}),
                    },
                )
            await self._perform_action(
                interaction,
                candidate,
            )

        @proposals.command(name="remediation", description="Propose a bounded remediation protocol")
        @app_commands.describe(open_stack="Open responses before filing")
        async def propose_remediation(
            interaction: discord.Interaction,
            source_discharge: str,
            contaminant_class: str,
            production_reduction_action: str,
            treatment_bed: str,
            fungal_culture: str,
            flow_rate_condition: str,
            moisture_condition: str,
            monitoring_method: str,
            upstream_sample: str,
            downstream_sample: str,
            evidence_requirement: str,
            saturation_limit: app_commands.Range[int, 1, 100],
            spent_substrate_destination: str,
            maintenance_condition: str,
            shutdown_condition: str,
            open_stack: bool = False,
        ) -> None:
            proposal_action = ProposeRemediationProtocolAction(
                action="propose_remediation_protocol",
                source_discharge=source_discharge,
                contaminant_class=contaminant_class,
                production_reduction_action=production_reduction_action,
                treatment_bed=treatment_bed,
                fungal_culture=fungal_culture,
                flow_rate_condition=flow_rate_condition,
                moisture_condition=moisture_condition,
                monitoring_method=monitoring_method,
                upstream_sample=upstream_sample,
                downstream_sample=downstream_sample,
                evidence_requirement=evidence_requirement,
                saturation_limit=int(saturation_limit),
                spent_substrate_destination=spent_substrate_destination,
                maintenance_condition=maintenance_condition,
                shutdown_condition=shutdown_condition,
            )
            candidate = proposal_action
            if open_stack:
                candidate = BeginStackAction(
                    action="begin_stack",
                    proposal={
                        "kind": "remediation_protocol",
                        **proposal_action.model_dump(exclude={"action"}),
                    },
                )
            await self._perform_action(
                interaction,
                candidate,
            )

        @proposals.command(name="memory", description="Propose a versioned public correction")
        @app_commands.describe(open_stack="Open responses before filing")
        async def propose_memory(
            interaction: discord.Interaction,
            original_claim: str,
            later_revision: str,
            physical_evidence: str,
            affected_observation: str,
            uncertainty: str,
            correction: str,
            unresolved_conflict: str,
            handling_requirement: str,
            open_stack: bool = False,
        ) -> None:
            proposal_action = ProposeMemoryArchiveAction(
                action="propose_memory_archive",
                original_claim=original_claim,
                later_revision=later_revision,
                physical_evidence=physical_evidence,
                affected_observation=affected_observation,
                uncertainty=uncertainty,
                correction=correction,
                unresolved_conflict=unresolved_conflict,
                handling_requirement=handling_requirement,
            )
            candidate: CandidateAction = proposal_action
            if open_stack:
                candidate = BeginStackAction(
                    action="begin_stack",
                    proposal={
                        "kind": "memory_archive",
                        **proposal_action.model_dump(exclude={"action"}),
                    },
                )
            await self._perform_action(
                interaction,
                candidate,
            )

        @proposals.command(name="reconstruction", description="Propose final production reform")
        @app_commands.describe(open_stack="Open responses before filing")
        async def propose_production_reform(
            interaction: discord.Interaction,
            production_line: str,
            current_output: app_commands.Range[float, 0.0, 100000.0],
            revised_output: app_commands.Range[float, 0.0, 100000.0],
            public_need_served: str,
            water_cap: app_commands.Range[float, 0.0, 100000.0],
            waste_reduction: str,
            worker_transition: str,
            ownership_or_governance: str,
            remediation_obligation: str,
            clean_flow_plan: str,
            spent_substrate_plan: str,
            monitoring: str,
            maintenance: str,
            historical_records: str,
            reassessment: str,
            shutdown_threshold: str,
            open_stack: bool = False,
        ) -> None:
            proposal_action = ProposeProductionReformAction(
                action="propose_production_reform",
                production_line=production_line,
                current_output=float(current_output),
                revised_output=float(revised_output),
                public_need_served=public_need_served,
                water_cap=float(water_cap),
                waste_reduction=waste_reduction,
                worker_transition=worker_transition,
                ownership_or_governance=ownership_or_governance,
                remediation_obligation=remediation_obligation,
                clean_flow_plan=clean_flow_plan,
                spent_substrate_plan=spent_substrate_plan,
                monitoring=monitoring,
                maintenance=maintenance,
                historical_records=historical_records,
                reassessment=reassessment,
                shutdown_threshold=shutdown_threshold,
            )
            candidate = proposal_action
            if open_stack:
                candidate = BeginStackAction(
                    action="begin_stack",
                    proposal={
                        "kind": "reconstruction",
                        **proposal_action.model_dump(exclude={"action"}),
                    },
                )
            await self._perform_action(
                interaction,
                candidate,
            )

        for command, parameters in (
            (propose_circulation, ("support_source",)),
            (propose_circulation_stack, ("support_source",)),
            (propose_translation, ("record_a", "record_b", "record_c")),
            (propose_translation_stack, ("record_a", "record_b", "record_c")),
            (propose_reciprocity, ("producer",)),
            (
                propose_remediation,
                (
                    "source_discharge",
                    "treatment_bed",
                    "upstream_sample",
                    "downstream_sample",
                    "spent_substrate_destination",
                ),
            ),
            (propose_production_reform, ("production_line",)),
        ):
            attach_entity_autocomplete(command, *parameters)
        attach_configured_autocomplete(
            propose_remediation, "contaminant_class", "contaminant_class"
        )
        attach_configured_autocomplete(propose_remediation, "fungal_culture", "culture")
        attach_configured_autocomplete(
            propose_remediation, "flow_rate_condition", "maintenance_condition"
        )

        group.add_command(proposals)

        async def reset_test_content(interaction: discord.Interaction, confirm: bool) -> None:
            environment = await self._authorize_admin(interaction, Environment.TEST)
            if environment is None:
                return
            if not confirm:
                await self._send(interaction, "Reset cancelled; set confirm to true.", environment)
                return
            if self.game is None:
                await self._send(
                    interaction, "Deterministic game content is unavailable.", environment
                )
                return
            result = await self.game.reset_test(interaction.user.id)
            await self._send(interaction, result.text, environment)

        @test_tools.command(name="reset", description="Destroy and reset isolated test progress")
        async def test_reset(interaction: discord.Interaction, confirm: bool) -> None:
            await reset_test_content(interaction, confirm)

        @test_tools.command(name="reset-position", description="Reset the isolated test position")
        async def test_reset_position(interaction: discord.Interaction, confirm: bool) -> None:
            await reset_test_content(interaction, confirm)

        @test_tools.command(
            name="force-observation", description="Force a debug-only test observation"
        )
        async def test_force_observation(
            interaction: discord.Interaction, observation_id: str, confirm: bool
        ) -> None:
            environment = await self._authorize_admin(interaction, Environment.TEST)
            if environment is None:
                return
            if not confirm:
                await self._send(
                    interaction, "Force action cancelled; set confirm to true.", environment
                )
                return
            if self.game is None:
                await self._send(
                    interaction, "Deterministic game content is unavailable.", environment
                )
                return
            try:
                result = await self.game.force_observation(observation_id, interaction.user.id)
            except StorageError as exc:
                await self._send(interaction, str(exc), environment)
                return
            await self._send(interaction, result.text, environment)

        @test_tools.command(name="debug-state", description="Show isolated test debug state")
        async def test_debug_state(interaction: discord.Interaction) -> None:
            environment = await self._authorize_admin(interaction, Environment.TEST)
            if environment is None:
                return
            if self.game is None:
                await self._send(
                    interaction, "Deterministic game content is unavailable.", environment
                )
                return
            await self._send(interaction, await self.game.debug_test_state(), environment)

        @test_tools.command(
            name="copy-live-content",
            description="Reload validated content into test without progress",
        )
        async def test_copy_live_content(interaction: discord.Interaction) -> None:
            environment = await self._authorize_admin(interaction, Environment.TEST)
            if environment is None:
                return
            if self.game is None:
                await self._send(
                    interaction, "Deterministic game content is unavailable.", environment
                )
                return
            result = await self.game.copy_live_content_to_test(interaction.user.id)
            await self._send(interaction, result.text, environment)

        @test_tools.command(name="checkpoint", description="Create an isolated test checkpoint")
        async def test_checkpoint(interaction: discord.Interaction, name: str) -> None:
            environment = await self._authorize_admin(interaction, Environment.TEST)
            if environment is None:
                return
            if self.operations is None:
                await self._send(interaction, "Operational controls are unavailable.", environment)
                return
            try:
                result = await self.operations.test_checkpoint(name, interaction.user.id)
            except StorageError as exc:
                await self._send(interaction, str(exc), environment)
                return
            await self._send(interaction, result.text, environment)

        @test_tools.command(name="rollback", description="Restore a paused test checkpoint")
        async def test_rollback(
            interaction: discord.Interaction, checkpoint_id: str, confirm: bool
        ) -> None:
            environment = await self._authorize_admin(interaction, Environment.TEST)
            if environment is None:
                return
            if self.operations is None:
                await self._send(interaction, "Operational controls are unavailable.", environment)
                return
            try:
                result = await self.operations.test_rollback_checkpoint(
                    checkpoint_id, interaction.user.id, confirm=confirm
                )
            except StorageError as exc:
                await self._send(interaction, str(exc), environment)
                return
            await self._send(interaction, result.text, environment)

        @test_tools.command(name="export", description="Export isolated test state")
        async def test_export(interaction: discord.Interaction) -> None:
            environment = await self._authorize_admin(interaction, Environment.TEST)
            if environment is None:
                return
            if self.operations is None:
                await self._send(interaction, "Operational controls are unavailable.", environment)
                return
            document = await self.operations.export(Environment.TEST)
            attachment = discord.File(
                io.BytesIO(document.encode("utf-8")),
                filename="uniflora-test-export.json",
            )
            marker = "[TEST SURFACE]\n" if self.settings.test_surface_marker_enabled else ""
            await interaction.response.send_message(
                f"{marker}Test export; the environment label is embedded.", file=attachment
            )

        @test_tools.command(name="import", description="Import a paused test export")
        async def test_import(
            interaction: discord.Interaction, attachment: discord.Attachment, confirm: bool
        ) -> None:
            environment = await self._authorize_admin(interaction, Environment.TEST)
            if environment is None:
                return
            if not confirm:
                await self._send(
                    interaction, "Test import cancelled; set confirm to true.", environment
                )
                return
            if self.operations is None:
                await self._send(interaction, "Operational controls are unavailable.", environment)
                return
            if attachment.size > 1_000_000:
                await self._send(interaction, "Test export exceeds the 1 MB limit.", environment)
                return
            try:
                try:
                    raw = await attachment.read()
                except discord.HTTPException as original_error:
                    try:
                        raw = await attachment.read(use_cached=True)
                    except discord.HTTPException:
                        raise original_error
                document = json.loads(raw.decode("utf-8"))
                if not isinstance(document, dict):
                    raise ValueError("document must be an object")
                result = await self.operations.import_test(
                    document, interaction.user.id, confirm=True
                )
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
                await self._send(interaction, f"Invalid test export: {exc}.", environment)
                return
            except (discord.HTTPException, StorageError) as exc:
                await self._send(interaction, str(exc), environment)
                return
            await self._send(interaction, result.text, environment)

        @test_tools.command(
            name="clear-history", description="Clear test GPT and narration context"
        )
        async def test_clear_history(interaction: discord.Interaction, confirm: bool) -> None:
            environment = await self._authorize_admin(interaction, Environment.TEST)
            if environment is None:
                return
            if self.operations is None:
                await self._send(interaction, "Operational controls are unavailable.", environment)
                return
            result = await self.operations.clear_test_history(interaction.user.id, confirm=confirm)
            await self._send(interaction, result.text, environment)

        @test_tools.command(name="force-event", description="Record a forced test-only event")
        async def test_force_event(
            interaction: discord.Interaction, label: str, note: str, confirm: bool
        ) -> None:
            environment = await self._authorize_admin(interaction, Environment.TEST)
            if environment is None:
                return
            if self.operations is None:
                await self._send(interaction, "Operational controls are unavailable.", environment)
                return
            try:
                result = await self.operations.force_test_event(
                    label, note, interaction.user.id, confirm=confirm
                )
            except StorageError as exc:
                await self._send(interaction, str(exc), environment)
                return
            await self._send(interaction, result.text, environment)

        @test_tools.command(name="set-position", description="Force a test position scaffold")
        async def test_set_position(
            interaction: discord.Interaction,
            position: app_commands.Range[int, 0, 6],
            confirm: bool,
        ) -> None:
            environment = await self._authorize_admin(interaction, Environment.TEST)
            if environment is None:
                return
            if self.operations is None:
                await self._send(interaction, "Operational controls are unavailable.", environment)
                return
            try:
                result = await self.operations.set_test_position(
                    int(position), interaction.user.id, confirm=confirm
                )
            except StorageError as exc:
                await self._send(interaction, str(exc), environment)
                return
            await self._send(interaction, result.text, environment)

        @test_tools.command(name="set-profile", description="Force a backed test response profile")
        async def test_set_profile(
            interaction: discord.Interaction, profile: str, confirm: bool
        ) -> None:
            environment = await self._authorize_admin(interaction, Environment.TEST)
            if environment is None:
                return
            if self.operations is None:
                await self._send(interaction, "Operational controls are unavailable.", environment)
                return
            try:
                result = await self.operations.set_test_profile(
                    profile, interaction.user.id, confirm=confirm
                )
            except StorageError as exc:
                await self._send(interaction, str(exc), environment)
                return
            await self._send(interaction, result.text, environment)

        async def set_test_gpt(interaction: discord.Interaction, enabled: bool) -> None:
            environment = await self._authorize_admin(interaction, Environment.TEST)
            if environment is None:
                return
            if self.operations is None:
                await self._send(interaction, "Operational controls are unavailable.", environment)
                return
            result = await self.operations.set_test_gpt(enabled, interaction.user.id)
            await self._send(interaction, result.text, environment)

        @test_tools.command(name="gpt-on", description="Enable GPT only on the test surface")
        async def test_gpt_on(interaction: discord.Interaction) -> None:
            await set_test_gpt(interaction, True)

        @test_tools.command(name="gpt-off", description="Disable GPT only on the test surface")
        async def test_gpt_off(interaction: discord.Interaction) -> None:
            await set_test_gpt(interaction, False)

        group.add_command(test_tools)
        group.add_command(ops_tools)

        @group.command(name="live-readiness", description="Report guarded live launch checks")
        async def live_readiness(interaction: discord.Interaction) -> None:
            environment = await self._authorize_admin(interaction, Environment.LIVE)
            if environment is None:
                return
            if self.operations is None:
                await self._send(interaction, "Operational controls are unavailable.", environment)
                return
            report = await self.operations.live_readiness()
            await self._send(interaction, report.text, environment)

        @group.command(name="start-live", description="Launch live only after readiness checks")
        async def start_live(interaction: discord.Interaction, confirm: bool) -> None:
            environment = await self._authorize_admin(interaction, Environment.LIVE)
            if environment is None:
                return
            if self.operations is None:
                await self._send(interaction, "Operational controls are unavailable.", environment)
                return
            result = await self.operations.start_live(interaction.user.id, confirm=confirm)
            await self._send(interaction, result.text, environment)

        @group.command(name="rollback", description="Restore through one scoped event")
        async def rollback(
            interaction: discord.Interaction, environment: str, event_id: str, confirm: bool
        ) -> None:
            selected = self._environment(environment)
            if selected is None:
                await interaction.response.send_message("Environment must be live or test.")
                return
            if await self._authorize_admin(interaction, selected) is None:
                return
            if self.operations is None:
                await self._send(interaction, "Operational controls are unavailable.", selected)
                return
            try:
                result = await self.operations.rollback(
                    selected, event_id, interaction.user.id, confirm=confirm
                )
            except StorageError as exc:
                await self._send(interaction, str(exc), selected)
                return
            await self._send(interaction, result.text, selected)

        @group.command(name="invalidate", description="Invalidate a paused scoped gameplay event")
        async def invalidate(
            interaction: discord.Interaction, environment: str, event_id: str, confirm: bool
        ) -> None:
            selected = self._environment(environment)
            if selected is None:
                await interaction.response.send_message("Environment must be live or test.")
                return
            if await self._authorize_admin(interaction, selected) is None:
                return
            if self.operations is None:
                await self._send(interaction, "Operational controls are unavailable.", selected)
                return
            try:
                result = await self.operations.invalidate(
                    selected, event_id, interaction.user.id, confirm=confirm
                )
            except StorageError as exc:
                await self._send(interaction, str(exc), selected)
                return
            await self._send(interaction, result.text, selected)

        @group.command(name="retry-event", description="Retry an invalidated typed event")
        async def retry_event(
            interaction: discord.Interaction, environment: str, event_id: str, confirm: bool
        ) -> None:
            selected = self._environment(environment)
            if selected is None:
                await interaction.response.send_message("Environment must be live or test.")
                return
            if await self._authorize_admin(interaction, selected) is None:
                return
            if self.operations is None:
                await self._send(interaction, "Operational controls are unavailable.", selected)
                return
            try:
                result = await self.operations.retry_event(
                    selected, event_id, interaction.user.id, confirm=confirm
                )
            except StorageError as exc:
                await self._send(interaction, str(exc), selected)
                return
            await self._send(interaction, result.text, selected)

        @group.command(name="debug-state", description="Show redacted state in diagnostics")
        async def debug_state(interaction: discord.Interaction, environment: str) -> None:
            if not await self._authorize_diagnostic(interaction):
                return
            selected = self._environment(environment)
            if selected is None:
                await interaction.response.send_message("Environment must be live or test.")
                return
            if self.operations is None:
                await interaction.response.send_message("Operational controls are unavailable.")
                return
            await interaction.response.send_message(await self.operations.debug_state(selected))

        @group.command(name="export", description="Export the TEST environment in diagnostics")
        async def export(interaction: discord.Interaction) -> None:
            selected = await self._authorize_admin(
                interaction,
                Environment.TEST,
            )
            if selected is None:
                return
            if self.operations is None:
                await interaction.response.send_message("Operational controls are unavailable.")
                return
            document = await self.operations.export(selected)
            attachment = discord.File(
                io.BytesIO(document.encode("utf-8")),
                filename=f"uniflora-{selected.value}-export.json",
            )
            await interaction.response.send_message(
                f"{selected.value.title()} export; environment label is embedded.",
                file=attachment,
            )

        @group.command(name="set-model", description="Set an environment-specific API model")
        async def set_model(
            interaction: discord.Interaction, environment: str, purpose: str, model: str
        ) -> None:
            selected = self._environment(environment)
            if selected is None:
                await interaction.response.send_message("Environment must be live or test.")
                return
            if await self._authorize_admin(interaction, selected) is None:
                return
            if self.operations is None:
                await self._send(interaction, "Operational controls are unavailable.", selected)
                return
            try:
                result = await self.operations.set_model(
                    selected, purpose, model, interaction.user.id
                )
            except StorageError as exc:
                await self._send(interaction, str(exc), selected)
                return
            await self._send(interaction, result.text, selected)

        @group.command(name="set-api-budget", description="Set scoped soft and hard API caps")
        async def set_api_budget(
            interaction: discord.Interaction,
            environment: str,
            period: str,
            soft: app_commands.Range[float, 0, 100000],
            hard: app_commands.Range[float, 0, 100000],
        ) -> None:
            selected = self._environment(environment)
            if selected is None:
                await interaction.response.send_message("Environment must be live or test.")
                return
            if await self._authorize_admin(interaction, selected) is None:
                return
            if self.operations is None:
                await self._send(interaction, "Operational controls are unavailable.", selected)
                return
            try:
                result = await self.operations.set_api_budget(
                    selected, period, float(soft), float(hard), interaction.user.id
                )
            except StorageError as exc:
                await self._send(interaction, str(exc), selected)
                return
            await self._send(interaction, result.text, selected)

        @group.command(name="fallback-mode", description="Toggle deterministic API fallback")
        async def fallback_mode(
            interaction: discord.Interaction, environment: str, enabled: bool
        ) -> None:
            selected = self._environment(environment)
            if selected is None:
                await interaction.response.send_message("Environment must be live or test.")
                return
            if await self._authorize_admin(interaction, selected) is None:
                return
            if self.operations is None:
                await self._send(interaction, "Operational controls are unavailable.", selected)
                return
            result = await self.operations.fallback_mode(selected, enabled, interaction.user.id)
            await self._send(interaction, result.text, selected)

        @group.command(
            name="validate-content",
            description="Validate content and Position 0",
        )
        async def validate_content(interaction: discord.Interaction) -> None:
            environment = await self._authorize_admin(interaction)
            if environment is None:
                return
            if self.game is None:
                await self._send(
                    interaction, "Deterministic game content is unavailable.", environment
                )
                return
            result = await self.game.validate_content()
            await self._send(interaction, result.text, environment)

        @group.error
        async def group_error(
            interaction: discord.Interaction, error: app_commands.AppCommandError
        ) -> None:
            logger.error(
                "application command failed",
                exc_info=(type(error), error, error.__traceback__),
                extra={
                    "environment": "system",
                    "guild_id": interaction.guild_id,
                    "channel_id": interaction.channel_id,
                    "user_id": interaction.user.id,
                },
            )
            message = "The interface encountered an operational error. No game state changed."
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)

        return group


def build_bot(
    settings: Settings,
    sessions: RuntimeSessions,
    routing: RuntimeRouting,
    health: HealthService,
    repository: GameRepository | None = None,
    session_refs: dict[Environment, SessionRef] | None = None,
    game: GameService | None = None,
    natural_language: NaturalLanguageInterpreter | None = None,
    operations: OperationsService | None = None,
    alerts: DiagnosticAlertSink | None = None,
) -> InteriorBot:
    return InteriorBot(
        settings,
        sessions,
        routing,
        health,
        repository,
        session_refs,
        game,
        natural_language,
        operations,
        alerts,
    )


def initial_routing(settings: Settings) -> RuntimeRouting:
    return RuntimeRouting(
        RoutingSnapshot(
            guild_id=settings.discord_guild_id,
            live_channel_id=settings.live_puzzle_channel_id,
            test_channel_id=settings.test_puzzle_channel_id,
            mycotroph_role_id=settings.mycotroph_role_id,
            admin_user_ids=settings.admin_user_ids,
            diagnostic_channel_id=settings.diagnostic_channel_id,
        )
    )
