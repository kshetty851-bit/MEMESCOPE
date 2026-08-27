"""V6 Forward Strategy Lab: six tables. Additive only, research-only.

No production table is touched. The Lab cannot reach paper, karthik or
real-wallet accounting — by schema as well as by code.

Revision ID: 0049_v6_strategy_lab
Revises: 0048_forward_arena
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0049_v6_strategy_lab"
down_revision = "0048_forward_arena"
branch_labels = None
depends_on = None

MONEY = sa.Numeric(24, 4)
PRICE = sa.Numeric(38, 18)
QTY = sa.Numeric(48, 18)
MULT = sa.Numeric(20, 6)
ROUTE = ("BUY_OK_SELL_OK", "BUY_OK_SELL_FAILED", "BUY_FAILED", "ROUTE_UNKNOWN")


def _pk():
    return sa.Column("id", postgresql.UUID(as_uuid=True),
                     server_default=sa.text("gen_random_uuid()"), nullable=False)


def _stamps():
    return (
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
    )


def upgrade() -> None:
    op.create_table(
        "lab_tournaments", _pk(),
        sa.Column("spec_version", sa.String(16), nullable=False),
        sa.Column("spec_hash", sa.String(64), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("snapshot_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("snapshot_taken_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("protocol_note", sa.Text(), nullable=True),
        *_stamps(),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("uq_lab_tournament_singleton", "lab_tournaments",
                    ["spec_version"], unique=True)

    op.create_table(
        "lab_strategies", _pk(),
        sa.Column("tournament_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("strategy_id", sa.String(8), nullable=False),
        sa.Column("name", sa.String(32), nullable=False),
        sa.Column("version", sa.String(16), nullable=False),
        sa.Column("spec_hash", sa.String(64), nullable=False),
        sa.Column("checkpoint_minutes", sa.Integer(), nullable=True),
        sa.Column("size_usd", MONEY, nullable=False),
        sa.Column("max_concurrent", sa.Integer(), nullable=False),
        sa.Column("max_exposure_usd", MONEY, nullable=False),
        sa.Column("rules", postgresql.JSONB(), nullable=False),
        sa.Column("starting_equity", MONEY, nullable=False),
        sa.Column("cash", MONEY, nullable=False),
        sa.Column("peak_equity", MONEY, nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("failed_reason", sa.String(48), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        *_stamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["tournament_id"], ["lab_tournaments.id"],
                                ondelete="CASCADE"),
        sa.UniqueConstraint("tournament_id", "strategy_id", name="uq_lab_strategy_once"),
        sa.CheckConstraint("status IN ('active','failed')", name="ck_lab_strategy_status"),
    )

    op.create_table(
        "lab_decisions", _pk(),
        sa.Column("strategy_row_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("strategy_id", sa.String(8), nullable=False),
        sa.Column("mint_address", sa.String(44), nullable=False),
        sa.Column("token_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("checkpoint_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("checkpoint_minutes", sa.Integer(), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("eligible", sa.Boolean(), nullable=False),
        sa.Column("skip_reason", sa.String(48), nullable=True),
        sa.Column("features", postgresql.JSONB(), nullable=True),
        sa.Column("snapshot_ids", postgresql.JSONB(), nullable=True),
        sa.Column("route_state", sa.String(20), nullable=True),
        sa.Column("quoted_impact_pct", sa.Numeric(12, 6), nullable=True),
        sa.Column("requested_size_usd", MONEY, nullable=True),
        *_stamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["strategy_row_id"], ["lab_strategies.id"],
                                ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["token_id"], ["discovered_tokens.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("strategy_row_id", "mint_address", name="uq_lab_decision_once"),
        sa.CheckConstraint(
            "route_state IS NULL OR route_state IN "
            f"({', '.join(repr(r) for r in ROUTE)})", name="ck_lab_decision_route"),
    )
    op.create_index("ix_lab_decisions_strategy_checkpoint", "lab_decisions",
                    ["strategy_row_id", "checkpoint_at"])
    op.create_index("ix_lab_decisions_mint", "lab_decisions", ["mint_address"])

    op.create_table(
        "lab_positions", _pk(),
        sa.Column("strategy_row_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("strategy_id", sa.String(8), nullable=False),
        sa.Column("decision_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("mint_address", sa.String(44), nullable=False),
        sa.Column("token_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("entry_price", PRICE, nullable=False),
        sa.Column("entry_liquidity_usd", MONEY, nullable=True),
        sa.Column("size_usd", MONEY, nullable=False),
        sa.Column("quantity", QTY, nullable=False),
        sa.Column("quantity_remaining", QTY, nullable=False),
        sa.Column("banked_proceeds_usd", MONEY, nullable=False, server_default="0"),
        sa.Column("entry_impact_pct", sa.Numeric(12, 6), nullable=True),
        sa.Column("entry_source", sa.String(16), nullable=False),
        sa.Column("status", sa.String(8), nullable=False, server_default="open"),
        sa.Column("peak_exec_multiple", MULT, nullable=False, server_default="1"),
        sa.Column("last_exec_multiple", MULT, nullable=True),
        sa.Column("last_open_value_usd", MONEY, nullable=True),
        sa.Column("break_even_armed", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("partial_done", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("partial_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("flat_since", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_evaluated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("exit_price", PRICE, nullable=True),
        sa.Column("exit_proceeds_usd", MONEY, nullable=True),
        sa.Column("exit_reason", sa.String(32), nullable=True),
        sa.Column("route_state", sa.String(20), nullable=True),
        sa.Column("reached_125", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("reached_150", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("reached_200", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("snapshot_value_usd", MONEY, nullable=True),
        *_stamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["strategy_row_id"], ["lab_strategies.id"],
                                ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["decision_id"], ["lab_decisions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["token_id"], ["discovered_tokens.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("strategy_row_id", "mint_address", name="uq_lab_position_once"),
        sa.CheckConstraint("status IN ('open','closed')", name="ck_lab_position_status"),
    )
    op.create_index("ix_lab_positions_open", "lab_positions",
                    ["strategy_row_id", "status"])

    op.create_table(
        "lab_equity_points", _pk(),
        sa.Column("strategy_row_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("strategy_id", sa.String(8), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cash", MONEY, nullable=False),
        sa.Column("deployed_cost", MONEY, nullable=False),
        sa.Column("open_value", MONEY, nullable=False),
        sa.Column("equity", MONEY, nullable=False),
        sa.Column("open_positions", sa.Integer(), nullable=False, server_default="0"),
        *_stamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["strategy_row_id"], ["lab_strategies.id"],
                                ondelete="CASCADE"),
    )
    op.create_index("ix_lab_equity_strategy_at", "lab_equity_points",
                    ["strategy_row_id", "captured_at"])

    op.create_table(
        "lab_snapshots", _pk(),
        sa.Column("tournament_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("label", sa.String(24), nullable=False),
        sa.Column("boundary_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("taken_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("elapsed_hours", sa.Float(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        *_stamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["tournament_id"], ["lab_tournaments.id"],
                                ondelete="CASCADE"),
        sa.UniqueConstraint("tournament_id", "label", name="uq_lab_snapshot_once"),
    )


def downgrade() -> None:
    for table in ("lab_snapshots", "lab_equity_points", "lab_positions",
                  "lab_decisions", "lab_strategies", "lab_tournaments"):
        op.drop_table(table)
