"""Forex Lab: `fx_candles`, `fx_ingest_hours` and `fx_sweep_runs`.

Purely additive — three new tables, no ALTER and no index on anything that
already existed. A database that runs this and never sets
`FOREX_LAB_ENABLED` is byte-identical in every table that existed before
it.

`fx_candles` is keyed on (symbol, minute) rather than a surrogate id because
the key IS the idempotency: re-running an hour-file upserts the same minutes
instead of duplicating them, which is the whole of what makes the loader safe
to re-run against a partially loaded window.

`fx_ingest_hours` carries the loader's resume state. `ok=false` is a file that
failed every retry, and the next pass asks for exactly those; `empty=true` is
an hour the feed genuinely has no ticks for and is never asked for again.

Parented to 0084 on `main`. The same lab was first written on `karthik-hq`,
where its migration is 0069 — but that branch is 264 commits behind main and
the two number the same slots differently: main's 0068 is `nse_breakout_phase2`
and its 0069 is `graduation_lab`. A migration parented to karthik-hq's
`0068_graduation_features` cannot run on a database that has never seen it,
which is to say it cannot run on production. This is the deployable one.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# 32 characters at most: alembic_version.version_num is varchar(32).
revision: str = "0085_forex_lab"
down_revision: str = "0084_v6_fast_accum"
branch_labels = None
depends_on = None

#: Dukascopy quotes EUR/USD to five decimals. 12/6 leaves a spare digit
#: without ever losing a point of an FX quote.
_PRICE = sa.Numeric(12, 6)


def upgrade() -> None:
    op.create_table(
        "fx_candles",
        sa.Column("symbol", sa.String(16), nullable=False),
        sa.Column("minute", sa.DateTime(timezone=True), nullable=False),
        sa.Column("bid_open", _PRICE, nullable=False),
        sa.Column("bid_high", _PRICE, nullable=False),
        sa.Column("bid_low", _PRICE, nullable=False),
        sa.Column("bid_close", _PRICE, nullable=False),
        sa.Column("ask_open", _PRICE, nullable=False),
        sa.Column("ask_high", _PRICE, nullable=False),
        sa.Column("ask_low", _PRICE, nullable=False),
        sa.Column("ask_close", _PRICE, nullable=False),
        # Ticks observed in the minute. Never zero: a minute with no tick has
        # no row, and that absence is what the gap check reads.
        sa.Column("ticks", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("symbol", "minute", name="pk_fx_candles"),
    )
    op.create_index("ix_fx_candles_minute", "fx_candles", ["minute"])

    op.create_table(
        "fx_ingest_hours",
        sa.Column("symbol", sa.String(16), nullable=False),
        sa.Column("hour_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ok", sa.Boolean(), nullable=False),
        sa.Column("empty", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("tick_count", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("candle_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("error", sa.String(256), nullable=True),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("symbol", "hour_start", name="pk_fx_ingest_hours"),
    )
    # The resume query is "which hours are not ok", so that is the index.
    op.create_index("ix_fx_ingest_hours_ok", "fx_ingest_hours", ["symbol", "ok"])

    # One row per parameter sweep, and the only table the dashboard reads. The
    # whole sweep is one JSONB document because it is only ever read as one:
    # twenty-seven configurations, their per-year P&L and the baselines are a
    # single answer to a single question.
    op.create_table(
        "fx_sweep_runs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("symbol", sa.String(16), nullable=False),
        sa.Column("first_minute", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_minute", sa.DateTime(timezone=True), nullable=False),
        sa.Column("candles", sa.BigInteger(), nullable=False),
        sa.Column("git_sha", sa.String(40), nullable=True),
        sa.Column("best_config", sa.String(32), nullable=False),
        sa.Column(
            "gate_passed", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column("result", postgresql.JSONB(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_fx_sweep_runs"),
    )
    op.create_index("ix_fx_sweep_runs_created", "fx_sweep_runs", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_fx_sweep_runs_created", table_name="fx_sweep_runs")
    op.drop_table("fx_sweep_runs")
    op.drop_index("ix_fx_ingest_hours_ok", table_name="fx_ingest_hours")
    op.drop_table("fx_ingest_hours")
    op.drop_index("ix_fx_candles_minute", table_name="fx_candles")
    op.drop_table("fx_candles")
