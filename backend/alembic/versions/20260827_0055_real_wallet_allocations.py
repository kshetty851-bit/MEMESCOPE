"""Divide the execution wallet between strategies. One new table, nothing touched.

A fraction per strategy, not a dollar amount. Dollars would need re-setting
every time the wallet grew, shrank, or took a fill, and an allocation that
drifts out of date is one that silently over-commits.

The sum-of-fractions invariant is NOT a constraint here. It spans rows, and a
row-level CHECK cannot see the other rows; `AllocationService` owns it. What
this migration does enforce is the per-row part a constraint CAN see: a
fraction outside (0, 1] is meaningless at any sum, so the database refuses it
regardless of which code path wrote it.

Additive. No existing table is altered, so a wallet running the single-strategy
path is unaffected until an operator writes a row.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0055_real_wallet_allocations"
down_revision: str = "0054_merge_karthik_hq"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "real_wallet_allocations",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("strategy_id", sa.String(64), nullable=False),
        sa.Column("fraction", sa.Numeric(6, 5), nullable=False),
        sa.Column(
            "enabled", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("note", sa.String(256), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("strategy_id", name="uq_real_wallet_allocation_strategy"),
        sa.CheckConstraint(
            "fraction > 0 AND fraction <= 1",
            name="ck_real_wallet_allocation_fraction",
        ),
    )


def downgrade() -> None:
    op.drop_table("real_wallet_allocations")
