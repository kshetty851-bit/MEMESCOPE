"""Durable record of what the execution wallet held, and whether the rail explains it.

Every other real-wallet guard asks whether a spend may PROCEED. None of them
notices money that left without going through one — a key used elsewhere, a
signature produced outside the rail, an operator transfer nobody recorded. The
only evidence for that is the chain balance itself, compared against what the
rail says it did.

A table rather than a Redis key. The comparison needs a previous observation to
be worth anything, and a cache that expires loses its baseline exactly when the
system was down — which is precisely the window an unexplained movement would
hide in. Append-only and tiny: one row every couple of minutes, retained like
every other telemetry table.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0053_wallet_balance_observations"
down_revision = "0052_real_position_exit_state"
branch_labels = None
depends_on = None

TABLE = "real_wallet_balance_observations"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("wallet_public_key", sa.String(44), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        # Integer lamports, never floating SOL. A balance that rounds is a
        # balance whose movement can be rounded away.
        sa.Column("lamports", sa.BigInteger(), nullable=False),
        # Against the previous observation. NULL on the first row for a wallet:
        # there is nothing to compare to, and zero would claim there was.
        sa.Column("delta_lamports", sa.BigInteger(), nullable=True),
        # NULL means "not assessed" — a first row, or a check that could not run.
        # False means assessed and accounted for. True is the alarm.
        sa.Column("unexplained", sa.Boolean(), nullable=True),
        sa.Column("note", sa.String(200), nullable=True),
    )
    # The only query this table serves: the newest row for one wallet.
    op.create_index(
        f"ix_{TABLE}_wallet_observed",
        TABLE,
        ["wallet_public_key", "observed_at"],
    )


def downgrade() -> None:
    op.drop_index(f"ix_{TABLE}_wallet_observed", table_name=TABLE)
    op.drop_table(TABLE)
