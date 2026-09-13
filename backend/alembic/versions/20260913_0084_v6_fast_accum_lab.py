"""V6 fast-accumulation research lab tables.

Additive only: two new `v6lab_*` tables and nothing else. No production table is
altered, no column is dropped, and no data is moved. `RESEARCH_ONLY`.

Revision ID: 0084_v6_fast_accum
Revises: 0083_remove_breakout
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0084_v6_fast_accum"
down_revision: str = "0083_remove_breakout"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "v6lab_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("experiment_id", sa.String(64), nullable=False),
        sa.Column("spec_version", sa.String(32), nullable=False),
        sa.Column("config_hash", sa.String(32), nullable=False),
        sa.Column("dataset_version", sa.String(32), nullable=False),
        sa.Column("git_sha", sa.String(40), nullable=True),
        sa.Column("random_seed", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("verdict", sa.String(48), nullable=False),
        sa.Column("gate_passed", sa.Boolean(), nullable=False,
                  server_default=sa.text("false")),
        sa.Column("leakage_passed", sa.Boolean(), nullable=False,
                  server_default=sa.text("true")),
        sa.Column("result", postgresql.JSONB(), nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.PrimaryKeyConstraint("id", name="pk_v6lab_runs"),
    )
    op.create_index("ix_v6lab_runs_experiment_id", "v6lab_runs", ["experiment_id"])
    op.create_index("ix_v6lab_runs_started", "v6lab_runs", ["started_at"])

    op.create_table(
        "v6lab_trades",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("strategy", sa.String(48), nullable=False),
        sa.Column("mint", sa.String(64), nullable=False),
        sa.Column("entry_ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("exit_ts", sa.DateTime(timezone=True), nullable=True),
        sa.Column("exit_reason", sa.String(24), nullable=False),
        sa.Column("censored", sa.Boolean(), nullable=False,
                  server_default=sa.text("false")),
        sa.Column("entry_progress_pct", sa.Numeric(6, 3), nullable=True),
        sa.Column("entry_mcap_sol", sa.Numeric(30, 9), nullable=True),
        sa.Column("elapsed_s", sa.Numeric(10, 3), nullable=True),
        sa.Column("gross_return", sa.Numeric(18, 8), nullable=True),
        sa.Column("net_return", sa.Numeric(18, 8), nullable=True),
        sa.Column("net_pnl_usd", sa.Numeric(24, 8), nullable=True),
        sa.Column("fees_usd", sa.Numeric(24, 8), nullable=True),
        sa.Column("slippage_usd", sa.Numeric(24, 8), nullable=True),
        sa.Column("mfe", sa.Numeric(18, 8), nullable=True),
        sa.Column("mae", sa.Numeric(18, 8), nullable=True),
        sa.Column("reached_100", sa.Boolean(), nullable=False,
                  server_default=sa.text("false")),
        sa.Column("graduated", sa.Boolean(), nullable=False,
                  server_default=sa.text("false")),
        sa.PrimaryKeyConstraint("id", name="pk_v6lab_trades"),
    )
    op.create_index("ix_v6lab_trades_run_strategy", "v6lab_trades",
                    ["run_id", "strategy"])
    op.create_index("ix_v6lab_trades_entry", "v6lab_trades", ["entry_ts"])


def downgrade() -> None:
    op.drop_index("ix_v6lab_trades_entry", table_name="v6lab_trades")
    op.drop_index("ix_v6lab_trades_run_strategy", table_name="v6lab_trades")
    op.drop_table("v6lab_trades")
    op.drop_index("ix_v6lab_runs_started", table_name="v6lab_runs")
    op.drop_index("ix_v6lab_runs_experiment_id", table_name="v6lab_runs")
    op.drop_table("v6lab_runs")
