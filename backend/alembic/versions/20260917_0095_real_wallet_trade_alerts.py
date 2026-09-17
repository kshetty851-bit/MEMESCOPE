"""Real wallet: one WhatsApp alert per trade event, sent at most once.

Revision ID: 0095_real_wallet_trade_alerts
Revises: 0094_rafiq_g1_features
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0095_real_wallet_trade_alerts"
down_revision: str = "0094_rafiq_g1_features"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "real_wallet_trade_alerts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("position_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("real_wallet_positions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.Text()),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.UniqueConstraint("position_id", "event", name="uq_real_wallet_trade_alerts_event"),
    )
    op.create_index("ix_real_wallet_trade_alerts_pending", "real_wallet_trade_alerts",
                    ["status", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_real_wallet_trade_alerts_pending", table_name="real_wallet_trade_alerts")
    op.drop_table("real_wallet_trade_alerts")
