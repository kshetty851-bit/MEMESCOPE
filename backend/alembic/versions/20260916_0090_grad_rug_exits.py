"""Graduation Lab: the rug arms' columns.

`graduated_at` for the arm that counts its hold from graduation, and
`exit_signal_at` / `exit_signal` for a stop that has fired and is waiting for
the market after it to sell into. Three nullable columns; nothing existing
changes.

Revision ID: 0090_grad_rug_exits
Revises: 0089_grad_paper_restatement
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0090_grad_rug_exits"
down_revision: str = "0089_grad_paper_restatement"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("grad_paper_positions",
                  sa.Column("graduated_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("grad_paper_positions",
                  sa.Column("exit_signal_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("grad_paper_positions",
                  sa.Column("exit_signal", sa.String(24), nullable=True))


def downgrade() -> None:
    op.drop_column("grad_paper_positions", "exit_signal")
    op.drop_column("grad_paper_positions", "exit_signal_at")
    op.drop_column("grad_paper_positions", "graduated_at")
