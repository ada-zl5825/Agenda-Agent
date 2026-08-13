"""Add Phase 7 idempotent Calendar link mapping.

Revision ID: 20260813_0008
Revises: 20260813_0007
Create Date: 2026-08-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260813_0008"
down_revision: str | Sequence[str] | None = "20260813_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "calendar_links",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("recruitment_event_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("calendar_event_id", sa.String(length=512), nullable=False),
        sa.Column("content_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=False),
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
        sa.CheckConstraint("length(provider) > 0", name="provider_not_empty"),
        sa.CheckConstraint(
            "length(calendar_event_id) > 0",
            name="calendar_event_id_not_empty",
        ),
        sa.CheckConstraint(
            "length(content_fingerprint) = 64",
            name="content_fingerprint_sha256",
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["app.microsoft_connections.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["recruitment_event_id"],
            ["app.recruitment_events.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "provider",
            "calendar_event_id",
            name="uq_calendar_links_provider_event",
        ),
        sa.UniqueConstraint(
            "recruitment_event_id",
            name="uq_calendar_links_recruitment_event",
        ),
        schema="app",
    )
    op.create_index(
        op.f("ix_app_calendar_links_account_id"),
        "calendar_links",
        ["account_id"],
        unique=False,
        schema="app",
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_app_calendar_links_account_id"),
        table_name="calendar_links",
        schema="app",
    )
    op.drop_table("calendar_links", schema="app")
