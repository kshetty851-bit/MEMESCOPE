"""Remove the Rafiq, Momentum and Forex Labs and the Robinhood Chain recorder.

Deleted at Karthik's request on 2026-09-25, to the same extent as the V6
Fast-Accumulation Lab (`0087`): code, page, nav, registrations and the
records. This is the half that removes the data; the code goes in the same
commit.

Rafiqv2 stays. It ran on parts of the Rafiq Lab's engine, which moved into
`app.labs.rafiqv2.base` unchanged; none of them read a `rafiq_lab_*` table,
and no other table holds a foreign key into any table dropped here (checked on
production before this was written).

The paper wallet's page went in the same commit but its tables stay: the real
wallet runs on the paper engine's code, and the tables are 2 MB.

Intentionally irreversible, like `0087`: the migrations that created these
tables stay in the chain as history, not as a restore path.
"""

from __future__ import annotations

from alembic import op

revision: str = "0103_remove_four_labs"
down_revision: str = "0102_real_wallet_family"
branch_labels = None
depends_on = None

TABLES = (
    # Rafiq Lab
    "rafiq_lab_adjustments",
    "rafiq_lab_candidates",
    "rafiq_lab_daily_state",
    "rafiq_lab_gate_rejections",
    "rafiq_lab_positions",
    "rafiq_lab_run_state",
    "rafiq_lab_strategies",
    # Momentum Lab
    "mom_candles",
    "mom_closes",
    "mom_pairs",
    "mom_positions",
    "mom_signals",
    # Robinhood Chain recorder
    "rhood_locks",
    "rhood_samples",
    # Forex Lab
    "fx_candles",
    "fx_ingest_hours",
    "fx_sweep_runs",
)


def upgrade() -> None:
    for table in TABLES:
        # `IF EXISTS`: a database restored from an older backup may lack some,
        # and a failed migration here would block an unrelated deploy.
        # `CASCADE` takes their indexes and their own foreign keys with them.
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")


def downgrade() -> None:
    # Intentionally irreversible: the data is gone.
    pass
