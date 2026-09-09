"""EVM launch stamps (Base first).

The discovery feed reaches back about seventy minutes, so a launch not caught
at the time is not recoverable. This table is the stamp; prices are fetched
retroactively from minute OHLCV, which is why there is no marks table beside it.

Revision ID: 0059_evm_launches
Revises: 0058_pumpfun_graduations
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0059_evm_launches"
down_revision = "0058_pumpfun_graduations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "evm_launches",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("network", sa.String(32), nullable=False),
        sa.Column("pool_address", sa.String(64), nullable=False),
        sa.Column("base_token_address", sa.String(64)),
        sa.Column("name", sa.String(128)),
        sa.Column("dex_id", sa.String(64)),
        sa.Column("pool_created_at", sa.DateTime(timezone=True)),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("liquidity_usd_at_sighting", sa.Numeric(30, 4)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.UniqueConstraint("network", "pool_address", name="uq_evm_launches_pool"),
    )
    op.create_index("ix_evm_launches_seen", "evm_launches",
                    ["network", sa.text("first_seen_at DESC")])
    op.create_index("ix_evm_launches_created", "evm_launches",
                    ["network", sa.text("pool_created_at DESC")])


def downgrade() -> None:
    op.drop_index("ix_evm_launches_created", table_name="evm_launches")
    op.drop_index("ix_evm_launches_seen", table_name="evm_launches")
    op.drop_table("evm_launches")
