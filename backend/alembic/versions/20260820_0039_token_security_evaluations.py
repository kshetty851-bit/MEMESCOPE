"""Shared token-security evidence.

Additive only. Creates one new table and touches nothing that exists: no
paper position, no wallet, no track record, and no real-wallet audit row is
read or written by this migration.

Deliberately **not** backfilled. Historical tokens have no entry-time
security evidence, and inventing PASS rows from today's chain state would
manufacture exactly the false history the phase exists to avoid.

Revision ID: 0039_token_security
Revises: 0aae34865a58
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0039_token_security"
down_revision = "0aae34865a58"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "token_security_evaluations",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("mint_address", sa.String(44), nullable=False),
        sa.Column(
            "evaluated_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("overall_status", sa.String(16), nullable=False),
        sa.Column("evaluator_version", sa.String(32), nullable=False),
        sa.Column("reason_codes", postgresql.JSONB(), nullable=False),
        sa.Column("checks", postgresql.JSONB(), nullable=False),
        sa.Column("evidence", postgresql.JSONB(), nullable=False),
        sa.Column("market_snapshot_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_token_security_mint_evaluated_desc",
        "token_security_evaluations",
        ["mint_address", sa.text("evaluated_at DESC")],
    )
    op.create_index(
        "ix_token_security_evaluated_at", "token_security_evaluations", ["evaluated_at"]
    )
    op.create_index(
        "ix_token_security_status", "token_security_evaluations", ["overall_status"]
    )


def downgrade() -> None:
    op.drop_index("ix_token_security_status", table_name="token_security_evaluations")
    op.drop_index("ix_token_security_evaluated_at", table_name="token_security_evaluations")
    op.drop_index(
        "ix_token_security_mint_evaluated_desc", table_name="token_security_evaluations"
    )
    op.drop_table("token_security_evaluations")
