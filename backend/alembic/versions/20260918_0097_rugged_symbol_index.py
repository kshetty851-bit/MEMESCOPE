"""An index for the wallet's rugged-name check.

`REAL_WALLET_BLOCK_RUGGED_SYMBOLS` asks, before every buy, whether any closed
paper trade under this token's name lost more than half. Without an index that
is a scan of `grad_paper_positions` on the buy path, which is the one path on
this platform that is racing a four-minute hold.

Built CONCURRENTLY: the paper book writes to this table every few seconds.

Revision ID: 0097_rugged_symbol_index
Revises: 0096_hot_path_indexes
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0097_rugged_symbol_index"
down_revision: str = "0096_hot_path_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.create_index(
            "ix_grad_paper_positions_symbol_norm", "grad_paper_positions",
            [sa.text("lower(trim(symbol))")],
            postgresql_concurrently=True, if_not_exists=True)


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.drop_index("ix_grad_paper_positions_symbol_norm",
                      table_name="grad_paper_positions",
                      postgresql_concurrently=True, if_exists=True)
