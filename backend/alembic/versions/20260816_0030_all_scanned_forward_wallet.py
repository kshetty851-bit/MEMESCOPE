"""Launch the forward-only all-scanned $10 TP/SL paper experiment.

All earlier generations are archived in place.  The new row's ``started_at``
is the immutable scanner-entry watermark: only discoveries written strictly
after it may be considered, so no historical stream is replayed.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0030_all_scanned_forward_wallet"
down_revision = "0029_paper_2x_trail25_reset"
branch_labels = None
depends_on = None

_REASON = (
    "Retired for the forward-only all-scanned TP 1.25x / SL 0.50x experiment. "
    "Historical positions, audits, and observations remain retained unchanged."
)


def upgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE paper_wallets SET archived_at = now(), archive_reason = :reason "
            "WHERE archived_at IS NULL"
        ).bindparams(reason=_REASON)
    )
    op.execute(
        sa.text(
            "INSERT INTO paper_wallets "
            "(id, strategy_id, strategy_version, generation, starting_balance, started_at, created_at, updated_at) "
            "SELECT gen_random_uuid(), 'paper_all_scanned_tp125_sl50_v1', '1.0.0-forward', "
            "COALESCE(MAX(generation), 0) + 1, 1000.0000, now(), now(), now() "
            "FROM paper_wallets "
            "WHERE NOT EXISTS (SELECT 1 FROM paper_wallets WHERE archived_at IS NULL)"
        )
    )


def downgrade() -> None:
    # Never delete or revive a forward experiment during schema rollback.
    pass
