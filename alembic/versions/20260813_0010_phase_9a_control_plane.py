"""Add Phase 9A runtime controls and asynchronous operation audit.

Revision ID: 20260813_0010
Revises: 20260813_0009
Create Date: 2026-08-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260813_0010"
down_revision: str | Sequence[str] | None = "20260813_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "runtime_controls",
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("mail_sync_enabled", sa.Boolean(), nullable=False),
        sa.Column("workflow_enabled", sa.Boolean(), nullable=False),
        sa.Column("calendar_write_enabled", sa.Boolean(), nullable=False),
        sa.Column("daily_brief_enabled", sa.Boolean(), nullable=False),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("reason", sa.String(length=32), nullable=False),
        sa.Column("updated_by", sa.String(length=32), nullable=False),
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
        sa.CheckConstraint(
            "NOT calendar_write_enabled OR workflow_enabled",
            name="runtime_control_calendar_requires_workflow",
        ),
        sa.CheckConstraint(
            "reason IN ('manual', 'testing', 'maintenance', 'incident', 'account_switch')",
            name="runtime_control_reason_valid",
        ),
        sa.CheckConstraint("version >= 1", name="runtime_control_version_positive"),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["app.microsoft_connections.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("account_id"),
        schema="app",
    )
    op.create_table(
        "operation_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("operation_type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("idempotency_key_hash", sa.String(length=64), nullable=False),
        sa.Column("source_email_id", sa.Uuid(), nullable=True),
        sa.Column("batch_limit", sa.Integer(), nullable=True),
        sa.Column("parent_operation_id", sa.Uuid(), nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempt_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
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
        sa.CheckConstraint(
            "attempt_count >= 0",
            name="operation_attempt_count_nonnegative",
        ),
        sa.CheckConstraint(
            "batch_limit IS NULL OR (batch_limit >= 1 AND batch_limit <= 100)",
            name="operation_batch_limit_bounded",
        ),
        sa.CheckConstraint(
            "length(idempotency_key_hash) = 64",
            name="operation_idempotency_hash_sha256",
        ),
        sa.CheckConstraint(
            "operation_type IN ('mail_sync', 'process_email', 'process_pending', "
            "'reset_mail_cursor')",
            name="operation_type_valid",
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed')",
            name="operation_status_valid",
        ),
        sa.CheckConstraint(
            "(operation_type = 'process_email' AND source_email_id IS NOT NULL "
            "AND batch_limit IS NULL) OR "
            "(operation_type = 'process_pending' AND source_email_id IS NULL "
            "AND batch_limit IS NOT NULL) OR "
            "(operation_type IN ('mail_sync', 'reset_mail_cursor') "
            "AND source_email_id IS NULL AND batch_limit IS NULL)",
            name="operation_parameters_match_type",
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["app.microsoft_connections.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["parent_operation_id"],
            ["app.operation_runs.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_email_id"],
            ["app.source_emails.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "account_id",
            "operation_type",
            "idempotency_key_hash",
            name="uq_operation_runs_idempotency",
        ),
        schema="app",
    )
    for column in (
        "account_id",
        "operation_type",
        "status",
        "source_email_id",
        "parent_operation_id",
        "requested_at",
    ):
        op.create_index(
            op.f(f"ix_app_operation_runs_{column}"),
            "operation_runs",
            [column],
            unique=False,
            schema="app",
        )


def downgrade() -> None:
    for column in reversed(
        (
            "account_id",
            "operation_type",
            "status",
            "source_email_id",
            "parent_operation_id",
            "requested_at",
        )
    ):
        op.drop_index(
            op.f(f"ix_app_operation_runs_{column}"),
            table_name="operation_runs",
            schema="app",
        )
    op.drop_table("operation_runs", schema="app")
    op.drop_table("runtime_controls", schema="app")
