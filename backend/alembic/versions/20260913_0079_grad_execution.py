"""graduation lab: record the pool depth a trade was actually executed against

A flat 25 bps of slippage, derived from a MEDIAN pool depth of ~$98,000, was
applied to every trade regardless of the pool it hit. Measured 2026-09-13:
487 of 1,902 paper trades went into pools holding LESS THAN $100 — one of them
$21, where a $100 order is five times the entire pool — and those trades
produced essentially all of the tournament's apparent profit. The leading arm
made $1,005, of which $878 was a single token whose pool held $21.

Execution is now computed from the pool's actual depth, so the depth has to be
stored: without it the fill cannot be audited, and the whole point of this
book is that a real wallet will be asked to reproduce it.

Revision ID: 0079_grad_execution
Revises: 0078_grad_tournament
"""

from alembic import op
import sqlalchemy as sa

revision = "0079_grad_execution"
down_revision = "0078_grad_tournament"
branch_labels = None
depends_on = None

_USD = sa.Numeric(24, 4)


def upgrade() -> None:
    op.add_column("grad_paper_positions",
                  sa.Column("liq_open_usd", _USD, nullable=True))
    op.add_column("grad_paper_positions",
                  sa.Column("liq_close_usd", _USD, nullable=True))
    op.add_column("grad_paper_positions",
                  sa.Column("impact_open", sa.Numeric(12, 6), nullable=True))
    op.add_column("grad_paper_positions",
                  sa.Column("impact_close", sa.Numeric(12, 6), nullable=True))


def downgrade() -> None:
    for column in ("impact_close", "impact_open", "liq_close_usd", "liq_open_usd"):
        op.drop_column("grad_paper_positions", column)
