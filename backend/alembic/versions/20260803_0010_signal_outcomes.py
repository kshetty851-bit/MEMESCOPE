"""Signal outcomes: two new `event_kind` values.

Purely additive, and deliberately *only* enum values. The outcome itself is
recorded in `opportunity_signals.status`, a column that has existed since 0008
and whose enum already declared `realised` and `invalidated` — nothing wrote
them until now. Adding a column to store an outcome that the status already
expresses would be the duplicate this sprint is forbidden to create.

`ADD VALUE IF NOT EXISTS` is safe inside a transaction on PostgreSQL 12+ so
long as the value is not *used* in the same transaction, which it is not. No
table, index or constraint is touched, so this applies while every service
runs.

Revision ID: 0010_outcomes
Revises: 0009_curve
Create Date: 2026-08-03 17:40:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0010_outcomes"
down_revision: str | None = "0009_curve"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NEW_EVENT_KINDS = ("signal_realised", "signal_invalidated")


def upgrade() -> None:
    for kind in _NEW_EVENT_KINDS:
        op.execute(f"ALTER TYPE event_kind ADD VALUE IF NOT EXISTS '{kind}'")


def downgrade() -> None:
    # PostgreSQL cannot drop an enum value. Recreating the type would require
    # rewriting every row that references it, and an event log is immutable —
    # the same reasoning 0008 recorded for its own eight additions.
    pass
