"""Graduation Lab: the early arm's signal, one table.

`grad_early_opens` holds the first moment a new pumpswap pool's own reserves
showed B3's depth ($198k), read on the vault socket within 90 seconds of the
migration. The early arm (B3E_198k_5m) buys from it instead of waiting for
DexScreener to list the pool.

Purely additive: a new table and its index, nothing that existed is touched.

Revision ID: 0088_grad_early_opens
Revises: 0087_remove_v6_fast_accum
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0088_grad_early_opens"
down_revision: str = "0087_remove_v6_fast_accum"
branch_labels = None
depends_on = None

_ADDRESS = sa.String(64)
_USD = sa.Numeric(24, 2)
_AT = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "grad_early_opens",
        sa.Column("mint", _ADDRESS, nullable=False),
        sa.Column("pool", _ADDRESS, nullable=False),
        sa.Column("migrated_at", _AT, nullable=False),
        sa.Column("first_seen_at", _AT, nullable=False),
        sa.Column("first_depth_usd", _USD, nullable=False),
        sa.Column("crossed_at", _AT, nullable=False),
        sa.Column("price_native", sa.Numeric(36, 18), nullable=False),
        sa.Column("depth_usd", _USD, nullable=False),
        sa.Column("sol_usd", sa.Numeric(18, 6), nullable=False),
        sa.PrimaryKeyConstraint("mint", name="pk_grad_early_opens"),
    )
    op.create_index("ix_grad_early_opens_crossed_at",
                    "grad_early_opens", ["crossed_at"])


def downgrade() -> None:
    op.drop_index("ix_grad_early_opens_crossed_at", table_name="grad_early_opens")
    op.drop_table("grad_early_opens")
