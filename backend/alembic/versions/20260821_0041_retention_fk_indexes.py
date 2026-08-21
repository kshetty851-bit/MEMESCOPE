"""Index the foreign keys that made retention impossible.

Five columns reference a table retention has to delete from, and none of them
were indexed. Postgres verifies every referencing row before it removes a
parent, so an unindexed inbound foreign key turns each deleted row into a
sequential scan of the child table. Measured on 2026-08-21: a single
50,000-row batch against `token_market_snapshots` ran **22 minutes and deleted
nothing**, while the SELECT choosing those same rows took 259 ms. Four child
scans per row, one of them across 769,305 rows, is the whole difference.

Additive and reversible: five indexes, no column, constraint or data change.

`radar_decision_outcomes.decision_id` was already indexed and is deliberately
absent here.

Revision ID: 0041_retention_fk_idx
Revises: 0040_nursery_lane
"""

from __future__ import annotations

from alembic import op

revision = "0041_retention_fk_idx"
down_revision = "0040_nursery_lane"
branch_labels = None
depends_on = None

_INDEXES = (
    ("ix_paper_decision_snapshots_market_snapshot_id", "paper_decision_snapshots", "market_snapshot_id"),
    ("ix_paper_decision_outcomes_market_snapshot_id", "paper_decision_outcomes", "market_snapshot_id"),
    ("ix_radar_decision_snapshots_market_snapshot_id", "radar_decision_snapshots", "market_snapshot_id"),
    ("ix_radar_decision_outcomes_market_snapshot_id", "radar_decision_outcomes", "market_snapshot_id"),
    ("ix_radar_rank_events_decision_id", "radar_rank_events", "decision_id"),
)


def upgrade() -> None:
    for name, table, column in _INDEXES:
        op.create_index(name, table, [column])


def downgrade() -> None:
    for name, table, _column in reversed(_INDEXES):
        op.drop_index(name, table_name=table)
