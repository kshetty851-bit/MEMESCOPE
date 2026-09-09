"""token_early_buyers: who bought a coin first

Revision ID: 0060_token_early_buyers
Revises: 0059_evm_launches
Create Date: 2026-09-09

The raw material for ranking wallets on what they DO. The scanner already
decodes the trader's address on every trade and, until now, folded it into
aggregate counts and discarded it — so nothing here could answer "which
wallets are repeatedly early into coins that go somewhere".

Bounded on purpose: only the first ~20 distinct BUYERS, and only of mints that
reached $100k liquidity. Roughly 690 mints a day qualify, so about 14,000 rows
a day, against the tens of millions of trades the scanner sees.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0060_token_early_buyers"
down_revision = "0059_evm_launches"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "token_early_buyers",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("mint_address", sa.String(length=64), nullable=False),
        sa.Column("wallet_address", sa.String(length=64), nullable=False),
        sa.Column("bought_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("buy_rank", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
        # The flush re-runs over a mint for as long as it stays qualified, so
        # without this every pass would write the same wallet again.
        sa.UniqueConstraint("mint_address", "wallet_address",
                            name="uq_early_buyer_once"),
    )
    op.create_index("ix_early_buyer_wallet", "token_early_buyers",
                    ["wallet_address", "bought_at"])
    op.create_index("ix_early_buyer_mint", "token_early_buyers", ["mint_address"])
    op.create_index("ix_early_buyer_at", "token_early_buyers", ["bought_at"])


def downgrade() -> None:
    op.drop_index("ix_early_buyer_at", table_name="token_early_buyers")
    op.drop_index("ix_early_buyer_mint", table_name="token_early_buyers")
    op.drop_index("ix_early_buyer_wallet", table_name="token_early_buyers")
    op.drop_table("token_early_buyers")
