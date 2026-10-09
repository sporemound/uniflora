from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from uniflora.announcements import SCHEDULED_ANNOUNCEMENTS, ScheduledAnnouncement
from uniflora.config import Settings
from uniflora.discord_adapter import build_bot, initial_routing
from uniflora.health import HealthService
from uniflora.runtime import RuntimeSessions


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        discord_token="fake",
        discord_guild_id="1",
        live_puzzle_channel_id="10",
        test_puzzle_channel_id="20",
        mycotroph_role_id="30",
        admin_user_ids="99",
    )  # type: ignore[arg-type]


def test_no_scheduled_announcements_remain() -> None:
    assert SCHEDULED_ANNOUNCEMENTS == ()


class _FakeGame:
    def __init__(self) -> None:
        self.marked: tuple[str, int, int] | None = None

    async def scheduled_announcement_delivered(self, announcement_id: str) -> bool:
        del announcement_id
        return False

    async def mark_scheduled_announcement_delivered(
        self, announcement_id: str, channel_id: int, message_id: int
    ) -> bool:
        self.marked = (announcement_id, channel_id, message_id)
        return True


class _FakeChannel:
    id = 44
    name = "field-interference"

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def send(self, text: str, **kwargs: Any) -> object:
        self.sent.append({"text": text, **kwargs})
        return SimpleNamespace(id=55)


@pytest.mark.asyncio
async def test_scheduled_announcement_disables_mentions_and_records_delivery() -> None:
    configured = _settings()
    sessions = RuntimeSessions()
    game = _FakeGame()
    bot = build_bot(
        configured,
        sessions,
        initial_routing(configured),
        HealthService(sessions, "127.0.0.1", 8080),
        game=game,  # type: ignore[arg-type]
    )
    channel = _FakeChannel()
    bot.get_guild = lambda guild_id: SimpleNamespace(  # type: ignore[method-assign]
        id=guild_id, text_channels=[channel]
    )

    announcement = ScheduledAnnouncement(
        announcement_id="delivery-test",
        channel_name="field-interference",
        send_at=datetime(2099, 1, 1, tzinfo=UTC),
        expires_at=datetime(2099, 1, 2, tzinfo=UTC),
        text="test announcement",
    )
    await bot._deliver_scheduled_announcement(announcement)

    assert channel.sent[0]["text"] == announcement.text
    allowed = channel.sent[0]["allowed_mentions"]
    assert allowed.everyone is False
    assert allowed.roles is False
    assert allowed.users is False
    assert game.marked == (announcement.announcement_id, 44, 55)
    await bot.close()
