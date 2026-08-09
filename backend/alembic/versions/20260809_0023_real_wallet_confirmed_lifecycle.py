"""add confirmed test-only real-wallet lifecycle ledger

Revision ID: 0023_real_wallet_confirmed_lifecycle
Revises: 0022_real_position_ledger
Create Date: 2026-08-09
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0023_wallet_lifecycle"
down_revision = "0022_real_position_ledger"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Existing pre-lifecycle rows retain their dry-run intent link. New rows
    # instead link to the confirmed live BUY intent; this additive migration
    # never rewrites historical evidence.
    op.alter_column("real_wallet_positions", "opened_intent_id", nullable=True)
    op.add_column(
        "real_wallet_positions",
        sa.Column("opened_live_intent_id", postgresql.UUID(as_uuid=True)),
    )
    op.create_foreign_key(
        "fk_real_position_opened_live_intent",
        "real_wallet_positions",
        "real_wallet_live_intents",
        ["opened_live_intent_id"],
        ["id"],
    )
    op.create_unique_constraint(
        "uq_real_position_opened_live_intent",
        "real_wallet_positions",
        ["opened_live_intent_id"],
    )
    op.drop_constraint("uq_real_wallet_positions_mint_address", "real_wallet_positions")
    op.create_index(
        "uq_real_wallet_open_position_mint",
        "real_wallet_positions",
        ["mint_address"],
        unique=True,
        postgresql_where=sa.text("status = 'OPEN'"),
    )
    op.add_column(
        "real_wallet_positions", sa.Column("entry_network_fee_lamports", sa.BigInteger())
    )
    op.add_column(
        "real_wallet_positions",
        sa.Column("exit_actual_input_amount", sa.Numeric(precision=38, scale=18)),
    )
    op.add_column(
        "real_wallet_positions", sa.Column("exit_network_fee_lamports", sa.BigInteger())
    )

    op.add_column("real_wallet_live_intents", sa.Column("input_mint", sa.String(length=44)))
    op.add_column("real_wallet_live_intents", sa.Column("output_mint", sa.String(length=44)))
    op.add_column(
        "real_wallet_live_intents",
        sa.Column("actual_input_amount_raw", sa.Numeric(precision=38, scale=0)),
    )
    op.add_column("real_wallet_live_intents", sa.Column("actual_input_decimals", sa.Integer()))
    op.add_column(
        "real_wallet_live_intents",
        sa.Column("actual_output_amount_raw", sa.Numeric(precision=38, scale=0)),
    )
    op.add_column(
        "real_wallet_live_intents", sa.Column("actual_output_decimals", sa.Integer())
    )
    op.add_column(
        "real_wallet_live_intents", sa.Column("network_fee_lamports", sa.BigInteger())
    )

    op.create_table(
        "real_wallet_execution_health",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("scope", sa.String(length=64), nullable=False),
        sa.Column("consecutive_failures", sa.Integer(), nullable=False),
        sa.Column("last_failure_reason", sa.String(length=128)),
        sa.Column("last_failure_at", sa.DateTime(timezone=True)),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("scope"),
    )


def downgrade() -> None:
    op.drop_table("real_wallet_execution_health")
    for column in (
        "network_fee_lamports",
        "actual_output_decimals",
        "actual_output_amount_raw",
        "actual_input_decimals",
        "actual_input_amount_raw",
        "output_mint",
        "input_mint",
    ):
        op.drop_column("real_wallet_live_intents", column)
    for column in (
        "exit_network_fee_lamports",
        "exit_actual_input_amount",
        "entry_network_fee_lamports",
    ):
        op.drop_column("real_wallet_positions", column)
    op.drop_index("uq_real_wallet_open_position_mint", table_name="real_wallet_positions")
    op.create_unique_constraint(
        "uq_real_wallet_positions_mint_address", "real_wallet_positions", ["mint_address"]
    )
    op.drop_constraint(
        "uq_real_position_opened_live_intent", "real_wallet_positions", type_="unique"
    )
    op.drop_constraint(
        "fk_real_position_opened_live_intent", "real_wallet_positions", type_="foreignkey"
    )
    op.drop_column("real_wallet_positions", "opened_live_intent_id")
    op.alter_column("real_wallet_positions", "opened_intent_id", nullable=False)
