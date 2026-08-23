"""Paper Wallet V2: three new tables, and nothing else.

**Purely additive.** No V1 table is altered, no V1 row is read or written, and
`downgrade` drops only what `upgrade` created. V2's isolation from V1 is a
property of the schema — separate tables — so this migration cannot affect the
original wallet's capital, positions, history or lineage even if it were run
twice.

No wallet row is seeded here. A V2 wallet is created by the service on first
activation, so a deployed-but-disabled V2 holds no capital and shows no
balance — an experiment that has not started should not look like one that has.

Revision ID: 0044_paper_wallet_v2
Revises: 0043_hq_ops
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0044_paper_wallet_v2"
down_revision = "0043_hq_ops"
branch_labels = None
depends_on = None

_PRICE = sa.Numeric(38, 18)
_MONEY = sa.Numeric(24, 4)
_QUANTITY = sa.Numeric(48, 18)


def upgrade() -> None:
    op.create_table(
        "paper_v2_wallets",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("strategy_id", sa.String(64), nullable=False),
        sa.Column("strategy_version", sa.String(32), nullable=False),
        sa.Column("starting_balance", _MONEY, nullable=False),
        sa.Column("trade_size_usd", _MONEY, nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archive_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_paper_v2_wallets"),
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_paper_v2_wallets_live ON paper_v2_wallets ((true)) "
        "WHERE archived_at IS NULL"
    )

    op.create_table(
        "paper_v2_positions",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("wallet_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("mint_address", sa.String(44), nullable=False),
        sa.Column("token_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("entry_price", _PRICE, nullable=False),
        sa.Column("initial_notional", _MONEY, nullable=False),
        sa.Column("initial_quantity", _QUANTITY, nullable=False),
        sa.Column("remaining_quantity", _QUANTITY, nullable=False),
        sa.Column("filled_rungs", postgresql.JSONB(), server_default="[]", nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("final_exit_reason", sa.String(24), nullable=True),
        sa.Column("entry_liquidity_usd", _MONEY, nullable=True),
        sa.Column("entry_market_cap", _MONEY, nullable=True),
        sa.Column("entry_cost_usd", _MONEY, nullable=True),
        sa.Column("entry_rank", sa.Integer(), nullable=True),
        sa.Column("decision_provenance", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column("last_evaluated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_paper_v2_positions"),
        sa.ForeignKeyConstraint(["wallet_id"], ["paper_v2_wallets.id"], ondelete="CASCADE",
                                name="fk_paper_v2_positions_wallet"),
        sa.ForeignKeyConstraint(["token_id"], ["discovered_tokens.id"], ondelete="SET NULL",
                                name="fk_paper_v2_positions_token"),
        sa.UniqueConstraint("wallet_id", "mint_address", name="uq_paper_v2_positions_wallet_mint"),
    )
    op.execute(
        "CREATE INDEX ix_paper_v2_positions_open ON paper_v2_positions (wallet_id, last_evaluated_at) "
        "WHERE status = 'open'"
    )
    op.create_index("ix_paper_v2_positions_mint", "paper_v2_positions", ["mint_address"])

    op.create_table(
        "paper_v2_fills",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("position_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("rung_index", sa.Integer(), nullable=True),
        sa.Column("reason", sa.String(24), nullable=False),
        sa.Column("filled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("quantity", _QUANTITY, nullable=False),
        sa.Column("execution_price", _PRICE, nullable=False),
        sa.Column("observed_price", _PRICE, nullable=False),
        sa.Column("gross_proceeds", _MONEY, nullable=False),
        sa.Column("fee_usd", _MONEY, nullable=True),
        sa.Column("impact_usd", _MONEY, nullable=True),
        sa.Column("net_proceeds", _MONEY, nullable=False),
        sa.Column("liquidity_usd", _MONEY, nullable=True),
        sa.Column("execution_model_version", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_paper_v2_fills"),
        sa.ForeignKeyConstraint(["position_id"], ["paper_v2_positions.id"], ondelete="CASCADE",
                                name="fk_paper_v2_fills_position"),
    )
    # A rung fires once. Enforced here so no future code path can double-sell.
    op.execute(
        "CREATE UNIQUE INDEX uq_paper_v2_fills_rung ON paper_v2_fills (position_id, rung_index) "
        "WHERE rung_index IS NOT NULL"
    )
    op.create_index("ix_paper_v2_fills_position", "paper_v2_fills", ["position_id", "filled_at"])


def downgrade() -> None:
    op.drop_table("paper_v2_fills")
    op.drop_table("paper_v2_positions")
    op.drop_table("paper_v2_wallets")
