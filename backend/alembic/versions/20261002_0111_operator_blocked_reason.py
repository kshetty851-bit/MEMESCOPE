"""Record why the money checks refused a graduation.

Karthik, 2026-10-02: "show this prevented rugs count". The checks refused
coins without a trace, so the count had to be replayed; `blocked_reason`
keeps it, and `rugged` (labelled five minutes on) says which were rugs.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0111_operator_blocked_reason"
down_revision: str = "0110_remove_rafiqv2_and_nse"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("grad_operators", sa.Column("blocked_reason", sa.String(32), nullable=True))


def downgrade() -> None:
    op.drop_column("grad_operators", "blocked_reason")
