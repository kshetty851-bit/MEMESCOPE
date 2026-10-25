"""Clean-up (Karthik, 2026-10-25: "delete 1 2 3 4 5").

Deletes the Pool Lab's and the fast arms' paper trades (POOL_10K_*, E75_4m,
E75T_4m), drops the retired Arena and BTC-candle tables, and EMPTIES four
tables the old engine's code still names but nothing has written since
September (research quotes, intelligence events, Jupiter universe, lab
equity points) — emptied, not dropped, so that code keeps running.
`grad_operators` is untouched: the real wallets' rug checks read it.

Intentionally irreversible, like `0103` and `0110`.
"""

from __future__ import annotations

from alembic import op

revision: str = "0126_cleanup"
down_revision: str = "0125_first_minute"
branch_labels = None
depends_on = None

BOOKS = ("POOL_10K_QUIET_3M", "POOL_10K_BUSY_3M", "POOL_10K_QUIET_5M", "E75_4m", "E75T_4m")
DROPPED = ("arena_positions", "arena_decisions", "arena_candidates", "btc_candles")
EMPTIED = ("research_quotes", "intelligence_events", "jupiter_universe_snapshots",
           "lab_equity_points")


def upgrade() -> None:
    books = ", ".join(f"'{b}'" for b in BOOKS)
    op.execute(f"DELETE FROM grad_paper_restatements WHERE position_id IN "
               f"(SELECT id FROM grad_paper_positions WHERE book IN ({books}))")
    op.execute(f"DELETE FROM grad_paper_positions WHERE book IN ({books})")
    for table in DROPPED:
        op.execute(f"DROP TABLE IF EXISTS {table}")
    op.execute(f"TRUNCATE {', '.join(EMPTIED)}")


def downgrade() -> None:
    raise NotImplementedError("0126 deleted records; there is nothing to restore")
