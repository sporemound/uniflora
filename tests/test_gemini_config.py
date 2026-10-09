from __future__ import annotations

import pytest
from pydantic import ValidationError

from uniflora.config import Settings

BASE = {
    "discord_token": "not-a-real-token",
    "discord_guild_id": "10",
    "live_puzzle_channel_id": "20",
    "test_puzzle_channel_id": "30",
    "mycotroph_role_id": "40",
    "admin_user_ids": "50",
}


def settings(**changes: str) -> Settings:
    return Settings(_env_file=None, **(BASE | changes))  # type: ignore[arg-type]


def test_gemini_chat_defaults_are_off() -> None:
    value = settings()
    assert value.feature_gemini_chat is False
    assert value.feature_gemini_discord_chat is False
    assert value.gemini_enabled is False
    assert value.gemini_dry_run is False
    assert value.gemini_chat_model == "gemini-3.8-flash"
    assert value.v2_live_enabled is False
    assert value.v2_live_database_path != value.v2_test_database_path
    assert value.v2_live_stream_id != value.v2_test_stream_id


def test_live_v2_cannot_share_test_storage_or_stream() -> None:
    with pytest.raises(ValidationError, match="V2_LIVE_DATABASE_PATH"):
        settings(v2_live_database_path="./data/v2-test-events.sqlite3")
    with pytest.raises(ValidationError, match="V2_LIVE_STREAM_ID"):
        settings(v2_live_stream_id="discord-test")


def test_gemini_enabled_requires_privacy_acknowledgement() -> None:
    with pytest.raises(ValidationError, match="GEMINI_PRIVACY_ACKNOWLEDGED"):
        settings(gemini_enabled="true", gemini_api_key="test-key")


def test_gemini_enabled_requires_api_key() -> None:
    with pytest.raises(ValidationError, match="GEMINI_API_KEY"):
        settings(
            gemini_enabled="true",
            gemini_privacy_acknowledged="true",
            gemini_api_key="",
        )


def test_gemini_network_and_dry_run_are_mutually_exclusive() -> None:
    with pytest.raises(ValidationError, match="GEMINI_ENABLED and GEMINI_DRY_RUN"):
        settings(
            gemini_enabled="true",
            gemini_dry_run="true",
            gemini_privacy_acknowledged="true",
            gemini_api_key="test-key",
        )


def test_discord_gemini_chat_requires_gemini_chat() -> None:
    with pytest.raises(ValidationError, match="FEATURE_GEMINI_DISCORD_CHAT"):
        settings(feature_gemini_discord_chat="true")
