"""Family wallets, stage 2: each member's own-wallet switch, and one open
position per coin PER WALLET.

* `real_wallet_family_members.own_enabled` / `own_ticket_usd`: whether a
  member's OWN wallet trades, and at what size. Separate from `enabled` /
  `ticket_usd`, which size their share of the owner's orders — JAYA's share
  was ON when this shipped, and reusing that flag would have started her own
  wallet trading by itself. Every member starts OFF.
* The open-position uniqueness moves from (mint) to (wallet, mint): the
  owner's wallet and a family wallet buy the same coin in the same second.
  Every existing position already records its wallet (262 rows, all the
  owner's, checked on production before this was written), so the new index
  holds for all of them.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0104_family_own_wallet_trading"
down_revision: str = "0103_remove_four_labs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("real_wallet_family_members", sa.Column(
        "own_enabled", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("real_wallet_family_members", sa.Column(
        "own_ticket_usd", sa.Numeric(12, 2), nullable=False, server_default="20"))
    op.add_column("real_wallet_family_members", sa.Column(
        "own_updated_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("real_wallet_family_members", sa.Column(
        "own_updated_by", sa.String(120), nullable=True))

    op.create_index(
        "uq_real_wallet_open_position_wallet_mint", "real_wallet_positions",
        ["wallet_public_key", "mint_address"], unique=True,
        postgresql_where=sa.text("status = 'OPEN'"))
    op.drop_index("uq_real_wallet_open_position_mint", table_name="real_wallet_positions")


def downgrade() -> None:
    op.create_index(
        "uq_real_wallet_open_position_mint", "real_wallet_positions",
        ["mint_address"], unique=True, postgresql_where=sa.text("status = 'OPEN'"))
    op.drop_index("uq_real_wallet_open_position_wallet_mint",
                  table_name="real_wallet_positions")
    for column in ("own_updated_by", "own_updated_at", "own_ticket_usd", "own_enabled"):
        op.drop_column("real_wallet_family_members", column)
