"""Persist Phase 2 devnet-only manual transaction evidence."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0036_real_wallet_devnet_manual"
down_revision = "0035_resume_generation_2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "real_wallet_devnet_quotes",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("wallet_public_key", sa.String(44), nullable=False),
        sa.Column("input_mint", sa.String(44), nullable=False),
        sa.Column("output_mint", sa.String(44), nullable=False),
        sa.Column("input_amount_raw", sa.Numeric(38, 0), nullable=False),
        sa.Column("expected_output_raw", sa.Numeric(38, 0), nullable=False),
        sa.Column("minimum_output_raw", sa.Numeric(38, 0), nullable=False),
        sa.Column("slippage_bps", sa.Integer(), nullable=False),
        sa.Column("price_impact_pct", sa.Numeric(20, 8)),
        sa.Column("estimated_fee_lamports", sa.BigInteger()),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("route", postgresql.JSONB()),
        sa.Column("quoted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("provider_payload", postgresql.JSONB()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_table(
        "real_wallet_devnet_intents",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("idempotency_key", sa.String(160), nullable=False, unique=True),
        sa.Column("wallet_public_key", sa.String(44), nullable=False),
        sa.Column("network", sa.String(16), nullable=False, server_default="devnet"),
        sa.Column("action_type", sa.String(32), nullable=False),
        sa.Column("input_mint", sa.String(44), nullable=False),
        sa.Column("output_mint", sa.String(44)),
        sa.Column("input_amount_raw", sa.Numeric(38, 0), nullable=False),
        sa.Column(
            "quote_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("real_wallet_devnet_quotes.id"),
        ),
        sa.Column("state", sa.String(32), nullable=False, server_default="DRAFT"),
        sa.Column("simulation_status", sa.String(32)),
        sa.Column("approval_status", sa.String(32)),
        sa.Column("signing_status", sa.String(32)),
        sa.Column("submission_status", sa.String(32)),
        sa.Column("quote_expires_at", sa.DateTime(timezone=True)),
        sa.Column("approval_expires_at", sa.DateTime(timezone=True)),
        sa.Column("transaction_signature", sa.String(128), unique=True),
        sa.Column("failure_reason", sa.Text()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_real_wallet_devnet_intent_state", "real_wallet_devnet_intents", ["state"]
    )
    op.create_table(
        "real_wallet_devnet_events",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "intent_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("real_wallet_devnet_intents.id"),
            nullable=False,
        ),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column(
            "detail", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_real_wallet_devnet_event_intent", "real_wallet_devnet_events", ["intent_id"]
    )


def downgrade() -> None:
    op.drop_table("real_wallet_devnet_events")
    op.drop_table("real_wallet_devnet_intents")
    op.drop_table("real_wallet_devnet_quotes")
