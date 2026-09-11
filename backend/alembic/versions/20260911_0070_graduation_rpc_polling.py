"""Graduation Lab off the metered trade stream and onto RPC polling.

Two new tables, and additive columns on three existing `grad_*` tables. **No
table outside this lab is touched**, and a database that runs this and never
sets `LAB_GRADUATION_ENABLED` is unchanged in every table that is not `grad_*`.

## Why the renames

`peak_market_cap_sol` and `market_cap_sol` become `..._quote`. A
USDC-denominated curve holds USDC in the reserve the SOL field normally
carries, so a column named `_sol` holding USDC is a silent unit error waiting
for whoever queries it. `grad_tokens.quote_currency` says which it is. Renamed
rather than dropped-and-added so anything already collected survives.

## What is NOT dropped

`grad_trades` stays, and stays empty. Per-trade detail came from PumpPortal's
`subscribeTokenTrade`, which is metered at 0.01 SOL per 10,000 events; the
chain reports curve state for the price of an RPC call, so the stream is gone.
A Phase 2 backfill may fill this table for GRADUATES ONLY — a few hundred
tokens a day rather than the ~36,000 that launch — and keeping the table means
that work needs no migration.

The trade-derived columns on `grad_tokens` and `grad_checkpoints`
(`buy_count`, `unique_buyers`, `top10_holder_share` and the rest) stay for the
same reason. A reader must treat 0 and null there as "not collected", never as
"none": the account reports reserves, not who moved them, so a poller cannot
count buyers at any price.

Parented to 0069.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# 32 characters at most: alembic_version.version_num is varchar(32).
revision: str = "0070_graduation_rpc"
down_revision: str = "0069_graduation_lab"
branch_labels = None
depends_on = None

_ADDRESS = sa.String(64)
_QUOTE = sa.Numeric(30, 9)
_TOKENS = sa.Numeric(38, 9)
_PCT = sa.Numeric(6, 3)
_USD = sa.Numeric(24, 8)
_USD2 = sa.Numeric(24, 2)


def upgrade() -> None:
    # --- grad_tokens: what the poller knows ---------------------------------
    op.add_column("grad_tokens", sa.Column("curve_address", _ADDRESS, nullable=True))
    op.add_column("grad_tokens", sa.Column(
        "quote_currency", sa.String(8), nullable=False,
        server_default=sa.text("'SOL'")))
    op.add_column("grad_tokens", sa.Column("last_progress_pct", _PCT, nullable=True))
    op.add_column("grad_tokens", sa.Column(
        "last_progress_change_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("grad_tokens", sa.Column(
        "first_sample_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("grad_tokens", sa.Column(
        "last_sample_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("grad_tokens", sa.Column(
        "sample_count", sa.Integer(), nullable=False, server_default=sa.text("0")))
    op.alter_column("grad_tokens", "peak_market_cap_sol",
                    new_column_name="peak_market_cap_quote")

    # --- grad_checkpoints: the quote side, both reserves ---------------------
    op.add_column("grad_checkpoints", sa.Column(
        "real_quote_reserves", _QUOTE, nullable=True))
    op.alter_column("grad_checkpoints", "market_cap_sol",
                    new_column_name="market_cap_quote")

    # --- grad_migrations: which signal arrived first -------------------------
    op.add_column("grad_migrations", sa.Column(
        "seen_complete_on_chain", sa.Boolean(), nullable=False,
        server_default=sa.false()))

    # --- the curve series ----------------------------------------------------
    op.create_table(
        "grad_curve_samples",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("mint", _ADDRESS, nullable=False),
        sa.Column("v_token_reserves", _TOKENS, nullable=True),
        sa.Column("real_token_reserves", _TOKENS, nullable=True),
        sa.Column("v_quote_reserves", _QUOTE, nullable=True),
        sa.Column("real_quote_reserves", _QUOTE, nullable=True),
        sa.Column("quote_currency", sa.String(8), nullable=True),
        sa.Column("token_total_supply", _TOKENS, nullable=True),
        sa.Column("progress_pct", _PCT, nullable=True),
        sa.Column("complete", sa.Boolean(), nullable=False,
                  server_default=sa.false()),
        sa.Column("market_cap_quote", _QUOTE, nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_grad_curve_samples"),
        # One reading per mint per poll. Dedupes a retried flush; a poll that
        # landed in the same instant is the same reading either way.
        sa.UniqueConstraint("mint", "ts", name="uq_grad_curve_samples_mint_ts"),
    )
    op.create_index("ix_grad_curve_samples_ts", "grad_curve_samples", ["ts"])
    op.create_index("ix_grad_curve_samples_mint_ts", "grad_curve_samples",
                    ["mint", "ts"])

    # --- the hour after graduation -------------------------------------------
    op.create_table(
        "grad_postgrad_samples",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("mint", _ADDRESS, nullable=False),
        # `dexscreener` (a live poll) or `geckoterminal` (a backfilled candle).
        # Not the same measurement, and must never be averaged without knowing
        # which is which.
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("pair_address", _ADDRESS, nullable=True),
        sa.Column("dex_id", sa.String(32), nullable=True),
        sa.Column("price_usd", _USD, nullable=True),
        sa.Column("price_native", _USD, nullable=True),
        sa.Column("liquidity_usd", _USD2, nullable=True),
        sa.Column("fdv", _USD2, nullable=True),
        sa.Column("volume_m5_usd", _USD2, nullable=True),
        sa.Column("volume_h1_usd", _USD2, nullable=True),
        sa.Column("volume_m1_usd", _USD2, nullable=True),
        sa.Column("txns_m5_buys", sa.Integer(), nullable=True),
        sa.Column("txns_m5_sells", sa.Integer(), nullable=True),
        sa.Column("txns_h1_buys", sa.Integer(), nullable=True),
        sa.Column("txns_h1_sells", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_grad_postgrad_samples"),
        sa.UniqueConstraint("mint", "ts", name="uq_grad_postgrad_samples_mint_ts"),
    )
    op.create_index("ix_grad_postgrad_samples_ts", "grad_postgrad_samples", ["ts"])
    op.create_index("ix_grad_postgrad_samples_mint_ts", "grad_postgrad_samples",
                    ["mint", "ts"])


def downgrade() -> None:
    op.drop_table("grad_postgrad_samples")
    op.drop_table("grad_curve_samples")
    op.drop_column("grad_migrations", "seen_complete_on_chain")
    op.alter_column("grad_checkpoints", "market_cap_quote",
                    new_column_name="market_cap_sol")
    op.drop_column("grad_checkpoints", "real_quote_reserves")
    op.alter_column("grad_tokens", "peak_market_cap_quote",
                    new_column_name="peak_market_cap_sol")
    for column in ("sample_count", "last_sample_at", "first_sample_at",
                   "last_progress_change_at", "last_progress_pct",
                   "quote_currency", "curve_address"):
        op.drop_column("grad_tokens", column)
