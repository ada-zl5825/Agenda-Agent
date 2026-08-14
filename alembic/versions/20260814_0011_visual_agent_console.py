"""Add visual-console auth separation, recipient settings, and Brief delivery.

Revision ID: 20260814_0011
Revises: 20260813_0010
Create Date: 2026-08-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260814_0011"
down_revision: str | Sequence[str] | None = "20260813_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "admin_identities",
        sa.Column("home_account_id", sa.String(length=255), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=True),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
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
        sa.PrimaryKeyConstraint("home_account_id"),
        schema="app",
    )
    op.execute(
        sa.text(
            "INSERT INTO app.admin_identities (home_account_id, tenant_id) "
            "SELECT DISTINCT home_account_id, tenant_id "
            "FROM app.microsoft_connections WHERE home_account_id IS NOT NULL "
            "ON CONFLICT (home_account_id) DO NOTHING"
        )
    )
    op.add_column(
        "runtime_controls",
        sa.Column("daily_brief_recipient", sa.String(length=254), nullable=True),
        schema="app",
    )
    op.create_check_constraint(
        "runtime_control_daily_brief_recipient_valid",
        "runtime_controls",
        "daily_brief_recipient IS NULL OR "
        "(length(daily_brief_recipient) BETWEEN 3 AND 254 "
        "AND position('@' in daily_brief_recipient) > 1)",
        schema="app",
    )
    op.drop_constraint(
        "operation_type_valid",
        "operation_runs",
        schema="app",
        type_="check",
    )
    op.drop_constraint(
        "operation_parameters_match_type",
        "operation_runs",
        schema="app",
        type_="check",
    )
    op.create_check_constraint(
        "operation_type_valid",
        "operation_runs",
        "operation_type IN ('mail_sync', 'process_email', 'process_pending', "
        "'reset_mail_cursor', 'send_daily_brief')",
        schema="app",
    )
    op.create_check_constraint(
        "operation_parameters_match_type",
        "operation_runs",
        "(operation_type = 'process_email' AND source_email_id IS NOT NULL "
        "AND batch_limit IS NULL) OR "
        "(operation_type = 'process_pending' AND source_email_id IS NULL "
        "AND batch_limit IS NOT NULL) OR "
        "(operation_type IN ('mail_sync', 'reset_mail_cursor', 'send_daily_brief') "
        "AND source_email_id IS NULL AND batch_limit IS NULL)",
        schema="app",
    )


def downgrade() -> None:
    op.drop_constraint(
        "operation_parameters_match_type",
        "operation_runs",
        schema="app",
        type_="check",
    )
    op.drop_constraint(
        "operation_type_valid",
        "operation_runs",
        schema="app",
        type_="check",
    )
    op.create_check_constraint(
        "operation_type_valid",
        "operation_runs",
        "operation_type IN ('mail_sync', 'process_email', 'process_pending', "
        "'reset_mail_cursor')",
        schema="app",
    )
    op.drop_constraint(
        "runtime_control_daily_brief_recipient_valid",
        "runtime_controls",
        schema="app",
        type_="check",
    )
    op.drop_column("runtime_controls", "daily_brief_recipient", schema="app")
    op.drop_table("admin_identities", schema="app")
    op.create_check_constraint(
        "operation_parameters_match_type",
        "operation_runs",
        "(operation_type = 'process_email' AND source_email_id IS NOT NULL "
        "AND batch_limit IS NULL) OR "
        "(operation_type = 'process_pending' AND source_email_id IS NULL "
        "AND batch_limit IS NOT NULL) OR "
        "(operation_type IN ('mail_sync', 'reset_mail_cursor') "
        "AND source_email_id IS NULL AND batch_limit IS NULL)",
        schema="app",
    )
