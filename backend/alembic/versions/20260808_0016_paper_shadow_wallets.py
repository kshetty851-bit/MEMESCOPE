"""paper shadow wallets

Revision ID: 20260808_0016
Revises: 0015_jupiter_execution_model
Create Date: 2026-08-08 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0016_paper_shadow_wallets"
down_revision = "0015_jupiter_execution_model"
branch_labels = None
depends_on = None


def _json() -> sa.JSON:
    return postgresql.JSONB().with_variant(sa.JSON(), "sqlite")


def upgrade() -> None:
    op.create_table(
        "paper_shadow_wallets",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("wallet_code", sa.String(length=16), nullable=False),
        sa.Column("strategy_id", sa.String(length=64), nullable=False),
        sa.Column("strategy_version", sa.String(length=32), nullable=False),
        sa.Column("display_name", sa.String(length=64), nullable=False),
        sa.Column("starting_balance", sa.Numeric(24, 4), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_paper_shadow_wallets")),
        sa.UniqueConstraint("wallet_code", name="uq_paper_shadow_wallets_code"),
    )
    op.create_index(
        "ix_paper_shadow_wallets_created_at", "paper_shadow_wallets", ["created_at"]
    )

    op.create_table(
        "paper_shadow_positions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("shadow_wallet_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("mint_address", sa.String(length=44), nullable=False),
        sa.Column("token_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("entry_rank", sa.Integer(), nullable=False),
        sa.Column("entry_price", sa.Numeric(38, 18), nullable=False),
        sa.Column("entry_observed_price", sa.Numeric(38, 18), nullable=True),
        sa.Column("size_usd", sa.Numeric(24, 4), nullable=False),
        sa.Column("quantity", sa.Numeric(48, 18), nullable=False),
        sa.Column("trailing_drawdown", sa.Numeric(6, 4), nullable=False),
        sa.Column("entry_market_cap", sa.Numeric(24, 4), nullable=True),
        sa.Column("entry_liquidity_usd", sa.Numeric(24, 4), nullable=True),
        sa.Column("entry_radar_score", sa.Numeric(20, 4), nullable=True),
        sa.Column("entry_confidence", sa.Numeric(20, 4), nullable=True),
        sa.Column("entry_token_age_seconds", sa.Integer(), nullable=True),
        sa.Column("entry_volume_24h", sa.Numeric(24, 4), nullable=True),
        sa.Column("entry_execution_quality", sa.String(length=8), nullable=True),
        sa.Column("entry_execution_model_version", sa.String(length=64), nullable=True),
        sa.Column("entry_execution_quote", _json(), nullable=True),
        sa.Column("entry_execution_quoted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("entry_execution_context_slot", sa.Integer(), nullable=True),
        sa.Column("entry_execution_price_impact_pct", sa.Numeric(20, 4), nullable=True),
        sa.Column("entry_execution_fee_usd", sa.Numeric(24, 4), nullable=True),
        sa.Column("entry_execution_route", sa.Text(), nullable=True),
        sa.Column("entry_execution_confidence", sa.String(length=32), nullable=True),
        sa.Column("entry_execution_fallback_reason", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("peak_price", sa.Numeric(38, 18), nullable=False),
        sa.Column("last_evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("exit_price", sa.Numeric(38, 18), nullable=True),
        sa.Column("exit_observed_price", sa.Numeric(38, 18), nullable=True),
        sa.Column("exit_reason", sa.String(length=16), nullable=True),
        sa.Column("exit_execution_model_version", sa.String(length=64), nullable=True),
        sa.Column("exit_execution_quote", _json(), nullable=True),
        sa.Column("exit_execution_quoted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("exit_execution_context_slot", sa.Integer(), nullable=True),
        sa.Column("exit_execution_price_impact_pct", sa.Numeric(20, 4), nullable=True),
        sa.Column("exit_execution_fee_usd", sa.Numeric(24, 4), nullable=True),
        sa.Column("exit_execution_route", sa.Text(), nullable=True),
        sa.Column("exit_execution_confidence", sa.String(length=32), nullable=True),
        sa.Column("exit_execution_fallback_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["shadow_wallet_id"],
            ["paper_shadow_wallets.id"],
            name=op.f("fk_paper_shadow_positions_shadow_wallet_id_paper_shadow_wallets"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["token_id"],
            ["discovered_tokens.id"],
            name=op.f("fk_paper_shadow_positions_token_id_discovered_tokens"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_paper_shadow_positions")),
        sa.UniqueConstraint(
            "shadow_wallet_id", "mint_address", name="uq_paper_shadow_positions_wallet_mint"
        ),
    )
    op.create_index(
        "ix_paper_shadow_positions_open_watermark",
        "paper_shadow_positions",
        ["shadow_wallet_id", "last_evaluated_at"],
        postgresql_where=sa.text("status = 'open'"),
    )
    op.create_index(
        "ix_paper_shadow_positions_closed_at",
        "paper_shadow_positions",
        ["shadow_wallet_id", "closed_at"],
    )
    op.create_index(
        "ix_paper_shadow_positions_mint", "paper_shadow_positions", ["mint_address"]
    )
    op.create_index(
        "ix_paper_shadow_positions_created_at", "paper_shadow_positions", ["created_at"]
    )

    op.create_table(
        "paper_shadow_trade_audit",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("position_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("shadow_wallet_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("wallet_code", sa.String(length=16), nullable=False),
        sa.Column("mint_address", sa.String(length=44), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=True),
        sa.Column("entry_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("entry_price", sa.Numeric(38, 18), nullable=False),
        sa.Column("entry_observed_price", sa.Numeric(38, 18), nullable=True),
        sa.Column("entry_market_cap", sa.Numeric(24, 4), nullable=True),
        sa.Column("entry_liquidity_usd", sa.Numeric(24, 4), nullable=True),
        sa.Column("size_usd", sa.Numeric(24, 4), nullable=False),
        sa.Column("quantity", sa.Numeric(48, 18), nullable=False),
        sa.Column("exit_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("exit_price", sa.Numeric(38, 18), nullable=False),
        sa.Column("exit_observed_price", sa.Numeric(38, 18), nullable=True),
        sa.Column("exit_market_cap", sa.Numeric(24, 4), nullable=True),
        sa.Column("exit_liquidity_usd", sa.Numeric(24, 4), nullable=True),
        sa.Column("gross_return_usd", sa.Numeric(24, 4), nullable=False),
        sa.Column("gross_return_pct", sa.Numeric(20, 4), nullable=False),
        sa.Column("fee_usd", sa.Numeric(24, 4), nullable=True),
        sa.Column("slippage_usd", sa.Numeric(24, 4), nullable=True),
        sa.Column("net_return_usd", sa.Numeric(24, 4), nullable=True),
        sa.Column("net_return_pct", sa.Numeric(20, 4), nullable=True),
        sa.Column("cost_unavailable_reason", sa.Text(), nullable=True),
        sa.Column("exit_reason", sa.String(length=16), nullable=False),
        sa.Column("strategy_id", sa.String(length=64), nullable=False),
        sa.Column("strategy_version", sa.String(length=32), nullable=False),
        sa.Column("wallet_generation", sa.Integer(), nullable=False),
        sa.Column("swap_fee_bps", sa.Numeric(10, 4), nullable=True),
        sa.Column("execution_model_version", sa.String(length=64), nullable=True),
        sa.Column("entry_execution_model_version", sa.String(length=64), nullable=True),
        sa.Column("exit_execution_model_version", sa.String(length=64), nullable=True),
        sa.Column("entry_execution_quote", _json(), nullable=True),
        sa.Column("exit_execution_quote", _json(), nullable=True),
        sa.Column("entry_execution_quoted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("exit_execution_quoted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("entry_execution_context_slot", sa.Integer(), nullable=True),
        sa.Column("exit_execution_context_slot", sa.Integer(), nullable=True),
        sa.Column("entry_execution_price_impact_pct", sa.Numeric(20, 4), nullable=True),
        sa.Column("exit_execution_price_impact_pct", sa.Numeric(20, 4), nullable=True),
        sa.Column("entry_execution_fee_usd", sa.Numeric(24, 4), nullable=True),
        sa.Column("exit_execution_fee_usd", sa.Numeric(24, 4), nullable=True),
        sa.Column("entry_execution_route", sa.Text(), nullable=True),
        sa.Column("exit_execution_route", sa.Text(), nullable=True),
        sa.Column("execution_confidence", sa.String(length=32), nullable=True),
        sa.Column("execution_fallback_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["position_id"],
            ["paper_shadow_positions.id"],
            name=op.f("fk_paper_shadow_trade_audit_position_id_paper_shadow_positions"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["shadow_wallet_id"],
            ["paper_shadow_wallets.id"],
            name=op.f("fk_paper_shadow_trade_audit_shadow_wallet_id_paper_shadow_wallets"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_paper_shadow_trade_audit")),
        sa.UniqueConstraint("position_id", name="uq_paper_shadow_trade_audit_position"),
    )
    op.create_index(
        "ix_paper_shadow_trade_audit_wallet_exit",
        "paper_shadow_trade_audit",
        ["shadow_wallet_id", "exit_at"],
    )
    op.create_index(
        "ix_paper_shadow_trade_audit_mint", "paper_shadow_trade_audit", ["mint_address"]
    )
    op.create_index(
        "ix_paper_shadow_trade_audit_created_at",
        "paper_shadow_trade_audit",
        ["created_at"],
    )

    op.create_table(
        "paper_shadow_decisions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("shadow_wallet_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("wallet_code", sa.String(length=16), nullable=False),
        sa.Column("strategy_id", sa.String(length=64), nullable=False),
        sa.Column("strategy_version", sa.String(length=32), nullable=False),
        sa.Column("mint_address", sa.String(length=44), nullable=False),
        sa.Column("token_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("radar_rank", sa.Integer(), nullable=False),
        sa.Column("radar_evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decision", sa.String(length=16), nullable=False),
        sa.Column("reason_codes", _json(), nullable=False),
        sa.Column("radar_score", sa.Numeric(20, 4), nullable=True),
        sa.Column("radar_confidence", sa.Numeric(20, 4), nullable=True),
        sa.Column("market_cap", sa.Numeric(24, 4), nullable=True),
        sa.Column("liquidity_usd", sa.Numeric(24, 4), nullable=True),
        sa.Column("volume_24h", sa.Numeric(24, 4), nullable=True),
        sa.Column("token_age_seconds", sa.Integer(), nullable=True),
        sa.Column("entry_impact_pct", sa.Numeric(20, 4), nullable=True),
        sa.Column("execution_quality", sa.String(length=8), nullable=True),
        sa.Column("execution_model_version", sa.String(length=64), nullable=True),
        sa.Column("execution_confidence", sa.String(length=32), nullable=True),
        sa.Column("execution_fallback_reason", sa.Text(), nullable=True),
        sa.Column("position_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["position_id"],
            ["paper_shadow_positions.id"],
            name=op.f("fk_paper_shadow_decisions_position_id_paper_shadow_positions"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["shadow_wallet_id"],
            ["paper_shadow_wallets.id"],
            name=op.f("fk_paper_shadow_decisions_shadow_wallet_id_paper_shadow_wallets"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["token_id"],
            ["discovered_tokens.id"],
            name=op.f("fk_paper_shadow_decisions_token_id_discovered_tokens"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_paper_shadow_decisions")),
        sa.UniqueConstraint(
            "wallet_code",
            "mint_address",
            "radar_evaluated_at",
            name="uq_paper_shadow_decisions_wallet_mint_eval",
        ),
    )
    op.create_index(
        "ix_paper_shadow_decisions_wallet_at",
        "paper_shadow_decisions",
        ["wallet_code", "decided_at"],
    )
    op.create_index(
        "ix_paper_shadow_decisions_mint", "paper_shadow_decisions", ["mint_address"]
    )
    op.create_index(
        "ix_paper_shadow_decisions_created_at", "paper_shadow_decisions", ["created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_paper_shadow_decisions_created_at", table_name="paper_shadow_decisions")
    op.drop_index("ix_paper_shadow_decisions_mint", table_name="paper_shadow_decisions")
    op.drop_index("ix_paper_shadow_decisions_wallet_at", table_name="paper_shadow_decisions")
    op.drop_table("paper_shadow_decisions")
    op.drop_index(
        "ix_paper_shadow_trade_audit_created_at", table_name="paper_shadow_trade_audit"
    )
    op.drop_index("ix_paper_shadow_trade_audit_mint", table_name="paper_shadow_trade_audit")
    op.drop_index(
        "ix_paper_shadow_trade_audit_wallet_exit", table_name="paper_shadow_trade_audit"
    )
    op.drop_table("paper_shadow_trade_audit")
    op.drop_index("ix_paper_shadow_positions_created_at", table_name="paper_shadow_positions")
    op.drop_index("ix_paper_shadow_positions_mint", table_name="paper_shadow_positions")
    op.drop_index("ix_paper_shadow_positions_closed_at", table_name="paper_shadow_positions")
    op.drop_index(
        "ix_paper_shadow_positions_open_watermark", table_name="paper_shadow_positions"
    )
    op.drop_table("paper_shadow_positions")
    op.drop_index("ix_paper_shadow_wallets_created_at", table_name="paper_shadow_wallets")
    op.drop_table("paper_shadow_wallets")
