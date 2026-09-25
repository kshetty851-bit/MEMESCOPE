"""Remove the family SHARES of the owner's wallet.

At Karthik's request on 2026-09-25, once Jaya, Asha and Apoorva had wallets of
their own (0104). Drops:

* `real_wallet_family_allocations` - each member's dollars inside an owner
  order. EMPTY on production when this shipped: no share was ever placed.
* `real_wallet_family_ledger` - bookkeeping of money put in for a member.
  Two rows on production: JAYA $20 deposit and $20 withdrawal, which net to
  nothing.
* `real_wallet_family_members.enabled` / `ticket_usd` - the share switch and
  size. JAYA's share was ON at $20; the owner's orders never carried it
  (see above), and from this release they are his own ticket only.

The members table stays: `own_enabled` / `own_ticket_usd` run their own wallets.

Intentionally irreversible, like 0087 and 0103: the data is gone, and the
code that read it is gone in the same commit.
"""

from __future__ import annotations

from alembic import op

revision: str = "0105_remove_family_shares"
down_revision: str = "0104_family_own_wallet_trading"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP TABLE IF EXISTS real_wallet_family_allocations CASCADE")
    op.execute("DROP TABLE IF EXISTS real_wallet_family_ledger CASCADE")
    op.execute("ALTER TABLE real_wallet_family_members DROP COLUMN IF EXISTS enabled")
    op.execute("ALTER TABLE real_wallet_family_members DROP COLUMN IF EXISTS ticket_usd")


def downgrade() -> None:
    # Intentionally irreversible: the data is gone.
    pass
