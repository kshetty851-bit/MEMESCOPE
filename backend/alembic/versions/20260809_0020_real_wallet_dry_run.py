"""append-only autonomous real-wallet dry-run decisions

Revision ID: 0020_real_wallet_dry_run
Revises: 0019_alpha_session_activity
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0020_real_wallet_dry_run"
down_revision = "0019_alpha_session_activity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "real_wallet_execution_intents",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("idempotency_key", sa.String(length=160), nullable=False),
        sa.Column("mint_address", sa.String(length=44), nullable=False),
        sa.Column("symbol", sa.String(length=64)),
        sa.Column("side", sa.String(length=8), nullable=False),
        sa.Column("mode", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("strategy_id", sa.String(length=64), nullable=False),
        sa.Column("strategy_version", sa.String(length=32), nullable=False),
        sa.Column("radar_rank", sa.Integer(), nullable=False),
        sa.Column("signal_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("requested_usd", sa.Numeric(24, 4), nullable=False),
        sa.Column("safety_evaluation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("safety_decision", sa.String(length=8)),
        sa.Column("reason_codes", postgresql.JSONB(), nullable=False),
        sa.Column("liquidity_usd", sa.Numeric(24, 4)),
        sa.Column("buy_impact_pct", sa.Numeric(20, 4)),
        sa.Column("sell_impact_pct", sa.Numeric(20, 4)),
        sa.Column("round_trip_loss_pct", sa.Numeric(20, 4)),
        sa.Column("buy_order", postgresql.JSONB()),
        sa.Column("sell_order", postgresql.JSONB()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["safety_evaluation_id"], ["real_wallet_safety_evaluations.id"]
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name="uq_real_wallet_execution_intent_key"),
    )
    op.create_index(
        "ix_real_wallet_execution_intent_evaluated",
        "real_wallet_execution_intents",
        ["evaluated_at"],
    )
    op.create_index(
        "ix_real_wallet_execution_intent_status", "real_wallet_execution_intents", ["status"]
    )
    op.create_table(
        "real_wallet_positions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("mint_address", sa.String(length=44), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("opened_intent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("quantity", sa.Numeric(38, 18), nullable=False),
        sa.Column("entry_price_usd", sa.Numeric(38, 18), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["opened_intent_id"], ["real_wallet_execution_intents.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("mint_address"),
    )


def downgrade() -> None:
    op.drop_table("real_wallet_positions")
    op.drop_index(
        "ix_real_wallet_execution_intent_status", table_name="real_wallet_execution_intents"
    )
    op.drop_index(
        "ix_real_wallet_execution_intent_evaluated", table_name="real_wallet_execution_intents"
    )
    op.drop_table("real_wallet_execution_intents")
