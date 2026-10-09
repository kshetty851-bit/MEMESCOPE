"""Drop ix_grad_postgrad_samples_mint_ts: an exact copy of the unique
constraint's own (mint, ts) index.

Karthik, 2026-10-09 ("ok do B and C"), from the server cleanup: two identical
~800 MB indexes on grad_postgrad_samples, the table written ~216k times a day.
Dropped CONCURRENTLY and IF EXISTS: it was dropped by hand on prod the same
day, before this migration reached it.

Revision ID: 0113_drop_duplicate_sample_index
Revises: 0112_btc_range_candles
"""

from __future__ import annotations

from alembic import op

revision: str = "0113_drop_duplicate_sample_index"
down_revision: str = "0112_btc_range_candles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_grad_postgrad_samples_mint_ts")


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_grad_postgrad_samples_mint_ts "
                   "ON grad_postgrad_samples (mint, ts)")
