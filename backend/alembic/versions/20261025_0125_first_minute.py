"""First-minute recorder: every new pumpswap pool's vault price, slot by slot.

Revision ID: 0125_first_minute
Revises: 0124_remove_fomo_lab
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0125_first_minute"
down_revision = "0124_remove_fomo_lab"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "grad_first_minute",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("mint", sa.String(64), nullable=False),
        sa.Column("pool", sa.String(64), nullable=False),
        sa.Column("slot", sa.BigInteger(), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("migrated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("price_native", sa.Numeric(36, 18), nullable=False),
        sa.Column("quote_reserve", sa.Numeric(30, 9), nullable=False),
        sa.Column("base_reserve", sa.Numeric(30, 6), nullable=False),
        sa.Column("virtual_quote", sa.Numeric(30, 0), nullable=False),
        sa.Column("sol_quoted", sa.Boolean(), nullable=False),
        sa.UniqueConstraint("mint", "slot", name="uq_grad_first_minute_mint_slot"),
    )
    op.create_index("ix_grad_first_minute_ts", "grad_first_minute", ["ts"])


def downgrade() -> None:
    op.drop_index("ix_grad_first_minute_ts", table_name="grad_first_minute")
    op.drop_table("grad_first_minute")
