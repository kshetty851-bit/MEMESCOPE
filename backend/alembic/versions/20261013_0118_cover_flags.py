"""Cover picture (DexScreener `info.header`) on samples and Boost Lab picks.

Karthik, 2026-10-13 ("apply no cover skip to boost lab since day 1"): Boost Lab
coins whose DexScreener profile has no cover picture lost on 7 of 8 trades.
`grad_postgrad_samples.has_header` is read on every poll from now on (NULL
where the coin has no profile); `grad_boost_picks.has_cover` keeps each pick's
answer, backfilled once for older picks from DexScreener's current profile.
IF NOT EXISTS: added by hand on prod before the deploy.

Revision ID: 0118_cover_flags
Revises: 0117_paper_chain_sells
"""

from __future__ import annotations

from alembic import op

revision: str = "0118_cover_flags"
down_revision: str = "0117_paper_chain_sells"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE grad_postgrad_samples ADD COLUMN IF NOT EXISTS has_header boolean")
    op.execute("ALTER TABLE grad_boost_picks ADD COLUMN IF NOT EXISTS has_cover boolean")


def downgrade() -> None:
    op.execute("ALTER TABLE grad_boost_picks DROP COLUMN IF EXISTS has_cover")
    op.execute("ALTER TABLE grad_postgrad_samples DROP COLUMN IF EXISTS has_header")
