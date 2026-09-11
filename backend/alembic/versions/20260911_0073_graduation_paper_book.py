"""Graduation Lab: the forward paper book, one table.

Purely additive — no ALTER, no DROP, no index on anything that existed. A
database that runs this and never sets `LAB_GRADUATION_PAPER_ENABLED` is
byte-identical in every table that existed before it.

**Paper only.** Nothing in this lab holds a key, a signer, or a route to a real
wallet, and `tests/test_isolation.py` fails if it ever imports one.

Parented to 0072.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0073_graduation_paper"
down_revision: str = "0072_rafiq_lab_v2"
branch_labels = None
depends_on = None

_ADDRESS = sa.String(64)
_QUOTE = sa.Numeric(30, 9)
_TOKENS = sa.Numeric(38, 9)
_USD = sa.Numeric(24, 8)


def upgrade() -> None:
    op.create_table(
        "grad_paper_positions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("mint", _ADDRESS, nullable=False),
        sa.Column("symbol", sa.String(32), nullable=True),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("open_quote", _USD, nullable=False),
        sa.Column("open_fill", _USD, nullable=False),
        sa.Column("notional_quote", _QUOTE, nullable=False),
        sa.Column("tokens", _TOKENS, nullable=False),
        # A RUNNING peak, updated each tick — never the window's eventual
        # high, which nothing could have known at the time.
        sa.Column("peak_quote", _USD, nullable=False),
        sa.Column("last_quote", _USD, nullable=True),
        sa.Column("marked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("close_quote", _USD, nullable=True),
        sa.Column("close_fill", _USD, nullable=True),
        sa.Column("close_reason", sa.String(24), nullable=True),
        sa.Column("pnl_quote", _QUOTE, nullable=True),
        sa.Column("net_return", sa.Numeric(18, 8), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_grad_paper_positions"),
        # One position per mint, ever. The book never re-enters a token it has
        # already traded, so a single name cannot be counted twice.
        sa.UniqueConstraint("mint", name="uq_grad_paper_positions_mint"),
    )
    op.create_index("ix_grad_paper_positions_opened_at",
                    "grad_paper_positions", ["opened_at"])
    op.create_index("ix_grad_paper_positions_open",
                    "grad_paper_positions", ["closed_at"])


def downgrade() -> None:
    op.drop_table("grad_paper_positions")
