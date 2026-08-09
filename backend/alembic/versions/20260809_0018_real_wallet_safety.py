"""append-only real-wallet safety evaluations

Revision ID: 0018_real_wallet_safety
Revises: 0017_token_image_url
Create Date: 2026-08-09 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0018_real_wallet_safety"
down_revision = "0017_token_image_url"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "real_wallet_safety_evaluations",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("mint_address", sa.String(length=44), nullable=False),
        sa.Column("decision", sa.String(length=8), nullable=False),
        sa.Column(
            "evaluated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("trade_size_usd", sa.Numeric(24, 4), nullable=False),
        sa.Column("policy_version", sa.String(length=64), nullable=False),
        sa.Column("reason_codes", postgresql.JSONB(), nullable=False),
        sa.Column("market_snapshot_at", sa.DateTime(timezone=True)),
        sa.Column("market_age_seconds", sa.Numeric(20, 4)),
        sa.Column("market_price_usd", sa.Numeric(38, 18)),
        sa.Column("liquidity_usd", sa.Numeric(24, 4)),
        sa.Column("buy_price_impact_pct", sa.Numeric(20, 4)),
        sa.Column("sell_price_impact_pct", sa.Numeric(20, 4)),
        sa.Column("round_trip_loss_usd", sa.Numeric(24, 4)),
        sa.Column("round_trip_loss_pct", sa.Numeric(20, 4)),
        sa.Column("position_liquidity_ratio", sa.Numeric(20, 8)),
        sa.Column("token_program", sa.String(length=44)),
        sa.Column("mint_authority_active", sa.Boolean()),
        sa.Column("freeze_authority_active", sa.Boolean()),
        sa.Column("token_extensions", postgresql.JSONB()),
        sa.Column("provenance", postgresql.JSONB(), nullable=False),
        sa.Column("buy_quote", postgresql.JSONB()),
        sa.Column("sell_quote", postgresql.JSONB()),
        sa.Column("token_configuration", postgresql.JSONB()),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_real_wallet_safety_evaluations")),
    )
    op.create_index(
        "ix_real_wallet_safety_evaluations_mint_address",
        "real_wallet_safety_evaluations",
        ["mint_address"],
    )
    op.create_index(
        "ix_real_wallet_safety_evaluations_decision",
        "real_wallet_safety_evaluations",
        ["decision"],
    )
    op.create_index(
        "ix_real_wallet_safety_evaluations_evaluated_at",
        "real_wallet_safety_evaluations",
        ["evaluated_at"],
    )
    op.create_index(
        "ix_real_wallet_safety_mint_evaluated_desc",
        "real_wallet_safety_evaluations",
        ["mint_address", sa.text("evaluated_at DESC")],
    )


def downgrade() -> None:
    op.drop_table("real_wallet_safety_evaluations")
