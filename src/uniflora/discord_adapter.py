from __future__ import annotations

import asyncio
import hashlib
import io
import json
import logging
import os
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from uniflora.access import AccessPolicy, AccessResult, RequestContext
from uniflora.alerts import DiagnosticAlertSink
from uniflora.announcements import SCHEDULED_ANNOUNCEMENTS, ScheduledAnnouncement
from uniflora.config import Settings
from uniflora.difficulty import (
    DIFFICULTY_LABELS,
    DIFFICULTY_POLL_TEXT,
    DifficultyLevel,
    difficulty_confirmation,
    guided_support_footer,
)
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
from uniflora.exterior_weather_rules import (
    ExteriorWeatherOutcome,
    StationScope,
    observation_from_aprsfi,
    render_settlement_effects,
)
from uniflora.exterior_weather_runtime import (
    ExteriorWeatherRuntimeState,
)
from uniflora.external_feeds.aprsfi import (
    AprsFiExteriorService,
    AprsFiSettings,
)
from uniflora.external_feeds.aprsfi.errors import AprsFiApiError
from uniflora.external_ufo_reports import (
    ExternalUfoReport,
    UfoReportFeed,
    UfoReportFeedError,
    UfoReportFeedService,
    UfoReportSettings,
)
from uniflora.game_service import GameService, PublicResult
from uniflora.gemini_chat import (
    GeminiGameChatProvider,
    GeminiVoiceReplyService,
    build_v2_chat_context,
)
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
    SessionMode,
)
from uniflora.storage.repository import (
    DifficultyBallotError,
    GameRepository,
    SessionRef,
    StorageError,
)
from uniflora.ufo_sidequests import build_ufosint_sidequest_url
from uniflora.v2_activity_projection import (
    V2ActivityPublisher,
    V2ActivityPublishError,
)
from uniflora.v2_test_runtime import V2TestRuntime, V2TestRuntimeError
from uniflora.voice_service import (
    EspeakVoiceService,
    VoiceSynthesisError,
)

logger = logging.getLogger(__name__)
_CONTENT_ASSETS_ROOT = Path(__file__).resolve().parent / "content" / "assets"

def _ufo_report_event_date_label(report: ExternalUfoReport) -> str:
    return (
        f"{report.observed_at.date().isoformat()}\n"
        "UFOSINT provides an event date, not an authoritative event time."
    )



def _ufo_report_embed_matches_posted(
    report: ExternalUfoReport,
    embed: Any,
    marker: str,
) -> bool:
    footer = getattr(getattr(embed, "footer", None), "text", "")
    if footer == marker:
        return True

    fields = tuple(getattr(embed, "fields", ()) or ())
    field_pairs = tuple(
        (
            str(getattr(field, "name", "") or ""),
            str(getattr(field, "value", "") or ""),
        )
        for field in fields
    )
    report_identifier = f"{report.source_key}:{report.report_id}"
    if any(
        name.casefold() == "report id" and value.strip() == report_identifier
        for name, value in field_pairs
    ):
        return True

    description = str(getattr(embed, "description", "") or "")
    if report.title not in description:
        return False

    field_text = "\n".join(value for _, value in field_pairs)
    event_values = {
        _ufo_report_event_date_label(report),
        report.observed_at.date().isoformat(),
        discord.utils.format_dt(report.observed_at, style="F"),
    }
    return (
        any(value and value in field_text for value in event_values)
        and f"{report.quality_score}/100" in field_text
        and report.location_name in field_text
    )


async def _first_unposted_ufo_report(
    service: UfoReportFeedService,
    channel: discord.TextChannel,
    candidates: tuple[ExternalUfoReport, ...],
    already_posted: Callable[
        [discord.TextChannel, str, ExternalUfoReport],
        Awaitable[bool],
    ],
    *,
    respect_seen_state: bool = True,
) -> ExternalUfoReport | None:
    for candidate in candidates:
        if respect_seen_state and service.is_seen(candidate):
            continue
        if await already_posted(channel, candidate.marker, candidate):
            service.mark_seen((candidate,))
            continue
        return candidate
    return None
_V2_POSITION_ONE_SOLO_GUIDE = """\
**Position 1 — First Return**

At 03:17, the Boundary Array retained an optical record and an independent radio return.
The records do not establish distance, trajectory, size, composition, cause, or identity.

**Current investigative functions**
• Field Observer — examines the optical record.
• Instrument Operator — checks the radio receiver and its diagnostic.
• Atmospheric Analyst — retrieves weather evidence and tests atmospheric propagation.
• Signal Correlator — compares the optical and radio timing.
• Protocol Auditor — documents unresolved gaps and prepares the assessment.

Use `/v2 role` to choose a function and optionally give it your own public title.
Use `/v2 command text:<command>` for evidence and investigation actions.
Use `/v2 status` to inspect the shared record.

Begin by assigning a Field Observer and examining `optical_record`. Another Discord member
must independently confirm the final assessment before the position can close."""



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


class DifficultyPollView(discord.ui.View):
    """Persistent, private per-user guidance choices for one verified Hypha post."""

    def __init__(self, bot: InteriorBot, *, disabled: bool = False) -> None:
        super().__init__(timeout=None)
        self.bot = bot
        if disabled:
            for item in self.children:
                if isinstance(item, discord.ui.Button):
                    item.disabled = True

    @discord.ui.button(
        label="Guided",
        style=discord.ButtonStyle.success,
        custom_id="interior:difficulty:guided",
    )
    async def guided(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button[DifficultyPollView],
    ) -> None:
        del button
        await self.bot._record_difficulty_selection(
            interaction,
            DifficultyLevel.GUIDED,
        )

    @discord.ui.button(
        label="Standard",
        style=discord.ButtonStyle.primary,
        custom_id="interior:difficulty:standard",
    )
    async def standard(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button[DifficultyPollView],
    ) -> None:
        del button
        await self.bot._record_difficulty_selection(
            interaction,
            DifficultyLevel.STANDARD,
        )

    @discord.ui.button(
        label="Expert",
        style=discord.ButtonStyle.secondary,
        custom_id="interior:difficulty:expert",
    )
    async def expert(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button[DifficultyPollView],
    ) -> None:
        del button
        await self.bot._record_difficulty_selection(
            interaction,
            DifficultyLevel.EXPERT,
        )


class UfoReportSidequestView(discord.ui.View):
    """Link-only advisory entry point for one sanitized UFOSINT report."""

    def __init__(self, url: str) -> None:
        super().__init__(timeout=None)
        self.add_item(
            discord.ui.Button(
                label="Investigate in Activity",
                style=discord.ButtonStyle.link,
                url=url,
            )
        )


def _ufo_report_sidequest_view(
    report: ExternalUfoReport,
    discord_application_id: int | str | None,
) -> UfoReportSidequestView | None:
    url = build_ufosint_sidequest_url(
        discord_application_id,
        source_key=report.source_key,
        report_id=report.report_id,
    )
    return UfoReportSidequestView(url) if url is not None else None


def _request_context(interaction: discord.Interaction) -> RequestContext:
    roles = getattr(interaction.user, "roles", ())
    channel = getattr(interaction, "channel", None)
    return RequestContext(
        guild_id=interaction.guild_id,
        channel_id=interaction.channel_id,
        user_id=interaction.user.id,
        role_ids=frozenset(role.id for role in roles),
        is_dm=interaction.guild_id is None,
        thread_parent_channel_id=(
            channel.parent_id if isinstance(channel, discord.Thread) else None
        ),
    )


