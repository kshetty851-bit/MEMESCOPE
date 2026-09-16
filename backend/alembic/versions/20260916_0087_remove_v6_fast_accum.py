"""Remove the V6 Fast-Accumulation Lab: its two `v6lab_*` tables and their rows.

Deleted on the operator's instruction, to the same extent as the Breakout and
Dex Labs — code, page, nav, registrations and the records. This is the half
that removes the data; the code goes in the same commit.

The lab was research only: a pre-registered edge test over the graduation lab's
curve samples, with no wallet, no execution path and no collector of its own.
Its one completed run (`V6_FAST_ACCUM_2026_09_13_001`) returned NO RELIABLE
EDGE IDENTIFIED, and its rows go with it.

Intentionally irreversible, following `0083_remove_breakout`. `0084_v6_fast_accum`
stays in the chain as the schema's history — and must, because
`0085_forex_lab` is parented to it — but it is not a restore path: the rows are
gone.
"""

from __future__ import annotations

from alembic import op

revision: str = "0087_remove_v6_fast_accum"
down_revision: str = "0086_grad_holder_shares"
branch_labels = None
depends_on = None

#: Dependants first. Neither declares a foreign key to the other — trades carry
#: `run_id` as a plain column — but the order keeps the intent if one is added.
TABLES = (
    "v6lab_trades",
    "v6lab_runs",
)


def upgrade() -> None:
    for table in TABLES:
        # `IF EXISTS`: a database restored from a backup taken before 0084 has
        # neither table, and a failed migration here would block an unrelated
        # deploy. `CASCADE` takes the tables' indexes with them.
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")


def downgrade() -> None:
    # Intentionally irreversible. 0084 remains in the chain as history; it is
    # not a restore path, because the data is gone.
    pass
