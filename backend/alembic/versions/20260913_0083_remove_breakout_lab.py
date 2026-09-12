"""Remove the Breakout Lab: its ten `bo_*` tables and everything in them.

Deleted on the operator's instruction, to the full extent asked for — code,
page, nav, registrations and the records. This is the half that frees the
space; the code is removed in the same commit.

The lab was a paper-only research product: momentum into daily resistance on
established Solana tokens, with a $1,000 paper book. It held no real money and
no real key. Two paper positions were open when it was removed, and they go
with it.

Intentionally irreversible, following `0032_remove_shadow`. Recreating the
schema would resurrect a live-looking product state with no code left to own
it, and the rows themselves cannot come back — which is what "delete" was
asked to mean.

Parented to `0082_grad_perf`, main's head when this landed. It was written
against 0068 and re-parented on rebase: the graduation lab added 0069-0082
in the meantime, and leaving the old parent would have left the chain with two
heads — which is a fault the graduation lab itself had to fix days earlier.
"""

from __future__ import annotations

from alembic import op

revision: str = "0083_remove_breakout"
down_revision: str = "0082_grad_perf"
branch_labels = None
depends_on = None

#: Dependants first, though none of the ten declares a foreign key to another
#: — the lab kept its tables independent so a replay could rewrite one without
#: cascading into the rest. Ordered anyway, so the intent survives a future
#: reader who adds one.
TABLES = (
    "bo_equity",
    "bo_trades",
    "bo_positions",
    "bo_account",
    "bo_episodes",
    "bo_setup_snapshots",
    "bo_levels",
    "bo_runs",
    "bo_candles",
    "bo_universe",
)


def upgrade() -> None:
    for table in TABLES:
        # `IF EXISTS`: the tables were created by 0064-0066, which every
        # environment has run, but a database restored from a backup taken
        # before those is a real possibility and a failed migration here would
        # block an unrelated deploy.
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")


def downgrade() -> None:
    # Intentionally irreversible. 0064-0066 remain in the chain as the schema's
    # history; they are not a restore path, because the data is gone.
    pass
