"""grad_trade_flows: insiders' and other traders' money in each coin Karthik's
arm bought, from graduation to its sell; grad_rug_verdicts: whether each
graduation rugged in its first hour (Karthik, 2026-09-27). Additive."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0108_grad_trade_flows"
down_revision: str = "0107_user_wallet_fees"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "grad_trade_flows",
        sa.Column("mint", sa.String(64), primary_key=True),
        sa.Column("window_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_to", sa.DateTime(timezone=True), nullable=False),
        sa.Column("insiders_known", sa.Integer, nullable=False),
        sa.Column("insider_buy_usd", sa.Numeric(14, 2), nullable=False),
        sa.Column("insider_sell_usd", sa.Numeric(14, 2), nullable=False),
        sa.Column("other_buy_usd", sa.Numeric(14, 2), nullable=False),
        sa.Column("other_sell_usd", sa.Numeric(14, 2), nullable=False),
        sa.Column("other_buyers", sa.Integer, nullable=False),
        sa.Column("swaps", sa.Integer, nullable=False),
        sa.Column("measured_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )


    op.create_table(
        "grad_rug_verdicts",
        sa.Column("mint", sa.String(64), primary_key=True),
        sa.Column("graduated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("measured", sa.Boolean, nullable=False),
        sa.Column("rugged", sa.Boolean, nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )
    op.create_index("ix_grad_rug_verdicts_graduated_at", "grad_rug_verdicts",
                    ["graduated_at"])


def downgrade() -> None:
    op.drop_index("ix_grad_rug_verdicts_graduated_at", "grad_rug_verdicts")
    op.drop_table("grad_rug_verdicts")
    op.drop_table("grad_trade_flows")
