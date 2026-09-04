"""When a token stopped being tradeable, recorded durably.

The platform already writes an `INACTIVE` snapshot when a pool stops being
indexed, and 696,092 of those rows exist across 130,005 mints. They are not
enough to measure anything, for two reasons.

**One marker is invisible to a window that does not contain it.** The row is
written once, at the moment the empty-run threshold is crossed. Any later
question — "was this token alive six hours after I bought it" — looks in a
window that marker is not in, finds nothing, and cannot tell a dead token from
an unpolled one.

**And snapshots expire.** `token_market_snapshots` is retained telemetry, so the
marker is deleted while the fact it recorded stays true forever.

A timestamp on the enrichment state fixes both: one column, written once,
outside the retention window, answering "dead by when" for any window without
needing a row inside it.

## Why this matters more than it looks

Measured 2026-09-04 against 39 days of production data. Estimating the market's
own return over a 6-8 hour hold gave **+16.4%** when tokens with no forward
price were dropped, and **-2.3%** when the deaths among them were counted. The
sign of the entire population's return depended on it, and the optimistic
version was the one that came out by default — because a query for a price
naturally excludes the tokens that no longer have one.

Nullable, no backfill. Deaths before this migration stay unmarked rather than
being guessed at from a counter that only holds its CURRENT value.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0054_token_delisted_at"
down_revision = "0053_wallet_balance_observations"
branch_labels = None
depends_on = None

TABLE = "token_enrichment_state"


def upgrade() -> None:
    op.add_column(
        TABLE,
        sa.Column("delisted_at", sa.DateTime(timezone=True), nullable=True),
    )
    # The only query this serves: "which of these mints were dead by time T".
    # Partial, because the overwhelming majority of rows are NULL and indexing
    # them would be paying for the answer nobody asks.
    op.create_index(
        f"ix_{TABLE}_delisted_at",
        TABLE,
        ["delisted_at"],
        postgresql_where=sa.text("delisted_at IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(f"ix_{TABLE}_delisted_at", table_name=TABLE)
    op.drop_column(TABLE, "delisted_at")
