"""Exit state on real positions, so the frozen exits can actually be evaluated.

The real wallet could open a position and never close one: nothing in production
created a SELL intent, and the position row carried none of the state the frozen
V6 exits are written against. `evaluate_exit` asks for the peak executable
multiple, the liquidity the position was entered at, whether break-even has armed
and whether the partial has already been taken — a trailing stop or a
break-even rule cannot be evaluated from entry price and quantity alone.

Every column is nullable with a safe default. A position opened before this
migration has no history to invent: its peak is seeded to its entry (1.0), which
is the honest floor rather than a guess, and an unknown entry liquidity disables
the liquidity-collapse rule for that position instead of firing it on a value
nobody measured.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0052_real_position_exit_state"
down_revision = "0051_password_reset"
branch_labels = None
depends_on = None

TABLE = "real_wallet_positions"


def upgrade() -> None:
    # The trigger basis for trailing and break-even. Seeded to 1.0 — a position
    # whose peak is unknown has not been shown to have risen, and 1.0 is the
    # only value that cannot invent a gain that never happened.
    op.add_column(TABLE, sa.Column(
        "peak_exec_multiple", sa.Numeric(20, 6), nullable=False,
        server_default=sa.text("1"),
    ))
    # NULL disables the liquidity-collapse exit for that position rather than
    # firing it against a number nobody measured.
    op.add_column(TABLE, sa.Column(
        "entry_liquidity_usd", sa.Numeric(24, 4), nullable=True,
    ))
    op.add_column(TABLE, sa.Column(
        "last_exec_multiple", sa.Numeric(20, 6), nullable=True,
    ))
    op.add_column(TABLE, sa.Column(
        "break_even_armed", sa.Boolean(), nullable=False,
        server_default=sa.false(),
    ))
    op.add_column(TABLE, sa.Column(
        "partial_done", sa.Boolean(), nullable=False, server_default=sa.false(),
    ))
    # When the executable multiple entered the stagnation band, for the
    # stagnation exit. NULL means "not flat", never "flat since forever".
    op.add_column(TABLE, sa.Column(
        "flat_since", sa.DateTime(timezone=True), nullable=True,
    ))
    # Proceeds already banked by a partial exit. The remaining quantity is what
    # `quantity` tracks; this is what has come back so far.
    op.add_column(TABLE, sa.Column(
        "banked_proceeds_usd", sa.Numeric(24, 4), nullable=False,
        server_default=sa.text("0"),
    ))
    op.add_column(TABLE, sa.Column(
        "last_marked_at", sa.DateTime(timezone=True), nullable=True,
    ))


def downgrade() -> None:
    for column in (
        "last_marked_at",
        "banked_proceeds_usd",
        "flat_since",
        "partial_done",
        "break_even_armed",
        "last_exec_multiple",
        "entry_liquidity_usd",
        "peak_exec_multiple",
    ):
        op.drop_column(TABLE, column)
