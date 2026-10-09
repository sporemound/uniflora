from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import discord
import pytest
from discord import app_commands

from uniflora.config import Settings
from uniflora.discord_adapter import (
    _message_request_context,
    _request_context,
    build_bot,
    initial_routing,
)
from uniflora.health import HealthService
from uniflora.runtime import Environment, RuntimeSessions, SessionMode


def _bot_with_locked_legacy_test():
    settings = Settings(
        _env_file=None,
        discord_token="fake",
        discord_guild_id=1,
        live_puzzle_channel_id=10,
        test_puzzle_channel_id=20,
        mycotroph_role_id=30,
        admin_user_ids="99",
        feature_natural_language=False,
        v2_test_enabled=True,
    )
    sessions = RuntimeSessions()
    bot = build_bot(
        settings,
        sessions,
        initial_routing(settings),
        HealthService(sessions, "127.0.0.1", 8080),
        v2_test_runtime=SimpleNamespace(),  # type: ignore[arg-type]
    )
    return bot, sessions


def _interaction(*, channel_id: int = 20, user_id: int = 99):
    replies: list[str] = []
    deferrals: list[bool] = []

    async def send_message(message: str, **_kwargs: object) -> None:
        replies.append(message)

    async def defer(**_kwargs: object) -> None:
        deferrals.append(True)

    interaction = SimpleNamespace(
        guild_id=1,
        channel_id=channel_id,
        user=SimpleNamespace(id=user_id),
        response=SimpleNamespace(
            is_done=lambda: False,
            send_message=send_message,
            defer=defer,
        ),
    )
    return interaction, replies, deferrals


def test_discord_thread_parent_is_carried_into_command_and_chat_contexts() -> None:
    thread = MagicMock(spec=discord.Thread)
    thread.id = 101
    thread.parent_id = 10
    interaction = SimpleNamespace(
        guild_id=1, channel_id=101, channel=thread, user=SimpleNamespace(id=99, roles=[])
    )
    message = SimpleNamespace(
        guild=SimpleNamespace(id=1), channel=thread, author=SimpleNamespace(id=99, roles=[])
    )
    assert _request_context(interaction).thread_parent_channel_id == 10
    assert _message_request_context(message).thread_parent_channel_id == 10


def test_non_thread_channel_cannot_claim_a_parent() -> None:
    channel = SimpleNamespace(id=101, parent_id=10)
    interaction = SimpleNamespace(
        guild_id=1, channel_id=101, channel=channel, user=SimpleNamespace(id=99, roles=[])
    )
    assert _request_context(interaction).thread_parent_channel_id is None


@pytest.mark.asyncio
async def test_v2_live_status_works_in_thread_under_live_channel() -> None:
    settings = Settings(
        _env_file=None,
        discord_token="fake",
        discord_guild_id=1,
        live_puzzle_channel_id=10,
        test_puzzle_channel_id=20,
        mycotroph_role_id=30,
        admin_user_ids="99",
        feature_natural_language=False,
    )
    calls: list[str] = []

    async def session() -> object:
        return SimpleNamespace(
            state=SimpleNamespace(completed_position_ids={"network_orientation"})
        )

    async def public_status(**_kwargs: object) -> object:
        calls.append("status-requested")
        return SimpleNamespace(to_text=lambda: "Live state")

    sessions = RuntimeSessions()
    bot = build_bot(
        settings,
        sessions,
        initial_routing(settings),
        HealthService(sessions, "127.0.0.1", 8080),
        v2_live_runtime=SimpleNamespace(session=session, public_status=public_status),  # type: ignore[arg-type]
    )
    group = bot.tree.get_command("v2-live")
    assert isinstance(group, app_commands.Group)
    status = group.get_command("status")
    assert status is not None
    interaction, replies, _deferrals = _interaction(channel_id=101)
    thread = MagicMock(spec=discord.Thread)
    thread.id = 101
    thread.parent_id = 10
    interaction.channel = thread

    await status.callback(interaction)

    assert calls == ["status-requested"]
    assert replies == ["[V2 · live]\nLive state"]


@pytest.mark.asyncio
async def test_v2_status_runs_in_test_channel_while_legacy_session_is_locked() -> None:
    bot, sessions = _bot_with_locked_legacy_test()
    assert (await sessions.snapshot(Environment.TEST)).mode is SessionMode.LOCKED
    group = bot.tree.get_command("v2")
    assert isinstance(group, app_commands.Group)
    status = group.get_command("status")
    assert status is not None

    calls: list[str] = []

    async def public_status(**_kwargs: object) -> object:
        calls.append("status-requested")
        return object()

    async def refresh() -> None:
        return None

    async def render(*_args: object, **_kwargs: object) -> str:
        return "Current v2 status"

    async def send(_interaction: object, message: str, **_kwargs: object) -> None:
        calls.append(message)

    bot.v2_test_runtime.public_status = public_status
    bot._refresh_v2_activity_projection = refresh  # type: ignore[method-assign]
    bot._render_v2_transport_response = render  # type: ignore[method-assign]
    bot._send_v2_test = send  # type: ignore[method-assign]
    interaction, replies, deferrals = _interaction()

    await status.callback(interaction)

    assert calls == ["status-requested", "Current v2 status"]
    assert replies == []
    assert len(deferrals) <= 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("channel_id", "user_id"),
    [(10, 99), (21, 99), (20, 98)],
)
async def test_v2_status_stays_admin_only_in_exact_test_channel(
    channel_id: int, user_id: int
) -> None:
    bot, _sessions = _bot_with_locked_legacy_test()
    group = bot.tree.get_command("v2")
    assert isinstance(group, app_commands.Group)
    status = group.get_command("status")
    assert status is not None
    interaction, replies, deferrals = _interaction(channel_id=channel_id, user_id=user_id)

    await status.callback(interaction)

    assert replies == ["The interface is inactive for this request."]
    assert deferrals == []
