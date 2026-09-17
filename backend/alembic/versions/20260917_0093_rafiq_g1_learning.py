"""Rafiq Lab G1: what the learning layer hears, and what it remembers.

* On positions: the hour after each exit (`forward_peak_multiple`,
  `forward_went_to_zero`) and `learning_recorded_at`, which marks the trade as
  fed to `Learning.on_trade_closed` exactly once.
* On `rafiq_lab_run_state`: `learning`, the learner's evidence as JSON, so a
  restart does not forget it. Its adjustments go to `rafiq_lab_adjustments`
  (0092).

Nullable columns only; nothing existing changes.

Revision ID: 0093_rafiq_g1_learning
Revises: 0092_rafiq_g1_run
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0093_rafiq_g1_learning"
down_revision: str = "0092_rafiq_g1_run"
branch_labels = None
depends_on = None


def _position_columns() -> list[sa.Column]:
    return [
        sa.Column("forward_peak_multiple", sa.Numeric(18, 6)),
        sa.Column("forward_went_to_zero", sa.Boolean()),
        sa.Column("learning_recorded_at", sa.DateTime(timezone=True)),
    ]


def upgrade() -> None:
    for column in _position_columns():
        op.add_column("rafiq_lab_positions", column)
    op.add_column("rafiq_lab_run_state",
                  sa.Column("learning", postgresql.JSONB(astext_type=sa.Text())))


def downgrade() -> None:
    op.drop_column("rafiq_lab_run_state", "learning")
    for column in reversed(_position_columns()):
        op.drop_column("rafiq_lab_positions", column.name)
