"""phase 6 guarded rollout controls

Revision ID: 0002_phase6
Revises: 0001_phase2
Create Date: 2026-07-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_phase6"
down_revision: str | None = "0001_phase2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "backup_records",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("path", sa.Text(), nullable=True),
        sa.Column("detail", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "runtime_controls",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("fallback_mode", sa.Boolean(), nullable=False),
        sa.Column("consecutive_api_failures", sa.Integer(), nullable=False),
        sa.Column("interpretation_model", sa.String(length=128), nullable=True),
        sa.Column("narration_model", sa.String(length=128), nullable=True),
        sa.Column("budget_overrides", sa.JSON(), nullable=False),
        sa.Column("feature_flags", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("environment", sa.String(length=8), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["game_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id", name="uq_runtime_control_session"),
    )


def downgrade() -> None:
    op.drop_table("runtime_controls")
    op.drop_table("backup_records")
