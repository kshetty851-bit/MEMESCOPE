"""The graduation lab's operator records, for the fast arms E75_4m / E75T_4m.

One row per graduation the fast arms looked at (bought or not): the wallets
that held 1%+ at entry and their funders, and whether the coin rugged five
minutes later. The trusted arm buys only operators with a clean record here.
A new table only; nothing existing is touched.

Revision ID: 0098_grad_operators
Revises: 0097_rugged_symbol_index
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0098_grad_operators"
down_revision: str = "0097_rugged_symbol_index"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "grad_operators",
        sa.Column("mint", sa.String(64), primary_key=True),
        sa.Column("pool", sa.String(64), nullable=False),
        sa.Column("migrated_at", sa.DateTime(timezone=True)),
        sa.Column("entry_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("price_native", sa.Numeric(36, 18), nullable=False),
        sa.Column("depth_usd", sa.Numeric(24, 2)),
        sa.Column("ids", postgresql.ARRAY(sa.String(64))),
        sa.Column("label_due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("rugged", sa.Boolean()),
        sa.Column("labelled_at", sa.DateTime(timezone=True)),
        sa.Column("exit_price_native", sa.Numeric(36, 18)),
        sa.Column("source", sa.String(8), nullable=False, server_default="live"),
    )
    op.create_index("ix_grad_operators_ids", "grad_operators", ["ids"],
                    postgresql_using="gin")
    op.create_index("ix_grad_operators_label_due_at", "grad_operators", ["label_due_at"])


def downgrade() -> None:
    op.drop_table("grad_operators")
