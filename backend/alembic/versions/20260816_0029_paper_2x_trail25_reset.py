"""Reset the active paper wallet for the forward-only 2x/25% trail experiment.

The prior live wallet is archived in place, including open positions and all
audit rows.  A fresh $1,000 generation is inserted; no historical research or
track-record row is deleted.  The additional nullable position fields preserve
the activation and observed-gap evidence required by the new strategy.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0029_paper_2x_trail25_reset"
down_revision = "0028_radar_forward_quality"
branch_labels = None
depends_on = None

_REASON = (
    "Retired for the forward-only PAPER_2X_TRAIL25_V1 experiment. Historical "
    "positions, trade audits, and research records are retained unchanged."
)


def upgrade() -> None:
    for name, column in (
        ("trailing_activation_multiple", sa.Numeric(precision=6, scale=4)),
        ("trailing_activated_at", sa.DateTime(timezone=True)),
        ("trailing_activation_observed_price", sa.Numeric(precision=38, scale=18)),
        ("trailing_stop_price", sa.Numeric(precision=38, scale=18)),
        ("trailing_trigger_price", sa.Numeric(precision=38, scale=18)),
        ("trailing_trigger_observed_price", sa.Numeric(precision=38, scale=18)),
    ):
        op.add_column("paper_positions", sa.Column(name, column, nullable=True))

    op.execute(
        sa.text(
            "UPDATE paper_wallets SET archived_at = now(), archive_reason = :reason "
            "WHERE archived_at IS NULL"
        ).bindparams(reason=_REASON)
    )
    # The partial unique index guarantees this can only create one new live
    # wallet.  The explicit generation remains correct even on installations
    # whose earlier migrations created more than one archived launch.
    op.execute(
        sa.text(
            "INSERT INTO paper_wallets "
            "(id, strategy_id, strategy_version, generation, starting_balance, started_at, created_at, updated_at) "
            "SELECT gen_random_uuid(), 'paper_2x_trail25_v1', '1.0.0-forward', "
            "COALESCE(MAX(generation), 0) + 1, 1000.0000, now(), now(), now() "
            "FROM paper_wallets "
            "WHERE NOT EXISTS (SELECT 1 FROM paper_wallets WHERE archived_at IS NULL)"
        )
    )


def downgrade() -> None:
    # A downgrade must never revive or delete the archival reset.  Removing the
    # additive evidence fields is sufficient for schema rollback.
    for name in (
        "trailing_trigger_observed_price",
        "trailing_trigger_price",
        "trailing_stop_price",
        "trailing_activation_observed_price",
        "trailing_activated_at",
        "trailing_activation_multiple",
    ):
        op.drop_column("paper_positions", name)
