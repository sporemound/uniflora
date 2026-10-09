from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def new_id() -> str:
    return str(uuid4())


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class SessionScopedMixin:
    """Every stateful table stores both durable session identity and environment."""

    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("game_sessions.id", ondelete="CASCADE"), nullable=False
    )
    environment: Mapped[str] = mapped_column(String(8), nullable=False)


class GuildConfiguration(Base, TimestampMixin):
    __tablename__ = "guild_configurations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    guild_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    live_channel_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    test_channel_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    mycotroph_role_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    admin_user_ids: Mapped[list[int]] = mapped_column(JSON, nullable=False, default=list)
    diagnostic_channel_id: Mapped[int | None] = mapped_column(BigInteger)


class GameSession(Base, TimestampMixin):
    __tablename__ = "game_sessions"
    __table_args__ = (
        UniqueConstraint("guild_configuration_id", "environment", name="uq_session_guild_env"),
        UniqueConstraint("id", "environment", name="uq_session_id_env"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    guild_configuration_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("guild_configurations.id", ondelete="CASCADE"), nullable=False
    )
    environment: Mapped[str] = mapped_column(String(8), nullable=False)
    mode: Mapped[str] = mapped_column(String(16), nullable=False, default="locked")
    current_position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    response_profile: Mapped[str] = mapped_column(
        String(64), nullable=False, default="surface_noise"
    )
    state_data: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    modified_by_force: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class Player(Base, TimestampMixin, SessionScopedMixin):
    __tablename__ = "players"
    __table_args__ = (UniqueConstraint("session_id", "participant_id", name="uq_player_session"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    participant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    discord_user_id: Mapped[int | None] = mapped_column(BigInteger)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    is_simulated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class PlayerDifficultyPreference(Base, TimestampMixin, SessionScopedMixin):
    __tablename__ = "player_difficulty_preferences"
    __table_args__ = (
        UniqueConstraint(
            "session_id",
            "environment",
            "discord_user_id",
            "poll_id",
            name="uq_player_difficulty_session_user_poll",
        ),
        CheckConstraint(
            "difficulty_level IN ('guided', 'standard', 'expert')",
            name="ck_player_difficulty_level",
        ),
        CheckConstraint("revision >= 1", name="ck_player_difficulty_revision"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    discord_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    poll_id: Mapped[str] = mapped_column(String(64), nullable=False)
    difficulty_level: Mapped[str] = mapped_column(
        String(16), nullable=False, default="standard"
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class DifficultyBallot(Base, TimestampMixin, SessionScopedMixin):
    __tablename__ = "difficulty_ballots"
    __table_args__ = (
        UniqueConstraint("message_id", name="uq_difficulty_ballot_message"),
        UniqueConstraint(
            "session_id",
            "environment",
            "poll_id",
            "active_key",
            name="uq_difficulty_active_ballot",
        ),
        Index(
            "ix_difficulty_ballot_session_status",
            "session_id",
            "environment",
            "status",
        ),
        CheckConstraint(
            "status IN ('open', 'closed', 'orphaned')",
            name="ck_difficulty_ballot_status",
        ),
        CheckConstraint(
            "(status = 'open' AND active_key = 'active') OR "
            "(status <> 'open' AND active_key IS NULL)",
            name="ck_difficulty_ballot_active_key",
        ),
        CheckConstraint("revision >= 1", name="ck_difficulty_ballot_revision"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    poll_id: Mapped[str] = mapped_column(String(64), nullable=False)
    guild_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    channel_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    message_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")
    active_key: Mapped[str | None] = mapped_column(String(8), nullable=True, default="active")
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DifficultySelectionEvent(Base, TimestampMixin, SessionScopedMixin):
    __tablename__ = "difficulty_selection_events"
    __table_args__ = (
        UniqueConstraint(
            "discord_interaction_id",
            name="uq_difficulty_selection_interaction",
        ),
        CheckConstraint(
            "difficulty_level IN ('guided', 'standard', 'expert')",
            name="ck_difficulty_selection_level",
        ),
        CheckConstraint(
            "previous_level IS NULL OR "
            "previous_level IN ('guided', 'standard', 'expert')",
            name="ck_difficulty_selection_previous_level",
        ),
        CheckConstraint(
            "preference_revision >= 1",
            name="ck_difficulty_selection_preference_revision",
        ),
        Index(
            "ix_difficulty_selection_ballot_user",
            "ballot_id",
            "discord_user_id",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    ballot_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("difficulty_ballots.id", ondelete="CASCADE"), nullable=False
    )
    discord_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    discord_interaction_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    previous_level: Mapped[str | None] = mapped_column(String(16))
    difficulty_level: Mapped[str] = mapped_column(String(16), nullable=False)
    preference_revision: Mapped[int] = mapped_column(Integer, nullable=False)


class WorldFlag(Base, TimestampMixin, SessionScopedMixin):
    __tablename__ = "world_flags"
    __table_args__ = (UniqueConstraint("session_id", "flag_key", name="uq_world_flag_key"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    flag_key: Mapped[str] = mapped_column(String(128), nullable=False)
    value: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    set_by_event_id: Mapped[str] = mapped_column(String(36), nullable=False)


class Contribution(Base, TimestampMixin, SessionScopedMixin):
    __tablename__ = "contributions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    event_id: Mapped[str] = mapped_column(String(36), nullable=False)
    participant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    function: Mapped[str] = mapped_column(String(64), nullable=False)
    data: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


class Observation(Base, TimestampMixin, SessionScopedMixin):
    __tablename__ = "observations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    observation_key: Mapped[str] = mapped_column(String(128), nullable=False)
    public_data: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


class UnlockedObservation(Base, TimestampMixin, SessionScopedMixin):
    __tablename__ = "unlocked_observations"
    __table_args__ = (
        UniqueConstraint("session_id", "observation_key", name="uq_unlocked_session_key"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    observation_key: Mapped[str] = mapped_column(String(128), nullable=False)
    unlocked_by_event_id: Mapped[str] = mapped_column(String(36), nullable=False)


class ReconstructionProposal(Base, TimestampMixin, SessionScopedMixin):
    __tablename__ = "reconstruction_proposals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    author_participant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    proposal_data: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    event_id: Mapped[str] = mapped_column(String(36), nullable=False)


class Confirmation(Base, TimestampMixin, SessionScopedMixin):
    __tablename__ = "confirmations"
    __table_args__ = (
        UniqueConstraint("proposal_id", "participant_id", name="uq_confirmation_participant"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    proposal_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("reconstruction_proposals.id", ondelete="CASCADE"), nullable=False
    )
    participant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    event_id: Mapped[str] = mapped_column(String(36), nullable=False)


class RelationalContribution(Base, TimestampMixin, SessionScopedMixin):
    __tablename__ = "relational_contributions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    source_participant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    target_participant_id: Mapped[str | None] = mapped_column(String(128))
    relation_type: Mapped[str] = mapped_column(String(64), nullable=False)
    event_id: Mapped[str] = mapped_column(String(36), nullable=False)
    data: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


class RateLimitRecord(Base, TimestampMixin, SessionScopedMixin):
    __tablename__ = "rate_limit_records"
    __table_args__ = (
        UniqueConstraint("session_id", "scope_key", "window_key", name="uq_rate_limit_window"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    scope_key: Mapped[str] = mapped_column(String(128), nullable=False)
    window_key: Mapped[str] = mapped_column(String(64), nullable=False)
    request_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class ApiUsageRecord(Base, TimestampMixin, SessionScopedMixin):
    __tablename__ = "api_usage_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    purpose: Mapped[str] = mapped_column(String(32), nullable=False)
    participant_id: Mapped[str | None] = mapped_column(String(128))
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cached_input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    estimated_cost: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)


class RuntimeControl(Base, TimestampMixin, SessionScopedMixin):
    __tablename__ = "runtime_controls"
    __table_args__ = (UniqueConstraint("session_id", name="uq_runtime_control_session"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    fallback_mode: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    consecutive_api_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    interpretation_model: Mapped[str | None] = mapped_column(String(128))
    narration_model: Mapped[str | None] = mapped_column(String(128))
    budget_overrides: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    feature_flags: Mapped[dict[str, bool]] = mapped_column(JSON, nullable=False, default=dict)


class BackupRecord(Base):
    __tablename__ = "backup_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    path: Mapped[str | None] = mapped_column(Text)
    detail: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class EventLog(Base):
    __tablename__ = "event_log"
    __table_args__ = (
        ForeignKeyConstraint(
            ["session_id", "environment"],
            ["game_sessions.id", "game_sessions.environment"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("session_id", "sequence", name="uq_event_sequence"),
        UniqueConstraint("session_id", "idempotency_key", name="uq_event_idempotency"),
        UniqueConstraint("session_id", "completion_key", name="uq_event_completion"),
        Index("ix_event_session_created", "session_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    session_id: Mapped[str] = mapped_column(String(36), nullable=False)
    environment: Mapped[str] = mapped_column(String(8), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(128), nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(256))
    completion_key: Mapped[str | None] = mapped_column(String(128))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    state_before: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    state_after: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    invalidated_by_event_id: Mapped[str | None] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class Checkpoint(Base, SessionScopedMixin):
    __tablename__ = "checkpoints"
    __table_args__ = (UniqueConstraint("session_id", "name", name="uq_checkpoint_name"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    event_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    state_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class Summary(Base, TimestampMixin, SessionScopedMixin):
    __tablename__ = "summaries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    summary_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    public_text: Mapped[str] = mapped_column(Text, nullable=False)
    through_event_sequence: Mapped[int] = mapped_column(Integer, nullable=False)


class NarrationHistory(Base, TimestampMixin, SessionScopedMixin):
    __tablename__ = "narration_history"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    event_id: Mapped[str] = mapped_column(String(36), nullable=False)
    profile: Mapped[str] = mapped_column(String(64), nullable=False)
    public_text: Mapped[str] = mapped_column(Text, nullable=False)
    generated_by: Mapped[str] = mapped_column(String(32), nullable=False)


class SimulatedIdentity(Base, TimestampMixin, SessionScopedMixin):
    __tablename__ = "simulated_identities"
    __table_args__ = (
        UniqueConstraint("session_id", "participant_id", name="uq_sim_identity_participant"),
        UniqueConstraint("session_id", "slug", name="uq_sim_identity_slug"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    participant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    slug: Mapped[str] = mapped_column(String(64), nullable=False)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    created_by_admin_id: Mapped[int] = mapped_column(BigInteger, nullable=False)


class TestIdentitySelection(Base, TimestampMixin, SessionScopedMixin):
    __tablename__ = "test_identity_selections"
    __table_args__ = (
        UniqueConstraint("session_id", "admin_user_id", name="uq_test_selection_admin"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    admin_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    participant_id: Mapped[str] = mapped_column(String(128), nullable=False)
