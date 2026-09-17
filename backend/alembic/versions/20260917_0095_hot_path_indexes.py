"""Indexes for two lookups that ran as full scans on every tick.

* `grad_tokens (lower(trim(symbol)), first_seen_at)`: the paper book's
  symbol-reuse count filters on `lower(trim(symbol))`, which 0077's index on
  `lower(symbol)` cannot serve. With the book ticking every 3 s it was a
  parallel scan of the whole table up to 20 times a minute.
* `lab_decisions (strategy_id, checkpoint_at)`: the real wallet's driver, exit
  driver and fast loop look decisions up by strategy CODE, and the only
  strategy index is on `strategy_row_id`, so every 3 s pass read all ~198k
  rows (99% of them from labs that are switched off).

Built CONCURRENTLY: both tables are written to while a deploy runs, and a
plain CREATE INDEX would block those writes until it finished.

Revision ID: 0095_hot_path_indexes
Revises: 0094_rafiq_g1_features
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0095_hot_path_indexes"
down_revision: str = "0094_rafiq_g1_features"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.create_index(
            "ix_grad_tokens_symbol_norm", "grad_tokens",
            [sa.text("lower(trim(symbol))"), "first_seen_at"],
            postgresql_concurrently=True, if_not_exists=True)
        op.create_index(
            "ix_lab_decisions_strategy_id_checkpoint", "lab_decisions",
            ["strategy_id", "checkpoint_at"],
            postgresql_concurrently=True, if_not_exists=True)


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.drop_index("ix_lab_decisions_strategy_id_checkpoint",
                      table_name="lab_decisions",
                      postgresql_concurrently=True, if_exists=True)
        op.drop_index("ix_grad_tokens_symbol_norm", table_name="grad_tokens",
                      postgresql_concurrently=True, if_exists=True)
