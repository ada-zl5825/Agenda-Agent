"""Add Phase 8 Daily Brief dispatch audit.

Revision ID: 20260813_0009
Revises: 20260813_0008
Create Date: 2026-08-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260813_0009"
down_revision: str | Sequence[str] | None = "20260813_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "daily_briefs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("brief_date", sa.Date(), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("dispatch_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("attempt_count >= 1", name="attempt_count_positive"),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["app.microsoft_connections.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "account_id",
            "brief_date",
            name="uq_daily_briefs_account_date",
        ),
        schema="app",
    )
    op.create_index(
        op.f("ix_app_daily_briefs_account_id"),
        "daily_briefs",
        ["account_id"],
        unique=False,
        schema="app",
    )
    op.create_index(
        op.f("ix_app_daily_briefs_status"),
        "daily_briefs",
        ["status"],
        unique=False,
        schema="app",
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_app_daily_briefs_status"),
        table_name="daily_briefs",
        schema="app",
    )
    op.drop_index(
        op.f("ix_app_daily_briefs_account_id"),
        table_name="daily_briefs",
        schema="app",
    )
    op.drop_table("daily_briefs", schema="app")
