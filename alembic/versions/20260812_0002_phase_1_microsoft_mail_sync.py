"""Create Phase 1 Microsoft authorization and mail synchronization tables.

Revision ID: 20260812_0002
Revises: 20260812_0001
Create Date: 2026-08-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260812_0002"
down_revision: str | Sequence[str] | None = "20260812_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "microsoft_connections",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("home_account_id", sa.String(length=255), nullable=True),
        sa.Column("tenant_id", sa.String(length=64), nullable=True),
        sa.Column("token_cache_ciphertext", sa.LargeBinary(), nullable=True),
        sa.Column("token_cache_nonce", sa.LargeBinary(), nullable=True),
        sa.Column("token_cache_key_version", sa.String(length=64), nullable=True),
        sa.Column("token_cache_revision", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_microsoft_connections"),
        sa.UniqueConstraint("home_account_id", name="uq_microsoft_connections_home_account_id"),
        schema="app",
    )

    op.create_table(
        "microsoft_authorization_flows",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("connection_id", sa.Uuid(), nullable=False),
        sa.Column("state_hash", sa.String(length=64), nullable=False),
        sa.Column("flow_ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("flow_nonce", sa.LargeBinary(), nullable=False),
        sa.Column("key_version", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["connection_id"],
            ["app.microsoft_connections.id"],
            name="fk_ms_auth_flows_connection",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_microsoft_authorization_flows"),
        sa.UniqueConstraint(
            "state_hash", name="uq_microsoft_authorization_flows_state_hash"
        ),
        schema="app",
    )
    op.create_index(
        "ix_microsoft_authorization_flows_connection_id",
        "microsoft_authorization_flows",
        ["connection_id"],
        schema="app",
    )
    op.create_index(
        "ix_microsoft_authorization_flows_expires_at",
        "microsoft_authorization_flows",
        ["expires_at"],
        schema="app",
    )

    op.create_table(
        "mail_sync_states",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("folder_id", sa.String(length=255), nullable=False),
        sa.Column("delta_link", sa.Text(), nullable=True),
        sa.Column("last_sync_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sync_finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=20), server_default="idle", nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["app.microsoft_connections.id"],
            name="fk_mail_sync_states_account_id_microsoft_connections",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_mail_sync_states"),
        sa.UniqueConstraint(
            "account_id", "folder_id", name="uq_mail_sync_states_account_folder"
        ),
        schema="app",
    )
    op.create_index(
        "ix_mail_sync_states_account_id",
        "mail_sync_states",
        ["account_id"],
        schema="app",
    )

    op.create_table(
        "source_emails",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("graph_message_id", sa.String(length=512), nullable=False),
        sa.Column("internet_message_id", sa.String(length=512), nullable=True),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("sender_domain", sa.String(length=255), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("outlook_web_link", sa.Text(), nullable=True),
        sa.Column("body_hash", sa.String(length=64), nullable=True),
        sa.Column("has_attachments", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column(
            "processing_status",
            sa.String(length=20),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("application_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["app.microsoft_connections.id"],
            name="fk_source_emails_account_id_microsoft_connections",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["application_id"],
            ["app.applications.id"],
            name="fk_source_emails_application_id_applications",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_source_emails"),
        sa.UniqueConstraint("graph_message_id", name="uq_source_emails_graph_message_id"),
        schema="app",
    )
    for name, columns in (
        ("ix_source_emails_account_id", ["account_id"]),
        ("ix_source_emails_application_id", ["application_id"]),
        ("ix_source_emails_internet_message_id", ["internet_message_id"]),
        ("ix_source_emails_processing_status", ["processing_status"]),
        ("ix_source_emails_received_at", ["received_at"]),
    ):
        op.create_index(name, "source_emails", columns, schema="app")


def downgrade() -> None:
    op.drop_table("source_emails", schema="app")
    op.drop_table("mail_sync_states", schema="app")
    op.drop_table("microsoft_authorization_flows", schema="app")
    op.drop_table("microsoft_connections", schema="app")
