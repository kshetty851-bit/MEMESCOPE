"""Add Phase 2 manual-devnet execution evidence.

Revision ID: 0037_real_wallet_devnet_exec
Revises: 0036_real_wallet_devnet_manual
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# ``alembic_version.version_num`` in already-deployed MEMESCOPE databases is
# varchar(32), so this identifier must remain within that established limit.
revision = "0037_real_wallet_devnet_exec"
down_revision = "0036_real_wallet_devnet_manual"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Alembic has no ``op.create_sequence`` helper. Keep this as explicit,
    # transactional PostgreSQL DDL so the event order is globally monotonic
    # without depending on a non-existent operation proxy method.
    op.execute("CREATE SEQUENCE real_wallet_devnet_event_order_seq")
    op.add_column(
        "real_wallet_devnet_events",
        sa.Column(
            "event_order",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text("nextval('real_wallet_devnet_event_order_seq')"),
        ),
    )
    op.create_index(
        "ix_real_wallet_devnet_event_intent_order",
        "real_wallet_devnet_events",
        ["intent_id", "event_order"],
    )
    op.add_column(
        "real_wallet_devnet_quotes",
        sa.Column("network", sa.String(16), nullable=False, server_default="devnet"),
    )
    op.add_column("real_wallet_devnet_quotes", sa.Column("provider_reference", sa.String(256)))
    op.add_column(
        "real_wallet_devnet_intents", sa.Column("destination_public_key", sa.String(44))
    )
    op.add_column(
        "real_wallet_devnet_intents",
        sa.Column("approved_by_user_id", postgresql.UUID(as_uuid=True)),
    )
    op.add_column(
        "real_wallet_devnet_intents", sa.Column("approved_at", sa.DateTime(timezone=True))
    )
    op.add_column("real_wallet_devnet_intents", sa.Column("transaction_base64", sa.Text()))
    op.add_column(
        "real_wallet_devnet_intents", sa.Column("transaction_fingerprint", sa.String(64))
    )
    op.add_column(
        "real_wallet_devnet_intents", sa.Column("transaction_metadata", postgresql.JSONB())
    )
    op.add_column(
        "real_wallet_devnet_intents", sa.Column("simulation_result", postgresql.JSONB())
    )
    op.add_column(
        "real_wallet_devnet_intents", sa.Column("simulation_logs", postgresql.JSONB())
    )
    op.add_column(
        "real_wallet_devnet_intents", sa.Column("simulation_units_consumed", sa.BigInteger())
    )
    op.add_column(
        "real_wallet_devnet_intents", sa.Column("simulation_context_slot", sa.BigInteger())
    )
    op.add_column(
        "real_wallet_devnet_intents", sa.Column("simulation_blockhash", sa.String(64))
    )
    op.add_column(
        "real_wallet_devnet_intents", sa.Column("simulated_at", sa.DateTime(timezone=True))
    )
    op.add_column(
        "real_wallet_devnet_intents", sa.Column("signer_validation", postgresql.JSONB())
    )
    op.add_column(
        "real_wallet_devnet_intents", sa.Column("signed_transaction_base64", sa.Text())
    )
    op.add_column(
        "real_wallet_devnet_intents", sa.Column("signed_at", sa.DateTime(timezone=True))
    )
    op.add_column("real_wallet_devnet_intents", sa.Column("rpc_endpoint", sa.String(512)))
    op.add_column(
        "real_wallet_devnet_intents", sa.Column("submitted_at", sa.DateTime(timezone=True))
    )
    op.add_column(
        "real_wallet_devnet_intents",
        sa.Column("submission_retry_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("real_wallet_devnet_intents", sa.Column("submission_error", sa.Text()))
    op.add_column(
        "real_wallet_devnet_intents", sa.Column("confirmation_status", sa.String(32))
    )
    op.add_column(
        "real_wallet_devnet_intents", sa.Column("confirmation_slot", sa.BigInteger())
    )
    op.add_column(
        "real_wallet_devnet_intents", sa.Column("confirmed_at", sa.DateTime(timezone=True))
    )
    op.add_column(
        "real_wallet_devnet_intents", sa.Column("reconciliation", postgresql.JSONB())
    )
    op.add_column(
        "real_wallet_devnet_intents", sa.Column("reconciled_at", sa.DateTime(timezone=True))
    )


def downgrade() -> None:
    op.drop_index("ix_real_wallet_devnet_event_intent_order", "real_wallet_devnet_events")
    op.drop_column("real_wallet_devnet_events", "event_order")
    op.execute("DROP SEQUENCE real_wallet_devnet_event_order_seq")
    for column in (
        "reconciled_at",
        "reconciliation",
        "confirmed_at",
        "confirmation_slot",
        "confirmation_status",
        "submission_error",
        "submission_retry_count",
        "submitted_at",
        "rpc_endpoint",
        "signed_at",
        "signed_transaction_base64",
        "signer_validation",
        "simulated_at",
        "simulation_blockhash",
        "simulation_context_slot",
        "simulation_units_consumed",
        "simulation_logs",
        "simulation_result",
        "transaction_metadata",
        "transaction_fingerprint",
        "transaction_base64",
        "approved_at",
        "approved_by_user_id",
        "destination_public_key",
    ):
        op.drop_column("real_wallet_devnet_intents", column)
    op.drop_column("real_wallet_devnet_quotes", "provider_reference")
    op.drop_column("real_wallet_devnet_quotes", "network")
