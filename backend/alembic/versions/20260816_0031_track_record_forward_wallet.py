"""Launch the forward-only Track Record $10 TP/SL paper experiment.

Generation 5 remains an immutable all-scanned record.  This migration archives
it in place and creates Generation 6 with a new exact UTC admission watermark;
historical Track Record rows are therefore ineligible by construction.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0031_track_record_forward_wallet"
down_revision = "0030_all_scanned_forward_wallet"
branch_labels = None
depends_on = None

_REASON = (
    "Retired for the forward-only Track Record TP 1.25x / SL 0.50x experiment. "
    "Generation 5 positions, decisions, audits, and market observations remain retained unchanged."
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
            "SELECT gen_random_uuid(), 'paper_track_record_tp125_sl50_v1', '1.0.0-forward', "
            "COALESCE(MAX(generation), 0) + 1, 1000.0000, now(), now(), now() "
            "FROM paper_wallets "
            "WHERE NOT EXISTS (SELECT 1 FROM paper_wallets WHERE archived_at IS NULL)"
        )
    )


def downgrade() -> None:
    # Forward records are never deleted or revived during schema rollback.
    pass
