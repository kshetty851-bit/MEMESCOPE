"""Remove the Long-watch Lab (Karthik, 2026-10-26: "delete long watch lab").

Its collector read every graduation of the last 48 hours from DexScreener every
10 minutes (~10,500 coins an hour) from 22 Oct; the graduation feed's first
reading slowed from ~36 s to ~50 s after graduation the next day. Drops its
readings, books and positions. Intentionally irreversible, like `0110`/`0126`.
"""

from __future__ import annotations

from alembic import op

revision: str = "0127_remove_longwatch"
down_revision: str = "0126_cleanup"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ("longwatch_positions", "longwatch_books", "longwatch_readings"):
        op.execute(f"DROP TABLE IF EXISTS {table}")


def downgrade() -> None:
    raise NotImplementedError("0127 deleted records; there is nothing to restore")
