"""Create Phase 3.5 canonical company entities.

Revision ID: 20260813_0004
Revises: 20260812_0003
Create Date: 2026-08-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260813_0004"
down_revision: str | Sequence[str] | None = "20260812_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "companies",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("canonical_name", sa.String(length=255), nullable=False),
        sa.Column("normalized_canonical_name", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("entity_type", sa.String(length=32), nullable=False),
        sa.Column("parent_company_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("length(canonical_name) > 0", name="canonical_name_not_empty"),
        sa.CheckConstraint(
            "length(normalized_canonical_name) > 0",
            name="normalized_canonical_name_not_empty",
        ),
        sa.CheckConstraint("length(display_name) > 0", name="display_name_not_empty"),
        sa.ForeignKeyConstraint(
            ["parent_company_id"],
            ["app.companies.id"],
            name="fk_companies_parent_company",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_companies"),
        sa.UniqueConstraint(
            "normalized_canonical_name",
            name="uq_companies_normalized_canonical_name",
        ),
        schema="app",
    )
    op.create_index(
        "ix_companies_entity_type",
        "companies",
        ["entity_type"],
        schema="app",
    )
    op.create_index(
        "ix_companies_parent_company_id",
        "companies",
        ["parent_company_id"],
        schema="app",
    )
    op.create_index("ix_companies_status", "companies", ["status"], schema="app")

    op.create_table(
        "company_aliases",
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("normalized_alias", sa.String(length=255), nullable=False),
        sa.Column("alias", sa.String(length=255), nullable=False),
        sa.Column("language", sa.String(length=16), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.CheckConstraint("length(alias) > 0", name="alias_not_empty"),
        sa.CheckConstraint("length(normalized_alias) > 0", name="normalized_alias_not_empty"),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="confidence_range",
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["app.companies.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "company_id",
            "normalized_alias",
            name="pk_company_aliases",
        ),
        schema="app",
    )
    op.create_index(
        "ix_company_aliases_normalized_alias",
        "company_aliases",
        ["normalized_alias"],
        schema="app",
    )

    op.create_table(
        "company_domains",
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("domain", sa.String(length=255), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.CheckConstraint("length(domain) > 0", name="domain_not_empty"),
        sa.CheckConstraint("domain = lower(domain)", name="domain_lowercase"),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="confidence_range",
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["app.companies.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("company_id", "domain", name="pk_company_domains"),
        schema="app",
    )
    op.create_index(
        "ix_company_domains_domain",
        "company_domains",
        ["domain"],
        schema="app",
    )

    op.add_column(
        "applications",
        sa.Column("company_id", sa.Uuid(), nullable=True),
        schema="app",
    )
    op.add_column(
        "applications",
        sa.Column("raw_company_name", sa.String(length=255), nullable=True),
        schema="app",
    )
    op.execute(
        sa.text(
            "UPDATE app.applications "
            "SET raw_company_name = company_name "
            "WHERE raw_company_name IS NULL"
        )
    )
    op.drop_index("ix_applications_normalized_identity", table_name="applications", schema="app")
    op.drop_constraint(
        "company_name_not_empty",
        "applications",
        schema="app",
        type_="check",
    )
    op.drop_column("applications", "company_normalized", schema="app")
    op.drop_column("applications", "company_name", schema="app")
    op.create_check_constraint(
        "raw_company_name_not_empty",
        "applications",
        "raw_company_name IS NULL OR length(btrim(raw_company_name)) > 0",
        schema="app",
    )
    op.create_foreign_key(
        "fk_applications_company",
        "applications",
        "companies",
        ["company_id"],
        ["id"],
        source_schema="app",
        referent_schema="app",
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_applications_company_id",
        "applications",
        ["company_id"],
        schema="app",
    )
    op.create_index(
        "ix_applications_company_role",
        "applications",
        ["company_id", "role_normalized"],
        schema="app",
    )


def downgrade() -> None:
    op.add_column(
        "applications",
        sa.Column("company_name", sa.String(length=255), nullable=True),
        schema="app",
    )
    op.add_column(
        "applications",
        sa.Column("company_normalized", sa.String(length=255), nullable=True),
        schema="app",
    )
    op.execute(
        sa.text(
            "UPDATE app.applications AS application "
            "SET company_name = COALESCE(application.raw_company_name, company.display_name), "
            "company_normalized = "
            "lower(COALESCE(application.raw_company_name, company.display_name)) "
            "FROM app.companies AS company "
            "WHERE application.company_id = company.id"
        )
    )
    op.execute(
        sa.text(
            "UPDATE app.applications "
            "SET company_name = COALESCE(company_name, raw_company_name, 'Unknown'), "
            "company_normalized = COALESCE(company_normalized, lower(raw_company_name), 'unknown')"
        )
    )
    op.alter_column("applications", "company_name", nullable=False, schema="app")
    op.alter_column("applications", "company_normalized", nullable=False, schema="app")
    op.drop_index("ix_applications_company_role", table_name="applications", schema="app")
    op.drop_index("ix_applications_company_id", table_name="applications", schema="app")
    op.drop_constraint(
        "fk_applications_company",
        "applications",
        schema="app",
        type_="foreignkey",
    )
    op.drop_constraint(
        "raw_company_name_not_empty",
        "applications",
        schema="app",
        type_="check",
    )
    op.drop_column("applications", "raw_company_name", schema="app")
    op.drop_column("applications", "company_id", schema="app")
    op.create_check_constraint(
        "company_name_not_empty",
        "applications",
        "length(company_name) > 0",
        schema="app",
    )
    op.create_index(
        "ix_applications_normalized_identity",
        "applications",
        ["company_normalized", "role_normalized"],
        schema="app",
    )
    op.drop_table("company_domains", schema="app")
    op.drop_table("company_aliases", schema="app")
    op.drop_table("companies", schema="app")
