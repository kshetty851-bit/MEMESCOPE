"""Graduation Lab: denominate the paper book in dollars.

Purely additive: two columns on `grad_paper_positions`, no other table
touched.

The book was specified as $1,000 over ten $100 slots, so it should report in
dollars. It can do so honestly because DexScreener answers with `price_usd`
AND `price_native` for the same pair at the same instant — the SOL/USD rate is
a measurement, not an assumption. It is stored per position so a later move in
SOL cannot rewrite what a past trade was worth, which is also how a real $100
order behaves.

Parented to 0073.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0074_graduation_paper_usd"
down_revision: str = "0073_graduation_paper"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("grad_paper_positions",
                  sa.Column("notional_usd", sa.Numeric(18, 2), nullable=False,
                            server_default=sa.text("0")))
    op.add_column("grad_paper_positions",
                  sa.Column("sol_usd_at_open", sa.Numeric(18, 6), nullable=False,
                            server_default=sa.text("0")))
    # size x return, both exact — never the SOL proceeds re-converted later.
    op.add_column("grad_paper_positions",
                  sa.Column("pnl_usd", sa.Numeric(18, 2), nullable=True))


def downgrade() -> None:
    op.drop_column("grad_paper_positions", "pnl_usd")
    op.drop_column("grad_paper_positions", "sol_usd_at_open")
    op.drop_column("grad_paper_positions", "notional_usd")
