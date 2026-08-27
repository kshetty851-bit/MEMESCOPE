"""Strategy Discovery: three new tables, and nothing else.

**Purely additive.** No existing table is altered, no column dropped, no row
read or written. Paper Wallet V1, Paper Wallet V2, Real Wallet, Radar, Nursery,
Track Record and Strategy Lab's own seven tables all keep exactly the schema
they had, so applying this cannot change any wallet's capital, positions,
history or lineage.

`downgrade` drops only what `upgrade` created, in dependency order.

Nothing is seeded. A deployed-but-unused discovery engine holds no rows, which
is what a search that has not been run should look like.

Revision ID: 0046_strategy_lab_discovery
Revises: 0045_strategy_lab
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0046_strategy_lab_discovery"
down_revision = "0045_strategy_lab"
branch_labels = None
depends_on = None

_MONEY = sa.Numeric(24, 4)
_PCT = sa.Numeric(14, 4)
_UUID = postgresql.UUID(as_uuid=True)
_JSONB = postgresql.JSONB(astext_type=sa.Text())


def _now() -> sa.TextClause:
    return sa.text("now()")


def upgrade() -> None:
    op.create_table(
        "strategy_lab_discovery_runs",
        sa.Column("id", _UUID, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("dataset_source", sa.String(32), nullable=False),
        sa.Column("engine_version", sa.String(16), nullable=False),
        sa.Column("space_version", sa.String(16), nullable=False),
        sa.Column("scoring_version", sa.String(16), nullable=False),
        sa.Column("canonical_version", sa.String(16), nullable=False),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), server_default=_now(), nullable=False
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("runtime_seconds", sa.Numeric(12, 3), nullable=True),
        sa.Column(
            "schedule_resolutions", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column(
            "universe_usable", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("exclusions", _JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("split", _JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("funnel", _JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column(
            "search_space", _JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column(
            "attribution", _JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_strategy_lab_discovery_runs"),
    )
    op.create_index(
        "ix_sl_discovery_runs_started", "strategy_lab_discovery_runs", ["started_at"]
    )

    op.create_table(
        "strategy_lab_discovery_candidates",
        sa.Column("id", _UUID, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("run_id", _UUID, nullable=False),
        sa.Column("strategy_id", sa.String(24), nullable=False),
        sa.Column("version", sa.String(16), nullable=False),
        sa.Column("definition_hash", sa.String(64), nullable=False),
        sa.Column("definition", _JSONB, nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("factors", _JSONB, nullable=False),
        sa.Column("entry_size_usd", _MONEY, nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("reference", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=_now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["strategy_lab_discovery_runs.id"],
            name="fk_sl_discovery_candidates_run_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_strategy_lab_discovery_candidates"),
        sa.UniqueConstraint("run_id", "strategy_id", name="uq_sl_discovery_candidate"),
    )
    op.create_index(
        "ix_sl_discovery_candidates_status",
        "strategy_lab_discovery_candidates",
        ["run_id", "status"],
    )

    op.create_table(
        "strategy_lab_discovery_results",
        sa.Column("id", _UUID, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("candidate_id", _UUID, nullable=False),
        sa.Column("block", sa.String(16), nullable=False),
        sa.Column("n", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("offered", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("capture_pct", _PCT, nullable=True),
        sa.Column("final_equity", _MONEY, nullable=True),
        sa.Column("return_pct", _PCT, nullable=True),
        sa.Column("profit_factor", _PCT, nullable=True),
        sa.Column("expectancy", _MONEY, nullable=True),
        sa.Column("max_drawdown_pct", _PCT, nullable=True),
        sa.Column("win_rate_pct", _PCT, nullable=True),
        sa.Column("rug_loss_usd", _MONEY, nullable=True),
        sa.Column("score", _PCT, nullable=True),
        sa.Column("survives", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("flags", _JSONB, server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("metrics", _JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=_now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["candidate_id"],
            ["strategy_lab_discovery_candidates.id"],
            name="fk_sl_discovery_results_candidate_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_strategy_lab_discovery_results"),
        sa.UniqueConstraint("candidate_id", "block", name="uq_sl_discovery_result_block"),
    )
    op.create_index(
        "ix_sl_discovery_results_block_score",
        "strategy_lab_discovery_results",
        ["block", "score"],
    )


def downgrade() -> None:
    op.drop_table("strategy_lab_discovery_results")
    op.drop_table("strategy_lab_discovery_candidates")
    op.drop_table("strategy_lab_discovery_runs")
