"""Add market snapshots and enrichment scheduling state

Revision ID: 0003_market_enrichment
Revises: 0002_discovered_tokens
Create Date: 2026-07-27
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_market_enrichment"
down_revision: str | None = "0002_discovered_tokens"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Money as NUMERIC, never float: binary floats cannot represent decimal
# fractions exactly, and the error compounds across millions of snapshots.
PRICE = sa.Numeric(38, 18)
MONEY = sa.Numeric(24, 4)


def upgrade() -> None:
    trading_status = postgresql.ENUM(
        "unknown", "trading", "inactive", name="trading_status", create_type=False
    )
    trading_status.create(op.get_bind(), checkfirst=True)

    enrichment_status = postgresql.ENUM(
        "active", "dead_letter", "paused", name="enrichment_status", create_type=False
    )
    enrichment_status.create(op.get_bind(), checkfirst=True)

    # --- Append-only snapshot history ---------------------------------------
    op.create_table(
        "token_market_snapshots",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("token_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("mint_address", sa.String(length=44), nullable=False),
        sa.Column(
            "captured_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("price_usd", PRICE, nullable=True),
        sa.Column("price_native", PRICE, nullable=True),
        sa.Column("liquidity_usd", MONEY, nullable=True),
        sa.Column("fully_diluted_valuation", MONEY, nullable=True),
        sa.Column("market_cap", MONEY, nullable=True),
        sa.Column("volume_24h", MONEY, nullable=True),
        sa.Column("volume_1h", MONEY, nullable=True),
        sa.Column("volume_5m", MONEY, nullable=True),
        sa.Column("buy_count_24h", sa.Integer(), nullable=True),
        sa.Column("sell_count_24h", sa.Integer(), nullable=True),
        sa.Column("dex_name", sa.String(length=64), nullable=True),
        sa.Column("trading_pair", sa.String(length=96), nullable=True),
        sa.Column("pool_address", sa.String(length=44), nullable=True),
        sa.Column("trading_status", trading_status, server_default="unknown", nullable=False),
        sa.Column("is_verified", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("provider_latency_ms", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_token_market_snapshots"),
        sa.ForeignKeyConstraint(
            ["token_id"],
            ["discovered_tokens.id"],
            name="fk_token_market_snapshots_token_id_discovered_tokens",
            ondelete="CASCADE",
        ),
    )

    # Serves both "history for this token" and the DISTINCT ON that resolves
    # each token's latest snapshot for trending.
    op.create_index(
        "ix_snapshots_mint_captured_desc",
        "token_market_snapshots",
        ["mint_address", sa.text("captured_at DESC")],
    )
    op.create_index(
        "ix_snapshots_token_captured_desc",
        "token_market_snapshots",
        ["token_id", sa.text("captured_at DESC")],
    )
    op.create_index(
        "ix_snapshots_captured_at",
        "token_market_snapshots",
        [sa.text("captured_at DESC")],
    )

    # --- Scheduler work queue ------------------------------------------------
    op.create_table(
        "token_enrichment_state",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("token_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("mint_address", sa.String(length=44), nullable=False),
        sa.Column("status", enrichment_status, server_default="active", nullable=False),
        sa.Column(
            "next_refresh_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consecutive_failures", sa.Integer(), server_default="0", nullable=False),
        sa.Column("total_refreshes", sa.Integer(), server_default="0", nullable=False),
        sa.Column("total_snapshots", sa.Integer(), server_default="0", nullable=False),
        sa.Column("consecutive_empty", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_error", sa.String(length=500), nullable=True),
        sa.Column("tier", sa.String(length=16), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name="pk_token_enrichment_state"),
        sa.ForeignKeyConstraint(
            ["token_id"],
            ["discovered_tokens.id"],
            name="fk_token_enrichment_state_token_id_discovered_tokens",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("token_id", name="uq_token_enrichment_state_token_id"),
    )
    op.create_index(
        "ix_token_enrichment_state_mint_address",
        "token_enrichment_state",
        ["mint_address"],
        unique=True,
    )
    # The claim query: WHERE status='active' AND next_refresh_at <= now()
    # ORDER BY next_refresh_at.
    op.create_index(
        "ix_enrichment_due", "token_enrichment_state", ["status", "next_refresh_at"]
    )
    op.create_index(
        "ix_token_enrichment_state_created_at", "token_enrichment_state", ["created_at"]
    )


def downgrade() -> None:
    op.drop_table("token_enrichment_state")
    op.drop_table("token_market_snapshots")
    op.execute("DROP TYPE IF EXISTS enrichment_status")
    op.execute("DROP TYPE IF EXISTS trading_status")
