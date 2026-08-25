"""Operator start/stop control for autonomous real-wallet trading.

Additive only. The switch authorises nothing on its own: the guard reads it as
one more required condition, so `off` refuses regardless of every other barrier,
and `on` satisfies only itself.

Revision ID: 0050_autotrade_switch
Revises: 0049_v6_strategy_lab
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0050_autotrade_switch"
down_revision = "0049_v6_strategy_lab"
branch_labels = None
depends_on = None


def _pk():
    return sa.Column("id", postgresql.UUID(as_uuid=True),
                     server_default=sa.text("gen_random_uuid()"), nullable=False)


def upgrade() -> None:
    op.create_table(
        "real_wallet_autotrade_switch", _pk(),
        sa.Column("scope", sa.String(32), nullable=False, server_default="default"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("nominated_strategy", sa.String(16), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_by", sa.String(128), nullable=True),
        sa.Column("start_reason", sa.String(256), nullable=True),
        sa.Column("stopped_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stopped_by", sa.String(128), nullable=True),
        sa.Column("stop_reason", sa.String(256), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("scope", name="uq_real_wallet_autotrade_scope"),
    )
    op.create_table(
        "real_wallet_autotrade_events", _pk(),
        sa.Column("scope", sa.String(32), nullable=False),
        sa.Column("action", sa.String(16), nullable=False),
        sa.Column("actor", sa.String(128), nullable=True),
        sa.Column("reason", sa.String(256), nullable=True),
        sa.Column("nominated_strategy", sa.String(16), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("action IN ('started','stopped')",
                           name="ck_autotrade_event_action"),
    )
    op.create_index("ix_autotrade_events_occurred", "real_wallet_autotrade_events",
                    ["occurred_at"])


def downgrade() -> None:
    op.drop_table("real_wallet_autotrade_events")
    op.drop_table("real_wallet_autotrade_switch")
