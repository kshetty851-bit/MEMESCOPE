"""Priority enrichment lane, and the full observation behind a peak.

Two additive changes, both forward-only.

**`token_enrichment_state.priority`** is a lane, not a queue. The claim query
orders by `next_refresh_at`, and the backlog reached 36,154 active tokens: a
Radar token asking for a 15-second refresh queued behind 36,000 rows that were
already hours overdue, so its measured p95 gap was 106 minutes. Sorting on this
column first lets the lane jump the backlog without a second queue, a second
worker or a second scheduler.

`ix_enrichment_priority_due` matches the new ORDER BY exactly. Without it the
priority sort degrades to a heap sort over the whole backlog on every claim —
and a partial index would not help, because the query reads both lanes.

**`radar_tokens.peak_liquidity` / `peak_volume_24h` / `peak_observed_at`** close
the inconsistency the Sprint 28 audit measured: `peak_market_cap` was written
only when the peak happened to be the *current* price, so a peak raised from a
between-sweeps high left the market cap behind. 6 of 88 rows carried
`peak_price` above `current_price` while `peak_market_cap` equalled
`current_market_cap`.

**No backfill.** The historical rows cannot be corrected without rewriting a
permanent record, and this platform does not rewrite one. Existing peaks keep
whatever market cap they were given; the new columns are null until a peak is
next raised, and null renders as "—" rather than as a figure.

Revision ID: 0012_priority_lane
Revises: 0011_paper_wallet
Create Date: 2026-08-04 18:55:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012_priority_lane"
down_revision: str | None = "0011_paper_wallet"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "token_enrichment_state",
        sa.Column(
            "priority",
            sa.SmallInteger(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    # Matches `ORDER BY priority DESC, next_refresh_at ASC` under the same
    # WHERE the existing `ix_enrichment_due` serves.
    op.create_index(
        "ix_enrichment_priority_due",
        "token_enrichment_state",
        ["status", sa.text("priority DESC"), "next_refresh_at"],
        unique=False,
    )

    op.add_column(
        "radar_tokens", sa.Column("peak_liquidity", sa.Numeric(24, 4), nullable=True)
    )
    op.add_column(
        "radar_tokens", sa.Column("peak_volume_24h", sa.Numeric(24, 4), nullable=True)
    )
    op.add_column(
        "radar_tokens",
        sa.Column("peak_observed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("radar_tokens", "peak_observed_at")
    op.drop_column("radar_tokens", "peak_volume_24h")
    op.drop_column("radar_tokens", "peak_liquidity")
    op.drop_index("ix_enrichment_priority_due", table_name="token_enrichment_state")
    op.drop_column("token_enrichment_state", "priority")
