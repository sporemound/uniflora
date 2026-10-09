from __future__ import annotations

import asyncio
import logging
import signal
import sys
from pathlib import Path

from dotenv import load_dotenv
from pydantic import ValidationError
from pydantic_settings import SettingsError

from uniflora.activity_chat_relay import ActivityChatRelay
from uniflora.activity_difficulty_sync import ActivityDifficultySync
from uniflora.alerts import DiagnosticAlertSink
from uniflora.backup import BackupService
from uniflora.config import Settings, get_settings
from uniflora.discord_adapter import build_bot, initial_routing
from uniflora.health import HealthService
from uniflora.logging import configure_logging
from uniflora.persistent_runtime import PersistentRouting, PersistentRuntimeSessions
from uniflora.storage.database import Database
from uniflora.storage.migrations import run_startup_migrations
from uniflora.storage.repository import GameRepository
from uniflora.v2_activity_projection import (
    V2ActivityPublisher,
    V2ActivityPublishError,
)
from uniflora.v2_test_runtime import V2TestRuntime

load_dotenv()

logger = logging.getLogger(__name__)


async def run(settings: Settings) -> None:
    if settings.run_migrations_on_startup:
        await run_startup_migrations(settings.database_url)
    database = Database(settings.database_url)
    repository = GameRepository(database)
    configured = initial_routing(settings).current
    persisted_routing, refs = await repository.bootstrap(configured)
    alerts = DiagnosticAlertSink(persisted_routing.diagnostic_channel_id)
    sessions = PersistentRuntimeSessions(repository, refs)
    routing = PersistentRouting(persisted_routing, repository)
    backup = BackupService(
        database,
        repository,
        Path(settings.backup_directory),
        enabled=settings.backup_enabled,
        interval_hours=settings.backup_interval_hours,
        refs=tuple(refs.values()),
    )
    await backup.start()
    health = HealthService(sessions, settings.health_host, settings.port)
    if not settings.v2_test_enabled:
        raise RuntimeError(
            "V2_TEST_ENABLED must be true; the retired position content is no longer loaded."
        )
    v2_test_runtime: V2TestRuntime | None = None
    v2_live_runtime: V2TestRuntime | None = None
    v2_activity_publisher: V2ActivityPublisher | None = None
    v2_live_activity_publisher: V2ActivityPublisher | None = None
    if settings.v2_test_enabled:
        v2_database = Path(settings.v2_test_database_path)
        v2_database.parent.mkdir(parents=True, exist_ok=True)
        v2_test_runtime = V2TestRuntime(
            v2_database,
            stream_id=settings.v2_test_stream_id,
        )
        v2_session = await v2_test_runtime.session()
        if settings.v2_activity_sync_enabled:
            if (
                settings.v2_activity_base_url is None
                or settings.hypha_activity_secret is None
            ):
                raise RuntimeError("validated v2 Activity sync settings are unavailable")
            v2_activity_publisher = V2ActivityPublisher(
                settings.v2_activity_base_url,
                settings.hypha_activity_secret.get_secret_value(),
            )
            try:
                await asyncio.wait_for(
                    v2_activity_publisher.publish(
                        v2_test_runtime.pack,
                        v2_session,
                    ),
                    timeout=5.0,
                )
            except (V2ActivityPublishError, TimeoutError):
                logger.warning(
                    "v2 Activity projection is stale at startup; authoritative v2 remains ready",
                    exc_info=True,
                    extra={"environment": "test"},
                )
    if settings.v2_live_enabled:
        live_database = Path(settings.v2_live_database_path)
        live_database.parent.mkdir(parents=True, exist_ok=True)
        v2_live_runtime = V2TestRuntime(
            live_database,
            stream_id=settings.v2_live_stream_id,
            initial_player_ids=(f"discord:{min(settings.admin_user_ids)}",),
        )
        live_session = await v2_live_runtime.session()
        if settings.v2_activity_sync_enabled:
            assert settings.v2_activity_base_url is not None
            assert settings.hypha_activity_secret is not None
            v2_live_activity_publisher = V2ActivityPublisher(
                settings.v2_activity_base_url,
                settings.hypha_activity_secret.get_secret_value(),
                environment="live",
            )
            try:
                await asyncio.wait_for(
                    v2_live_activity_publisher.publish(v2_live_runtime.pack, live_session),
                    timeout=5.0,
                )
            except (V2ActivityPublishError, TimeoutError):
                logger.warning(
                    "live v2 Activity projection is stale at startup",
                    exc_info=True,
                    extra={"environment": "live"},
                )
    bot = build_bot(
        settings,
        sessions,
        routing,
        health,
        repository,
        refs,
        None,
        None,
        None,
        alerts,
        v2_test_runtime,
        v2_activity_publisher,
        v2_live_runtime,
        v2_live_activity_publisher,
    )
    alerts.bind(bot)
    stop_event = asyncio.Event()
    activity_chat_relay: ActivityChatRelay | None = None
    activity_chat_task: asyncio.Task[None] | None = None
    live_activity_chat_task: asyncio.Task[None] | None = None
    difficulty_sync_task: asyncio.Task[None] | None = None
    if (
        settings.v2_activity_sync_enabled
        and settings.v2_activity_base_url is not None
        and settings.hypha_activity_secret is not None
    ):
        difficulty_sync = ActivityDifficultySync(
            settings.v2_activity_base_url,
            settings.hypha_activity_secret.get_secret_value(),
            repository,
            refs,
        )
        difficulty_sync_task = asyncio.create_task(
            difficulty_sync.run(stop_event), name="activity-difficulty-sync"
        )
    if (
        settings.feature_gemini_chat
        and settings.v2_activity_sync_enabled
        and settings.v2_activity_base_url is not None
        and settings.hypha_activity_secret is not None
        and bot.gemini_voice is not None
        and v2_test_runtime is not None
    ):
        activity_chat_relay = ActivityChatRelay(
            settings.v2_activity_base_url,
            settings.hypha_activity_secret.get_secret_value(),
            v2_test_runtime,
            bot.gemini_voice,
            settings.v2_test_stream_id,
        )
        activity_chat_task = asyncio.create_task(
            activity_chat_relay.run(stop_event),
            name="activity-hypha-chat-relay",
        )
        if v2_live_runtime is not None:
            live_relay = ActivityChatRelay(
                settings.v2_activity_base_url,
                settings.hypha_activity_secret.get_secret_value(),
                v2_live_runtime,
                bot.gemini_voice,
                settings.v2_live_stream_id,
                environment="live",
            )
            live_activity_chat_task = asyncio.create_task(
                live_relay.run(stop_event), name="activity-hypha-live-chat-relay",
            )
    loop = asyncio.get_running_loop()

    def request_shutdown() -> None:
        logger.info("shutdown requested", extra={"environment": "system"})
        stop_event.set()

    for signame in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(signame, request_shutdown)
        except (NotImplementedError, RuntimeError):
            signal.signal(signame, lambda *_: loop.call_soon_threadsafe(request_shutdown))

    await health.start()
    logger.warning(
        "health service temporarily disabled",
        extra={"environment": "system"},
    )
    bot_task = asyncio.create_task(
        bot.start(settings.discord_token.get_secret_value()), name="discord-client"
    )
    stop_task = asyncio.create_task(stop_event.wait(), name="shutdown-waiter")

    try:
        done, _ = await asyncio.wait({bot_task, stop_task}, return_when=asyncio.FIRST_COMPLETED)
        if bot_task in done:
            exception = bot_task.exception()
            if exception is not None:
                raise exception
    finally:
        health.shutting_down = True
        stop_task.cancel()
        if activity_chat_task is not None:
            activity_chat_task.cancel()
            await asyncio.gather(activity_chat_task, return_exceptions=True)
        if live_activity_chat_task is not None:
            live_activity_chat_task.cancel()
            await asyncio.gather(live_activity_chat_task, return_exceptions=True)
        if difficulty_sync_task is not None:
            difficulty_sync_task.cancel()
            await asyncio.gather(difficulty_sync_task, return_exceptions=True)
        if not bot.is_closed():
            await bot.close()
        if not bot_task.done():
            bot_task.cancel()
        await asyncio.gather(bot_task, stop_task, return_exceptions=True)
        await health.stop()
        await backup.stop()
        if v2_test_runtime is not None:
            await v2_test_runtime.close()
        if v2_live_runtime is not None:
            await v2_live_runtime.close()
        await database.dispose()
        logger.info("shutdown complete", extra={"environment": "system"})


def main() -> None:
    try:
        settings = get_settings()
    except (ValidationError, SettingsError) as exc:
        print("Configuration error:\n" + str(exc), file=sys.stderr)
        raise SystemExit(2) from exc
    configure_logging(settings.log_level)
    try:
        asyncio.run(run(settings))
    except KeyboardInterrupt:
        pass
    except Exception:
        logger.exception("service terminated unexpectedly", extra={"environment": "system"})
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
