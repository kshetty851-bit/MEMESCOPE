"""Meme Lifecycle Lab: ten `mll_*` tables, and a general candle table.

See docs/MEME_LIFECYCLE_LAB.md. Additive apart from the candle rename: no
existing table the pipeline reads or writes is touched.

**`token_market_candles_1h` becomes `token_market_candles`.** Created in 0038
and never read or written since, so the rename moves no data anybody depends
on. Its key widens from `(mint_address, bucket)` to `(mint_address,
resolution_s, source, bucket)`: a 1-minute GeckoTerminal bar and a derived
hourly bar for the same mint and bucket are different facts. The new columns'
defaults (`3600`, `'derived'`, `'forward'`) give any existing row exactly the
meaning it had.

**Enumerations are strings, not native enums** — see `app/models/lifecycle_lab.py`.

**`uq_mll_meme_events_identity` is an expression index** over
`coalesce(mint_address, '')`, so a meme-level event (mint NULL) dedupes too.
Alembic does not compare expression indexes, so `alembic check` cannot catch
drift between this text and the model's: edit both together.

Downgrade drops the Lab's tables and restores the candle table's original name
and key. Bars that only the wider key could hold (any resolution or source
other than the hourly derived one) are deleted first — the old key cannot
represent them, and the Lab that wrote them is gone with the downgrade.

Revision ID: 0112_meme_lifecycle_lab
Revises: 0111_operator_blocked_reason
Create Date: 2026-10-03
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0112_meme_lifecycle_lab"
down_revision: str | None = "0111_operator_blocked_reason"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_USD = sa.Numeric(precision=24, scale=4)
_PRICE = sa.Numeric(precision=38, scale=18)
_VALUE = sa.Numeric(precision=38, scale=8)
_CONFIDENCE = sa.Numeric(precision=5, scale=4)
_TS = sa.DateTime(timezone=True)


def _id() -> sa.Column:
    return sa.Column(
        "id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
    )


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", _TS, server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", _TS, server_default=sa.text("now()"), nullable=False),
    ]


def _created_at_index(table: str) -> None:
    # TimestampMixin declares `index=True`; without this `alembic check` fails.
    op.create_index(f"ix_{table}_created_at", table, ["created_at"], unique=False)


def _meme_fk(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["meme_id"],
        ["mll_memes.id"],
        name=f"fk_{table}_meme_id_mll_memes",
        ondelete="CASCADE",
    )


def upgrade() -> None:
    # --- candles -------------------------------------------------------------
    op.rename_table("token_market_candles_1h", "token_market_candles")
    op.drop_constraint("pk_token_market_candles_1h", "token_market_candles", type_="primary")
    op.drop_index("ix_candles_1h_mint_bucket_desc", table_name="token_market_candles")
    op.add_column(
        "token_market_candles",
        sa.Column("resolution_s", sa.Integer(), server_default="3600", nullable=False),
    )
    op.add_column(
        "token_market_candles",
        sa.Column("source", sa.String(length=32), server_default="derived", nullable=False),
    )
    op.add_column(
        "token_market_candles",
        sa.Column(
            "data_class", sa.String(length=16), server_default="forward", nullable=False
        ),
    )
    op.add_column("token_market_candles", sa.Column("retrieved_at", _TS, nullable=True))
    op.create_primary_key(
        "pk_token_market_candles",
        "token_market_candles",
        ["mint_address", "resolution_s", "source", "bucket"],
    )
    op.create_index(
        "ix_token_market_candles_mint_bucket_desc",
        "token_market_candles",
        ["mint_address", sa.text("bucket DESC")],
        unique=False,
    )

    # --- identity ------------------------------------------------------------
    op.create_table(
        "mll_memes",
        _id(),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), server_default="tracked", nullable=False),
        sa.Column("tracking_started_at", _TS, nullable=False),
        sa.Column("wikipedia_title", sa.String(length=300), nullable=True),
        sa.Column("gdelt_query", sa.String(length=500), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_mll_memes"),
        sa.UniqueConstraint("slug", name="uq_mll_memes_slug"),
    )
    _created_at_index("mll_memes")

    op.create_table(
        "mll_meme_aliases",
        _id(),
        sa.Column("meme_id", sa.UUID(), nullable=False),
        sa.Column("alias", sa.String(length=200), nullable=False),
        sa.Column("alias_normalized", sa.String(length=200), nullable=False),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("added_at", _TS, nullable=False),
        *_timestamps(),
        _meme_fk("mll_meme_aliases"),
        sa.PrimaryKeyConstraint("id", name="pk_mll_meme_aliases"),
        sa.UniqueConstraint(
            "meme_id", "alias_normalized", "kind", name="uq_mll_meme_aliases_identity"
        ),
    )
    _created_at_index("mll_meme_aliases")

    op.create_table(
        "mll_meme_tokens",
        _id(),
        sa.Column("meme_id", sa.UUID(), nullable=False),
        sa.Column("mint_address", sa.String(length=64), nullable=False),
        sa.Column("method", sa.String(length=32), nullable=False),
        sa.Column("confidence", _CONFIDENCE, nullable=False),
        sa.Column("linked_at", _TS, nullable=False),
        sa.Column("unlinked_at", _TS, nullable=True),
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("linked_by", sa.String(length=128), nullable=False),
        *_timestamps(),
        _meme_fk("mll_meme_tokens"),
        sa.PrimaryKeyConstraint("id", name="pk_mll_meme_tokens"),
        sa.UniqueConstraint("meme_id", "mint_address", name="uq_mll_meme_tokens_meme_mint"),
    )
    _created_at_index("mll_meme_tokens")
    op.create_index("ix_mll_meme_tokens_mint", "mll_meme_tokens", ["mint_address"])

    # --- collection ----------------------------------------------------------
    op.create_table(
        "mll_collection_runs",
        _id(),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=True),
        sa.Column("data_class", sa.String(length=16), nullable=False),
        sa.Column("started_at", _TS, nullable=False),
        sa.Column("finished_at", _TS, nullable=False),
        sa.Column("meme_id", sa.UUID(), nullable=True),
        sa.Column("mint_address", sa.String(length=64), nullable=True),
        sa.Column("observations_written", sa.Integer(), server_default="0", nullable=False),
        sa.Column("detail", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        _meme_fk("mll_collection_runs"),
        sa.PrimaryKeyConstraint("id", name="pk_mll_collection_runs"),
    )
    op.create_index(
        "ix_mll_collection_runs_source_finished",
        "mll_collection_runs",
        ["source", sa.text("finished_at DESC")],
    )
    op.create_index(
        "ix_mll_collection_runs_meme_source_finished",
        "mll_collection_runs",
        ["meme_id", "source", "finished_at"],
    )

    op.create_table(
        "mll_attention_observations",
        _id(),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("metric", sa.String(length=32), nullable=False),
        sa.Column("value_kind", sa.String(length=16), nullable=False),
        sa.Column("data_class", sa.String(length=16), nullable=False),
        sa.Column("source_timestamp", _TS, nullable=False),
        sa.Column("observed_at", _TS, nullable=False),
        sa.Column("retrieved_at", _TS, nullable=False),
        sa.Column("raw_value", _VALUE, nullable=False),
        sa.Column("normalized_value", _VALUE, nullable=True),
        sa.Column("meme_id", sa.UUID(), nullable=True),
        sa.Column("mint_address", sa.String(length=64), nullable=True),
        sa.Column("window_start", _TS, nullable=True),
        sa.Column("window_end", _TS, nullable=True),
        sa.Column("query", sa.String(length=500), nullable=True),
        sa.Column("source_url", sa.String(length=2048), nullable=True),
        sa.Column("confidence", _CONFIDENCE, server_default="1", nullable=False),
        sa.Column("raw_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("collection_run_id", sa.UUID(), nullable=True),
        sa.Column("dedupe_key", sa.String(length=64), nullable=False),
        _meme_fk("mll_attention_observations"),
        sa.ForeignKeyConstraint(
            ["collection_run_id"],
            ["mll_collection_runs.id"],
            name="fk_mll_obs_collection_run_id",
            ondelete="SET NULL",
            # The collector writes observations before their run row.
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_mll_attention_observations"),
        sa.UniqueConstraint("dedupe_key", name="uq_mll_attention_observations_dedupe_key"),
    )
    op.create_index(
        "ix_mll_obs_meme_retrieved", "mll_attention_observations", ["meme_id", "retrieved_at"]
    )
    op.create_index(
        "ix_mll_obs_mint_retrieved",
        "mll_attention_observations",
        ["mint_address", "retrieved_at"],
    )
    op.create_index(
        "ix_mll_obs_source_observed", "mll_attention_observations", ["source", "observed_at"]
    )

    # --- research ------------------------------------------------------------
    op.create_table(
        "mll_experiments",
        _id(),
        sa.Column("experiment_key", sa.String(length=128), nullable=False),
        sa.Column("hypothesis", sa.Text(), nullable=False),
        sa.Column("data_cutoff", _TS, nullable=True),
        sa.Column("train_start", _TS, nullable=True),
        sa.Column("train_end", _TS, nullable=True),
        sa.Column("validation_start", _TS, nullable=True),
        sa.Column("validation_end", _TS, nullable=True),
        sa.Column("test_start", _TS, nullable=True),
        sa.Column("test_end", _TS, nullable=True),
        sa.Column("strategy_spec", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("spec_hash", sa.String(length=64), nullable=False),
        sa.Column("mode", sa.String(length=16), nullable=False),
        sa.Column("arm", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("split_meaningful", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("split_note", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_mll_experiments"),
        sa.UniqueConstraint("experiment_key", name="uq_mll_experiments_experiment_key"),
    )
    _created_at_index("mll_experiments")
    op.create_index("ix_mll_experiments_spec_hash", "mll_experiments", ["spec_hash"])

    op.create_table(
        "mll_backtest_runs",
        _id(),
        sa.Column("experiment_id", sa.UUID(), nullable=False),
        sa.Column("mode", sa.String(length=16), nullable=False),
        sa.Column("segment", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("started_at", _TS, nullable=False),
        sa.Column("finished_at", _TS, nullable=True),
        sa.Column("window_start", _TS, nullable=False),
        sa.Column("window_end", _TS, nullable=False),
        sa.Column("config_spec", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("input_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("trades_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("ending_equity", _USD, nullable=True),
        sa.Column("summary", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("contains_backfill", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("hindsight_links", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["experiment_id"],
            ["mll_experiments.id"],
            name="fk_mll_backtest_runs_experiment_id_mll_experiments",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_mll_backtest_runs"),
    )
    _created_at_index("mll_backtest_runs")
    op.create_index(
        "ix_mll_backtest_runs_experiment_started",
        "mll_backtest_runs",
        ["experiment_id", "started_at"],
    )
    op.create_index(
        "ix_mll_backtest_runs_mode_finished", "mll_backtest_runs", ["mode", "finished_at"]
    )

    op.create_table(
        "mll_meme_events",
        _id(),
        sa.Column("meme_id", sa.UUID(), nullable=False),
        sa.Column("event_type", sa.String(length=48), nullable=False),
        sa.Column("detected_at", _TS, nullable=False),
        sa.Column("mode", sa.String(length=16), nullable=False),
        sa.Column("detector_version", sa.String(length=48), nullable=False),
        sa.Column("mint_address", sa.String(length=64), nullable=True),
        sa.Column("divergence_case", sa.String(length=8), nullable=True),
        sa.Column("lifecycle_state", sa.String(length=24), nullable=True),
        sa.Column("features", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("contains_backfill", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("source_run_id", sa.UUID(), nullable=True),
        sa.Column("price_before_detection", _PRICE, nullable=True),
        sa.Column("price_at_detection", _PRICE, nullable=True),
        sa.Column("return_5m", _VALUE, nullable=True),
        sa.Column("return_15m", _VALUE, nullable=True),
        sa.Column("return_30m", _VALUE, nullable=True),
        sa.Column("return_1h", _VALUE, nullable=True),
        sa.Column("return_2h", _VALUE, nullable=True),
        sa.Column("return_6h", _VALUE, nullable=True),
        sa.Column("return_24h", _VALUE, nullable=True),
        sa.Column("run_up_before_detection", _VALUE, nullable=True),
        sa.Column("outcome_reasons", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("outcomes_complete_at", _TS, nullable=True),
        *_timestamps(),
        _meme_fk("mll_meme_events"),
        sa.ForeignKeyConstraint(
            ["source_run_id"],
            ["mll_backtest_runs.id"],
            name="fk_mll_meme_events_source_run_id_mll_backtest_runs",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_mll_meme_events"),
    )
    _created_at_index("mll_meme_events")
    # Same text as the model's Index — alembic does not compare expressions.
    op.create_index(
        "uq_mll_meme_events_identity",
        "mll_meme_events",
        [
            "meme_id",
            "event_type",
            "detected_at",
            "detector_version",
            "mode",
            sa.text("coalesce(mint_address, '')"),
        ],
        unique=True,
    )
    op.create_index(
        "ix_mll_meme_events_meme_detected", "mll_meme_events", ["meme_id", "detected_at"]
    )

    op.create_table(
        "mll_paper_trades",
        _id(),
        sa.Column("backtest_run_id", sa.UUID(), nullable=False),
        sa.Column("trade_key", sa.String(length=128), nullable=False),
        sa.Column("arm", sa.String(length=64), nullable=False),
        sa.Column("meme_id", sa.UUID(), nullable=False),
        sa.Column("mint_address", sa.String(length=64), nullable=False),
        sa.Column("entry_at", _TS, nullable=False),
        sa.Column("entry_price", _PRICE, nullable=False),
        sa.Column("size_usd", _USD, nullable=False),
        sa.Column("quantity", _PRICE, nullable=False),
        sa.Column("entry_fees_usd", _USD, nullable=False),
        sa.Column("entry_market_cap", _USD, nullable=True),
        sa.Column("entry_liquidity_usd", _USD, nullable=True),
        sa.Column("token_age_seconds", sa.BigInteger(), nullable=True),
        sa.Column("age_bucket", sa.String(length=16), nullable=False),
        sa.Column("lifecycle_state", sa.String(length=24), nullable=True),
        sa.Column("divergence_case", sa.String(length=8), nullable=True),
        sa.Column("entry_reason", sa.Text(), nullable=False),
        sa.Column("entry_features", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "evidence_timeline", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("cost_model", sa.String(length=16), nullable=False),
        sa.Column("exit_at", _TS, nullable=True),
        sa.Column("exit_price", _PRICE, nullable=True),
        sa.Column("exit_reason", sa.String(length=32), nullable=True),
        sa.Column("exit_fees_usd", _USD, nullable=True),
        sa.Column("pnl_usd", _USD, nullable=True),
        sa.Column("return_pct", _VALUE, nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("contains_backfill", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("hindsight", sa.Boolean(), server_default="false", nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["backtest_run_id"],
            ["mll_backtest_runs.id"],
            name="fk_mll_paper_trades_backtest_run_id_mll_backtest_runs",
            ondelete="CASCADE",
        ),
        _meme_fk("mll_paper_trades"),
        sa.PrimaryKeyConstraint("id", name="pk_mll_paper_trades"),
        sa.UniqueConstraint(
            "backtest_run_id", "mint_address", "entry_at", name="uq_mll_paper_trades_entry"
        ),
    )
    _created_at_index("mll_paper_trades")
    op.create_index(
        "ix_mll_paper_trades_meme_entry", "mll_paper_trades", ["meme_id", "entry_at"]
    )

    op.create_table(
        "mll_portfolio_snapshots",
        _id(),
        sa.Column("backtest_run_id", sa.UUID(), nullable=False),
        sa.Column("at", _TS, nullable=False),
        sa.Column("equity", _USD, nullable=True),
        sa.Column("cash", _USD, nullable=False),
        sa.Column("deployed", _USD, nullable=False),
        sa.Column("realized_pnl", _USD, nullable=False),
        sa.Column("unrealized_pnl", _USD, nullable=True),
        sa.Column("open_positions", sa.Integer(), nullable=False),
        sa.Column("peak_equity", _USD, nullable=True),
        sa.Column("drawdown", sa.Numeric(precision=10, scale=6), nullable=True),
        sa.ForeignKeyConstraint(
            ["backtest_run_id"],
            ["mll_backtest_runs.id"],
            name="fk_mll_portfolio_snapshots_backtest_run_id_mll_backtest_runs",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_mll_portfolio_snapshots"),
        sa.UniqueConstraint("backtest_run_id", "at", name="uq_mll_portfolio_snapshots_run_at"),
    )


def downgrade() -> None:
    # Children first: every FK below points up this list.
    for table in (
        "mll_portfolio_snapshots",
        "mll_paper_trades",
        "mll_meme_events",
        "mll_backtest_runs",
        "mll_experiments",
        "mll_attention_observations",
        "mll_collection_runs",
        "mll_meme_tokens",
        "mll_meme_aliases",
        "mll_memes",
    ):
        op.drop_table(table)

    # Bars the old (mint_address, bucket) key cannot hold would make the
    # primary key below fail on duplicates. Only the Lab wrote them.
    op.execute(
        "DELETE FROM token_market_candles WHERE resolution_s <> 3600 OR source <> 'derived'"
    )
    op.drop_index(
        "ix_token_market_candles_mint_bucket_desc", table_name="token_market_candles"
    )
    op.drop_constraint("pk_token_market_candles", "token_market_candles", type_="primary")
    op.drop_column("token_market_candles", "retrieved_at")
    op.drop_column("token_market_candles", "data_class")
    op.drop_column("token_market_candles", "source")
    op.drop_column("token_market_candles", "resolution_s")
    op.rename_table("token_market_candles", "token_market_candles_1h")
    op.create_primary_key(
        "pk_token_market_candles_1h", "token_market_candles_1h", ["mint_address", "bucket"]
    )
    op.create_index(
        "ix_candles_1h_mint_bucket_desc",
        "token_market_candles_1h",
        ["mint_address", sa.text("bucket DESC")],
        unique=False,
    )
