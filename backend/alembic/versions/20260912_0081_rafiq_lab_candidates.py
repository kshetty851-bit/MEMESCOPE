"""Rafiq Lab: every candidate decided on, entered or refused, and what followed.

## Why

Every statistic in `FINDINGS.md` is conditioned on trades that were taken,
which makes the question the lab exists to answer unanswerable: a filter
cannot be evaluated against a population nobody recorded.
`rafiq_lab_gate_rejections` counts refusals and keeps no features, so it can
say the gate refused 4,812 candidates and nothing about whether refusing them
was right.

One new table. Nothing existing is altered, nothing is dropped.

## One row per (strategy, mint)

An entry supersedes an earlier rejection of the same mint — one decision
matters and it is the entry. A repeated rejection is discarded in favour of
the first, because the first is the one whose feature snapshot is
point-in-time with respect to the forward window measured from it. The unique
constraint is what the service's `ON CONFLICT` rule is written against.

## The forward columns

`max_return_*` / `final_return_*` / `dead_*` at +1h, +6h and +24h, computed
from `token_market_snapshots` alone — the platform already prices every
admitted token about every sixteen seconds, so no external endpoint is called
and none can rate-limit the measurement. `dead` is the horizon's last observed
liquidity below $1,000.

`max_return` is a ceiling nobody could have captured, not a claim that any
exit rule did. It bounds what was available.

`outcomes_attempted` records which horizons have been tried, with a null value
for an attempt that found no snapshots at all, so a token that stopped
printing is not retried for ever.

Revision ID: 0081_rafiq_lab_candidates
Revises: 0080_rafiq_entry_features
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0081_rafiq_lab_candidates"
down_revision = "0080_rafiq_entry_features"
branch_labels = None
depends_on = None

_MONEY = sa.Numeric(24, 4)
_PRICE = sa.Numeric(38, 18)
_RETURN = sa.Numeric(18, 6)
_TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "rafiq_lab_candidates",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("strategy_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("mint_address", sa.String(44), nullable=False),
        sa.Column("symbol", sa.String(32), nullable=True),
        sa.Column("detected_at", _TS, nullable=True),
        sa.Column("decided_at", _TS, nullable=False),
        sa.Column("outcome", sa.String(8), nullable=False),
        sa.Column("reject_reason", sa.String(48), nullable=True),
        sa.Column("position_id", postgresql.UUID(as_uuid=True), nullable=True),
        # the market as the decision saw it
        sa.Column("observed_at", _TS, nullable=True),
        sa.Column("price_usd", _PRICE, nullable=True),
        sa.Column("liquidity_usd", _MONEY, nullable=True),
        sa.Column("market_cap_usd", _MONEY, nullable=True),
        sa.Column("volume_m5", _MONEY, nullable=True),
        sa.Column("liquidity_change_15m", sa.Numeric(12, 6), nullable=True),
        sa.Column("opportunity_score", sa.Numeric(10, 4), nullable=True),
        sa.Column("flow", postgresql.JSONB(), nullable=True),
        # what sizing and the gate made of it
        sa.Column("notional_usd", _MONEY, nullable=True),
        sa.Column("stop_pct", sa.Numeric(10, 4), nullable=True),
        sa.Column("entry_impact_pct", sa.Numeric(10, 4), nullable=True),
        # the instrumented features, same source as the position row
        sa.Column("safety_status", sa.String(16), nullable=True),
        sa.Column("safety_observed_at", _TS, nullable=True),
        sa.Column("top10_holder_pct", sa.Numeric(9, 4), nullable=True),
        sa.Column("top10_captured_at", _TS, nullable=True),
        sa.Column("lp_status", sa.String(16), nullable=True),
        sa.Column("lp_reason_codes", postgresql.JSONB(), nullable=True),
        sa.Column("lp_checked_at", _TS, nullable=True),
        sa.Column("features_error", sa.String(64), nullable=True),
        # forward outcomes
        sa.Column("max_return_1h", _RETURN, nullable=True),
        sa.Column("final_return_1h", _RETURN, nullable=True),
        sa.Column("dead_1h", sa.Boolean(), nullable=True),
        sa.Column("max_return_6h", _RETURN, nullable=True),
        sa.Column("final_return_6h", _RETURN, nullable=True),
        sa.Column("dead_6h", sa.Boolean(), nullable=True),
        sa.Column("max_return_24h", _RETURN, nullable=True),
        sa.Column("final_return_24h", _RETURN, nullable=True),
        sa.Column("dead_24h", sa.Boolean(), nullable=True),
        sa.Column("outcomes_attempted", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", _TS, nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", _TS, nullable=False,
                  server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["strategy_id"], ["rafiq_lab_strategies.id"],
                                ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["position_id"], ["rafiq_lab_positions.id"],
                                ondelete="SET NULL"),
        sa.UniqueConstraint("strategy_id", "mint_address",
                            name="uq_rafiq_lab_candidates_strategy_mint"),
    )
    op.create_index("ix_rafiq_lab_candidates_decided", "rafiq_lab_candidates",
                    ["decided_at"])
    op.create_index("ix_rafiq_lab_candidates_outcome", "rafiq_lab_candidates",
                    ["outcome", "reject_reason"])


def downgrade() -> None:
    op.drop_index("ix_rafiq_lab_candidates_outcome", table_name="rafiq_lab_candidates")
    op.drop_index("ix_rafiq_lab_candidates_decided", table_name="rafiq_lab_candidates")
    op.drop_table("rafiq_lab_candidates")
