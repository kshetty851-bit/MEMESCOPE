"""preserve exact confirmed real-wallet P&L precision

Revision ID: 0024_wallet_pnl_precision
Revises: 0023_wallet_lifecycle
Create Date: 2026-08-09
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0024_wallet_pnl_precision"
down_revision = "0023_wallet_lifecycle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for column in ("realised_gross_pnl_usd", "realised_net_pnl_usd"):
        op.alter_column(
            "real_wallet_positions",
            column,
            existing_type=sa.Numeric(precision=24, scale=4),
            type_=sa.Numeric(precision=38, scale=18),
            postgresql_using=f"{column}::numeric(38,18)",
        )


def downgrade() -> None:
    for column in ("realised_gross_pnl_usd", "realised_net_pnl_usd"):
        op.alter_column(
            "real_wallet_positions",
            column,
            existing_type=sa.Numeric(precision=38, scale=18),
            type_=sa.Numeric(precision=24, scale=4),
            postgresql_using=f"{column}::numeric(24,4)",
        )
