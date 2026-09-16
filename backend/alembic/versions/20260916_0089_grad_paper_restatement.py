"""Graduation Lab: restate closed trades under the fixed exit and fee rules.

Two nullable columns on `grad_paper_positions` — the pool fee tier charged,
and why a trade counts for nothing — and `grad_paper_restatements`, which keeps
what a restated row said before it was restated.

Additive only: no existing row or column changes here. The restatement itself
is `python -m app.labs.graduation restate`, run after this.

Revision ID: 0089_grad_paper_restatement
Revises: 0088_grad_early_opens
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0089_grad_paper_restatement"
down_revision: str = "0088_grad_early_opens"
branch_labels = None
depends_on = None

_PRICE = sa.Numeric(36, 18)
_AT = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.add_column("grad_paper_positions",
                  sa.Column("pool_fee_bps", sa.Integer(), nullable=True))
    op.add_column("grad_paper_positions",
                  sa.Column("excluded", sa.String(32), nullable=True))
    op.create_table(
        "grad_paper_restatements",
        sa.Column("position_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("rule", sa.String(32), nullable=False),
        sa.Column("reason", sa.String(64), nullable=False),
        sa.Column("restated_at", _AT, nullable=False, server_default=sa.func.now()),
        sa.Column("was_open_fill", _PRICE, nullable=False),
        sa.Column("was_tokens", sa.Numeric(38, 9), nullable=False),
        sa.Column("was_close_quote", _PRICE, nullable=True),
        sa.Column("was_close_fill", _PRICE, nullable=True),
        sa.Column("was_close_reason", sa.String(24), nullable=True),
        sa.Column("was_liq_close_usd", sa.Numeric(24, 4), nullable=True),
        sa.Column("was_pnl_quote", sa.Numeric(30, 9), nullable=True),
        sa.Column("was_pnl_usd", sa.Numeric(18, 2), nullable=True),
        sa.Column("was_net_return", sa.Numeric(18, 8), nullable=True),
        sa.Column("was_closed_at", _AT, nullable=True),
        sa.Column("exit_seen_at", _AT, nullable=True),
        sa.Column("exit_source", sa.String(16), nullable=True),
        sa.ForeignKeyConstraint(
            ["position_id"], ["grad_paper_positions.id"], ondelete="CASCADE",
            name="fk_grad_paper_restatements_position_id"),
        sa.PrimaryKeyConstraint("position_id", name="pk_grad_paper_restatements"),
    )


def downgrade() -> None:
    op.drop_table("grad_paper_restatements")
    op.drop_column("grad_paper_positions", "excluded")
    op.drop_column("grad_paper_positions", "pool_fee_bps")
