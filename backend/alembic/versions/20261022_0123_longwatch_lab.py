"""Long-watch Lab: 48-hour readings of every graduation, and two paper books.

Revision ID: 0123_longwatch_lab
Revises: 0122_fomo_consensus
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0123_longwatch_lab"
down_revision = "0122_fomo_consensus"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "longwatch_readings",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("mint", sa.String(64), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("pair", sa.String(64)),
        sa.Column("price_usd", sa.Numeric(38, 18)),
        sa.Column("liquidity_usd", sa.Numeric(24, 4)),
        sa.Column("fdv", sa.Numeric(24, 4)),
        sa.Column("volume_h1", sa.Numeric(24, 4)),
        sa.Column("buys_h1", sa.Integer()),
        sa.Column("sells_h1", sa.Integer()),
    )
    op.create_index("ix_longwatch_readings_mint_ts", "longwatch_readings", ["mint", "ts"])
    op.create_index("ix_longwatch_readings_ts", "longwatch_readings", ["ts"])
    op.create_table(
        "longwatch_books",
        sa.Column("book", sa.String(16), primary_key=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cash_usd", sa.Numeric(24, 4), nullable=False),
    )
    op.create_table(
        "longwatch_positions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("book", sa.String(16), nullable=False),
        sa.Column("mint", sa.String(64), nullable=False),
        sa.Column("symbol", sa.String(64)),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("entry_price", sa.Numeric(38, 18), nullable=False),
        sa.Column("quantity", sa.Numeric(48, 18), nullable=False),
        sa.Column("spent_usd", sa.Numeric(24, 4), nullable=False),
        sa.Column("peak_price", sa.Numeric(38, 18), nullable=False),
        sa.Column("last_price", sa.Numeric(38, 18)),
        sa.Column("last_liquidity_usd", sa.Numeric(24, 4)),
        sa.Column("status", sa.String(8), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True)),
        sa.Column("exit_price", sa.Numeric(38, 18)),
        sa.Column("proceeds_usd", sa.Numeric(24, 4)),
        sa.Column("reason", sa.String(32)),
        sa.Column("trigger", postgresql.JSONB()),
    )
    op.create_index("ix_longwatch_positions_created_at", "longwatch_positions", ["created_at"])
    op.create_index("ix_longwatch_positions_book_status", "longwatch_positions", ["book", "status"])
    op.create_index("ix_longwatch_positions_book_mint", "longwatch_positions", ["book", "mint"], unique=True)


def downgrade() -> None:
    op.drop_table("longwatch_positions")
    op.drop_table("longwatch_books")
    op.drop_index("ix_longwatch_readings_ts", table_name="longwatch_readings")
    op.drop_index("ix_longwatch_readings_mint_ts", table_name="longwatch_readings")
    op.drop_table("longwatch_readings")
