"""remove stored OpenAI prompt context

Revision ID: 0003_privacy
Revises: 0002_phase6
Create Date: 2026-07-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_privacy"
down_revision: str | None = "0002_phase6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Deliberately deletes previously stored prompt/context rows. The integration no longer
    # persists inputs or formats them into a reusable context/training-style collection.
    op.drop_table("gpt_context_records")


def downgrade() -> None:
    op.create_table(
        "gpt_context_records",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("purpose", sa.String(length=32), nullable=False),
        sa.Column("context_data", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("environment", sa.String(length=8), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["game_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
