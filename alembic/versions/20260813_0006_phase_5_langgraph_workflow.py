"""Create Phase 5 workflow audit and LangGraph checkpoint storage.

Revision ID: 20260813_0006
Revises: 20260813_0005
Create Date: 2026-08-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260813_0006"
down_revision: str | Sequence[str] | None = "20260813_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "processing_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_email_id", sa.Uuid(), nullable=False),
        sa.Column("graph_thread_id", sa.String(length=64), nullable=False),
        sa.Column("current_stage", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("prompt_version", sa.String(length=64), nullable=False),
        sa.Column("model_deployment", sa.String(length=255), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_detail_sanitized", sa.String(length=255), nullable=True),
        sa.CheckConstraint(
            "length(graph_thread_id) > 0",
            name="graph_thread_id_not_empty",
        ),
        sa.CheckConstraint("length(current_stage) > 0", name="current_stage_not_empty"),
        sa.ForeignKeyConstraint(
            ["source_email_id"],
            ["app.source_emails.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_processing_runs"),
        sa.UniqueConstraint("graph_thread_id", name="uq_processing_runs_graph_thread_id"),
        schema="app",
    )
    op.create_index(
        "ix_processing_runs_source_email_id",
        "processing_runs",
        ["source_email_id"],
        schema="app",
    )
    op.create_index(
        "ix_processing_runs_current_stage",
        "processing_runs",
        ["current_stage"],
        schema="app",
    )
    op.create_index(
        "ix_processing_runs_status",
        "processing_runs",
        ["status"],
        schema="app",
    )

    op.create_table(
        "llm_extractions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("processing_run_id", sa.Uuid(), nullable=False),
        sa.Column("source_email_id", sa.Uuid(), nullable=False),
        sa.Column("extraction", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("validation", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "company_resolution",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "role_resolution",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("prompt_version", sa.String(length=64), nullable=False),
        sa.Column("company_resolution_audit_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["company_resolution_audit_id"],
            ["app.company_resolution_attempts.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["processing_run_id"],
            ["app.processing_runs.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_email_id"],
            ["app.source_emails.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_llm_extractions"),
        sa.UniqueConstraint(
            "processing_run_id",
            name="uq_llm_extractions_processing_run_id",
        ),
        schema="app",
    )
    op.create_index(
        "ix_llm_extractions_source_email_id",
        "llm_extractions",
        ["source_email_id"],
        schema="app",
    )

    op.create_table(
        "review_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("processing_run_id", sa.Uuid(), nullable=False),
        sa.Column("review_type", sa.String(length=40), nullable=False),
        sa.Column("reason", sa.String(length=64), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("allowed_choices", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("resolution", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("length(reason) > 0", name="reason_not_empty"),
        sa.CheckConstraint("length(question) > 0", name="question_not_empty"),
        sa.CheckConstraint("version >= 1", name="version_positive"),
        sa.ForeignKeyConstraint(
            ["processing_run_id"],
            ["app.processing_runs.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_review_items"),
        schema="app",
    )
    op.create_index(
        "ix_review_items_processing_run_id",
        "review_items",
        ["processing_run_id"],
        schema="app",
    )
    op.create_index(
        "ix_review_items_review_type",
        "review_items",
        ["review_type"],
        schema="app",
    )
    op.create_index(
        "ix_review_items_status",
        "review_items",
        ["status"],
        schema="app",
    )

    op.execute(sa.text("CREATE SCHEMA IF NOT EXISTS agent_checkpoint"))
    op.create_table(
        "checkpoint_migrations",
        sa.Column("v", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("v", name="pk_checkpoint_migrations"),
        schema="agent_checkpoint",
    )
    op.create_table(
        "checkpoints",
        sa.Column("thread_id", sa.Text(), nullable=False),
        sa.Column("checkpoint_ns", sa.Text(), server_default="", nullable=False),
        sa.Column("checkpoint_id", sa.Text(), nullable=False),
        sa.Column("parent_checkpoint_id", sa.Text(), nullable=True),
        sa.Column("type", sa.Text(), nullable=True),
        sa.Column("checkpoint", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint(
            "thread_id",
            "checkpoint_ns",
            "checkpoint_id",
            name="pk_checkpoints",
        ),
        schema="agent_checkpoint",
    )
    op.create_table(
        "checkpoint_blobs",
        sa.Column("thread_id", sa.Text(), nullable=False),
        sa.Column("checkpoint_ns", sa.Text(), server_default="", nullable=False),
        sa.Column("channel", sa.Text(), nullable=False),
        sa.Column("version", sa.Text(), nullable=False),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("blob", sa.LargeBinary(), nullable=True),
        sa.PrimaryKeyConstraint(
            "thread_id",
            "checkpoint_ns",
            "channel",
            "version",
            name="pk_checkpoint_blobs",
        ),
        schema="agent_checkpoint",
    )
    op.create_table(
        "checkpoint_writes",
        sa.Column("thread_id", sa.Text(), nullable=False),
        sa.Column("checkpoint_ns", sa.Text(), server_default="", nullable=False),
        sa.Column("checkpoint_id", sa.Text(), nullable=False),
        sa.Column("task_id", sa.Text(), nullable=False),
        sa.Column("idx", sa.Integer(), nullable=False),
        sa.Column("channel", sa.Text(), nullable=False),
        sa.Column("type", sa.Text(), nullable=True),
        sa.Column("blob", sa.LargeBinary(), nullable=False),
        sa.Column("task_path", sa.Text(), server_default="", nullable=False),
        sa.PrimaryKeyConstraint(
            "thread_id",
            "checkpoint_ns",
            "checkpoint_id",
            "task_id",
            "idx",
            name="pk_checkpoint_writes",
        ),
        schema="agent_checkpoint",
    )
    op.create_index(
        "checkpoints_thread_id_idx",
        "checkpoints",
        ["thread_id"],
        schema="agent_checkpoint",
    )
    op.create_index(
        "checkpoint_blobs_thread_id_idx",
        "checkpoint_blobs",
        ["thread_id"],
        schema="agent_checkpoint",
    )
    op.create_index(
        "checkpoint_writes_thread_id_idx",
        "checkpoint_writes",
        ["thread_id"],
        schema="agent_checkpoint",
    )
    op.execute(
        sa.text(
            "INSERT INTO agent_checkpoint.checkpoint_migrations (v) "
            "SELECT generate_series(0, 9)"
        )
    )


def downgrade() -> None:
    op.drop_table("review_items", schema="app")
    op.drop_table("llm_extractions", schema="app")
    op.drop_table("processing_runs", schema="app")
    op.execute(sa.text("DROP SCHEMA agent_checkpoint CASCADE"))
