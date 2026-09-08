"""pumpfun_social_snapshots — point-in-time comment activity

Additive only: one new table, nothing existing altered.

Revision ID: 0057_pumpfun_social
Revises: 0056_pumpfun_signals
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PgUUID

revision = "0057_pumpfun_social"
down_revision = "0056_pumpfun_signals"
branch_labels = None
depends_on = None

USD = sa.Numeric(24, 4)


def upgrade() -> None:
    op.create_table(
        "pumpfun_social_snapshots",
        sa.Column("id", PgUUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("mint_address", sa.String(64), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reply_count", sa.BigInteger(), nullable=True),
        sa.Column("usd_market_cap", USD, nullable=True),
        sa.Column("ath_market_cap", USD, nullable=True),
        sa.Column("complete", sa.Boolean(), nullable=True),
        sa.Column("is_currently_live", sa.Boolean(), nullable=True),
        sa.Column("source_sort", sa.String(24), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
    )
    op.create_index("ix_pf_social_mint_at", "pumpfun_social_snapshots",
                    ["mint_address", "observed_at"])
    op.create_index("ix_pf_social_at", "pumpfun_social_snapshots", ["observed_at"])


def downgrade() -> None:
    op.drop_index("ix_pf_social_at", table_name="pumpfun_social_snapshots")
    op.drop_index("ix_pf_social_mint_at", table_name="pumpfun_social_snapshots")
    op.drop_table("pumpfun_social_snapshots")
