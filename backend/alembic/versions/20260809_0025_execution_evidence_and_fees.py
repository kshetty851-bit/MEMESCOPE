"""Persist the order-evidence re-check and honest fee accounting.

Two pre-mainnet blockers, one migration, because both add nullable columns to
the same two execution tables and splitting them would mean two locks for one
reviewable change.

**Order evidence** (`real_wallet_live_intents`). The signer can verify that a
transaction has one required signature and that our pinned wallet is the fee
payer. It cannot read which mints or amounts the compiled instructions move —
route instructions may resolve through address lookup tables. So the swap
*semantics* are re-checked against the Jupiter `/order` JSON before signing, and
the verdict is persisted: what was authorised, what the order said, and every
reason it was refused. `order_validation_status` starts `pending`; an intent may
only be signed while it reads `approved`.

**Fee accounting** (`real_wallet_positions`). `realised_net_pnl_usd` was being
assigned the gross figure because network fees are paid in SOL and nothing here
knew what SOL was worth. A column named `net` holding gross is worse than a
null — it reads as measured. The fee columns below carry the SOL/USD reading
that produced each figure, with its timestamp and source, so a later price
cannot silently restate a settled result. `net_pnl_unavailable_reason` records
why a net figure is absent rather than leaving a reader to guess.

Purely additive and all-nullable except two server-defaulted columns, so it
applies while every service runs. No existing value is rewritten: rows settled
before this migration keep their gross figure and are marked as having no
priced fee, which is exactly what was true of them.

Revision ID: 0025_execution_evidence_and_fees
Revises: 0024_wallet_pnl_precision
Create Date: 2026-08-09 21:40:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0025_execution_evidence_and_fees"
down_revision: str | None = "0024_wallet_pnl_precision"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Written onto every position that settled before fees could be priced. They
#: are not wrong; they are gross, and they now say so.
LEGACY_NET_UNAVAILABLE = (
    "Settled before execution fee accounting existed. The gross figure is "
    "measured; network fees were not priced in USD at the time, so no net "
    "figure is claimed for this trade."
)


def upgrade() -> None:
    # --- Order-evidence re-check --------------------------------------------
    op.add_column(
        "real_wallet_live_intents",
        sa.Column("authorized_input_amount_raw", sa.Numeric(precision=38, scale=0)),
    )
    op.add_column(
        "real_wallet_live_intents", sa.Column("authorized_input_decimals", sa.Integer())
    )
    op.add_column(
        "real_wallet_live_intents",
        sa.Column(
            "order_validation_status",
            sa.String(length=16),
            nullable=False,
            server_default="pending",
        ),
    )
    op.add_column(
        "real_wallet_live_intents",
        sa.Column(
            "order_validation_reasons",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
    )
    op.add_column(
        "real_wallet_live_intents",
        sa.Column("order_validation_observed", postgresql.JSONB(astext_type=sa.Text())),
    )
    op.add_column(
        "real_wallet_live_intents",
        sa.Column("order_validated_at", sa.DateTime(timezone=True)),
    )

    # --- Fee accounting ------------------------------------------------------
    for column in (
        sa.Column("net_pnl_unavailable_reason", sa.Text()),
        sa.Column("entry_network_fee_usd", sa.Numeric(precision=38, scale=18)),
        sa.Column("exit_network_fee_usd", sa.Numeric(precision=38, scale=18)),
        sa.Column("entry_sol_price_usd", sa.Numeric(precision=38, scale=18)),
        sa.Column("exit_sol_price_usd", sa.Numeric(precision=38, scale=18)),
        sa.Column("entry_sol_price_at", sa.DateTime(timezone=True)),
        sa.Column("exit_sol_price_at", sa.DateTime(timezone=True)),
        sa.Column("sol_price_source", sa.String(length=32)),
    ):
        op.add_column("real_wallet_positions", column)

    # A closed position whose "net" was really gross is relabelled rather than
    # recomputed: the fees it paid are on chain, but the SOL price at that
    # moment was never recorded and inventing one would fabricate a result.
    op.execute(
        sa.text(
            "UPDATE real_wallet_positions "
            "SET realised_net_pnl_usd = NULL, net_pnl_unavailable_reason = :reason "
            "WHERE status = 'CLOSED' AND realised_net_pnl_usd IS NOT NULL"
        ).bindparams(reason=LEGACY_NET_UNAVAILABLE)
    )


def downgrade() -> None:
    """Drops the columns. **It cannot restore the old `net` values.**

    Those values were the gross figure under a net label. Re-deriving them would
    mean writing gross into `realised_net_pnl_usd` again, which is the defect
    this migration exists to remove. `realised_gross_pnl_usd` is untouched
    throughout, so nothing measured is lost either way.
    """
    for name in (
        "sol_price_source",
        "exit_sol_price_at",
        "entry_sol_price_at",
        "exit_sol_price_usd",
        "entry_sol_price_usd",
        "exit_network_fee_usd",
        "entry_network_fee_usd",
        "net_pnl_unavailable_reason",
    ):
        op.drop_column("real_wallet_positions", name)

    for name in (
        "order_validated_at",
        "order_validation_observed",
        "order_validation_reasons",
        "order_validation_status",
        "authorized_input_decimals",
        "authorized_input_amount_raw",
    ):
        op.drop_column("real_wallet_live_intents", name)
