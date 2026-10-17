"""Phone push alerts: subscriptions, and when each trade alert was pushed.

Revision ID: 0120_push_alerts
Revises: 0119_open_buys
"""

from __future__ import annotations

from alembic import op

revision: str = "0120_push_alerts"
down_revision: str = "0119_open_buys"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS push_subscriptions (
            endpoint text PRIMARY KEY,
            p256dh varchar(200) NOT NULL,
            auth varchar(100) NOT NULL,
            owner varchar(320),
            created_at timestamptz NOT NULL DEFAULT now())""")
    op.execute("ALTER TABLE real_wallet_trade_alerts ADD COLUMN IF NOT EXISTS pushed_at timestamptz")


def downgrade() -> None:
    op.execute("ALTER TABLE real_wallet_trade_alerts DROP COLUMN IF EXISTS pushed_at")
    op.execute("DROP TABLE IF EXISTS push_subscriptions")
