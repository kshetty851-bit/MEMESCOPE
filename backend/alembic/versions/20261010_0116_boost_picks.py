"""grad_boost_picks: the Boost Lab's picks, kept.

A pick proved by a market snapshot loses its proof the next day: retention
keeps one day of `token_market_snapshots`, and three of the first 28 picks
had already dropped out of the book by 10 Oct. Each coin the lab finds paid
at its buy is written here once and read back on every build.

Revision ID: 0116_boost_picks
Revises: 0115_sample_paid_flags
"""

from __future__ import annotations

from alembic import op

revision: str = "0116_boost_picks"
down_revision: str = "0115_sample_paid_flags"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS grad_boost_picks (
            mint varchar(64) PRIMARY KEY,
            opened_at timestamptz NOT NULL,
            has_profile boolean NOT NULL,
            boosts_active integer,
            found_at timestamptz NOT NULL DEFAULT now())
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS grad_boost_picks")
