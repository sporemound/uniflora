from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    """Startup configuration loaded exclusively from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    discord_token: SecretStr
    discord_guild_id: int
    live_puzzle_channel_id: int
    test_puzzle_channel_id: int
    mycotroph_role_id: int
    admin_user_ids: Annotated[frozenset[int], NoDecode]
    diagnostic_channel_id: int | None = None

    health_host: str = "0.0.0.0"
    port: int = Field(default=8080, ge=1, le=65535)
    log_level: str = "INFO"
    test_surface_marker_enabled: bool = True
    database_url: str = "sqlite+aiosqlite:///./data/interior.db"
    run_migrations_on_startup: bool = True
    backup_enabled: bool = True
    backup_directory: str = "./backups"
    backup_interval_hours: int = Field(default=24, ge=1, le=168)
    player_action_cooldown_seconds: int = Field(default=0, ge=0, le=3600)
    api_failure_fallback_threshold: int = Field(default=3, ge=1, le=20)
    feature_natural_language: bool = True
    feature_gpt_narration: bool = True
    feature_tactical_stack: bool = True
    feature_triggered_reactions: bool = True
    feature_proposal_kickers: bool = True
    feature_settlement_events: bool = True
    feature_gemini_chat: bool = False
    feature_gemini_discord_chat: bool = False
    settlement_intervention_excluded_user_ids: Annotated[frozenset[int], NoDecode] = frozenset()
    settlement_event_response_minutes: int = Field(default=120, ge=5, le=1440)
    settlement_event_poll_seconds: int = Field(default=60, ge=10, le=600)

    v2_test_enabled: bool = False
    v2_test_database_path: str = "./data/v2-test-events.sqlite3"
    v2_test_stream_id: str = "discord-test"
    v2_live_enabled: bool = False
    v2_live_database_path: str = "./data/v2-live-events.sqlite3"
    v2_live_stream_id: str = "discord-live"
    v2_activity_sync_enabled: bool = False
    v2_activity_base_url: str | None = None
    hypha_activity_secret: SecretStr | None = None
    v2_bulletin_channel_id: int | None = None

    # Hypha voice is an optional presentation surface. Disabling it never
    # changes game state, command availability, or text delivery.
    hypha_voice_enabled: bool = True
    hypha_voice_bulletins_enabled: bool = True
    hypha_voice_reply_attachments_enabled: bool = False
    hypha_voice_espeak_command: str | None = None
    hypha_voice_espeak_data_root: str | None = None
    hypha_voice_ffmpeg_command: str | None = None
    hypha_voice_max_characters: int = Field(default=6000, ge=1, le=20_000)
    hypha_voice_process_timeout_seconds: float = Field(default=45.0, gt=0, le=120)
    hypha_voice_queue_timeout_seconds: float = Field(default=3.0, gt=0, le=30)
    hypha_voice_max_concurrent_requests: int = Field(default=1, ge=1, le=4)
    hypha_voice_max_pending_requests: int = Field(default=2, ge=0, le=20)
    hypha_voice_cache_enabled: bool = True
    hypha_voice_cache_max_entries: int = Field(default=32, ge=0, le=256)

    openai_api_key: SecretStr | None = None
    openai_enabled: bool = False
    openai_dry_run: bool = False
    openai_privacy_acknowledged: bool = False
    openai_interpretation_model: str = "gpt-5.4-nano"
    openai_narration_model: str = "gpt-5.4-nano"
    openai_interpretation_confidence_threshold: float = Field(default=0.78, ge=0, le=1)
    openai_request_timeout_seconds: float = Field(default=12.0, gt=0, le=60)
    openai_max_prompt_tokens: int = Field(default=1400, ge=256, le=16000)
    openai_max_output_tokens: int = Field(default=300, ge=64, le=2000)
    openai_per_user_cooldown_seconds: int = Field(default=8, ge=0, le=3600)
    openai_global_cooldown_seconds: int = Field(default=2, ge=0, le=3600)
    openai_soft_daily_budget_usd: float = Field(default=1.0, ge=0)
    openai_hard_daily_budget_usd: float = Field(default=2.0, ge=0)
    openai_soft_monthly_budget_usd: float = Field(default=10.0, ge=0)
    openai_hard_monthly_budget_usd: float = Field(default=20.0, ge=0)
    openai_interpretation_input_usd_per_million: float = Field(default=0.20, ge=0)
    openai_interpretation_cached_input_usd_per_million: float = Field(default=0.02, ge=0)
    openai_interpretation_output_usd_per_million: float = Field(default=1.25, ge=0)
    openai_narration_input_usd_per_million: float = Field(default=0.20, ge=0)
    openai_narration_cached_input_usd_per_million: float = Field(default=0.02, ge=0)
    openai_narration_output_usd_per_million: float = Field(default=1.25, ge=0)

    # Optional Gemini dialogue path. This is presentation-only until explicitly
    # connected to an authenticated Activity/Discord chat surface.
    gemini_api_key: SecretStr | None = None
    gemini_enabled: bool = False
    gemini_dry_run: bool = False
    gemini_privacy_acknowledged: bool = False
    gemini_chat_model: str = "gemini-3.8-flash"
    gemini_request_timeout_seconds: float = Field(default=12.0, gt=0, le=60)
    gemini_max_output_tokens: int = Field(default=1500, ge=64, le=4000)
    gemini_temperature: float = Field(default=0.65, ge=0, le=2)

    @field_validator(
        "discord_guild_id",
        "live_puzzle_channel_id",
        "test_puzzle_channel_id",
        "mycotroph_role_id",
    )
    @classmethod
    def positive_discord_id(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("Discord IDs must be positive integers")
        return value

    @field_validator(
        "diagnostic_channel_id",
        "v2_bulletin_channel_id",
        mode="before",
    )
    @classmethod
    def normalize_optional_discord_id(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("diagnostic_channel_id", "v2_bulletin_channel_id")
    @classmethod
    def positive_optional_discord_id(cls, value: int | None) -> int | None:
        if value is not None and value <= 0:
            raise ValueError("optional Discord channel IDs must be positive integers")
        return value

    @field_validator("admin_user_ids", mode="before")
    @classmethod
    def parse_admin_ids(cls, value: object) -> object:
        if isinstance(value, str):
            parts = [item.strip() for item in value.split(",") if item.strip()]
            try:
                return frozenset(int(item) for item in parts)
            except ValueError as exc:
                raise ValueError("ADMIN_USER_IDS must be comma-separated numeric IDs") from exc
        return value

    @field_validator("settlement_intervention_excluded_user_ids", mode="before")
    @classmethod
    def parse_settlement_exclusions(cls, value: object) -> object:
        if isinstance(value, str):
            parts = [item.strip() for item in value.split(",") if item.strip()]
            try:
                return frozenset(int(item) for item in parts)
            except ValueError as exc:
                raise ValueError(
                    "SETTLEMENT_INTERVENTION_EXCLUDED_USER_IDS must be comma-separated numeric IDs"
                ) from exc
        return value

    @field_validator("admin_user_ids")
    @classmethod
    def require_admin(cls, value: frozenset[int]) -> frozenset[int]:
        if not value:
            raise ValueError("at least one configured administrator is required")
        if any(item <= 0 for item in value):
            raise ValueError("administrator IDs must be positive integers")
        return value

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, value: str) -> str:
        normalized = value.upper()
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if normalized not in allowed:
            raise ValueError(f"LOG_LEVEL must be one of: {', '.join(sorted(allowed))}")
        return normalized

    @field_validator("database_url")
    @classmethod
    def normalize_database_url(cls, value: str) -> str:
        if value.startswith("postgres://"):
            return "postgresql+asyncpg://" + value.removeprefix("postgres://")
        if value.startswith("postgresql://"):
            return "postgresql+asyncpg://" + value.removeprefix("postgresql://")
        if not value.startswith(("sqlite+aiosqlite://", "postgresql+asyncpg://")):
            raise ValueError("DATABASE_URL must use SQLite/aiosqlite or PostgreSQL/asyncpg")
        return value

    @field_validator(
        "v2_test_database_path", "v2_test_stream_id",
        "v2_live_database_path", "v2_live_stream_id",
    )
    @classmethod
    def require_v2_test_setting(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("v2 test settings must not be blank")
        return normalized

    @field_validator("v2_activity_base_url", mode="before")
    @classmethod
    def normalize_v2_activity_base_url(cls, value: object) -> object:
        if isinstance(value, str):
            normalized = value.strip()
            return normalized or None
        return value

    @field_validator(
        "hypha_voice_espeak_command",
        "hypha_voice_espeak_data_root",
        "hypha_voice_ffmpeg_command",
        mode="before",
    )
    @classmethod
    def normalize_optional_voice_path(cls, value: object) -> object:
        if isinstance(value, str):
            normalized = value.strip()
            return normalized or None
        return value

    @model_validator(mode="after")
    def channels_are_distinct(self) -> Settings:
        if not self.settlement_intervention_excluded_user_ids:
            self.settlement_intervention_excluded_user_ids = self.admin_user_ids
        if self.live_puzzle_channel_id == self.test_puzzle_channel_id:
            raise ValueError("LIVE_PUZZLE_CHANNEL_ID and TEST_PUZZLE_CHANNEL_ID must differ")
        if self.v2_live_database_path == self.v2_test_database_path:
            raise ValueError("V2_LIVE_DATABASE_PATH must differ from V2_TEST_DATABASE_PATH")
        if self.v2_live_stream_id == self.v2_test_stream_id:
            raise ValueError("V2_LIVE_STREAM_ID must differ from V2_TEST_STREAM_ID")
        if self.diagnostic_channel_id in {
            self.live_puzzle_channel_id,
            self.test_puzzle_channel_id,
        }:
            raise ValueError("DIAGNOSTIC_CHANNEL_ID must be distinct from puzzle channels")
        if self.v2_bulletin_channel_id is not None and (
            self.v2_bulletin_channel_id
            in {
                self.live_puzzle_channel_id,
                self.test_puzzle_channel_id,
                self.diagnostic_channel_id,
            }
        ):
            raise ValueError(
                "V2_BULLETIN_CHANNEL_ID must be distinct from puzzle and diagnostic channels"
            )
        if self.openai_enabled and self.openai_dry_run:
            raise ValueError("OPENAI_ENABLED and OPENAI_DRY_RUN cannot both be true")
        if self.openai_enabled:
            if not self.openai_privacy_acknowledged:
                raise ValueError(
                    "OPENAI_PRIVACY_ACKNOWLEDGED=true is required when OPENAI_ENABLED is true"
                )
            if self.openai_api_key is None or not self.openai_api_key.get_secret_value().strip():
                raise ValueError("OPENAI_API_KEY is required when OPENAI_ENABLED is true")
        if self.gemini_enabled and self.gemini_dry_run:
            raise ValueError("GEMINI_ENABLED and GEMINI_DRY_RUN cannot both be true")
        if self.gemini_enabled:
            if not self.gemini_privacy_acknowledged:
                raise ValueError(
                    "GEMINI_PRIVACY_ACKNOWLEDGED=true is required when GEMINI_ENABLED is true"
                )
            if self.gemini_api_key is None or not self.gemini_api_key.get_secret_value().strip():
                raise ValueError("GEMINI_API_KEY is required when GEMINI_ENABLED is true")
        if self.feature_gemini_chat and not (self.gemini_enabled or self.gemini_dry_run):
            raise ValueError(
                "FEATURE_GEMINI_CHAT requires GEMINI_ENABLED=true or GEMINI_DRY_RUN=true"
            )
        if self.feature_gemini_discord_chat and not self.feature_gemini_chat:
            raise ValueError("FEATURE_GEMINI_DISCORD_CHAT requires FEATURE_GEMINI_CHAT=true")
        if self.openai_soft_daily_budget_usd > self.openai_hard_daily_budget_usd:
            raise ValueError("soft daily API budget cannot exceed hard daily budget")
        if self.openai_soft_monthly_budget_usd > self.openai_hard_monthly_budget_usd:
            raise ValueError("soft monthly API budget cannot exceed hard monthly budget")
        if self.v2_activity_sync_enabled:
            if not self.v2_test_enabled:
                raise ValueError(
                    "V2_TEST_ENABLED=true is required when V2_ACTIVITY_SYNC_ENABLED is true"
                )
            if self.v2_activity_base_url is None:
                raise ValueError(
                    "V2_ACTIVITY_BASE_URL is required when V2_ACTIVITY_SYNC_ENABLED is true"
                )
            if (
                self.hypha_activity_secret is None
                or not self.hypha_activity_secret.get_secret_value().strip()
            ):
                raise ValueError(
                    "HYPHA_ACTIVITY_SECRET is required when V2_ACTIVITY_SYNC_ENABLED is true"
                )
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
