"""kol_wallet_ranks: the wallets a KOL tournament froze at activation

Revision ID: 0061_kol_wallet_ranks
Revises: 0060_token_early_buyers
Create Date: 2026-09-09

Stored rather than recomputed. A ranking refreshed on a schedule would start
including the trades the lab is deciding about; freezing it makes the
tournament a forward test of one dated claim.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0061_kol_wallet_ranks"
down_revision = "0060_token_early_buyers"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "kol_wallet_ranks",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("spec_version", sa.String(length=16), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("wallet_address", sa.String(length=64), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("early_buys", sa.Integer(), nullable=False),
        sa.Column("hits", sa.Integer(), nullable=False),
        sa.Column("hit_rate", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("spec_version", "wallet_address",
                            name="uq_kol_rank_once"),
    )
    op.create_index("ix_kol_rank_lookup", "kol_wallet_ranks",
                    ["spec_version", "wallet_address"])


def downgrade() -> None:
    op.drop_index("ix_kol_rank_lookup", table_name="kol_wallet_ranks")
    op.drop_table("kol_wallet_ranks")
