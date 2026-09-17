"""Rafiq Lab G1: LP lock at entry, and the rejected candidates by name.

* `rafiq_lab_positions.entry_lp_locked` and `rafiq_lab_candidates.lp_locked`:
  true / false / null, read point-in-time from the same LIQUIDITY_SECURITY
  check whose raw status both tables already carry. Top-10 holder
  concentration needed no column: `entry_top10_holder_pct` and
  `top10_holder_pct` have been recorded since 0080 / 0081.
* `rafiq_lab_rejected_candidates`, a VIEW over `rafiq_lab_candidates`: every
  refused candidate with its run, both features and its forward returns
  (`forward_max_return_1h` is `max_return_1h`). A view, not a second table,
  so a rejection is written once and cannot disagree with itself.

The view depends on `rafiq_lab_candidates`' columns: a later migration that
drops or retypes one of them must drop and recreate it.

Revision ID: 0094_rafiq_g1_features
Revises: 0093_rafiq_g1_learning
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0094_rafiq_g1_features"
down_revision: str = "0093_rafiq_g1_learning"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("rafiq_lab_positions", sa.Column("entry_lp_locked", sa.Boolean()))
    op.add_column("rafiq_lab_candidates", sa.Column("lp_locked", sa.Boolean()))
    op.execute("""
        CREATE VIEW rafiq_lab_rejected_candidates AS
        SELECT c.id, s.lab_run_id, s.code AS strategy_code, c.strategy_id,
               c.mint_address, c.symbol, c.detected_at, c.decided_at,
               c.reject_reason, c.observed_at, c.price_usd, c.liquidity_usd,
               c.market_cap_usd, c.opportunity_score, c.notional_usd,
               c.entry_impact_pct,
               c.top10_holder_pct, c.top10_captured_at,
               c.lp_locked, c.lp_status, c.lp_reason_codes, c.lp_checked_at,
               c.features_error,
               c.max_return_1h AS forward_max_return_1h,
               c.final_return_1h AS forward_final_return_1h,
               c.dead_1h AS forward_dead_1h,
               c.outcomes_attempted
        FROM rafiq_lab_candidates c
        JOIN rafiq_lab_strategies s ON s.id = c.strategy_id
        WHERE c.outcome = 'rejected'
    """)


def downgrade() -> None:
    op.execute("DROP VIEW rafiq_lab_rejected_candidates")
    op.drop_column("rafiq_lab_candidates", "lp_locked")
    op.drop_column("rafiq_lab_positions", "entry_lp_locked")
