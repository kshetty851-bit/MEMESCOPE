"""Real wallet: the trade size chosen at Start.

`ticket_usd` on the switch (what the running wallet spends per graduation
trade) and on its event history (what each Start chose). Nullable: a row
without one trades the configured `REAL_WALLET_ENTRY_SIZE_USD`, as before.

Revision ID: 0091_real_wallet_ticket
Revises: 0090_grad_rug_exits
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0091_real_wallet_ticket"
down_revision: str = "0090_grad_rug_exits"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ("real_wallet_autotrade_switch", "real_wallet_autotrade_events"):
        op.add_column(table, sa.Column("ticket_usd", sa.Numeric(12, 2), nullable=True))


def downgrade() -> None:
    for table in ("real_wallet_autotrade_events", "real_wallet_autotrade_switch"):
        op.drop_column(table, "ticket_usd")
