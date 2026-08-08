"""Paper wallet manual sell provenance.

Sprint 35. Manual Sell is paper-only: no wallet is connected, no order is
routed, and the production trailing-stop strategy is unchanged. The additional
columns below preserve the one fact existing history could not represent: the
human action time is distinct from the market observation used as the exit quote.

Revision ID: 0014_paper_manual_sell
Revises: 0013_paper_wallet_v2
Create Date: 2026-08-08 15:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014_paper_manual_sell"
down_revision: str | None = "0013_paper_wallet_v2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "paper_positions",
        sa.Column("manual_action_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "paper_trade_audit",
        sa.Column("manual_action_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("paper_trade_audit", "manual_action_at")
    op.drop_column("paper_positions", "manual_action_at")
