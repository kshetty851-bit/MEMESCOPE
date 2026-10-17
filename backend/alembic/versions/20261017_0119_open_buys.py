"""grad_open_buys: did anyone buy a coin's pool when it opened?

Karthik, 2026-10-17 ("apply no-buy skip to karthik lab since day 1"): coins
whose pool had no buy over 0.5 SOL in its first minute rugged 24% of the time.

Revision ID: 0119_open_buys
Revises: 0118_cover_flags
"""

from __future__ import annotations

from alembic import op

revision: str = "0119_open_buys"
down_revision: str = "0118_cover_flags"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS grad_open_buys (
            mint varchar(64) PRIMARY KEY,
            read boolean NOT NULL,
            open_buy_sol numeric(20, 9),
            checked_at timestamptz NOT NULL DEFAULT now())""")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS grad_open_buys")
