"""token_market_snapshots.boosts_active: DexScreener's paid boosts on a coin.

Karthik, 2026-10-10 ("yes set up both in different lab"): record each coin's
active boosts so the Boost Lab can test whether boosted coins pay. Nullable,
no default: an ADD COLUMN that rewrites nothing on a large table. IF NOT
EXISTS: added by hand on prod before the deploy, because the new code writes
it on every snapshot and the deploy does not run migrations.

Revision ID: 0114_snapshot_boosts
Revises: 0113_drop_duplicate_sample_index
"""

from __future__ import annotations

from alembic import op

revision: str = "0114_snapshot_boosts"
down_revision: str = "0113_drop_duplicate_sample_index"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE token_market_snapshots ADD COLUMN IF NOT EXISTS boosts_active integer")


def downgrade() -> None:
    op.execute("ALTER TABLE token_market_snapshots DROP COLUMN IF EXISTS boosts_active")
