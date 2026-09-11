"""NSE Breakout Tracker: five new `bt_*` tables. Nothing existing is touched.

Purely additive: no ALTER, no DROP, no index on an existing table. A database
that runs this migration and never enables `NSE_BREAKOUT_ENABLED` is
byte-identical in every table that existed before it, and a test asserts that.

Parented to 0066_breakout_trader, main's head when this landed.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0067_nse_breakout"
down_revision: str = "0066_breakout_trader"
branch_labels = None
depends_on = None

_SYMBOL = sa.String(32)
#: Indian equities run from a few rupees to ~1,50,000 (MRF); four decimals is
#: finer than the exchange quotes.
_PRICE = sa.Numeric(18, 4)
_INR = sa.Numeric(24, 2)


def upgrade() -> None:
    op.create_table(
        "bt_universe",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("symbol", _SYMBOL, nullable=False),
        sa.Column("name", sa.String(128), nullable=True),
        sa.Column("isin", sa.String(16), nullable=True),
        sa.Column("series", sa.String(4), nullable=False),
        sa.Column("last_close", _PRICE, nullable=True),
        sa.Column("turnover_20d", _INR, nullable=True),
        sa.Column("bars", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("first_seen", sa.Date(), nullable=False),
        sa.Column("last_seen", sa.Date(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("inactive_reason", sa.String(16), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("symbol", name="uq_bt_universe_symbol"),
    )
    op.create_index("ix_bt_universe_active_turnover", "bt_universe",
                    ["active", "turnover_20d"])

    op.create_table(
        "bt_candles",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("symbol", _SYMBOL, nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("open", _PRICE, nullable=False),
        sa.Column("high", _PRICE, nullable=False),
        sa.Column("low", _PRICE, nullable=False),
        sa.Column("close", _PRICE, nullable=False),
        sa.Column("volume", sa.Numeric(20, 0), nullable=False),
        sa.Column("turnover", _INR, nullable=True),
        sa.Column("adjusted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("suspect_gap", sa.Boolean(), nullable=False,
                  server_default=sa.false()),
        sa.PrimaryKeyConstraint("id"),
        # What makes ingest idempotent: a re-ingested day is the same rows.
        sa.UniqueConstraint("symbol", "date", name="uq_bt_candles_symbol_date"),
    )
    op.create_index("ix_bt_candles_date", "bt_candles", ["date"])

    op.create_table(
        "bt_index_closes",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("index_name", sa.String(32), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("close", _PRICE, nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("index_name", "date", name="uq_bt_index_closes_name_date"),
    )

    op.create_table(
        "bt_ingest_days",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(8), nullable=False),
        sa.Column("rows", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("symbols", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("failures", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("date", name="uq_bt_ingest_days_date"),
    )

    op.create_table(
        "bt_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("phase", sa.String(16), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("days", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("rows", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("symbols", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("detail", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("errors", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_bt_runs_started_at", "bt_runs", ["started_at"])


def downgrade() -> None:
    op.drop_index("ix_bt_runs_started_at", table_name="bt_runs")
    op.drop_table("bt_runs")
    op.drop_table("bt_ingest_days")
    op.drop_table("bt_index_closes")
    op.drop_index("ix_bt_candles_date", table_name="bt_candles")
    op.drop_table("bt_candles")
    op.drop_index("ix_bt_universe_active_turnover", table_name="bt_universe")
    op.drop_table("bt_universe")
