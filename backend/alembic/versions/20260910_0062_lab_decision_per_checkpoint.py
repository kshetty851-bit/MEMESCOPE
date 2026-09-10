"""A decision is unique per (arm, mint, CHECKPOINT), not per (arm, mint).

Revision ID: 0062_lab_decision_per_checkpoint
Revises: 0061_kol_wallet_ranks
Create Date: 2026-09-10

`uq_lab_decision_once` said a token is judged once per arm, for ever. The
Matrix Lab's AGED section is a rolling SAMPLE of established tokens and is
meant to re-draw a token six hours later (`REJUDGE_BY_SOURCE`); the first
re-draw, at 00:33Z on 2026-09-10 — six hours forty minutes after activation —
violated the constraint, rolled back the whole tick, and kept doing so on most
minutes after, because a random draw from a pool that has all been judged
once lands on a judged token more often than not. Three hours of a
twenty-four-wallet tournament went unmarked and unsettled.

Keying on the checkpoint keeps every judgement a permanent, distinct record:
a launch has one checkpoint per arm and is still judged once; a sample has a
new checkpoint on every draw. Nothing here is a downgrade hazard — the new
constraint is strictly looser and the old one is restored on downgrade only
if no arm has judged a mint twice by then.
"""

from __future__ import annotations

from alembic import op

revision = "0062_lab_decision_per_checkpoint"
down_revision = "0061_kol_wallet_ranks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("uq_lab_decision_once", "lab_decisions", type_="unique")
    op.create_unique_constraint(
        "uq_lab_decision_per_checkpoint", "lab_decisions",
        ["strategy_row_id", "mint_address", "checkpoint_at"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_lab_decision_per_checkpoint", "lab_decisions", type_="unique")
    op.create_unique_constraint(
        "uq_lab_decision_once", "lab_decisions", ["strategy_row_id", "mint_address"],
    )
