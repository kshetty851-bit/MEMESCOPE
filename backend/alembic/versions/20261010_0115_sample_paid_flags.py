"""grad_postgrad_samples.has_profile / boosts_active: paid DexScreener promotion
seen on the lab's own reads.

Karthik, 2026-10-10 ("yes add that"): the market snapshots saw only about one
coin in five before the books bought it, so the Boost Lab was blind to the
rest. The lab reads every graduation from DexScreener within seconds; that
same answer carries the paid profile (`info`) and `boosts.active`. NULL where
absent, so the large table grows by almost nothing. IF NOT EXISTS: added by
hand on prod before the deploy, as the new code writes them on every sample.

Revision ID: 0115_sample_paid_flags
Revises: 0114_snapshot_boosts
"""

from __future__ import annotations

from alembic import op

revision: str = "0115_sample_paid_flags"
down_revision: str = "0114_snapshot_boosts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE grad_postgrad_samples ADD COLUMN IF NOT EXISTS has_profile boolean, "
               "ADD COLUMN IF NOT EXISTS boosts_active integer")


def downgrade() -> None:
    op.execute("ALTER TABLE grad_postgrad_samples DROP COLUMN IF EXISTS has_profile, "
               "DROP COLUMN IF EXISTS boosts_active")
