"""add live execution readiness persistence

Revision ID: 0021_live_execution_readiness
Revises: 0020_real_wallet_dry_run
Create Date: 2026-08-09
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0021_live_execution_readiness"
down_revision = "0020_real_wallet_dry_run"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "real_wallet_live_intents",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("idempotency_key", sa.String(length=160), nullable=False),
        sa.Column("mint_address", sa.String(length=44), nullable=False),
        sa.Column("side", sa.String(length=8), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("strategy_id", sa.String(length=64), nullable=False),
        sa.Column("strategy_version", sa.String(length=32), nullable=False),
        sa.Column("wallet_public_key", sa.String(length=44), nullable=False),
        sa.Column("position_id", postgresql.UUID(as_uuid=True)),
        sa.Column("safety_evaluation_id", postgresql.UUID(as_uuid=True)),
        sa.Column("requested_usd", sa.Numeric(precision=24, scale=4)),
        sa.Column("requested_token_quantity", sa.Numeric(precision=38, scale=18)),
        sa.Column("jupiter_request_id", sa.String(length=128)),
        sa.Column("order_evidence", postgresql.JSONB()),
        sa.Column("order_created_at", sa.DateTime(timezone=True)),
        sa.Column("submitted_at", sa.DateTime(timezone=True)),
        sa.Column("confirmed_at", sa.DateTime(timezone=True)),
        sa.Column("transaction_signature", sa.String(length=128)),
        sa.Column("failure_reason", sa.String(length=128)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["position_id"], ["real_wallet_positions.id"]),
        sa.ForeignKeyConstraint(
            ["safety_evaluation_id"], ["real_wallet_safety_evaluations.id"]
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key"),
        sa.UniqueConstraint("jupiter_request_id"),
        sa.UniqueConstraint("transaction_signature"),
    )
    op.create_index("ix_real_wallet_live_intent_state", "real_wallet_live_intents", ["state"])
    op.create_index(
        "ix_real_wallet_live_intent_mint", "real_wallet_live_intents", ["mint_address"]
    )
    op.create_table(
        "real_wallet_execution_events",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("intent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("detail", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["intent_id"], ["real_wallet_live_intents.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_real_wallet_execution_event_intent", "real_wallet_execution_events", ["intent_id"]
    )
    op.create_table(
        "real_wallet_kill_switches",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("reason", sa.String(length=256)),
        sa.Column("activated_at", sa.DateTime(timezone=True)),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("kind"),
    )


def downgrade() -> None:
    op.drop_table("real_wallet_kill_switches")
    op.drop_index(
        "ix_real_wallet_execution_event_intent", table_name="real_wallet_execution_events"
    )
    op.drop_table("real_wallet_execution_events")
    op.drop_index("ix_real_wallet_live_intent_mint", table_name="real_wallet_live_intents")
    op.drop_index("ix_real_wallet_live_intent_state", table_name="real_wallet_live_intents")
    op.drop_table("real_wallet_live_intents")
