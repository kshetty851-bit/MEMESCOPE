"""add confirmed real position ledger fields

Revision ID: 0022_real_position_ledger
Revises: 0021_live_execution_readiness
Create Date: 2026-08-09
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0022_real_position_ledger"
down_revision = "0021_live_execution_readiness"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "real_wallet_positions", sa.Column("wallet_public_key", sa.String(length=44))
    )
    op.add_column("real_wallet_positions", sa.Column("strategy_id", sa.String(length=64)))
    op.add_column("real_wallet_positions", sa.Column("strategy_version", sa.String(length=32)))
    op.add_column(
        "real_wallet_positions",
        sa.Column("entry_safety_evaluation_id", postgresql.UUID(as_uuid=True)),
    )
    op.add_column(
        "real_wallet_positions",
        sa.Column("entry_transaction_signature", sa.String(length=128)),
    )
    op.add_column(
        "real_wallet_positions",
        sa.Column("entry_actual_input_amount", sa.Numeric(precision=38, scale=18)),
    )
    op.add_column(
        "real_wallet_positions",
        sa.Column("entry_actual_output_amount", sa.Numeric(precision=38, scale=18)),
    )
    op.add_column(
        "real_wallet_positions", sa.Column("exit_intent_id", postgresql.UUID(as_uuid=True))
    )
    op.add_column(
        "real_wallet_positions", sa.Column("exit_transaction_signature", sa.String(length=128))
    )
    op.add_column(
        "real_wallet_positions",
        sa.Column("exit_actual_output_amount", sa.Numeric(precision=38, scale=18)),
    )
    op.add_column("real_wallet_positions", sa.Column("exit_reason", sa.String(length=64)))
    op.add_column(
        "real_wallet_positions",
        sa.Column("realised_gross_pnl_usd", sa.Numeric(precision=24, scale=4)),
    )
    op.add_column(
        "real_wallet_positions",
        sa.Column("realised_net_pnl_usd", sa.Numeric(precision=24, scale=4)),
    )
    op.create_foreign_key(
        "fk_real_position_entry_safety",
        "real_wallet_positions",
        "real_wallet_safety_evaluations",
        ["entry_safety_evaluation_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_real_position_exit_intent",
        "real_wallet_positions",
        "real_wallet_live_intents",
        ["exit_intent_id"],
        ["id"],
    )
    op.create_unique_constraint(
        "uq_real_position_entry_signature",
        "real_wallet_positions",
        ["entry_transaction_signature"],
    )
    op.create_unique_constraint(
        "uq_real_position_exit_signature",
        "real_wallet_positions",
        ["exit_transaction_signature"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_real_position_exit_signature", "real_wallet_positions", type_="unique"
    )
    op.drop_constraint(
        "uq_real_position_entry_signature", "real_wallet_positions", type_="unique"
    )
    op.drop_constraint(
        "fk_real_position_exit_intent", "real_wallet_positions", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_real_position_entry_safety", "real_wallet_positions", type_="foreignkey"
    )
    for column in (
        "realised_net_pnl_usd",
        "realised_gross_pnl_usd",
        "exit_reason",
        "exit_actual_output_amount",
        "exit_transaction_signature",
        "exit_intent_id",
        "entry_actual_output_amount",
        "entry_actual_input_amount",
        "entry_transaction_signature",
        "entry_safety_evaluation_id",
        "strategy_version",
        "strategy_id",
        "wallet_public_key",
    ):
        op.drop_column("real_wallet_positions", column)
