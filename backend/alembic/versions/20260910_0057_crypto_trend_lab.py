"""Crypto Trend Lab: four new `ct_*` tables. Nothing existing is touched.

Purely additive: no ALTER, no DROP, no index on an existing table. A database
that runs this migration and never enables `CRYPTO_TREND_LAB_ENABLED` is
byte-identical in every table that existed before it, and a test asserts
exactly that.

Parented to 0056 on `karthik-hq`. On `main` the same lab migration would need
renumbering and re-parenting, as the Rafiq lab's 0056 became 0063 there.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0057_crypto_trend_lab"
down_revision: str = "0056_rafiq_lab"
branch_labels = None
depends_on = None

_PRICE = sa.Numeric(24, 8)
_VOLUME = sa.Numeric(30, 8)


def _uuid_pk() -> sa.Column:
    return sa.Column("id", postgresql.UUID(as_uuid=True),
                     server_default=sa.text("gen_random_uuid()"), nullable=False)


def upgrade() -> None:
    op.create_table(
        "ct_universe",
        _uuid_pk(),
        sa.Column("coingecko_id", sa.String(64), nullable=False),
        sa.Column("ticker", sa.String(16), nullable=False),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("binance_symbol", sa.String(24), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("market_cap_rank", sa.Integer(), nullable=True),
        sa.Column("market_cap_usd", sa.Numeric(24, 2), nullable=True),
        sa.Column("added_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("refreshed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("coingecko_id", name="uq_ct_universe_coingecko_id"),
    )

    op.create_table(
        "ct_candles",
        _uuid_pk(),
        sa.Column("symbol", sa.String(24), nullable=False),
        sa.Column("timeframe", sa.String(4), nullable=False),
        sa.Column("open_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("open", _PRICE, nullable=False),
        sa.Column("high", _PRICE, nullable=False),
        sa.Column("low", _PRICE, nullable=False),
        sa.Column("close", _PRICE, nullable=False),
        sa.Column("volume", _VOLUME, nullable=False),
        sa.Column("close_time", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("symbol", "timeframe", "open_time",
                            name="uq_ct_candles_symbol_timeframe_open_time"),
    )

    op.create_table(
        "ct_funding",
        _uuid_pk(),
        sa.Column("symbol", sa.String(24), nullable=False),
        sa.Column("funding_rate", sa.Numeric(12, 8), nullable=False),
        sa.Column("mark_price", _PRICE, nullable=True),
        sa.Column("next_funding_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("symbol", "next_funding_time",
                            name="uq_ct_funding_symbol_next_funding_time"),
    )

    op.create_table(
        "ct_runs",
        _uuid_pk(),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("universe_refreshed", sa.Boolean(), nullable=False,
                  server_default=sa.false()),
        sa.Column("candles_upserted", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("funding_upserted", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("requests", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("skipped", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("errors", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ct_runs_started_at", "ct_runs", ["started_at"])


def downgrade() -> None:
    op.drop_index("ix_ct_runs_started_at", table_name="ct_runs")
    op.drop_table("ct_runs")
    op.drop_table("ct_funding")
    op.drop_table("ct_candles")
    op.drop_table("ct_universe")
