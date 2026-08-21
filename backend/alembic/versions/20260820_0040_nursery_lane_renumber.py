"""Make room for the fresh-token nursery lane.

`token_enrichment_state.priority` gains a lane between the ordinary population
and the display lane: 0 stays NORMAL, 1 becomes the NURSERY, the display lane
moves 1 -> 2 and Track Record quote acquisition moves 2 -> 3 (see the `LANE_*`
constants in `app.models.market`). Data-only — no schema change, and the
existing `(status, priority DESC, next_refresh_at)` index is value-agnostic.

One predicated UPDATE, ordered so no row can be counted twice: every currently
prioritised row moves up by exactly one lane. The nursery itself is populated
by the membership beat within a minute of deploy, not by this migration —
membership is derived from current state, never accumulated.

Revision ID: 0040_nursery_lane
Revises: 0039_token_security
"""

from __future__ import annotations

from alembic import op

revision = "0040_nursery_lane"
down_revision = "0039_token_security"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE token_enrichment_state SET priority = priority + 1 WHERE priority > 0")


def downgrade() -> None:
    # Nursery rows fold back into the ordinary population — the lane does not
    # exist in the old numbering.
    op.execute("UPDATE token_enrichment_state SET priority = priority - 1 WHERE priority > 0")
