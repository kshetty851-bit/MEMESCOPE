"""Strategy Lab: seven new tables, and nothing else.

**Purely additive.** No existing table is altered, no existing column is
dropped, no existing row is read or written. Paper Wallet V1, Paper Wallet V2,
Real Wallet, Radar, Nursery and Track Record all keep exactly the schema they
had before this ran, so applying it cannot change any wallet's capital,
positions, history or lineage.

`downgrade` drops only what `upgrade` created, in dependency order.

No wallet row and no strategy row is seeded here. Strategy Lab registers its
definitions and creates its simulated wallets from the service on first run, so
a deployed-but-idle Lab holds no rows and reports no balance — research that
has not started should not look like research that has.

`strategy_lab_opportunities.source_decision_id` deliberately has **no** foreign
key to `radar_decision_snapshots`. Research results must survive their source
audit row being pruned; a result that vanished with its provenance would be
worse than one with an id that no longer resolves.

Revision ID: 0045_strategy_lab
Revises: 0044_paper_wallet_v2
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0045_strategy_lab"
down_revision = "0044_paper_wallet_v2"
branch_labels = None
depends_on = None

_PRICE = sa.Numeric(38, 18)
_MONEY = sa.Numeric(24, 4)
_QUANTITY = sa.Numeric(48, 18)
_RATIO = sa.Numeric(20, 8)
_UUID = postgresql.UUID(as_uuid=True)
_JSONB = postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.create_table(
        "strategy_lab_runs",
        sa.Column("id", _UUID, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("mode", sa.String(24), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("canonical_version", sa.String(16), nullable=False),
        sa.Column("metrics_version", sa.String(16), nullable=False),
        sa.Column("rules_version", sa.String(64), nullable=False),
        sa.Column("dataset_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dataset_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("candidates", sa.Integer(), nullable=False),
        sa.Column("usable", sa.Integer(), nullable=False),
        sa.Column("excluded", sa.Integer(), nullable=False),
        sa.Column("exclusions", _JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("venues", _JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("observation_count", sa.Integer(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_strategy_lab_runs"),
    )
    op.create_index("ix_strategy_lab_runs_started", "strategy_lab_runs", ["started_at"])

    op.create_table(
        "strategy_lab_strategies",
        sa.Column("id", _UUID, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("strategy_id", sa.String(16), nullable=False),
        sa.Column("version", sa.String(16), nullable=False),
        sa.Column("name", sa.String(96), nullable=False),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("entry_size_usd", _MONEY, nullable=False),
        sa.Column("definition_hash", sa.String(64), nullable=False),
        sa.Column("definition", _JSONB, nullable=False),
        sa.Column("benchmark", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_strategy_lab_strategies"),
        sa.UniqueConstraint("strategy_id", "version", name="uq_strategy_lab_strategy_version"),
    )

    op.create_table(
        "strategy_lab_opportunities",
        sa.Column("id", _UUID, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("source_decision_id", _UUID, nullable=False),
        sa.Column("mint_address", sa.String(44), nullable=False),
        sa.Column("eligible_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("entry_price", _PRICE, nullable=True),
        sa.Column("liquidity_usd", _MONEY, nullable=True),
        sa.Column("market_cap", _MONEY, nullable=True),
        sa.Column("liq_to_mcap", _RATIO, nullable=True),
        sa.Column("volume_24h", _MONEY, nullable=True),
        sa.Column("volume_1h", _MONEY, nullable=True),
        sa.Column("buys_24h", sa.Integer(), nullable=True),
        sa.Column("sells_24h", sa.Integer(), nullable=True),
        sa.Column("buy_sell_ratio_24h", _RATIO, nullable=True),
        sa.Column("pool_address", sa.String(44), nullable=True),
        sa.Column("venue", sa.String(64), nullable=True),
        sa.Column("trading_pair", sa.String(96), nullable=True),
        sa.Column("discovery_age_seconds", sa.Numeric(20, 3), nullable=True),
        sa.Column("first_discovered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("radar_rank", sa.Integer(), nullable=True),
        sa.Column("radar_score", sa.Numeric(7, 3), nullable=True),
        sa.Column("confidence_score", sa.Numeric(7, 3), nullable=True),
        sa.Column("risk_score", sa.Numeric(7, 3), nullable=True),
        sa.Column("risk_band", sa.String(32), nullable=True),
        sa.Column("security_status", sa.String(16), nullable=True),
        sa.Column("security_evaluated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("observation_cadence_seconds", sa.Numeric(20, 6), nullable=True),
        sa.Column("radar_input_snapshot_count", sa.Integer(), nullable=True),
        sa.Column("evidence_coverage_pct", sa.Numeric(7, 2), nullable=True),
        sa.Column("canonical_version", sa.String(16), nullable=False),
        sa.Column("excluded_reason", sa.String(48), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_strategy_lab_opportunities"),
        sa.UniqueConstraint("mint_address", name="uq_strategy_lab_opportunity_mint"),
    )
    op.create_index(
        "ix_strategy_lab_opportunities_eligible", "strategy_lab_opportunities", ["eligible_at"]
    )
    op.create_index(
        "ix_strategy_lab_opportunities_source",
        "strategy_lab_opportunities",
        ["source_decision_id"],
    )

    op.create_table(
        "strategy_lab_wallets",
        sa.Column("id", _UUID, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("run_id", _UUID, nullable=True),
        sa.Column("strategy_id", sa.String(16), nullable=False),
        sa.Column("version", sa.String(16), nullable=False),
        sa.Column("definition_hash", sa.String(64), nullable=False),
        sa.Column("mode", sa.String(24), nullable=False),
        sa.Column("starting_balance", _MONEY, nullable=False),
        sa.Column("entry_size_usd", _MONEY, nullable=False),
        sa.Column("cash", _MONEY, nullable=False),
        sa.Column("peak_equity", _MONEY, server_default=sa.text("0"), nullable=False),
        sa.Column(
            "max_drawdown_pct", sa.Numeric(9, 4), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("equity_curve", _JSONB, server_default=sa.text("'[]'::jsonb"), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["strategy_lab_runs.id"],
            name="fk_strategy_lab_wallets_run_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_strategy_lab_wallets"),
        sa.UniqueConstraint(
            "strategy_id", "version", "mode", "run_id", name="uq_strategy_lab_wallet"
        ),
    )
    op.create_index("ix_strategy_lab_wallets_mode", "strategy_lab_wallets", ["mode"])

    op.create_table(
        "strategy_lab_positions",
        sa.Column("id", _UUID, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("wallet_id", _UUID, nullable=False),
        sa.Column("opportunity_id", _UUID, nullable=False),
        sa.Column("mint_address", sa.String(44), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("entry_price", _PRICE, nullable=False),
        sa.Column("size_usd", _MONEY, nullable=False),
        sa.Column("initial_quantity", _QUANTITY, nullable=False),
        sa.Column("remaining_quantity", _QUANTITY, nullable=False),
        sa.Column("entry_cost", _MONEY, nullable=False),
        sa.Column("entry_liquidity_usd", _MONEY, nullable=True),
        sa.Column("venue", sa.String(64), nullable=True),
        sa.Column("pool_address", sa.String(44), nullable=True),
        sa.Column("filled_rungs", _JSONB, server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("fired_decay", _JSONB, server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("trail_armed", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("trail_high", _PRICE, nullable=True),
        sa.Column("observed_peak_multiple", _RATIO, nullable=True),
        sa.Column("executable_peak_multiple", _RATIO, nullable=True),
        sa.Column("terminal_multiple", _RATIO, nullable=True),
        sa.Column("batch_rung_fills", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("evaluated_through", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("close_reason", sa.String(32), nullable=True),
        sa.Column("unsettled", sa.Boolean(), server_default=sa.false(), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["wallet_id"],
            ["strategy_lab_wallets.id"],
            name="fk_strategy_lab_positions_wallet_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["opportunity_id"],
            ["strategy_lab_opportunities.id"],
            name="fk_strategy_lab_positions_opportunity_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_strategy_lab_positions"),
        sa.UniqueConstraint("wallet_id", "opportunity_id", name="uq_strategy_lab_position"),
    )
    op.create_index(
        "ix_strategy_lab_positions_wallet_open",
        "strategy_lab_positions",
        ["wallet_id", "closed_at"],
    )
    op.create_index("ix_strategy_lab_positions_mint", "strategy_lab_positions", ["mint_address"])
    op.create_index("ix_strategy_lab_positions_opened", "strategy_lab_positions", ["opened_at"])

    op.create_table(
        "strategy_lab_fills",
        sa.Column("id", _UUID, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("position_id", _UUID, nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("filled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", sa.String(24), nullable=False),
        sa.Column("price_usd", _PRICE, nullable=False),
        sa.Column("quantity", _QUANTITY, nullable=False),
        sa.Column("liquidity_usd", _MONEY, nullable=True),
        sa.Column("rung_indexes", _JSONB, server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("trigger_price", _PRICE, nullable=True),
        sa.Column("gross_proceeds", _MONEY, nullable=False),
        sa.Column("execution_cost", _MONEY, nullable=False),
        sa.Column("net_proceeds", _MONEY, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["position_id"],
            ["strategy_lab_positions.id"],
            name="fk_strategy_lab_fills_position_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_strategy_lab_fills"),
        sa.UniqueConstraint("position_id", "sequence", name="uq_strategy_lab_fill_sequence"),
    )
    op.create_index("ix_strategy_lab_fills_position", "strategy_lab_fills", ["position_id"])
    op.create_index("ix_strategy_lab_fills_at", "strategy_lab_fills", ["filled_at"])

    op.create_table(
        "strategy_lab_refusals",
        sa.Column("id", _UUID, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("wallet_id", _UUID, nullable=False),
        sa.Column("opportunity_id", _UUID, nullable=False),
        sa.Column("mint_address", sa.String(44), nullable=False),
        sa.Column("refused_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", sa.String(48), nullable=False),
        sa.Column("cash_at_refusal", _MONEY, nullable=False),
        sa.Column("peak_multiple", _RATIO, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["wallet_id"],
            ["strategy_lab_wallets.id"],
            name="fk_strategy_lab_refusals_wallet_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["opportunity_id"],
            ["strategy_lab_opportunities.id"],
            name="fk_strategy_lab_refusals_opportunity_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_strategy_lab_refusals"),
        sa.UniqueConstraint("wallet_id", "opportunity_id", name="uq_strategy_lab_refusal"),
    )
    op.create_index(
        "ix_strategy_lab_refusals_wallet", "strategy_lab_refusals", ["wallet_id", "reason"]
    )


def downgrade() -> None:
    op.drop_table("strategy_lab_refusals")
    op.drop_table("strategy_lab_fills")
    op.drop_table("strategy_lab_positions")
    op.drop_table("strategy_lab_wallets")
    op.drop_table("strategy_lab_opportunities")
    op.drop_table("strategy_lab_strategies")
    op.drop_table("strategy_lab_runs")
