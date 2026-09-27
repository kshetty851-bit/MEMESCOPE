"""User wallets' monthly profit fee: a rate per user and one row per month.

Karthik, 2026-09-27: 20% of each user wallet's new profit, charged monthly on
a high-water mark and sent to his fee address; USER 1 pays none. Additive
only, so it runs BEFORE the new code starts.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0107_user_wallet_fees"
down_revision: str = "0106_user_wallets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("real_wallet_family_members",
                  sa.Column("fee_rate", sa.Numeric(5, 4), nullable=False,
                            server_default="0.20"))
    op.execute("UPDATE real_wallet_family_members SET fee_rate = 0 WHERE name = 'USER1'")
    op.create_table(
        "real_wallet_user_fees",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("member", sa.String(16), nullable=False),
        sa.Column("wallet", sa.String(64), nullable=False),
        sa.Column("period", sa.Date, nullable=False),
        sa.Column("profit_usd", sa.Numeric(14, 2), nullable=False),
        sa.Column("hwm_before_usd", sa.Numeric(14, 2), nullable=False),
        sa.Column("hwm_after_usd", sa.Numeric(14, 2), nullable=False),
        sa.Column("fee_rate", sa.Numeric(5, 4), nullable=False),
        sa.Column("fee_usd", sa.Numeric(14, 2), nullable=False),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("sol_usd", sa.Numeric(14, 4)),
        sa.Column("lamports", sa.Numeric(20, 0)),
        sa.Column("signature", sa.String(120)),
        sa.Column("note", sa.String(200)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("member", "period", name="uq_real_wallet_user_fee_month"),
    )
    op.create_index("ix_real_wallet_user_fees_member", "real_wallet_user_fees", ["member"])


def downgrade() -> None:
    op.drop_index("ix_real_wallet_user_fees_member", "real_wallet_user_fees")
    op.drop_table("real_wallet_user_fees")
    op.drop_column("real_wallet_family_members", "fee_rate")
