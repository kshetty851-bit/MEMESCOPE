"""grad_paper_positions.chain_sells_before: the coin's sells before the buy.

Karthik, 2026-10-12 ("daily profit table looks same in lab still"): the $10k
book skips a coin in a pool under $100k that had fewer than 22 sells by the
moment it was bought (a bundled launch: everyone buys, nobody sells). Counted
from chain history once per position, capped at 22 (all the rule asks). A fact
from before the entry, so filling it after the close changes no outcome. NULL
until read; -1 when the history could not be read. IF NOT EXISTS: added by hand
on prod before the deploy.

Revision ID: 0117_paper_chain_sells
Revises: 0116_boost_picks
"""

from __future__ import annotations

from alembic import op

revision: str = "0117_paper_chain_sells"
down_revision: str = "0116_boost_picks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE grad_paper_positions ADD COLUMN IF NOT EXISTS chain_sells_before integer")


def downgrade() -> None:
    op.execute("ALTER TABLE grad_paper_positions DROP COLUMN IF EXISTS chain_sells_before")
