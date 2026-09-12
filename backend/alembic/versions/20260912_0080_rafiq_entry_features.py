"""Rafiq Lab: the entry decision's two instrumented features.

## What this changes

Six additive, nullable columns on `rafiq_lab_positions`. No other table is
touched, nothing is dropped, nothing is rewritten, and a deployment that never
sets `RAFIQ_LAB_ENABLED` is unaffected.

## Why six columns for two facts

`FINDINGS.md` ranks holder concentration and LP-lock status at entry as the
most likely movers of the total-loss rate, and records that no book checks
either — a complete blind spot. Two value columns instrument them. The other
four exist because a null in this table has to be interpretable:

* `entry_top10_captured_at` / `entry_lp_checked_at` — when the reading was
  taken. Age at the decision is `opened_at` minus this, which is the only form
  in which age stays true; stored as an age it would be an age-at-write-time.
* `entry_lp_reason_codes` — `LP_OUTSTANDING` (a redeemable claim on the
  reserves exists, so someone can withdraw) and `POOL_CUSTODY_OUT_OF_SCOPE`
  (the evaluator has nothing to say about this token) are both status
  `UNKNOWN` and mean opposite things. Without the codes every non-PASS
  collapses into one bucket and the instrument cannot answer the question it
  was added for.
* `entry_features_error` — which store was silent. "No row in the store" and
  "a row that measured this as null" are different facts about the platform's
  collectors, and an analysis that cannot tell them apart reads a switched-off
  collector as a population of tokens with no holders.

## Nullable, and not backfilled

All six are nullable because both are genuinely unavailable much of the time,
and there is no `server_default`: a default would put a value nobody measured
into a row that predates the instrument. Existing rows stay null, permanently
and correctly — those decisions were made without these readings, and a
backfill would write today's on-chain state into a trade that closed
yesterday. `test_entry_features_are_never_backfilled` holds that line in code.

Revision ID: 0080_rafiq_entry_features
Revises: 0079_grad_execution
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0080_rafiq_entry_features"
down_revision = "0079_grad_execution"
branch_labels = None
depends_on = None

_TABLE = "rafiq_lab_positions"
#: Built per call rather than held as module-level `Column` objects: a
#: `Column` binds to the table it is added to, so a shared instance cannot be
#: used for both directions of this migration.
_COLUMNS: tuple[tuple[str, object], ...] = (
    ("entry_top10_holder_pct", sa.Numeric(9, 4)),
    ("entry_top10_captured_at", sa.DateTime(timezone=True)),
    ("entry_lp_status", sa.String(16)),
    ("entry_lp_reason_codes", postgresql.JSONB()),
    ("entry_lp_checked_at", sa.DateTime(timezone=True)),
    ("entry_features_error", sa.String(64)),
)


def upgrade() -> None:
    for name, type_ in _COLUMNS:
        op.add_column(_TABLE, sa.Column(name, type_, nullable=True))


def downgrade() -> None:
    for name, _ in reversed(_COLUMNS):
        op.drop_column(_TABLE, name)
