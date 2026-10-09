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


def test_voice_defaults_are_bounded_and_optional() -> None:
    value = settings()

    assert value.hypha_voice_enabled is True
    assert value.hypha_voice_max_characters == 6000
    assert value.hypha_voice_process_timeout_seconds == 45.0
    assert value.hypha_voice_queue_timeout_seconds == 3.0
    assert value.hypha_voice_max_concurrent_requests == 1
    assert value.hypha_voice_max_pending_requests == 2
    assert value.hypha_voice_cache_enabled is True
    assert value.hypha_voice_cache_max_entries == 32


def test_blank_voice_paths_request_automatic_discovery() -> None:
    value = settings(
        hypha_voice_espeak_command=" ",
        hypha_voice_espeak_data_root="",
        hypha_voice_ffmpeg_command="  ",
    )

    assert value.hypha_voice_espeak_command is None
    assert value.hypha_voice_espeak_data_root is None
    assert value.hypha_voice_ffmpeg_command is None


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("hypha_voice_max_characters", "0"),
        ("hypha_voice_process_timeout_seconds", "0"),
        ("hypha_voice_queue_timeout_seconds", "0"),
        ("hypha_voice_max_concurrent_requests", "0"),
        ("hypha_voice_max_pending_requests", "-1"),
        ("hypha_voice_cache_max_entries", "-1"),
    ),
)
def test_voice_resource_bounds_are_validated(field: str, value: str) -> None:
    with pytest.raises(ValidationError):
        settings(**{field: value})
