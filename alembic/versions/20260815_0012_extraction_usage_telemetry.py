"""Add extraction usage telemetry columns for cost and latency auditing.

Revision ID: 20260815_0012
Revises: 20260814_0011
Create Date: 2026-08-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260815_0012"
down_revision: str | Sequence[str] | None = "20260814_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "llm_extractions",
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        schema="app",
    )
    op.add_column(
        "llm_extractions",
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        schema="app",
    )
    op.add_column(
        "llm_extractions",
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        schema="app",
    )
    op.create_check_constraint(
        "llm_extractions_prompt_tokens_nonnegative",
        "llm_extractions",
        "prompt_tokens IS NULL OR prompt_tokens >= 0",
        schema="app",
    )
    op.create_check_constraint(
        "llm_extractions_completion_tokens_nonnegative",
        "llm_extractions",
        "completion_tokens IS NULL OR completion_tokens >= 0",
        schema="app",
    )
    op.create_check_constraint(
        "llm_extractions_latency_ms_nonnegative",
        "llm_extractions",
        "latency_ms IS NULL OR latency_ms >= 0",
        schema="app",
    )


def downgrade() -> None:
    op.drop_constraint(
        "llm_extractions_latency_ms_nonnegative",
        "llm_extractions",
        schema="app",
        type_="check",
    )
    op.drop_constraint(
        "llm_extractions_completion_tokens_nonnegative",
        "llm_extractions",
        schema="app",
        type_="check",
    )
    op.drop_constraint(
        "llm_extractions_prompt_tokens_nonnegative",
        "llm_extractions",
        schema="app",
        type_="check",
    )
    op.drop_column("llm_extractions", "latency_ms", schema="app")
    op.drop_column("llm_extractions", "completion_tokens", schema="app")
    op.drop_column("llm_extractions", "prompt_tokens", schema="app")
