"""Give the kill switch a way out, and make a signature durable before submission.

## The kill switch

`real_wallet_kill_switches` could be armed and never cleared. There was no clear
function anywhere in the codebase — only `activate_kill_switch`. A switch with
no exit is a switch whose first automatic arming permanently ends execution, so
the only way back is an `UPDATE` typed by hand into production: untracked,
unattributed, and indistinguishable afterwards from a switch never armed at all.

So clearing becomes a first-class attributed operation. The switch row records
who armed and who cleared, and `real_wallet_kill_switch_events` keeps the whole
arm/clear sequence rather than only the row's current state — the switch row
answers "is execution blocked right now", the event table answers "how many
times has this happened and who decided".

**Written to converge rather than to assert**, in the same spirit as 0041. The
deployed database already carried `actor`, `cleared_at`, `cleared_by` and
`cleared_reason` on this table with no migration behind them — added by hand at
some point and never reflected in the model, which is why the first run of this
migration failed on `column "cleared_at" already exists`. The columns are the
right ones, so this adopts them instead of adding a parallel set: the model now
maps `actor`, and every statement here is idempotent. An audit column is a
structural fact; converging on "it exists" is correct however it got there.

Additive and reversible. No existing row changes meaning, and an armed switch
stays armed across this migration.

## The signature index

`real_wallet_live_intents.transaction_signature` was only ever written *after*
`/execute` answered. That is one moment too late: if the response is lost — a
timeout, a killed worker, a dropped connection — the transaction may well have
landed, and nothing durable names it. The intent then sits in `SUBMITTED`
forever, because reconciliation looks a transaction up by signature and there is
no signature to look up. "Never blindly resubmit" held; "the chain decides the
final state" did not, because the chain could not be asked.

An ed25519 signature is deterministic in the key and the message, so it is known
the instant the signer produces it, before any network call. Persisting it at
`SIGNED` makes a lost response reconcilable, and the unique index makes the same
value serve as the replay guard: a second attempt to sign the same message
cannot be recorded twice.

Partial (`WHERE ... IS NOT NULL`), so the many intents that never reach a
signature are unaffected.

Revision ID: 0042_kill_switch_clear
Revises: 0041_retention_fk_idx
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0042_kill_switch_clear"
down_revision = "0041_retention_fk_idx"
branch_labels = None
depends_on = None

_COLUMNS = (
    ("actor", "VARCHAR(128)"),
    ("cleared_at", "TIMESTAMP WITH TIME ZONE"),
    ("cleared_by", "VARCHAR(128)"),
    ("cleared_reason", "VARCHAR(256)"),
)


def upgrade() -> None:
    for name, column_type in _COLUMNS:
        op.execute(
            sa.text(
                "ALTER TABLE real_wallet_kill_switches "
                f"ADD COLUMN IF NOT EXISTS {name} {column_type}"
            )
        )
    op.execute(
        sa.text(
            """
            CREATE TABLE IF NOT EXISTS real_wallet_kill_switch_events (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                kind VARCHAR(64) NOT NULL,
                action VARCHAR(16) NOT NULL,
                actor VARCHAR(128),
                reason VARCHAR(256) NOT NULL,
                created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
            )
            """
        )
    )
    op.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_real_wallet_kill_switch_event_kind "
            "ON real_wallet_kill_switch_events (kind)"
        )
    )
    op.execute(
        sa.text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_real_wallet_live_intent_signature "
            "ON real_wallet_live_intents (transaction_signature) "
            "WHERE transaction_signature IS NOT NULL"
        )
    )


def downgrade() -> None:
    op.execute(sa.text("DROP INDEX IF EXISTS uq_real_wallet_live_intent_signature"))
    op.execute(sa.text("DROP TABLE IF EXISTS real_wallet_kill_switch_events"))
    for name, _ in _COLUMNS:
        op.execute(
            sa.text(f"ALTER TABLE real_wallet_kill_switches DROP COLUMN IF EXISTS {name}")
        )