def _message_request_context(message: discord.Message) -> RequestContext:
    roles = getattr(message.author, "roles", ())
    return RequestContext(
        guild_id=message.guild.id if message.guild else None,
        channel_id=message.channel.id,
        user_id=message.author.id,
        role_ids=frozenset(role.id for role in roles),
        is_dm=message.guild is None,
        thread_parent_channel_id=(
            message.channel.parent_id if isinstance(message.channel, discord.Thread) else None
        ),
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
    reply_author = getattr(reply, "author", None)
    reply_author_id = getattr(reply_author, "id", None)

    if reply_author_id is not None and reply_author_id not in seen:
        referenced.append(_participant_identity(reply_author))
        seen.add(reply_author_id)

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
        v2_test_runtime: V2TestRuntime | None = None,
        v2_activity_publisher: V2ActivityPublisher | None = None,
        v2_live_runtime: V2TestRuntime | None = None,
        v2_live_activity_publisher: V2ActivityPublisher | None = None,
    ) -> None:
        intents = discord.Intents.none()
        intents.guilds = True
        message_chat_enabled = (
            settings.feature_natural_language or settings.feature_gemini_discord_chat
        )
        intents.messages = message_chat_enabled
        intents.message_content = message_chat_enabled
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
        self.v2_test_runtime = v2_test_runtime
        self.v2_activity_publisher = v2_activity_publisher
        self.v2_live_runtime = v2_live_runtime
        self.v2_live_activity_publisher = v2_live_activity_publisher
        self.voice = EspeakVoiceService.from_settings(settings)
        self.gemini_voice: GeminiVoiceReplyService | None = None
        if settings.feature_gemini_chat:
            self.gemini_voice = GeminiVoiceReplyService(
                GeminiGameChatProvider.from_settings(settings),
                self.voice,
            )
        self._commands_synced = False
        self._settlement_expiry_task: asyncio.Task[None] | None = None
        self._scheduled_announcement_task: asyncio.Task[None] | None = None
        self._ufo_report_task: asyncio.Task[None] | None = None
        self._position_announcement_locks = {
            environment: asyncio.Lock() for environment in Environment
        }
        self._v2_bulletin_lock = asyncio.Lock()
        self._voice_delivery_tasks: set[asyncio.Task[None]] = set()

        self._ufo_report_service: UfoReportFeedService | None = None
        ufo_report_settings = UfoReportSettings.from_environment(
            default_channel_id=settings.v2_bulletin_channel_id,
        )
        if ufo_report_settings.enabled:
            self._ufo_report_service = UfoReportFeedService(ufo_report_settings)

        self._aprsfi_service: AprsFiExteriorService | None = None
        aprsfi_enabled = os.getenv("UNIFLORA_APRSFI_ENABLED", "").strip().casefold() in {
            "1",
            "true",
            "yes",
            "on",
        }
        if aprsfi_enabled:
            aprsfi_targets_path = (
                Path(__file__).resolve().parent
                / "external_feeds"
                / "aprsfi"
                / "targets.json"
            )
            self._aprsfi_service = AprsFiExteriorService(
                AprsFiSettings.from_environment(aprsfi_targets_path)
            )
        self._exterior_weather_states: dict[
            Environment, ExteriorWeatherRuntimeState
        ] = {
            environment: ExteriorWeatherRuntimeState()
            for environment in Environment
        }
        self._exterior_cached_weather_records: tuple[Any, ...] = ()

        if self.game is not None:
            self.tree.add_command(self._build_command_group())
        if self.v2_test_runtime is not None:
            self.tree.add_command(self._build_v2_command_group())
        if self.v2_live_runtime is not None:
            self.tree.add_command(self._build_v2_live_command_group())

    async def setup_hook(self) -> None:
        self.add_view(SettlementInterventionView(self))
        self.add_view(DifficultyPollView(self))
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
        if self._ufo_report_service is not None and self._ufo_report_task is None:
            self._ufo_report_task = asyncio.create_task(
                self._ufo_report_loop(), name="ufosint-report-intake"
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

    async def on_resumed(self) -> None:
        self.health.discord_connected = True
        logger.info("discord client resumed", extra={"environment": "system"})

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
        if not (
            self.settings.feature_natural_language
            or self.settings.feature_gemini_discord_chat
        ):
            return
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

        # Gemini chat is conversational only when Hypha is directly addressed.
        # It cannot execute actions or mutate the v2 stream.
        if (
            self.settings.feature_gemini_discord_chat
            and self.gemini_voice is not None
            and self.v2_test_runtime is not None
            and decision.environment is Environment.TEST
            and (signals.mentions_bot or signals.replies_to_bot)
        ):
            try:
                context = await build_v2_chat_context(
                    self.v2_test_runtime,
                    player_id=f"discord:{message.author.id}",
                    player_message=message.content,
                    privacy_metadata=_privacy_metadata(message),
                )
                spoken = await self.gemini_voice.reply(context)
                if spoken.clip is not None:
                    await message.channel.send(
                        file=discord.File(
                            io.BytesIO(spoken.clip.audio),
                            filename=spoken.clip.filename,
                            description="Hypha sealed-stone voice reply",
                        ),
                        allowed_mentions=discord.AllowedMentions.none(),
                    )
                elif spoken.text.strip():
                    # Audio is primary. Text is an explicit fallback only when
                    # the sealed-stone renderer cannot produce a clip.
                    await message.channel.send(
                        spoken.text,
                        allowed_mentions=discord.AllowedMentions.none(),
                    )
                return
            except Exception:
                logger.exception(
                    "Gemini sealed-stone chat reply failed",
                    extra={
                        "environment": decision.environment.value,
                        "message_id": message.id,
                        "user_id": message.author.id,
                    },
                )
                await message.channel.send(
                    "Hypha could not render a response. No game state changed.",
                    allowed_mentions=discord.AllowedMentions.none(),
                )
                return

        if self.natural_language is None:
            return

        try:
            result = await self.natural_language.handle(
                decision.environment,
                message.author.id,
                message.content,
                signals,
                idempotency_key=f"discord-message:{message.id}",
                privacy_metadata=_privacy_metadata(message),
            )
        except Exception:
            logger.exception(
                "Natural-language message handling failed",
                extra={
                    "environment": decision.environment.value,
                    "message_id": message.id,
                    "user_id": message.author.id,
                },
            )
            marker = (
                "[TEST SURFACE]\n"
                if (
                    decision.environment is Environment.TEST
                    and self.settings.test_surface_marker_enabled
                )
                else ""
            )
            await message.channel.send(
                marker
                + "Natural-language interpretation encountered an internal error. "
                "No game state changed.",
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return

        if not result.should_respond:
            return

        marker = (
            "[TEST SURFACE]\n"
            if (
                decision.environment is Environment.TEST
                and self.settings.test_surface_marker_enabled
            )
            else ""
        )
        rendered = await self._with_phase_footer(
            result.text,
            decision.environment,
            await self._difficulty_for_user(
                message.author.id,
                decision.environment,
            ),
        )
        chunks = self._discord_chunks(rendered, marker)

        await message.channel.send(
            chunks[0],
            allowed_mentions=discord.AllowedMentions.none(),
        )
        for chunk in chunks[1:]:
            await message.channel.send(
                chunk,
                allowed_mentions=discord.AllowedMentions.none(),
            )

        try:
            voice_file = await self._build_voice_file(
                result.text,
                decision.environment,
                source_message_id=message.id,
            )
            if voice_file is not None:
                await message.channel.send(
                    file=voice_file,
                    allowed_mentions=discord.AllowedMentions.none(),
                )
        except Exception:
            logger.exception(
                "Natural-language voice rendering failed after text delivery",
                extra={
                    "environment": decision.environment.value,
                    "message_id": message.id,
                },
            )

        await self._announce_current_position(
            decision.environment,
            message.channel,
        )

    @staticmethod
    def _render_original_weather_observation(record: Any) -> str:
        """Render one unified Deir el-Medina exterior weather register."""

        reported_at = getattr(record, "reported_at", None)
        if reported_at is None:
            observed_text = "unavailable"
        else:
            observed_text = reported_at.astimezone(UTC).strftime(
                "%Y-%m-%d %H:%M:%S UTC"
            )

        lines = [
            "DEIR EL-MEDINA EXTERIOR REGISTER",
            "════════════════════════════════",
            f"observed at: {observed_text}",
        ]

        fields = (
            ("temperature", "temperature_c", "°C", 1),
            ("pressure", "pressure_mbar", "mbar", 1),
            ("humidity", "humidity_percent", "%", 0),
            ("wind direction", "wind_direction_degrees", "°", 0),
            ("wind speed", "wind_speed_mps", "m/s", 1),
            ("wind gust", "wind_gust_mps", "m/s", 1),
            ("rain / 1h", "rain_1h_mm", "mm", 1),
            ("rain / 24h", "rain_24h_mm", "mm", 1),
            (
                "rain since midnight",
                "rain_since_midnight_mm",
                "mm",
                1,
            ),
            ("luminosity", "luminosity_wm2", "W/m²", 1),
        )

        for label, attribute, unit, precision in fields:
            value = getattr(record, attribute, None)
            if value is None:
                continue
            rendered = f"{float(value):.{precision}f}"
            lines.append(f"{label}: {rendered} {unit}".rstrip())

        lines.append("source: aprs.fi")
        return "\n".join(lines)

    async def _build_exterior_voice_file(
        self,
        report_text: str,
        source_message_id: int,
    ) -> discord.File | None:
        spoken_lines: list[str] = []
        for raw_line in report_text.splitlines():
            line = raw_line.strip()
            if not line or line in {"```", "```text"}:
                continue
            if line.startswith("Data source:"):
                line = "Data source: aprs dot fi"
            if set(line) <= {"═", "─"}:
                continue

            line = line.strip("*")
            line = line.replace(" // ", ". ")
            line = line.replace("°C", " degrees Celsius")
            line = line.replace("mbar", " millibars")
            line = line.replace("m/s", " meters per second")
            line = line.replace("W/m²", " watts per square meter")
            line = line.replace("mm", " millimeters")
            line = line.replace("%", " percent")
            line = line.replace("×", " times ")
            line = line.replace(
                "CONTINUOUS WEATHER INFLUENCE",
                "Continuous weather influence",
            )
            line = line.replace(
                "WATER SYSTEM RESPONSE",
                "Water system response",
            )
            line = line.replace("rain / 1h", "rain during the last hour")
            line = line.replace("rain / 24h", "rain during the last 24 hours")
            line = line.replace("aprs.fi", "A P R S dot fi")

            # The post retains exact multipliers such as ×1.1430. For speech,
            # the percentage and status carry the same game information more
            # clearly and keep the attachment within a practical duration.
            if " (" in line and " times " in line:
                before_multiplier, remainder = line.split(" (", 1)
                if ") " in remainder:
                    _, status = remainder.split(") ", 1)
                    line = f"{before_multiplier}. {status.lstrip('—- ').strip()}"

            spoken_lines.append(line)

        spoken_text = ". ".join(spoken_lines)

        # Exterior reports are intentionally longer than ordinary Hypha
        # responses. Do not let the general-purpose eligibility length gate
        # silently suppress the requested weather attachment.
        if not spoken_text.strip():
            return None

        if not self.voice.eligible(spoken_text):
            logger.info(
                "forcing exterior voice synthesis beyond standard eligibility",
                extra={
                    "environment": Environment.LIVE.value,
                    "message_id": source_message_id,
                    "characters": len(spoken_text),
                },
            )

        try:
            clip = await self.voice.synthesize(spoken_text)
            return discord.File(
                io.BytesIO(clip.audio),
                filename=clip.filename,
                description="Hypha exterior weather voice rendering",
            )
        except VoiceSynthesisError:
            logger.exception(
                "Hypha exterior voice synthesis failed",
                extra={
                    "environment": Environment.LIVE.value,
                    "message_id": source_message_id,
                    "characters": len(spoken_text),
                },
            )
            return None
        except (OSError, ValueError):
            logger.exception(
                "Hypha exterior voice attachment could not be prepared",
                extra={
                    "environment": Environment.LIVE.value,
                    "message_id": source_message_id,
                },
            )
            return None

    async def _send_exterior_weather_report(
        self,
        interaction: discord.Interaction,
        environment: Environment,
        *,
        force_refresh: bool = False,
    ) -> None:
        """Fetch, classify, log, voice, and publish one exterior observation."""

        service = self._aprsfi_service
        if service is None:
            message = "The exterior register is disabled. No game state changed."
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)
            return

        if not interaction.response.is_done():
            await interaction.response.defer()

        try:
            report = await service.report(force_refresh=force_refresh)

            weather_records = self._exterior_cached_weather_records
            if not report.from_cache:
                weather_names = tuple(
                    target.name
                    for target in service.settings.targets
                    if target.enabled and target.weather
                )
                weather_records = (
                    await service.client.query_weather(weather_names)
                    if weather_names
                    else ()
                )
                self._exterior_cached_weather_records = weather_records
        except AprsFiApiError:
            logger.exception("aprs.fi exterior report failed")
            await interaction.followup.send(
                "The exterior register could not be reached. "
                "No game state changed.",
                ephemeral=True,
            )
            return

        effect_text = (
            "SETTLEMENT EFFECT\n"
            "• no usable weather observation was available; "
            "settlement state unchanged"
        )

        usable_record = next(
            (
                record
                for record in weather_records
                if getattr(record, "reported_at", None) is not None
            ),
            None,
        )

        if usable_record is not None:
            observation = observation_from_aprsfi(
                usable_record,
                scope=StationScope.REGIONAL_RELAY,
            )
            weather_state = self._exterior_weather_states[environment]
            outcome = weather_state.evaluate(observation)
            effect_text = await self._record_exterior_weather_outcome(
                interaction=interaction,
                environment=environment,
                outcome=outcome,
            )

            if not outcome.duplicate:
                weather_state.accept(outcome)

        if usable_record is not None:
            weather_text = self._render_original_weather_observation(
                usable_record
            )
            combined_text = (
                f"```text\n{weather_text}\n\n"
                f"{effect_text}\n```\n"
                "*external observation evaluated under deterministic "
                "settlement rules*"
            )
            voice_report_text = f"{weather_text}\n\n{effect_text}"
        else:
            combined_text = report.text
            voice_report_text = report.text
        voice_file = await self._build_exterior_voice_file(
            voice_report_text,
            interaction.id,
        )

        options: dict[str, Any] = {
            "allowed_mentions": discord.AllowedMentions.none(),
        }
        if voice_file is not None:
            options["file"] = voice_file

        await interaction.followup.send(
            combined_text,
            **options,
        )

    async def _record_exterior_weather_outcome(
        self,
        *,
        interaction: discord.Interaction,
        environment: Environment,
        outcome: ExteriorWeatherOutcome,
    ) -> str:
        """
        Apply the optional GameService hook and return public effect text.

        The adapter remains compatible before the persistence hook exists.
        A future GameService implementation may provide:

            async def record_exterior_weather(
                environment: Environment,
                event_payload: dict[str, Any],
                actor_user_id: int,
            ) -> PublicResult
        """

        fallback_text = render_settlement_effects(outcome)
        payload = outcome.to_event_payload(
            environment=environment.value,
        )

        logger.info(
            "exterior weather evaluated",
            extra={
                "environment": environment.value,
                "station": outcome.current.station,
                "observation_key": outcome.current.observation_key,
                "duplicate": outcome.duplicate,
                "conditions": sorted(
                    condition.value for condition in outcome.conditions
                ),
                "triggers": [
                    trigger.kind.value for trigger in outcome.triggers
                ],
                "continuous_influence": payload[
                    "continuous_influence"
                ],
            },
        )

        if self.game is None or outcome.duplicate:
            return fallback_text

        recorder = getattr(self.game, "record_exterior_weather", None)
        if recorder is None:
            return fallback_text

        try:
            result = await recorder(
                environment,
                payload,
                interaction.user.id,
            )
        except (StorageError, ValueError) as exc:
            logger.exception("exterior weather state update failed")
            return (
                f"{fallback_text}\n"
                f"• persistence hook rejected the update: {exc}"
            )

        if isinstance(result, PublicResult):
            return result.text

        result_text = getattr(result, "text", None)
        if isinstance(result_text, str) and result_text.strip():
            return result_text

        return fallback_text

    async def _build_voice_file(
            self,
            text: str,
            environment: Environment,
            *,
            source_message_id: int,
        ) -> discord.File | None:
        if not self.settings.hypha_voice_reply_attachments_enabled:
            return None
        if not self.voice.eligible(text):
            return None

        try:
            clip = await self.voice.synthesize(text)
            return discord.File(
                io.BytesIO(clip.audio),
                filename=clip.filename,
                description="Hypha sealed-stone voice rendering",
            )

        except VoiceSynthesisError:
            logger.exception(
                "Hypha voice synthesis failed",
                extra={
                    "environment": environment.value,
                    "message_id": source_message_id,
                },
            )
            return None

        except discord.HTTPException:
            logger.exception(
                "Hypha voice attachment delivery failed",
                extra={
                    "environment": environment.value,
                    "message_id": source_message_id,
                },
            )
            return None

    async def on_error(self, event_method: str, *args: object, **kwargs: object) -> None:
        del args, kwargs
        logger.exception(
            "unhandled discord event error",
            extra={"event": event_method, "environment": "system"},
        )

    async def close(self) -> None:
        voice_tasks = tuple(self._voice_delivery_tasks)
        for task in voice_tasks:
            task.cancel()
        if voice_tasks:
            await asyncio.gather(*voice_tasks, return_exceptions=True)
        self._voice_delivery_tasks.clear()
        if self._ufo_report_task is not None:
            self._ufo_report_task.cancel()
            try:
                await self._ufo_report_task
            except asyncio.CancelledError:
                pass
            self._ufo_report_task = None
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
        if self._aprsfi_service is not None:
            await self._aprsfi_service.close()
        if self.gemini_voice is not None:
            await self.gemini_voice.close()
            self.gemini_voice = None
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
        send_method = (
            interaction.followup.send
            if interaction.response.is_done()
            else interaction.response.send_message
        )
        await send_method(
            "The interface is inactive for this request.",
            ephemeral=True,
        )
        print(
            "DISCORD AUTH REJECTED:"
            f" reason={decision.reason!r}"
            f" environment={decision.environment.value if decision.environment else 'outside'}"
            f" guild_id={interaction.guild_id}"
            f" channel_id={interaction.channel_id}"
            f" user_id={interaction.user.id}",
            flush=True,
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

    async def _authorize_difficulty_selection(
        self,
        interaction: discord.Interaction,
        required_environment: Environment | None = None,
    ) -> Environment | None:
        decision = self.policy.authorize_difficulty_selection(
            _request_context(interaction),
            self.routing.current,
            required_environment,
        )
        if decision.result is AccessResult.ALLOWED:
            return decision.environment
        await interaction.response.send_message(
            "The difficulty selector is inactive for this request.",
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )
        return None

    async def _difficulty_for(
        self,
        interaction: discord.Interaction,
        environment: Environment,
    ) -> DifficultyLevel:
        discord_user_id = getattr(getattr(interaction, "user", None), "id", None)
        if not isinstance(discord_user_id, int):
            return DifficultyLevel.STANDARD
        return await self._difficulty_for_user(discord_user_id, environment)

    async def _difficulty_for_user(
        self,
        discord_user_id: int,
        environment: Environment,
    ) -> DifficultyLevel:
        if self.repository is None or self.session_refs is None:
            return DifficultyLevel.STANDARD
        try:
            preference = await self.repository.difficulty_preference(
                self.session_refs[environment],
                discord_user_id,
            )
        except (KeyError, StorageError, TypeError, ValueError):
            logger.warning(
                "difficulty preference unavailable; using standard presentation",
                extra={"environment": environment.value},
            )
            return DifficultyLevel.STANDARD
        return preference.level

    async def _record_difficulty_selection(
        self,
        interaction: discord.Interaction,
        level: DifficultyLevel,
    ) -> None:
        environment = await self._authorize_difficulty_selection(
            interaction,
        )
        if environment is None:
            return
        if self.repository is None or self.session_refs is None:
            await interaction.response.send_message(
                "Difficulty preference storage is unavailable. Nothing changed.",
                ephemeral=True,
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return
        message = interaction.message
        if (
            message is None
            or interaction.guild_id is None
            or interaction.channel_id is None
        ):
            await interaction.response.send_message(
                "This difficulty selector is not bound to a verified Hypha message.",
                ephemeral=True,
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return
        try:
            result = await self.repository.record_difficulty_selection(
                self.session_refs[environment],
                guild_id=interaction.guild_id,
                channel_id=interaction.channel_id,
                message_id=message.id,
                discord_user_id=interaction.user.id,
                discord_interaction_id=interaction.id,
                level=level,
            )
        except DifficultyBallotError:
            await interaction.response.send_message(
                "This difficulty selector is closed, stale, copied, or at its safety limit. "
                "Nothing changed.",
                ephemeral=True,
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return
        prefix = "Already saved. " if result.duplicate or not result.changed else ""
        await interaction.response.send_message(
            prefix + difficulty_confirmation(result.preference.level),
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    async def _disable_difficulty_poll_message(self, ballot: Any) -> None:
        try:
            channel = self.get_channel(ballot.channel_id)
            if channel is None:
                channel = await self.fetch_channel(ballot.channel_id)
            fetch_message = getattr(channel, "fetch_message", None)
            if fetch_message is None:
                return
            message = await fetch_message(ballot.message_id)
            await message.edit(
                content=(
                    f"{DIFFICULTY_POLL_TEXT}\n\n"
                    "**This selector is closed. Saved personal preferences remain active.**"
                ),
                view=DifficultyPollView(self, disabled=True),
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except discord.HTTPException:
            logger.warning(
                "closed difficulty selector message could not be disabled",
                extra={"environment": ballot.environment},
            )

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

        difficulty = await self._difficulty_for(interaction, environment)
        rendered = await self._with_phase_footer(
            message,
            environment,
            difficulty,
        )
        chunks = self._discord_chunks(rendered, marker)

        send_options: dict[str, Any] = {
            "allowed_mentions": discord.AllowedMentions.none(),
        }

        if view is not None:
            send_options["view"] = view

        send_method = (
            interaction.followup.send
            if interaction.response.is_done()
            else interaction.response.send_message
        )

        await send_method(chunks[0], **send_options)

        for chunk in chunks[1:]:
            await interaction.followup.send(
                chunk,
                allowed_mentions=discord.AllowedMentions.none(),
            )

        voice_file = await self._build_voice_file(
            message,
            environment,
            source_message_id=interaction.id,
        )
        if voice_file is not None:
            await interaction.followup.send(
                "Optional Hypha narration of the text response above.",
                file=voice_file,
                allowed_mentions=discord.AllowedMentions.none(),
            )

    async def _send_v2_test(
        self,
        interaction: discord.Interaction,
        message: str,
        *,
        identity: str | None = None,
    ) -> None:
        """Send a public v2 response without a v1 phase footer."""

        marker = "[V2]\n"
        if identity is not None:
            marker = f"[V2 · {identity}]\n"
        difficulty = await self._difficulty_for(interaction, Environment.TEST)
        if difficulty is DifficultyLevel.GUIDED:
            message = f"{message}\n\n{guided_support_footer(v2=True)}"
        chunks = self._discord_chunks(message, marker)
        send_method = (
            interaction.followup.send
            if interaction.response.is_done()
            else interaction.response.send_message
        )
        await send_method(
            chunks[0],
            allowed_mentions=discord.AllowedMentions.none(),
        )
        for chunk in chunks[1:]:
            await interaction.followup.send(
                chunk,
                allowed_mentions=discord.AllowedMentions.none(),
            )

    async def _render_v2_transport_response(
        self,
        interaction: discord.Interaction,
        response: Any,
        *,
        projection_status: str | None = None,
    ) -> str:
        del interaction

        result_code = (
            None
            if response.code == "session_state"
            else f"Result code: `{response.code}`"
        )

        return "\n".join(
            filter(
                None,
                (
                    response.to_text(),
                    result_code,
                    projection_status,
                ),
            )
        )

    async def _refresh_v2_activity_projection(self) -> str | None:
        if self.v2_test_runtime is None or self.v2_activity_publisher is None:
            return None
        try:
            session = await self.v2_test_runtime.session()
            result = await asyncio.wait_for(
                self.v2_activity_publisher.publish(
                    self.v2_test_runtime.pack,
                    session,
                ),
                timeout=5.0,
            )
        except (V2ActivityPublishError, TimeoutError):
            logger.warning(
                "v2 Activity projection refresh failed; authoritative v2 remains committed",
                exc_info=True,
                extra={"environment": Environment.TEST.value},
            )
            return (
                "Activity projection: stale; authoritative v2 is still committed "
                "and the next status or accepted command will retry."
            )
        if result.published:
            return f"Activity projection: published revision {result.revision}."
        return f"Activity projection: already current at revision {result.revision}."

    async def _ufo_report_loop(self) -> None:
        service = self._ufo_report_service
        if service is None:
            return
        await self.wait_until_ready()
        while not self.is_closed():
            try:
                result = await service.poll()
                if result.first_successful_poll:
                    logger.info(
                        "UFOSINT report index initialized",
                        extra={
                            "source": result.feed.source_key,
                            "report_count": len(result.feed.reports),
                            "minimum_quality": service.settings.minimum_quality_score,
                            "environment": "system",
                        },
                    )
                else:
                    now = datetime.now(UTC)
                    eligible = tuple(
                        report
                        for report in result.unseen_reports
                        if report.quality_score
                        >= service.settings.minimum_quality_score
                    )
                    recent = tuple(
                        report
                        for report in eligible
                        if report.is_recent_event(
                            now, service.settings.event_max_age_hours
                        )
                    )
                    logger.info(
                        "UFOSINT report intake poll completed",
                        extra={
                            "source": result.feed.source_key,
                            "report_count": len(result.feed.reports),
                            "unseen_count": len(result.unseen_reports),
                            "eligible_count": len(eligible),
                            "recent_count": len(recent),
                            "minimum_quality": service.settings.minimum_quality_score,
                            "environment": "system",
                        },
                    )
                    non_recent = tuple(
                        report for report in eligible if report not in recent
                    )
                    if non_recent:
                        service.mark_seen(non_recent)
                    limit = service.settings.max_announcements_per_poll
                    announced: list[ExternalUfoReport] = []
                    for report in recent[:limit]:
                        if await self._deliver_ufo_report(report):
                            announced.append(report)
                    if announced:
                        service.mark_seen(announced)
                    remaining = recent[limit:]
                    if remaining and await self._deliver_ufo_report_summary(remaining):
                        service.mark_seen(remaining)
                    if not recent:
                        await self._deliver_ufo_report_idle_summary(
                            result.feed,
                            unseen_count=len(result.unseen_reports),
                            recent_count=len(recent),
                        )
            except asyncio.CancelledError:
                raise
            except UfoReportFeedError:
                logger.warning(
                    "UFOSINT report intake failed; no game state changed",
                    exc_info=True,
                    extra={"environment": "system"},
                )
            except (discord.DiscordException, OSError, RuntimeError, ValueError):
                logger.exception(
                    "UFOSINT report delivery failed; no game state changed",
                    extra={"environment": "system"},
                )
            await asyncio.sleep(service.settings.poll_seconds)

    async def _ufo_report_channel(self) -> discord.TextChannel:
        service = self._ufo_report_service
        if service is None or service.settings.channel_id is None:
            raise RuntimeError("UFOSINT report channel is not configured")
        channel = self.get_channel(service.settings.channel_id)
        if channel is None:
            channel = await self.fetch_channel(service.settings.channel_id)
        if (
            not isinstance(channel, discord.TextChannel)
            or channel.guild.id != self.settings.discord_guild_id
        ):
            raise RuntimeError(
                "configured UFO report channel is not a text channel in the configured guild"
            )
        return channel

    async def _ufo_report_already_posted(
        self,
        channel: discord.TextChannel,
        marker: str,
        report: ExternalUfoReport | None = None,
    ) -> bool:
        async for message in channel.history(limit=500):
            if message.author.id != (self.user.id if self.user else None):
                continue
            for embed in message.embeds:
                if report is not None:
                    if _ufo_report_embed_matches_posted(report, embed, marker):
                        return True
                elif getattr(getattr(embed, "footer", None), "text", "") == marker:
                    return True
        return False

    async def _deliver_ufo_report(self, report: ExternalUfoReport) -> bool:
        service = self._ufo_report_service
        if service is None:
            return False
        if report.quality_score < service.settings.minimum_quality_score:
            logger.warning(
                "discarded UFOSINT report below configured quality threshold",
                extra={
                    "source": report.source_key,
                    "report_id": report.report_id,
                    "quality_score": report.quality_score,
                    "minimum_quality": service.settings.minimum_quality_score,
                    "environment": "system",
                },
            )
            return False
        channel = await self._ufo_report_channel()
        if await self._ufo_report_already_posted(channel, report.marker, report):
            return True
        embed = discord.Embed(
            title="UFOSINT REPORT INDEX UPDATE",
            description=report.title[:4096],
            color=discord.Color.from_rgb(214, 176, 91),
            url=report.source_url or report.source_page_url,
        )
        if report.summary:
            summary_parts = [
                report.summary[index:index + 1024]
                for index in range(0, len(report.summary), 1024)
            ]

            for index, part in enumerate(summary_parts):
                embed.add_field(
                    name=(
                        "Witness summary"
                        if index == 0
                        else f"Witness summary continued {index + 1}"
                    ),
                    value=part,
                    inline=False,
                )
        embed.add_field(
            name="Event date",
            value=_ufo_report_event_date_label(report),
            inline=True,
        )
        embed.add_field(
            name="Detected in index",
            value=discord.utils.format_dt(report.indexed_at, style="R"),
            inline=True,
        )
        embed.add_field(
            name="Report ID",
            value=f"{report.source_key}:{report.report_id}",
            inline=True,
        )
        embed.add_field(
            name="Data quality",
            value=(
                f"{report.quality_score}/100 · required "
                f">= {service.settings.minimum_quality_score}"
            ),
            inline=True,
        )
        embed.add_field(
            name="Location",
            value=(
                f"{report.location_name}\n"
                f"Approximation: {report.coordinate_precision}"
            )[:1024],
            inline=False,
        )
        embed.add_field(
            name="Source and status",
            value=(
                f"{report.source_name} · {report.status}\n"
                "Newly indexed external record. UFOSINT does not expose a "
                "per-record publication timestamp. No authoritative game-state effect."
            )[:1024],
            inline=False,
        )
        embed.set_footer(text=report.marker)
        sidequest_view = _ufo_report_sidequest_view(
            report,
            self.application_id,
        )
        voice_file: discord.File | None = None

        if (
            service.settings.voice_enabled
            and self.settings.hypha_voice_enabled
        ):
            voice_file = await self._build_ufo_report_voice_file(
                report,
            )

        if voice_file is not None:
            await channel.send(
                embed=embed,
                file=voice_file,
                view=sidequest_view,
                allowed_mentions=(
                    discord.AllowedMentions.none()
                ),
            )
        else:
            await channel.send(
                embed=embed,
                view=sidequest_view,
                allowed_mentions=(
                    discord.AllowedMentions.none()
                ),
            )

        return True

    async def _deliver_ufo_report_summary(
        self,
        reports: tuple[ExternalUfoReport, ...],
    ) -> bool:
        if not reports:
            return True
        channel = await self._ufo_report_channel()
        marker_seed = "|".join(
            f"{report.source_key}:{report.report_id}" for report in reports
        )
        marker = (
            "Hypha external report batch · "
            + hashlib.sha256(marker_seed.encode("utf-8")).hexdigest()[:20]
        )
        if await self._ufo_report_already_posted(channel, marker):
            return True
        embed = discord.Embed(
            title="UFOSINT REPORT INDEX SUMMARY",
            description=(
                f"{len(reports)} additional newly detected UFOSINT records "
                "describe events within the configured recent-event window. "
                "All passed the quality threshold above 50 percent and are "
                "available on the map. Individual narration was suppressed "
                "to prevent channel flooding."
            ),
            color=discord.Color.from_rgb(165, 146, 190),
        )
        embed.set_footer(text=marker)
        await channel.send(
            embed=embed,
            allowed_mentions=discord.AllowedMentions.none(),
        )
        return True


    async def _deliver_ufo_report_idle_summary(
        self,
        feed: UfoReportFeed,
        *,
        unseen_count: int,
        recent_count: int,
    ) -> bool:
        channel = await self._ufo_report_channel()
        latest = max(
            feed.reports,
            key=lambda report: (
                report.indexed_at,
                report.observed_at,
                report.report_id,
            ),
            default=None,
        )
        embed = discord.Embed(
            title="UFOSINT INTAKE STATUS",
            description=(
                "Automatic UFOSINT intake completed. No newly eligible report "
                "was posted in this cycle."
            ),
            color=discord.Color.from_rgb(91, 132, 170),
        )
        embed.add_field(
            name="Poll result",
            value=(
                f"Qualifying records returned: {len(feed.reports)}\n"
                f"Not recorded as delivered: {unseen_count}\n"
                f"Recent enough to announce: {recent_count}"
            ),
            inline=False,
        )
        if latest is not None:
            embed.add_field(
                name="Latest returned record",
                value=(
                    f"{latest.title}\n"
                    f"Report ID: {latest.source_key}:{latest.report_id}\n"
                    f"Event date: {latest.observed_at.date().isoformat()}\n"
                    f"Quality: {latest.quality_score}/100"
                )[:1024],
                inline=False,
            )
        event_window_hours = (
            self._ufo_report_service.settings.event_max_age_hours
            if self._ufo_report_service else 48
        )
        embed.add_field(
            name="Policy",
            value=(
                "The automatic report post only announces records that are both "
                "not already recorded as delivered and within the configured "
                f"{event_window_hours}-hour event window."
            )[:1024],
            inline=False,
        )
        await channel.send(
            embed=embed,
            allowed_mentions=discord.AllowedMentions.none(),
        )
        return True

    async def _build_ufo_report_voice_file(
        self,
        report: ExternalUfoReport,
    ) -> discord.File | None:
        summary = (
            report.summary
            or report.title
        ).strip()

        spoken_text = (
            "Hypha UFOSINT report index update. "
            "Witness summary. "
            f"{summary} "
            "The event date is "
            f"{report.observed_at.strftime('%B %d, %Y')}. "
            "The reported location is "
            f"{report.location_name}, with "
            f"{report.coordinate_precision} precision. "
            "The UFOSINT data quality score is "
            f"{report.quality_score} out of 100. "
            "This is an unverified external index record, "
            "not a confirmed live event, and it has no "
            "effect on authoritative investigation state."
        )

        try:
            clip = await self.voice.synthesize(
                spoken_text,
            )

            return discord.File(
                io.BytesIO(clip.audio),
                filename=(
                    f"hypha-ufosint-"
                    f"{report.report_id}.ogg"
                )[:240],
                description=(
                    "Hypha speak-ng narration of a "
                    "UFOSINT index update"
                ),
            )

        except asyncio.CancelledError:
            raise

        except (
            VoiceSynthesisError,
            OSError,
            ValueError,
        ):
            logger.exception(
                "UFOSINT voice synthesis failed; "
                "sending text-only report",
                extra={
                    "source": report.source_key,
                    "report_id": report.report_id,
                    "environment": "system",
                },
            )
            return None

    async def _deliver_ufo_report_voice(
        self,
        channel: discord.TextChannel,
        report: ExternalUfoReport,
    ) -> None:
        summary = (report.summary or report.title).strip()
        spoken_text = (
            "Hypha UFOSINT report index update. "
            "Witness summary. "
            f"{summary} "
            f"The event date is {report.observed_at.strftime('%B %d, %Y')}. "
            f"The reported location is {report.location_name}, with "
            f"{report.coordinate_precision} precision. "
            f"The UFOSINT data quality score is {report.quality_score} out of 100. "
            "This is an unverified external index record, not a confirmed live event, "
            "and it has no effect on authoritative investigation state."
        )
        try:
            clip = await self.voice.synthesize(spoken_text)
            await channel.send(
                "Optional Hypha speak-ng narration of the UFOSINT record above.",
                file=discord.File(
                    io.BytesIO(clip.audio),
                    filename=(
                        f"hypha-ufosint-{report.report_id}.ogg"
                    )[:240],
                    description="Hypha speak-ng narration of a UFOSINT index update",
                ),
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except asyncio.CancelledError:
            raise
        except (discord.DiscordException, VoiceSynthesisError, OSError, ValueError):
            logger.exception(
                "UFOSINT voice synthesis failed; text was already delivered",
                extra={
                    "source": report.source_key,
                    "report_id": report.report_id,
                    "environment": "system",
                },
            )

    def _current_v2_bulletin(
        self,
        session: Any,
    ) -> tuple[str, str, str, tuple[str, ...]] | None:
        if self.v2_test_runtime is None:
            return None
        pack = self.v2_test_runtime.pack
        state = session.state
        position = next(
            (item for item in pack.positions if item.id == state.current_position_id),
            None,
        )
        if position is None:
            return None

        ending_selection = state.get_adaptation_selection("ending")
        if position.id in state.completed_position_ids and ending_selection is not None:
            if pack.endings is None:
                return None
            ending = next(
                (
                    item
                    for item in (
                        pack.endings.corrective,
                        pack.endings.baseline,
                        pack.endings.advanced,
                    )
                    if item.presentation_id == ending_selection.presentation_id
                ),
                None,
            )
            if ending is None:
                return None
            return (
                ending.presentation_id,
                "FINAL DISTRIBUTED RECORD",
                ending.prose,
                (),
            )

        selection = state.get_adaptation_selection(position.id)
        if selection is not None and position.adaptation is not None:
            variant = next(
                (
                    item
                    for item in (
                        position.adaptation.corrective,
                        position.adaptation.baseline,
                        position.adaptation.advanced,
                    )
                    if item.presentation_id == selection.presentation_id
                ),
                None,
            )
            if variant is not None:
                return (
                    variant.presentation_id,
                    f"POSITION {position.ordinal} · {position.title.upper()}",
                    variant.prologue,
                    tuple(variant.guidance),
                )

        if position.fixed_opening is None:
            return None
        return (
            position.fixed_opening.presentation_id,
            f"POSITION {position.ordinal} · {position.title.upper()}",
            position.fixed_opening.prologue,
            tuple(position.fixed_opening.guidance),
        )

    async def _deliver_current_v2_bulletin(self) -> str:
        channel_id = self.settings.v2_bulletin_channel_id
        if channel_id is None or self.v2_test_runtime is None:
            return "disabled"

        async with self._v2_bulletin_lock:
            try:
                session = await self.v2_test_runtime.session()
                bulletin = self._current_v2_bulletin(session)
                if bulletin is None:
                    return "no-bulletin"
                presentation_id, title, prose, guidance = bulletin
                marker = f"Hypha record · {presentation_id}"

                channel = self.get_channel(channel_id)
                if channel is None:
                    channel = await self.fetch_channel(channel_id)
                if (
                    not isinstance(channel, discord.TextChannel)
                    or channel.guild.id != self.settings.discord_guild_id
                ):
                    raise RuntimeError(
                        "configured v2 bulletin channel is not a text channel "
                        "in the configured guild"
                    )

                async for message in channel.history(limit=100):
                    if message.author.id != (self.user.id if self.user else None):
                        continue
                    if any(embed.footer.text == marker for embed in message.embeds):
                        return "already-present"

                embed = discord.Embed(
                    title=title[:256],
                    description=prose[:4096],
                    color=discord.Color.from_rgb(95, 158, 160),
                )
                if guidance:
                    guidance_text = "\n".join(f"• {item}" for item in guidance)
                    embed.add_field(
                        name="Routing instructions",
                        value=guidance_text[:1024],
                        inline=False,
                    )
                embed.set_footer(text=marker)

                files: list[discord.File] = []
                bulletin_images: dict[str, tuple[str, str, str]] = {
                    "network_orientation_fixed_opening": (
                        "6_positions.png",
                        "position0.png",
                        "The six facility consoles at the opening of the observation window.",
                    ),
                }

                lowered_title = title.casefold()

                if (
                    presentation_id not in bulletin_images
                    and (
                        "first return" in lowered_title
                        or lowered_title.startswith("position 1")
                    )
                ):
                    bulletin_images[presentation_id] = (
                        "boundary_array.png",
                        "boundary_array.png",
                        "The Boundary Array visual record accompanying Position 1 ? First Return.",
                    )

                image_spec = bulletin_images.get(presentation_id)

                if image_spec is not None:
                    asset_filename, attachment_filename, attachment_description = image_spec
                    image_path = _CONTENT_ASSETS_ROOT / asset_filename

                    try:
                        image_bytes = await asyncio.to_thread(image_path.read_bytes)
                    except OSError:
                        image_bytes = None

                    if image_bytes is not None:
                        files.append(
                            discord.File(
                                io.BytesIO(image_bytes),
                                filename=attachment_filename,
                                description=attachment_description,
                            )
                        )
                        embed.set_image(
                            url=f"attachment://{attachment_filename}"
                        )
                    else:
                        logger.error(
                            "v2 bulletin image is missing",
                            extra={
                                "environment": Environment.TEST.value,
                                "channel_id": channel_id,
                                "presentation_id": presentation_id,
                                "image_path": str(image_path),
                            },
                        )

                spoken_guidance = ". ".join(guidance)
                spoken_text = f"{title}. {prose}"
                if spoken_guidance:
                    spoken_text = f"{spoken_text}. Routing instructions. {spoken_guidance}"

                await channel.send(
                    embed=embed,
                    files=files,
                    allowed_mentions=discord.AllowedMentions.none(),
                )

                if self.settings.hypha_voice_bulletins_enabled:
                    voice_task = asyncio.create_task(
                        self._deliver_v2_bulletin_voice(
                            channel=channel,
                            channel_id=channel_id,
                            presentation_id=presentation_id,
                            spoken_text=spoken_text,
                        ),
                        name=f"v2-bulletin-voice:{presentation_id}",
                    )
                    self._voice_delivery_tasks.add(voice_task)
                    voice_task.add_done_callback(
                        self._voice_delivery_tasks.discard
                    )
                return "delivered"
            except (
                discord.DiscordException,
                OSError,
                RuntimeError,
                V2TestRuntimeError,
                ValueError,
            ):
                logger.exception(
                    "v2 circulation-desk delivery failed; authoritative state is unchanged",
                    extra={
                        "environment": Environment.TEST.value,
                        "channel_id": channel_id,
                    },
                )
                return "failed"

    async def _deliver_v2_bulletin_voice(
        self,
        *,
        channel: discord.TextChannel,
        channel_id: int,
        presentation_id: str,
        spoken_text: str,
    ) -> None:
        """Deliver redundant bulletin narration without delaying command text."""

        try:
            clip = await self.voice.synthesize(spoken_text)
            await channel.send(
                "Optional Hypha narration of the bulletin above. "
                "The complete text remains in the bulletin.",
                file=discord.File(
                    io.BytesIO(clip.audio),
                    filename=f"hypha-{presentation_id}.ogg",
                    description=(
                        "Optional Hypha voice rendering of the "
                        "same facility bulletin text"
                    ),
                ),
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except asyncio.CancelledError:
            raise
        except (discord.DiscordException, VoiceSynthesisError):
            logger.exception(
                "v2 bulletin voice synthesis or delivery failed; "
                "text and image were already delivered",
                extra={
                    "environment": Environment.TEST.value,
                    "channel_id": channel_id,
                    "presentation_id": presentation_id,
                },
            )


    async def _send_deferred_action(
        self,
        interaction: discord.Interaction,
        result: PublicResult,
        environment: Environment,
        view: discord.ui.View | None = None,
    ) -> None:
        message = result.text
        phase_footer = result.phase_footer
        difficulty = await self._difficulty_for(interaction, environment)

        if difficulty is DifficultyLevel.EXPERT:
            rendered = message
        elif phase_footer:
            rendered = f"{message}\n\n{phase_footer}"
            if difficulty is DifficultyLevel.GUIDED:
                rendered = f"{rendered}\n\n{guided_support_footer()}"
        else:
            rendered = await self._with_phase_footer(
                message,
                environment,
                difficulty,
            )

        marker = ""
        if environment is Environment.TEST and self.settings.test_surface_marker_enabled:
            marker = "[TEST SURFACE]\n"

        chunks = self._discord_chunks(rendered, marker)
        files: list[discord.File] = []

        image_attachment = result.attachment
        if image_attachment is not None:
            files.append(
                discord.File(
                    io.BytesIO(image_attachment.image_bytes),
                    filename=image_attachment.image_filename,
                    description=image_attachment.image_alt_text,
                )
            )

        send_options: dict[str, Any] = {
            "allowed_mentions": discord.AllowedMentions.none(),
        }

        if files:
            send_options["files"] = files

        if view is not None:
            send_options["view"] = view

        await interaction.followup.send(
            chunks[0],
            **send_options,
        )

        for chunk in chunks[1:]:
            await interaction.followup.send(
                chunk,
                allowed_mentions=discord.AllowedMentions.none(),
            )

        voice_file = await self._build_voice_file(
            result.text,
            environment,
            source_message_id=interaction.id,
        )
        if voice_file is not None:
            await interaction.followup.send(
                "Optional Hypha narration of the text response above.",
                file=voice_file,
                allowed_mentions=discord.AllowedMentions.none(),
            )

    async def _with_phase_footer(
        self,
        message: str,
        environment: Environment,
        difficulty: DifficultyLevel = DifficultyLevel.STANDARD,
    ) -> str:
        if difficulty is DifficultyLevel.EXPERT:
            return message
        rendered = message
        if self.game is None:
            if difficulty is DifficultyLevel.GUIDED:
                return f"{rendered}\n\n{guided_support_footer()}"
            return rendered
        try:
            footer = await self.game.current_phase_footer(environment)
        except StorageError:
            logger.warning(
                "current phase unavailable for Discord reply",
                extra={"environment": environment.value},
            )
        else:
            rendered = f"{rendered}\n\n{footer}"
        if difficulty is DifficultyLevel.GUIDED:
            rendered = f"{rendered}\n\n{guided_support_footer()}"
        return rendered

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

    def _build_v2_command_group(self) -> app_commands.Group:
        group = app_commands.Group(
            name="v2",
            description="Authoritative public commands for The Missing Interior v2",
        )

        @group.command(name="status", description="Show the shared v2 investigation state")
        async def v2_status(interaction: discord.Interaction) -> None:
            environment = await self._authorize_admin(interaction, Environment.TEST)
            if environment is None:
                return
            if self.v2_test_runtime is None:
                await self._send_v2_test(
                    interaction,
                    "The v2 runtime is not enabled on this deployment.",
                )
                return

            if not interaction.response.is_done():
                await interaction.response.defer(thinking=True)

            try:
                response = await self.v2_test_runtime.public_status(
                    player_id=f"discord:{interaction.user.id}",
                )
                projection_status = await self._refresh_v2_activity_projection()
                await self._send_v2_test(
                    interaction,
                    await self._render_v2_transport_response(
                        interaction,
                        response,
                        projection_status=projection_status,
                    ),
                )
            except Exception:
                logger.exception(
                    "unhandled v2 status failure",
                    extra={
                        "environment": environment.value,
                        "discord_user_id": interaction.user.id,
                    },
                )
                await self._send_v2_test(
                    interaction,
                    "The v2 status command failed internally. Check the Hypha console.",
                )

        @group.command(
            name="start",
            description="Post the current opening to the circulation desk",
        )
        async def v2_start(interaction: discord.Interaction) -> None:
            environment = await self._authorize_admin(interaction, Environment.TEST)
            if environment is None:
                return
            delivery = await self._deliver_current_v2_bulletin()
            responses = {
                "delivered": (
                    "Hypha posted the current opening, image, and voice rendering "
                    "to the circulation desk."
                ),
                "already-present": (
                    "The current opening is already present in the circulation desk; "
                    "Hypha did not duplicate it."
                ),
                "disabled": (
                    "The circulation desk is not configured, so nothing was posted."
                ),
                "no-bulletin": (
                    "The current v2 state has no opening bulletin to post."
                ),
                "failed": (
                    "Hypha could not post the current opening. No v2 state changed."
                ),
            }
            await self._send_v2_test(interaction, responses[delivery])

        @group.command(
            name="ufo-latest-test",
            description="Post and narrate the latest qualifying UFOSINT report",
        )
        async def v2_ufo_latest_test(
            interaction: discord.Interaction,
        ) -> None:
            permissions = interaction.user.guild_permissions

            if not (
                permissions.administrator
                or permissions.manage_guild
            ):
                send_method = (
                    interaction.followup.send
                    if interaction.response.is_done()
                    else interaction.response.send_message
                )
                await send_method(
                    "This maintenance test requires Administrator "
                    "or Manage Server permission.",
                    ephemeral=True,
                )
                return

            environment = Environment.TEST

            service = self._ufo_report_service

            if service is None:
                await self._send_v2_test(
                    interaction,
                    "UFOSINT intake is not enabled on this deployment.",
                )
                return

            if not interaction.response.is_done():
                await interaction.response.defer(
                    thinking=True,
                )

            try:
                candidates = (
                    await service.latest_qualifying_reports()
                )

                if not candidates:
                    await interaction.followup.send(
                        "UFOSINT returned no qualifying "
                        "reports during the configured "
                        f"{service.settings.ufosint_lookback_days}-day search window.",
                        allowed_mentions=(
                            discord.AllowedMentions.none()
                        ),
                    )
                    return

                channel = await self._ufo_report_channel()
                latest = await _first_unposted_ufo_report(
                    service,
                    channel,
                    candidates,
                    self._ufo_report_already_posted,
                    respect_seen_state=False,
                )

                if latest is None:
                    await interaction.followup.send(
                        "Every qualifying UFOSINT report in the configured "
                        f"{service.settings.ufosint_lookback_days}-day search window "
                        "has already been posted or recorded as delivered.",
                        allowed_mentions=(
                            discord.AllowedMentions.none()
                        ),
                    )
                    return

                delivered = await self._deliver_ufo_report(
                    latest,
                )

                if delivered:
                    service.mark_seen((latest,))
                    message = (
                        "Hypha posted the newest not-yet-posted qualifying UFOSINT "
                        "report to the circulation desk in one message. "
                        "Observed date: "
                        f"{latest.observed_at.date().isoformat()}."
                    )

                    if (
                        service.settings.voice_enabled
                        and self.settings.hypha_voice_enabled
                    ):
                        message += (
                            " The same message includes speak-ng "
                            "narration of the complete sanitized "
                            "witness summary."
                        )
                    else:
                        message += (
                            " Voice narration is currently disabled."
                        )
                else:
                    message = (
                        "The report was not delivered. Check the "
                        "Hypha console for the specific error."
                    )

                await interaction.followup.send(
                    message,
                    view=(
                        _ufo_report_sidequest_view(
                            latest,
                            self.application_id,
                        )
                        if delivered
                        else None
                    ),
                    allowed_mentions=discord.AllowedMentions.none(),
                )

            except UfoReportFeedError:
                logger.exception(
                    "manual UFOSINT test fetch failed",
                    extra={
                        "environment": environment.value,
                        "discord_user_id": interaction.user.id,
                    },
                )

                await interaction.followup.send(
                    "UFOSINT could not be reached. Nothing was posted.",
                    allowed_mentions=discord.AllowedMentions.none(),
                )

            except (
                discord.DiscordException,
                OSError,
                RuntimeError,
                ValueError,
            ):
                logger.exception(
                    "manual UFOSINT test delivery failed",
                    extra={
                        "environment": environment.value,
                        "discord_user_id": interaction.user.id,
                    },
                )

                await interaction.followup.send(
                    "The test delivery failed. No game state changed.",
                    allowed_mentions=discord.AllowedMentions.none(),
                )

        @group.command(
            name="begin",
            description="Complete Position 0 orientation and open Position 1",
        )
        async def v2_begin(interaction: discord.Interaction) -> None:
            environment = await self._authorize_admin(interaction, Environment.TEST)
            if environment is None:
                return
            if self.v2_test_runtime is None:
                await self._send_v2_test(
                    interaction,
                    "The v2 test runtime is not enabled on this deployment.",
                    identity="investigator-a",
                )
                return
            try:
                response = await self.v2_test_runtime.execute(
                    identity="investigator-a",
                    text="begin-investigation",
                )
            except V2TestRuntimeError:
                logger.exception(
                    "v2 Position 0 transition failed",
                    extra={"environment": environment.value},
                )
                await self._send_v2_test(
                    interaction,
                    "Position 0 could not close safely. No v2 state changed.",
                    identity="investigator-a",
                )
                return
            projection_status = (
                await self._refresh_v2_activity_projection()
                if response.accepted
                else None
            )
            if response.accepted:
                await self._deliver_current_v2_bulletin()
            await self._send_v2_test(
                interaction,
                await self._render_v2_transport_response(
                    interaction,
                    response,
                    projection_status=projection_status,
                ),
                identity="investigator-a",
            )

        @group.command(
            name="command",
            description="Run one strict v2 command as your Discord identity",
        )
        @app_commands.describe(
            text="Strict v2 command text, such as: examine-evidence optical_record",
        )
        async def v2_command(
            interaction: discord.Interaction,
            text: str,
        ) -> None:
            environment = await self._authorize_admin(interaction, Environment.TEST)
            if environment is None:
                return

            if self.v2_test_runtime is None:
                await self._send_v2_test(
                    interaction,
                    "The v2 runtime is not enabled on this deployment.",
                )
                return

            # Acknowledge Discord before executing potentially slow work.
            if not interaction.response.is_done():
                await interaction.response.defer()

            player_id = f"discord:{interaction.user.id}"

            try:
                response = await self.v2_test_runtime.execute_public(
                    player_id=player_id,
                    text=text,
                )
            except V2TestRuntimeError:
                logger.exception(
                    "public v2 command failed",
                    extra={
                        "environment": environment.value,
                        "discord_user_id": interaction.user.id,
                    },
                )
                await self._send_v2_test(
                    interaction,
                    "The v2 command could not run. No v2 state changed.",
                )
                return
            except Exception:
                logger.exception(
                    "unexpected public v2 command failure",
                    extra={
                        "environment": environment.value,
                        "discord_user_id": interaction.user.id,
                    },
                )
                await self._send_v2_test(
                    interaction,
                    "Hypha encountered an unexpected v2 error. Check the bot console.",
                )
                return

            projection_status = None
            if response.accepted:
                try:
                    projection_status = await self._refresh_v2_activity_projection()
                except Exception:
                    logger.exception(
                        "unexpected v2 Activity synchronization failure",
                        extra={
                            "environment": environment.value,
                            "discord_user_id": interaction.user.id,
                        },
                    )
                    projection_status = (
                        "Activity projection: update failed; authoritative v2 state "
                        "remains committed."
                    )

            await self._send_v2_test(
                interaction,
                await self._render_v2_transport_response(
                    interaction,
                    response,
                    projection_status=projection_status,
                ),
                identity=interaction.user.display_name,
            )

            if response.accepted:
                try:
                    await self._deliver_current_v2_bulletin()
                except Exception:
                    logger.exception(
                        "v2 post-command bulletin delivery failed",
                        extra={
                            "environment": environment.value,
                            "discord_user_id": interaction.user.id,
                        },
                    )

        async def v2_command_autocomplete(
            interaction: discord.Interaction,
            current: str,
        ) -> list[app_commands.Choice[str]]:
            """Show valid commands and every current-position role."""

            fallback = (
                ("Release current role", "release-role"),
                ("Examine optical record", "examine-evidence optical_record"),
                ("Examine radio return", "examine-evidence radio_return"),
                ("Inspect optical record", "perform-action inspect_optical_record"),
                (
                    "Run receiver diagnostic",
                    "perform-action calibrate_radio_receiver",
                ),
                (
                    "Retrieve weather record",
                    "perform-action request_weather_record",
                ),
                (
                    "Compare source timing",
                    "perform-action compare_source_timing",
                ),
            )

            query = current.strip().casefold()
            candidates: list[tuple[str, str]] = []

            if self.v2_test_runtime is not None:
                try:
                    guided = await self.v2_test_runtime.available_public_commands(
                        player_id=f"discord:{interaction.user.id}",
                        current="",
                    )
                    candidates.extend(
                        (label, command)
                        for command, label in guided
                    )

                    # Fetch every role valid for the current position. Passing an
                    # empty query prevents role filtering before the combined
                    # command autocomplete applies the user's search text.
                    roles = await self.v2_test_runtime.available_public_roles("")
                    candidates.extend(
                        (
                            f"Assign role — {label}",
                            f"assign-role {role_id}",
                        )
                        for role_id, label in roles
                    )
                except Exception:
                    logger.exception(
                        "dynamic public v2 autocomplete failed; using fallback",
                        extra={"discord_user_id": interaction.user.id},
                    )

            # Role release must remain visible even when guided suggestions do
            # not currently require a role change.
            candidates.append(("Release current role", "release-role"))

            if not candidates:
                candidates.extend(fallback)

            unique: list[tuple[str, str]] = []
            seen_commands: set[str] = set()

            for label, command in candidates:
                if command in seen_commands:
                    continue

                if query and (
                    query not in label.casefold()
                    and query not in command.casefold()
                ):
                    continue

                seen_commands.add(command)
                unique.append((label, command))

            return [
                app_commands.Choice(
                    name=label[:100],
                    value=command[:100],
                )
                for label, command in unique[:25]
                if len(command) <= 100
            ]

        v2_command.autocomplete("text")(v2_command_autocomplete)

        @group.command(
            name="role",
            description="Choose a current investigative function and optional public title",
        )
        @app_commands.describe(
            role="Canonical function; begin typing to see currently available roles",
            name="Optional public title for this assignment",
            description="Optional short description of how you will approach the function",
        )
        async def v2_role(
            interaction: discord.Interaction,
            role: str,
            name: str | None = None,
            description: str | None = None,
        ) -> None:
            environment = await self._authorize_admin(interaction, Environment.TEST)
            if environment is None:
                return

            if self.v2_test_runtime is None:
                await self._send_v2_test(
                    interaction,
                    "The v2 runtime is not enabled on this deployment.",
                )
                return
            if not interaction.response.is_done():
                await interaction.response.defer(thinking=True)
            try:
                response = await self.v2_test_runtime.assign_public_role(
                    player_id=f"discord:{interaction.user.id}",
                    role_id=role,
                    display_name=name,
                    description=description,
                )
            except (V2TestRuntimeError, ValueError):
                logger.exception(
                    "public v2 role assignment failed",
                    extra={"discord_user_id": interaction.user.id, "role_id": role},
                )
                await self._send_v2_test(
                    interaction,
                    "That role assignment could not be recorded. No v2 state changed.",
                )
                return
            projection_status = (
                await self._refresh_v2_activity_projection()
                if response.accepted
                else None
            )
            await self._send_v2_test(
                interaction,
                await self._render_v2_transport_response(
                    interaction,
                    response,
                    projection_status=projection_status,
                ),
                identity=interaction.user.display_name,
            )

        async def v2_role_autocomplete(
            interaction: discord.Interaction,
            current: str,
        ) -> list[app_commands.Choice[str]]:
            if self.v2_test_runtime is None:
                return []
            try:
                choices = await self.v2_test_runtime.available_public_roles(current)
            except V2TestRuntimeError:
                return []
            return [
                app_commands.Choice(name=label[:100], value=role_id)
                for role_id, label in choices
                if len(role_id) <= 100
            ]

        v2_role.autocomplete("role")(v2_role_autocomplete)

        @group.command(
            name="guide",
            description="Show the current public case guide and available functions",
        )
        async def v2_guide(
            interaction: discord.Interaction,
        ) -> None:
            environment = await self._authorize_admin(interaction, Environment.TEST)
            if environment is None:
                return

            if self.v2_test_runtime is None:
                await self._send_v2_test(
                    interaction,
                    "The v2 runtime is not enabled on this deployment.",
                )
                return

            try:
                guide = await self.v2_test_runtime.public_guide(
                    player_id=f"discord:{interaction.user.id}",
                )
            except V2TestRuntimeError:
                logger.exception(
                    "public v2 guide failed",
                    extra={"discord_user_id": interaction.user.id},
                )
                await self._send_v2_test(
                    interaction,
                    "The current guide could not be assembled safely.",
                )
                return

            await self._send_v2_test(
                interaction,
                guide,
            )

        @group.command(
            name="difficulty",
            description="Open or inspect the private per-user difficulty selector",
        )
        @app_commands.describe(
            action="Open, close, or inspect the selector",
            confirm="Required only when closing the active selector",
        )
        @app_commands.choices(
            action=[
                app_commands.Choice(name="Open selector", value="open"),
                app_commands.Choice(name="Close selector", value="close"),
                app_commands.Choice(name="Selector status", value="status"),
                app_commands.Choice(name="My selection", value="mine"),
            ]
        )
        async def v2_difficulty(
            interaction: discord.Interaction,
            action: app_commands.Choice[str],
            confirm: bool = False,
        ) -> None:
            await self._handle_v2_difficulty_action(
                interaction, action, confirm, Environment.TEST,
            )

        return group

    async def _handle_v2_difficulty_action(
        self, interaction: discord.Interaction, action: app_commands.Choice[str],
        confirm: bool, required_environment: Environment,
    ) -> None:
        marker = "[V2 TEST]" if required_environment is Environment.TEST else "[V2 LIVE]"
        if action.value == "mine":
            environment = await self._authorize_difficulty_selection(
                interaction,
                required_environment,
            )
        else:
            environment = await self._authorize_admin(
                interaction,
                required_environment,
            )
        if environment is None:
            return
        if self.repository is None or self.session_refs is None:
            await interaction.response.send_message(
                "Difficulty preference storage is unavailable. Nothing changed.",
                ephemeral=True,
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return
        ref = self.session_refs[environment]

        if action.value == "mine":
            try:
                preference = await self.repository.difficulty_preference(
                    ref,
                    interaction.user.id,
                )
            except StorageError:
                await interaction.response.send_message(
                    "Your difficulty preference is temporarily unavailable. "
                    "Nothing changed.",
                    ephemeral=True,
                    allowed_mentions=discord.AllowedMentions.none(),
                )
                return
            await interaction.response.send_message(
                f"Your current selection is **{DIFFICULTY_LABELS[preference.level]}** "
                f"(preference revision {preference.revision}).",
                ephemeral=True,
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return

        if action.value == "status":
            try:
                ballot = await self.repository.active_difficulty_ballot(ref)
                if ballot is None:
                    status = "No Hypha difficulty selector is open."
                else:
                    responses = await self.repository.difficulty_ballot_response_count(
                        ref,
                        ballot.ballot_id,
                    )
                    status = (
                        "Hypha difficulty selector is open "
                        f"(message `{ballot.message_id}`, responses `{responses}`)."
                    )
            except StorageError:
                status = (
                    "Difficulty selector status is temporarily unavailable. "
                    "Nothing changed."
                )
            await interaction.response.send_message(
                status,
                ephemeral=True,
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return

        if action.value == "close":
            if not confirm:
                await interaction.response.send_message(
                    "Closing requires `confirm:true`. Saved personal preferences "
                    "will remain active.",
                    ephemeral=True,
                    allowed_mentions=discord.AllowedMentions.none(),
                )
                return
            try:
                ballot = await self.repository.close_difficulty_ballot(ref)
            except DifficultyBallotError:
                await interaction.response.send_message(
                    "There is no open Hypha difficulty selector. Nothing changed.",
                    ephemeral=True,
                    allowed_mentions=discord.AllowedMentions.none(),
                )
                return
            except StorageError:
                await interaction.response.send_message(
                    "The difficulty selector could not be closed safely. "
                    "Nothing changed.",
                    ephemeral=True,
                    allowed_mentions=discord.AllowedMentions.none(),
                )
                return
            await interaction.response.send_message(
                "The Hypha difficulty selector is closed. Saved preferences remain active.",
                ephemeral=True,
                allowed_mentions=discord.AllowedMentions.none(),
            )
            await self._disable_difficulty_poll_message(ballot)
            return

        if action.value != "open":
            await interaction.response.send_message(
                "Unknown difficulty-selector action. Nothing changed.",
                ephemeral=True,
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return
        try:
            active = await self.repository.active_difficulty_ballot(ref)
        except StorageError:
            await interaction.response.send_message(
                "The difficulty selector could not be checked safely. Nothing changed.",
                ephemeral=True,
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return
        if active is not None:
            await interaction.response.send_message(
                "A Hypha difficulty selector is already open. Close it before posting "
                "another.",
                ephemeral=True,
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return
        await interaction.response.send_message(
            f"{marker}\n{DIFFICULTY_POLL_TEXT}",
            view=DifficultyPollView(self),
            allowed_mentions=discord.AllowedMentions.none(),
        )
        message = await interaction.original_response()
        try:
            await self.repository.open_difficulty_ballot(
                ref,
                guild_id=interaction.guild_id or 0,
                channel_id=interaction.channel_id or 0,
                message_id=message.id,
            )
        except DifficultyBallotError:
            await message.edit(
                content=(
                    f"{marker}\n"
                    "The difficulty selector could not be activated safely. "
                    "Its controls are disabled."
                ),
                view=DifficultyPollView(self, disabled=True),
                allowed_mentions=discord.AllowedMentions.none(),
            )
            await interaction.followup.send(
                "Difficulty selector activation failed. No preference can be changed "
                "through that message.",
                ephemeral=True,
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except StorageError:
            await message.edit(
                content=(
                    f"{marker}\n"
                    "The difficulty selector could not be activated safely. "
                    "Its controls are disabled."
                ),
                view=DifficultyPollView(self, disabled=True),
                allowed_mentions=discord.AllowedMentions.none(),
            )
            await interaction.followup.send(
                "Difficulty preference storage is unavailable. No preference can be "
                "changed through that message.",
                ephemeral=True,
                allowed_mentions=discord.AllowedMentions.none(),
            )


    def _build_v2_live_command_group(self) -> app_commands.Group:
        """A separate live v2 stream; test utilities never touch this runtime."""

        group = app_commands.Group(name="v2-live", description="Live v2 investigation")

        async def send(interaction: discord.Interaction, message: str) -> None:
            if await self._difficulty_for(interaction, Environment.LIVE) is DifficultyLevel.GUIDED:
                message = (
                    f"{message}\n\n"
                    "Guided support: use `/v2-live status` for your current state and "
                    "`/v2-live guide` for available steps."
                )
            chunks = self._discord_chunks(message, "[V2 · live]\n")
            method = (
                interaction.followup.send
                if interaction.response.is_done()
                else interaction.response.send_message
            )
            await method(chunks[0], allowed_mentions=discord.AllowedMentions.none())
            for chunk in chunks[1:]:
                await interaction.followup.send(
                    chunk, allowed_mentions=discord.AllowedMentions.none(),
                )

        async def authorize_player(interaction: discord.Interaction) -> bool:
            runtime = self.v2_live_runtime
            if runtime is None:
                return False
            session = await runtime.session()
            started = "network_orientation" in session.state.completed_position_ids
            if not started:
                await interaction.response.send_message(
                    "The live v2 investigation has not begun.", ephemeral=True,
                )
                return False
            decision = self.policy.authorize_player(
                _request_context(interaction), self.routing.current,
                {Environment.TEST: SessionMode.LOCKED, Environment.LIVE: SessionMode.RUNNING},
            )
            if decision.result is AccessResult.ALLOWED and decision.environment is Environment.LIVE:
                return True
            await interaction.response.send_message(
                "The interface is inactive for this request.", ephemeral=True,
            )
            return False

        async def publish() -> None:
            runtime = self.v2_live_runtime
            publisher = self.v2_live_activity_publisher
            if runtime is None or publisher is None:
                return
            try:
                await publisher.publish(runtime.pack, await runtime.session())
            except V2ActivityPublishError:
                logger.exception("live v2 Activity projection failed")

        @group.command(name="difficulty", description="Open or inspect live personal guidance")
        @app_commands.describe(
            action="Open, close, or inspect the selector",
            confirm="Required only when closing the active selector",
        )
        @app_commands.choices(
            action=[
                app_commands.Choice(name="Open selector", value="open"),
                app_commands.Choice(name="Close selector", value="close"),
                app_commands.Choice(name="Selector status", value="status"),
                app_commands.Choice(name="My selection", value="mine"),
            ]
        )
        async def difficulty(
            interaction: discord.Interaction,
            action: app_commands.Choice[str],
            confirm: bool = False,
        ) -> None:
            await self._handle_v2_difficulty_action(
                interaction, action, confirm, Environment.LIVE,
            )

        @group.command(name="status", description="Read the live v2 investigation state")
        async def status(interaction: discord.Interaction) -> None:
            runtime = self.v2_live_runtime
            if runtime is None:
                return
            session = await runtime.session()
            if "network_orientation" not in session.state.completed_position_ids:
                if await self._authorize_admin(interaction, Environment.LIVE) is None:
                    return
            elif not await authorize_player(interaction):
                return
            response = await runtime.public_status(player_id=f"discord:{interaction.user.id}")
            await send(interaction, response.to_text())

        @group.command(name="begin", description="Begin the separate live v2 stream")
        async def begin(interaction: discord.Interaction, confirm: bool) -> None:
            if await self._authorize_admin(interaction, Environment.LIVE) is None:
                return
            if not confirm:
                await send(interaction, "Set confirm:true to begin live v2 progression.")
                return
            runtime = self.v2_live_runtime
            if runtime is None:
                return
            await interaction.response.defer(thinking=True)
            response = await runtime.execute_public(
                player_id=f"discord:{interaction.user.id}", text="begin-investigation",
            )
            if response.accepted:
                await publish()
            await send(interaction, response.to_text())

        @group.command(name="command", description="Run one strict live v2 command")
        @app_commands.describe(text="Strict v2 command text")
        async def command(interaction: discord.Interaction, text: str) -> None:
            if not await authorize_player(interaction):
                return
            runtime = self.v2_live_runtime
            if runtime is None:
                return
            await interaction.response.defer(thinking=True)
            response = await runtime.execute_public(
                player_id=f"discord:{interaction.user.id}", text=text,
            )
            if response.accepted:
                await publish()
            await send(interaction, response.to_text())

        @group.command(name="role", description="Choose your live investigative function")
        @app_commands.describe(
            role="Canonical function; begin typing to see available roles",
            name="Optional public title for your function",
            description="Optional public description of your approach",
        )
        async def role(
            interaction: discord.Interaction,
            role: str,
            name: str | None = None,
            description: str | None = None,
        ) -> None:
            if not await authorize_player(interaction):
                return
            runtime = self.v2_live_runtime
            if runtime is None:
                return
            await interaction.response.defer(thinking=True)
            try:
                response = await runtime.assign_public_role(
                    player_id=f"discord:{interaction.user.id}",
                    role_id=role,
                    display_name=name,
                    description=description,
                )
            except (V2TestRuntimeError, ValueError):
                logger.exception("live v2 role assignment failed")
                await send(
                    interaction,
                    "That role could not be recorded. Check the live guide and try again.",
                )
                return
            if response.accepted:
                await publish()
            await send(interaction, response.to_text())

        async def role_autocomplete(
            interaction: discord.Interaction,
            current: str,
        ) -> list[app_commands.Choice[str]]:
            if self.policy.resolve_environment(
                _request_context(interaction), self.routing.current,
            ) is not Environment.LIVE:
                return []
            runtime = self.v2_live_runtime
            if runtime is None:
                return []
            try:
                choices = await runtime.available_public_roles(current)
            except V2TestRuntimeError:
                return []
            return [
                app_commands.Choice(name=label[:100], value=role_id)
                for role_id, label in choices
                if len(role_id) <= 100
            ]

        role.autocomplete("role")(role_autocomplete)

        @group.command(name="guide", description="Read your current live v2 guide")
        async def guide(interaction: discord.Interaction) -> None:
            if not await authorize_player(interaction):
                return
            runtime = self.v2_live_runtime
            if runtime is not None:
                guide_text = await runtime.public_guide(
                    player_id=f"discord:{interaction.user.id}",
                )
                roles = await runtime.available_public_roles()
                role_lines = "\n".join(
                    f"• {label} (`{role_id}`)" for role_id, label in roles
                )
                await send(
                    interaction,
                    f"{guide_text}\n\n**Available functions**\n{role_lines}\n"
                    "Choose one with `/v2-live role`, or use `release-role` through "
                    "`/v2-live command` before changing functions.",
                )

        @group.command(name="ask", description="Ask Hypha for a read-only spoken reply")
        @app_commands.describe(question="Question about the public live investigation")
        async def ask(interaction: discord.Interaction, question: str) -> None:
            if not await authorize_player(interaction):
                return
            runtime = self.v2_live_runtime
            if runtime is None or self.gemini_voice is None:
                await send(interaction, "Hypha voice is unavailable.")
                return
            await interaction.response.defer(thinking=True)
            try:
                context = await build_v2_chat_context(
                    runtime,
                    player_id=f"discord:{interaction.user.id}",
                    player_message=question,
                    privacy_metadata=DiscordPrivacyMetadata(
                        current_participant=_participant_identity(interaction.user),
                    ),
                    shared_public_only=True,
                    environment="live",
                )
                spoken = await self.gemini_voice.reply(context)
                if spoken.clip is None:
                    await send(interaction, spoken.text or "Hypha could not render a response.")
                    return
                await interaction.followup.send(
                    spoken.text[:1800],
                    file=discord.File(io.BytesIO(spoken.clip.audio), filename=spoken.clip.filename),
                    allowed_mentions=discord.AllowedMentions.none(),
                )
            except Exception:
                logger.exception("live v2 Hypha voice failed")
                await interaction.followup.send(
                    "Hypha could not render a response. No game state changed.",
                    allowed_mentions=discord.AllowedMentions.none(),
                )

        return group

    def _build_command_group(self) -> app_commands.Group:
        group = app_commands.Group(name="interior", description="Controls")
        test_tools = app_commands.Group(name="test", description="Isolated test utilities")
        ops_tools = app_commands.Group(name="ops", description="Routing and features")

        @group.command(
            name="exterior",
            description="Read the exterior station register",
        )
        async def exterior(interaction: discord.Interaction) -> None:
            environment = await self._authorize_player(interaction)
            if environment is None:
                return
            if environment is not Environment.LIVE:
                await interaction.response.send_message(
                    "The exterior register is attached to the live surface.",
                    ephemeral=True,
                )
                return
            await self._send_exterior_weather_report(
                interaction,
                environment,
            )

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

                # Prefix the visible Discord labels so we can see which
                # GameService catalogue produced each option. The submitted
                # values remain unchanged, so selecting an item still invokes
                # Observe normally.
                tagged_choices = [
                    (f"[DISCOVERY] {label}", value)
                    for label, value in discovery_choices
                ] + [
                    (f"[KNOWN] {label}", value)
                    for label, value in known_choices
                ]

                choices: list[tuple[str, str]] = []
                seen_values: set[str] = set()
                for label, value in tagged_choices:
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

        @test_tools.command(
            name="export",
            description="Export isolated test state",
        )
        async def test_export(interaction: discord.Interaction) -> None:
            environment = await self._authorize_admin(
                interaction,
                Environment.TEST,
            )
            if environment is None:
                return

            if self.operations is None:
                await interaction.response.send_message(
                    "Operational controls are unavailable.",
                    ephemeral=True,
                )
                return

            await interaction.response.defer(thinking=True)

            document = await self.operations.export(Environment.TEST)

            attachment = discord.File(
                io.BytesIO(document.encode("utf-8")),
                filename="uniflora-test-export.json",
            )

            marker = (
                "[TEST SURFACE]\n"
                if self.settings.test_surface_marker_enabled
                else ""
            )

            await interaction.followup.send(
                f"{marker}Test export; the environment label is embedded.",
                file=attachment,
                allowed_mentions=discord.AllowedMentions.none(),
            )
            marker = "[TEST SURFACE]\n" if self.settings.test_surface_marker_enabled else ""
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
                        raise original_error from None
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

        @group.command(
            name="export",
            description="Export the TEST environment in diagnostics",
        )
        async def export(interaction: discord.Interaction) -> None:
            selected = await self._authorize_admin(
                interaction,
                Environment.TEST,
            )
            if selected is None:
                return

            if self.operations is None:
                await interaction.response.send_message(
                    "Operational controls are unavailable.",
                    ephemeral=True,
                )
                return

            # Acknowledge the interaction before generating the export.
            await interaction.response.defer(thinking=True)

            document = await self.operations.export(selected)

            attachment = discord.File(
                io.BytesIO(document.encode("utf-8")),
                filename=f"uniflora-{selected.value}-export.json",
            )

            await interaction.followup.send(
                f"{selected.value.title()} export; environment label is embedded.",
                file=attachment,
                allowed_mentions=discord.AllowedMentions.none(),
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

        @ops_tools.command(
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
            interaction: discord.Interaction,
            error: app_commands.AppCommandError,
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
    v2_test_runtime: V2TestRuntime | None = None,
    v2_activity_publisher: V2ActivityPublisher | None = None,
    v2_live_runtime: V2TestRuntime | None = None,
    v2_live_activity_publisher: V2ActivityPublisher | None = None,
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
        v2_test_runtime,
        v2_activity_publisher,
        v2_live_runtime,
        v2_live_activity_publisher,
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
