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
    "admin_user_ids": "50, 60",
}


def settings(**changes: str) -> Settings:
    values = BASE | changes
    return Settings(_env_file=None, **values)  # type: ignore[arg-type]


def test_settings_parse_admin_ids() -> None:
    value = settings()
    assert value.admin_user_ids == frozenset({50, 60})
    assert value.discord_token.get_secret_value() == "not-a-real-token"
    assert value.settlement_intervention_excluded_user_ids == frozenset({50, 60})
    assert value.v2_test_enabled is False
    assert value.v2_test_database_path == "./data/v2-test-events.sqlite3"
    assert value.v2_test_stream_id == "discord-test"
    assert value.v2_activity_sync_enabled is False
    assert value.v2_activity_base_url is None
    assert value.hypha_activity_secret is None


def test_settlement_intervention_exclusions_can_be_explicit() -> None:
    value = settings(settlement_intervention_excluded_user_ids="70, 80")
    assert value.settlement_intervention_excluded_user_ids == frozenset({70, 80})


def test_settlement_event_clock_has_safe_bounds() -> None:
    with pytest.raises(ValidationError):
        settings(settlement_event_response_minutes="1")
    with pytest.raises(ValidationError):
        settings(settlement_event_poll_seconds="1")


def test_blank_optional_diagnostic_channel_is_unset() -> None:
    value = settings(diagnostic_channel_id="")
    assert value.diagnostic_channel_id is None


def test_live_and_test_channels_must_differ() -> None:
    with pytest.raises(ValidationError, match="must differ"):
        settings(test_puzzle_channel_id="20")


def test_readable_failure_for_missing_admins() -> None:
    with pytest.raises(ValidationError, match="at least one configured administrator"):
        settings(admin_user_ids="")


def test_non_numeric_id_is_rejected() -> None:
    with pytest.raises(ValidationError):
        settings(discord_guild_id="guild-name")


@pytest.mark.parametrize(
    "field",
    ("v2_test_database_path", "v2_test_stream_id"),
)
def test_v2_test_settings_must_not_be_blank(field: str) -> None:
    with pytest.raises(ValidationError, match="must not be blank"):
        settings(**{field: "   "})


def test_v2_activity_sync_requires_runtime_url_and_secret() -> None:
    with pytest.raises(ValidationError, match="V2_TEST_ENABLED"):
        settings(v2_activity_sync_enabled="true")
    with pytest.raises(ValidationError, match="V2_ACTIVITY_BASE_URL"):
        settings(v2_test_enabled="true", v2_activity_sync_enabled="true")
    with pytest.raises(ValidationError, match="HYPHA_ACTIVITY_SECRET"):
        settings(
            v2_test_enabled="true",
            v2_activity_sync_enabled="true",
            v2_activity_base_url="https://activity.example",
        )

    configured = settings(
        v2_test_enabled="true",
        v2_activity_sync_enabled="true",
        v2_activity_base_url=" https://activity.example ",
        hypha_activity_secret="test-secret",
    )
    assert configured.v2_activity_base_url == "https://activity.example"


def test_comma_separated_admin_ids_load_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in BASE.items():
        monkeypatch.setenv(key.upper(), value)
    loaded = Settings(_env_file=None)  # type: ignore[call-arg]
    assert loaded.admin_user_ids == frozenset({50, 60})


@pytest.mark.parametrize("scheme", ["postgres://", "postgresql://"])
def test_cloud_postgres_urls_use_async_driver(scheme: str) -> None:
    loaded = settings(database_url=f"{scheme}user:secret@host/interior")
    assert loaded.database_url == "postgresql+asyncpg://user:secret@host/interior"


def test_enabling_openai_requires_api_key() -> None:
    with pytest.raises(ValidationError, match="OPENAI_API_KEY"):
        settings(
            openai_enabled="true",
            openai_privacy_acknowledged="true",
            openai_api_key="",
        )


def test_enabling_openai_requires_explicit_privacy_acknowledgement() -> None:
    with pytest.raises(ValidationError, match="OPENAI_PRIVACY_ACKNOWLEDGED"):
        settings(openai_enabled="true", openai_api_key="test-key")


def test_network_and_dry_run_modes_are_mutually_exclusive() -> None:
    with pytest.raises(ValidationError, match="cannot both be true"):
        settings(
            openai_enabled="true",
            openai_dry_run="true",
            openai_privacy_acknowledged="true",
            openai_api_key="test-key",
        )


def test_soft_api_budgets_cannot_exceed_hard_caps() -> None:
    with pytest.raises(ValidationError, match="soft daily"):
        settings(openai_soft_daily_budget_usd="3", openai_hard_daily_budget_usd="2")
