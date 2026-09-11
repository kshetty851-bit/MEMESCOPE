"""Breakout Lab: three new `bo_*` tables. Nothing existing is touched.

Purely additive: no ALTER, no DROP, no index on an existing table. A database
that runs this migration and never enables `BREAKOUT_LAB_ENABLED` is
byte-identical in every table that existed before it, and a test asserts that.

Two shapes are worth a note:

* **Prices carry 18 decimals.** Solana tokens are quoted far below a cent —
  a memecoin at 6.3e-9 is ordinary — and `Numeric(24, 8)` would round that to
  zero. USD aggregates keep 2.
* **`bo_universe.holders` is created and never filled in Phase 1.** Neither
  GeckoTerminal's public pool payload nor DexScreener's pair payload carries a
  holder count, and the brief asks for it "if available". The column exists so
  a later phase with a holder source needs no migration.

Parented to 0063_rafiq_lab, main's head when this landed.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# 32 characters at most: alembic_version.version_num is varchar(32).
revision: str = "0064_breakout_lab"
down_revision: str = "0063_rafiq_lab"
branch_labels = None
depends_on = None

_ADDRESS = sa.String(64)
#: 18 decimals: see the module docstring.
_PRICE = sa.Numeric(36, 18)
_USD = sa.Numeric(24, 2)


def upgrade() -> None:
    op.create_table(
        "bo_universe",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("mint", _ADDRESS, nullable=False),
        sa.Column("symbol", sa.String(32), nullable=True),
        sa.Column("name", sa.String(128), nullable=True),
        sa.Column("pool_address", _ADDRESS, nullable=False),
        sa.Column("dex", sa.String(32), nullable=False),
        sa.Column("pair_created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("liquidity_usd", _USD, nullable=True),
        sa.Column("volume_24h_usd", _USD, nullable=True),
        sa.Column("price_usd", _PRICE, nullable=True),
        sa.Column("fdv", _USD, nullable=True),
        # Always NULL in Phase 1; see the module docstring.
        sa.Column("holders", sa.Integer(), nullable=True),
        sa.Column("alt_pools", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("first_seen", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("inactive_reason", sa.String(32), nullable=True),
        sa.Column("fetch_failures", sa.Integer(), nullable=False,
                  server_default=sa.text("0")),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("mint", name="uq_bo_universe_mint"),
    )
    # The candle queue's order: active tokens by 24h volume, descending.
    op.create_index("ix_bo_universe_active_volume", "bo_universe",
                    ["active", "volume_24h_usd"])

    op.create_table(
        "bo_candles",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("mint", _ADDRESS, nullable=False),
        sa.Column("pool_address", _ADDRESS, nullable=False),
        sa.Column("timeframe", sa.String(8), nullable=False),
        sa.Column("open_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("open", _PRICE, nullable=False),
        sa.Column("high", _PRICE, nullable=False),
        sa.Column("low", _PRICE, nullable=False),
        sa.Column("close", _PRICE, nullable=False),
        sa.Column("volume_usd", _USD, nullable=True),
        sa.Column("close_time", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        # What makes the poll idempotent: the same bar upserted twice is one row.
        sa.UniqueConstraint("mint", "timeframe", "open_time",
                            name="uq_bo_candles_mint_timeframe_open_time"),
    )

    op.create_table(
        "bo_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("phase", sa.String(16), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("universe_size", sa.Integer(), nullable=False,
                  server_default=sa.text("0")),
        sa.Column("added", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("dropped", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("candles_upserted", sa.Integer(), nullable=False,
                  server_default=sa.text("0")),
        sa.Column("tokens_refreshed", sa.Integer(), nullable=False,
                  server_default=sa.text("0")),
        sa.Column("tokens_carried", sa.Integer(), nullable=False,
                  server_default=sa.text("0")),
        sa.Column("requests", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("errors", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_bo_runs_started_at", "bo_runs", ["started_at"])


def downgrade() -> None:
    op.drop_index("ix_bo_runs_started_at", table_name="bo_runs")
    op.drop_table("bo_runs")
    op.drop_table("bo_candles")
    op.drop_index("ix_bo_universe_active_volume", table_name="bo_universe")
    op.drop_table("bo_universe")
