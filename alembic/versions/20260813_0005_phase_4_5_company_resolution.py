"""Create Phase 4.5 company-resolution audit records.

Revision ID: 20260813_0005
Revises: 20260813_0004
Create Date: 2026-08-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260813_0005"
down_revision: str | Sequence[str] | None = "20260813_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "company_resolution_attempts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_email_id", sa.Uuid(), nullable=False),
        sa.Column("sender_domain", sa.String(length=255), nullable=True),
        sa.Column("raw_company_name", sa.Text(), nullable=True),
        sa.Column("company_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("method", sa.String(length=32), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("matched_value", sa.String(length=255), nullable=True),
        sa.Column("role_raw", sa.Text(), nullable=True),
        sa.Column("role_normalized", sa.Text(), nullable=True),
        sa.Column("role_family", sa.String(length=32), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "raw_company_name IS NULL OR length(btrim(raw_company_name)) > 0",
            name="raw_company_name_not_empty",
        ),
        sa.CheckConstraint(
            "matched_value IS NULL OR length(btrim(matched_value)) > 0",
            name="matched_value_not_empty",
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="confidence_range",
        ),
        sa.CheckConstraint(
            "role_raw IS NULL OR length(btrim(role_raw)) > 0",
            name="role_raw_not_empty",
        ),
        sa.ForeignKeyConstraint(
            ["source_email_id"],
            ["app.source_emails.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["app.companies.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_company_resolution_attempts"),
        schema="app",
    )
    op.create_index(
        "ix_company_resolution_attempts_source_email_id",
        "company_resolution_attempts",
        ["source_email_id"],
        schema="app",
    )
    op.create_index(
        "ix_company_resolution_attempts_company_id",
        "company_resolution_attempts",
        ["company_id"],
        schema="app",
    )
    op.create_index(
        "ix_company_resolution_attempts_status",
        "company_resolution_attempts",
        ["status"],
        schema="app",
    )

    op.create_table(
        "company_resolution_candidates",
        sa.Column("resolution_attempt_id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["resolution_attempt_id"],
            ["app.company_resolution_attempts.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["app.companies.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "resolution_attempt_id",
            "company_id",
            name="pk_company_resolution_candidates",
        ),
        schema="app",
    )


def downgrade() -> None:
    op.drop_table("company_resolution_candidates", schema="app")
    op.drop_index(
        "ix_company_resolution_attempts_status",
        table_name="company_resolution_attempts",
        schema="app",
    )
    op.drop_index(
        "ix_company_resolution_attempts_company_id",
        table_name="company_resolution_attempts",
        schema="app",
    )
    op.drop_index(
        "ix_company_resolution_attempts_source_email_id",
        table_name="company_resolution_attempts",
        schema="app",
    )
    op.drop_table("company_resolution_attempts", schema="app")
