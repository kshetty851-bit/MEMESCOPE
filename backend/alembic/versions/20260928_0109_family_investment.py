"""Family investment (Karthik, 2026-09-28): each user wallet gets a coin-size
band (`own_band`, a key of `app.real_wallet.family.BANDS`), and USER 1-7 are
set to the $500 plan — USER 1-4 $50 trades on $1M-$20M coins, USER 5-7 $100
trades on $5M-$100M coins. Every switch stays exactly as it was (off)."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0109_family_investment"
down_revision: str = "0108_grad_trade_flows"
branch_labels = None
depends_on = None

PLAN = (("1m-20m", 50, ("USER1", "USER2", "USER3", "USER4")),
        ("5m-100m", 100, ("USER5", "USER6", "USER7")))


def upgrade() -> None:
    op.add_column("real_wallet_family_members",
                  sa.Column("own_band", sa.String(16), nullable=False, server_default="any"))
    for band, ticket, members in PLAN:
        for name in members:
            op.get_bind().execute(
                sa.text("update real_wallet_family_members set own_band = :b, "
                        "own_ticket_usd = :t where name = :n"),
                {"b": band, "t": ticket, "n": name})


def downgrade() -> None:
    op.drop_column("real_wallet_family_members", "own_band")
