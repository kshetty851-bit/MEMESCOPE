"""Remove the Rafiqv2 Lab and the NSE Breakout Tracker.

Deleted at Karthik's request on 2026-10-01 ("delete rafiqv2 lab, nse
breakouts ... lets free the space"), to the same extent as `0103`: code,
pages, nav, scheduled tasks and the records, in one commit. No table outside
these two labs holds a foreign key into them (checked on production); the
only links are rafiqv2's own, which CASCADE takes with them. bt_candles alone
is ~300 MB.

Intentionally irreversible, like `0087` and `0103`: the migrations that
created these tables stay in the chain as history, not as a restore path.
"""

from __future__ import annotations

from alembic import op

revision: str = "0110_remove_rafiqv2_and_nse"
down_revision: str = "0109_family_investment"
branch_labels = None
depends_on = None

TABLES = (
    # Rafiqv2 Lab
    "rafiqv2_adjustments",
    "rafiqv2_positions",
    "rafiqv2_books",
    # NSE Breakout Tracker
    "bt_episode_events",
    "bt_episodes",
    "bt_states",
    "bt_runs",
    "bt_candles",
    "bt_index_closes",
    "bt_ingest_days",
    "bt_universe",
)


def upgrade() -> None:
    for table in TABLES:
        # `IF EXISTS`: a database restored from an older backup may lack some.
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")


def downgrade() -> None:
    raise NotImplementedError("0110 deletes two labs' records; restore from a backup")
