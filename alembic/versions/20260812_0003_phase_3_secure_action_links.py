"""Create Phase 3 encrypted secure action links.

Revision ID: 20260812_0003
Revises: 20260812_0002
Create Date: 2026-08-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260812_0003"
down_revision: str | Sequence[str] | None = "20260812_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "secure_links",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_email_id", sa.Uuid(), nullable=False),
        sa.Column("ref", sa.String(length=32), nullable=False),
        sa.Column("link_type", sa.String(length=32), nullable=False),
        sa.Column("domain", sa.String(length=255), nullable=False),
        sa.Column("encrypted_url", sa.LargeBinary(), nullable=False),
        sa.Column("nonce", sa.LargeBinary(), nullable=False),
        sa.Column("encryption_key_version", sa.String(length=128), nullable=False),
        sa.Column("display_text", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["source_email_id"],
            ["app.source_emails.id"],
            name="fk_secure_links_source_email_id_source_emails",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_secure_links"),
        sa.UniqueConstraint(
            "source_email_id",
            "ref",
            name="uq_secure_links_source_email_ref",
        ),
        schema="app",
    )
    op.create_index(
        "ix_secure_links_source_email_id",
        "secure_links",
        ["source_email_id"],
        schema="app",
    )
    op.create_index(
        "ix_secure_links_link_type",
        "secure_links",
        ["link_type"],
        schema="app",
    )
    op.create_foreign_key(
        "fk_action_items_secure_link",
        "action_items",
        "secure_links",
        ["secure_link_id"],
        ["id"],
        source_schema="app",
        referent_schema="app",
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_action_items_secure_link",
        "action_items",
        schema="app",
        type_="foreignkey",
    )
    op.drop_table("secure_links", schema="app")
