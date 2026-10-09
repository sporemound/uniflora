"""add private per-user difficulty ballots

Revision ID: 0004_difficulty
Revises: 0003_privacy
Create Date: 2026-07-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_difficulty"
down_revision: str | None = "0003_privacy"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "difficulty_ballots",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("poll_id", sa.String(length=64), nullable=False),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("channel_id", sa.BigInteger(), nullable=False),
        sa.Column("message_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("active_key", sa.String(length=8), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("environment", sa.String(length=8), nullable=False),
        sa.CheckConstraint(
            "status IN ('open', 'closed', 'orphaned')",
            name="ck_difficulty_ballot_status",
        ),
        sa.CheckConstraint(
            "(status = 'open' AND active_key = 'active') OR "
            "(status <> 'open' AND active_key IS NULL)",
            name="ck_difficulty_ballot_active_key",
        ),
        sa.CheckConstraint("revision >= 1", name="ck_difficulty_ballot_revision"),
        sa.ForeignKeyConstraint(["session_id"], ["game_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("message_id", name="uq_difficulty_ballot_message"),
        sa.UniqueConstraint(
            "session_id",
            "environment",
            "poll_id",
            "active_key",
            name="uq_difficulty_active_ballot",
        ),
    )
    op.create_index(
        "ix_difficulty_ballot_session_status",
        "difficulty_ballots",
        ["session_id", "environment", "status"],
    )

    op.create_table(
        "player_difficulty_preferences",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("discord_user_id", sa.BigInteger(), nullable=False),
        sa.Column("poll_id", sa.String(length=64), nullable=False),
        sa.Column("difficulty_level", sa.String(length=16), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("environment", sa.String(length=8), nullable=False),
        sa.CheckConstraint(
            "difficulty_level IN ('guided', 'standard', 'expert')",
            name="ck_player_difficulty_level",
        ),
        sa.CheckConstraint("revision >= 1", name="ck_player_difficulty_revision"),
        sa.ForeignKeyConstraint(["session_id"], ["game_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "session_id",
            "environment",
            "discord_user_id",
            "poll_id",
            name="uq_player_difficulty_session_user_poll",
        ),
    )

    op.create_table(
        "difficulty_selection_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("ballot_id", sa.String(length=36), nullable=False),
        sa.Column("discord_user_id", sa.BigInteger(), nullable=False),
        sa.Column("discord_interaction_id", sa.BigInteger(), nullable=False),
        sa.Column("previous_level", sa.String(length=16), nullable=True),
        sa.Column("difficulty_level", sa.String(length=16), nullable=False),
        sa.Column("preference_revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("environment", sa.String(length=8), nullable=False),
        sa.CheckConstraint(
            "difficulty_level IN ('guided', 'standard', 'expert')",
            name="ck_difficulty_selection_level",
        ),
        sa.CheckConstraint(
            "previous_level IS NULL OR "
            "previous_level IN ('guided', 'standard', 'expert')",
            name="ck_difficulty_selection_previous_level",
        ),
        sa.CheckConstraint(
            "preference_revision >= 1",
            name="ck_difficulty_selection_preference_revision",
        ),
        sa.ForeignKeyConstraint(
            ["ballot_id"],
            ["difficulty_ballots.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["session_id"], ["game_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "discord_interaction_id",
            name="uq_difficulty_selection_interaction",
        ),
    )
    op.create_index(
        "ix_difficulty_selection_ballot_user",
        "difficulty_selection_events",
        ["ballot_id", "discord_user_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_difficulty_selection_ballot_user",
        table_name="difficulty_selection_events",
    )
    op.drop_table("difficulty_selection_events")
    op.drop_table("player_difficulty_preferences")
    op.drop_index(
        "ix_difficulty_ballot_session_status",
        table_name="difficulty_ballots",
    )
    op.drop_table("difficulty_ballots")
