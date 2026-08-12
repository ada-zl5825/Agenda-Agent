"""Create Phase 0 domain foundation.

Revision ID: 20260812_0001
Revises:
Create Date: 2026-08-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260812_0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS app")

    op.create_table(
        "applications",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_name", sa.String(length=255), nullable=False),
        sa.Column("company_normalized", sa.String(length=255), nullable=False),
        sa.Column("role_name", sa.String(length=255), nullable=True),
        sa.Column("role_normalized", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=32), server_default="unknown", nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("length(company_name) > 0", name="company_name_not_empty"),
        sa.PrimaryKeyConstraint("id", name="pk_applications"),
        schema="app",
    )
    op.create_index("ix_applications_status", "applications", ["status"], schema="app")
    op.create_index(
        "ix_applications_normalized_identity",
        "applications",
        ["company_normalized", "role_normalized"],
        schema="app",
    )

    op.create_table(
        "application_status_history",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("application_id", sa.Uuid(), nullable=False),
        sa.Column("from_status", sa.String(length=32), nullable=True),
        sa.Column("to_status", sa.String(length=32), nullable=False),
        sa.Column("reason", sa.String(length=255), nullable=True),
        sa.Column("source_email_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["application_id"],
            ["app.applications.id"],
            name="fk_application_status_history_application_id_applications",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_application_status_history"),
        schema="app",
    )
    op.create_index(
        "ix_application_status_history_application_id",
        "application_status_history",
        ["application_id"],
        schema="app",
    )

    op.create_table(
        "recruitment_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("application_id", sa.Uuid(), nullable=False),
        sa.Column("type", sa.String(length=40), nullable=False),
        sa.Column("round", sa.String(length=100), nullable=True),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("timezone", sa.String(length=64), nullable=True),
        sa.Column("source_datetime_text", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), server_default="active", nullable=False),
        sa.Column("semantic_fingerprint", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["application_id"],
            ["app.applications.id"],
            name="fk_recruitment_events_application_id_applications",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_recruitment_events"),
        sa.UniqueConstraint(
            "application_id",
            "semantic_fingerprint",
            name="uq_recruitment_events_application_fingerprint",
        ),
        schema="app",
    )
    op.create_index(
        "ix_recruitment_events_application_id",
        "recruitment_events",
        ["application_id"],
        schema="app",
    )
    op.create_index("ix_recruitment_events_status", "recruitment_events", ["status"], schema="app")
    op.create_index("ix_recruitment_events_type", "recruitment_events", ["type"], schema="app")

    op.create_table(
        "event_history",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("recruitment_event_id", sa.Uuid(), nullable=False),
        sa.Column("previous_starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("previous_deadline_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("previous_timezone", sa.String(length=64), nullable=True),
        sa.Column("previous_status", sa.String(length=20), nullable=True),
        sa.Column("reason", sa.String(length=255), nullable=False),
        sa.Column("source_email_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["recruitment_event_id"],
            ["app.recruitment_events.id"],
            name="fk_event_history_recruitment_event_id_recruitment_events",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_event_history"),
        schema="app",
    )
    op.create_index(
        "ix_event_history_recruitment_event_id",
        "event_history",
        ["recruitment_event_id"],
        schema="app",
    )

    op.create_table(
        "action_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("application_id", sa.Uuid(), nullable=False),
        sa.Column("source_email_id", sa.Uuid(), nullable=False),
        sa.Column("type", sa.String(length=40), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("secure_link_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(length=20), server_default="open", nullable=False),
        sa.Column("idempotency_key", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("length(title) > 0", name="title_not_empty"),
        sa.ForeignKeyConstraint(
            ["application_id"],
            ["app.applications.id"],
            name="fk_action_items_application_id_applications",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_action_items"),
        sa.UniqueConstraint(
            "application_id",
            "idempotency_key",
            name="uq_action_items_application_idempotency_key",
        ),
        schema="app",
    )
    op.create_index(
        "ix_action_items_application_id", "action_items", ["application_id"], schema="app"
    )
    op.create_index(
        "ix_action_items_source_email_id", "action_items", ["source_email_id"], schema="app"
    )
    op.create_index("ix_action_items_status", "action_items", ["status"], schema="app")


def downgrade() -> None:
    op.drop_table("action_items", schema="app")
    op.drop_table("event_history", schema="app")
    op.drop_table("recruitment_events", schema="app")
    op.drop_table("application_status_history", schema="app")
    op.drop_table("applications", schema="app")
    op.execute("DROP SCHEMA IF EXISTS app")
