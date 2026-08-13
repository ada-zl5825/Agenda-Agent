"""Add Phase 6 source-evidence integrity constraints.

Revision ID: 20260813_0007
Revises: 20260813_0006
Create Date: 2026-08-13
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260813_0007"
down_revision: str | Sequence[str] | None = "20260813_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_foreign_key(
        "fk_application_status_history_source_email",
        "application_status_history",
        "source_emails",
        ["source_email_id"],
        ["id"],
        source_schema="app",
        referent_schema="app",
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_event_history_source_email",
        "event_history",
        "source_emails",
        ["source_email_id"],
        ["id"],
        source_schema="app",
        referent_schema="app",
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_action_items_source_email",
        "action_items",
        "source_emails",
        ["source_email_id"],
        ["id"],
        source_schema="app",
        referent_schema="app",
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_action_items_source_email",
        "action_items",
        schema="app",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_event_history_source_email",
        "event_history",
        schema="app",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_application_status_history_source_email",
        "application_status_history",
        schema="app",
        type_="foreignkey",
    )
