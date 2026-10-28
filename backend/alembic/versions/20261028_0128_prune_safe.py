"""Free disk (Karthik, 2026-10-28: "do your suggestion, delete the safe ones").

* grad_curve_samples: emptied. Curve polling has been off since 15 Oct; nothing
  writes or reads it.
* lab_decisions before 28 Sep (the old V6/V7 and DEX tournaments): deleted,
  except any a lab position points at or a real-wallet intent matches.
* grad_tokens that never graduated, first seen before 14 Oct: deleted, except
  any a paper position names. The labs read graduated coins only.

Dates are fixed so the migration means the same thing whenever it runs.
Intentionally irreversible, like 0126/0127. The space returns to the disk with a
VACUUM FULL of the two smaller tables, run separately (outside a transaction).
"""

from __future__ import annotations

from alembic import op

revision: str = "0128_prune_safe"
down_revision: str = "0127_remove_longwatch"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("TRUNCATE grad_curve_samples")
    op.execute("""
        DELETE FROM lab_decisions d
        WHERE d.created_at < '2026-09-28'
          AND NOT EXISTS (SELECT 1 FROM lab_positions p WHERE p.decision_id = d.id)
          AND NOT EXISTS (SELECT 1 FROM real_wallet_live_intents i
                          WHERE i.mint_address = d.mint_address AND i.strategy_id = d.strategy_id)""")
    op.execute("""
        DELETE FROM grad_tokens t
        WHERE t.migrated_at IS NULL AND t.first_seen_at < '2026-10-14'
          AND NOT EXISTS (SELECT 1 FROM grad_migrations m WHERE m.mint = t.mint)
          AND NOT EXISTS (SELECT 1 FROM grad_paper_positions p WHERE p.mint = t.mint)""")


def downgrade() -> None:
    raise NotImplementedError("0128 deleted records; there is nothing to restore")
