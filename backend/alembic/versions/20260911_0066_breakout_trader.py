"""Breakout Lab phase 3: the paper trader's own ledger, four `bo_*` tables.

Purely additive. **This is a separate ledger from every other book in the
repo** — not the platform paper wallet, not the Karthik wallet, not another
lab's. $1,000, ten slots, no key and no signer, behind its own
`BREAKOUT_TRADING_ENABLED` flag which is separate from the lab's.

`bo_account` carries a `scope` column whose only job is to hold a unique
constraint, so "there is one account" is a schema fact rather than a
convention someone breaks later.

Parented to 0065_breakout_setups.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# 32 characters at most: alembic_version.version_num is varchar(32).
revision: str = "0066_breakout_trader"
down_revision: str = "0065_breakout_setups"
branch_labels = None
depends_on = None

_ADDRESS = sa.String(64)
_PRICE = sa.Numeric(36, 18)
_MONEY = sa.Numeric(20, 6)
_QTY = sa.Numeric(38, 12)


def upgrade() -> None:
    op.create_table(
        "bo_account",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("scope", sa.String(16), nullable=False,
                  server_default=sa.text("'default'")),
        sa.Column("equity", _MONEY, nullable=False),
        sa.Column("cash", _MONEY, nullable=False),
        sa.Column("peak_equity", _MONEY, nullable=False),
        sa.Column("halted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("halted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("halted_reason", sa.String(64), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        # One row, enforced by the schema rather than by hope.
        sa.UniqueConstraint("scope", name="uq_bo_account_scope"),
    )

    op.create_table(
        "bo_positions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("mint", _ADDRESS, nullable=False),
        sa.Column("episode_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("qty", _QTY, nullable=False),
        sa.Column("entry_price", _PRICE, nullable=False),
        sa.Column("slot_size", _MONEY, nullable=False),
        sa.Column("high_water_value", _MONEY, nullable=False),
        sa.Column("entry_fees", _MONEY, nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("entry_bar", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        # One open position per token, and what makes a re-run idempotent.
        sa.UniqueConstraint("mint", name="uq_bo_positions_mint"),
    )

    op.create_table(
        "bo_trades",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("mint", _ADDRESS, nullable=False),
        sa.Column("symbol", sa.String(32), nullable=True),
        sa.Column("episode_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("qty", _QTY, nullable=False),
        sa.Column("entry_price", _PRICE, nullable=False),
        sa.Column("exit_price", _PRICE, nullable=False),
        sa.Column("slot_size", _MONEY, nullable=False),
        sa.Column("pnl_usd", _MONEY, nullable=False),
        sa.Column("pnl_pct", sa.Numeric(16, 4), nullable=False),
        sa.Column("fees_usd", _MONEY, nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("entry_bar", sa.DateTime(timezone=True), nullable=False),
        sa.Column("exit_bar", sa.DateTime(timezone=True), nullable=False),
        sa.Column("exit_reason", sa.String(24), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("mint", "entry_bar", name="uq_bo_trades_mint_entry_bar"),
    )
    op.create_index("ix_bo_trades_closed_at", "bo_trades", ["closed_at"])

    op.create_table(
        "bo_equity",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("bar_close_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("equity", _MONEY, nullable=False),
        sa.Column("cash", _MONEY, nullable=False),
        sa.Column("unrealised", _MONEY, nullable=False),
        sa.Column("positions", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("bar_close_time", name="uq_bo_equity_bar"),
    )


def downgrade() -> None:
    op.drop_table("bo_equity")
    op.drop_index("ix_bo_trades_closed_at", table_name="bo_trades")
    op.drop_table("bo_trades")
    op.drop_table("bo_positions")
    op.drop_table("bo_account")
