"""Remove retired shadow-wallet experiments and their research ledger rows.

The old shadow wallets, including the V1.1 simulation, were experimental
paper-only products.  They are deliberately removed as a unit; active and
archived primary paper-wallet generations are not touched.
"""

from __future__ import annotations

from alembic import op

revision = "0032_remove_shadow"
down_revision = "0031_track_record_forward_wallet"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The research ledger has restrictive foreign keys back to its decision
    # snapshot.  Delete only rows written by the retired shadow subsystem.
    op.execute(
        "DELETE FROM paper_decision_enrichments "
        "WHERE decision_id IN ("
        "SELECT id FROM paper_decision_snapshots WHERE decision_source = 'shadow'"
        ")"
    )
    op.execute(
        "DELETE FROM paper_decision_outcomes "
        "WHERE decision_id IN ("
        "SELECT id FROM paper_decision_snapshots WHERE decision_source = 'shadow'"
        ")"
    )
    op.execute("DELETE FROM paper_decision_snapshots WHERE decision_source = 'shadow'")

    # Drop dependants first.  This deletes only the retired shadow-wallet
    # records; paper_wallets, paper_positions, paper_trade_audit, and all
    # forward observations remain intact.
    op.drop_table("paper_shadow_decisions")
    op.drop_table("paper_shadow_trade_audit")
    op.drop_table("paper_shadow_positions")
    op.drop_table("paper_shadow_wallets")


def downgrade() -> None:
    # Intentionally irreversible: resurrecting an experimental wallet would
    # fabricate a live product state with no code to own it.
    pass
