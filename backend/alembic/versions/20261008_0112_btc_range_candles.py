"""BTC Range Lab: closed 15-minute BTCUSDT candles.

The lab's live paper book is a replay over this table, so the table is the
record. PK (symbol, timeframe, open_time) makes ingest idempotent; the
repository's `ON CONFLICT ... WHERE is_closed IS false` makes a closed candle
immutable.

`created_at` is indexed because `TimestampMixin` declares it on every table -
omit it and `alembic check` reports drift.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0112_btc_range_candles"
down_revision: str = "0111_operator_blocked_reason"
branch_labels = None
depends_on = None

_PRICE = sa.Numeric(24, 8)


def upgrade() -> None:
    op.create_table(
        "btc_candles",
        sa.Column("symbol", sa.String(16), nullable=False),
        sa.Column("timeframe", sa.String(8), nullable=False),
        sa.Column("open_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("open", _PRICE, nullable=False),
        sa.Column("high", _PRICE, nullable=False),
        sa.Column("low", _PRICE, nullable=False),
        sa.Column("close", _PRICE, nullable=False),
        sa.Column("volume", _PRICE, nullable=False),
        sa.Column("is_closed", sa.Boolean(), nullable=False),
        sa.Column("close_time", sa.DateTime(timezone=True), nullable=True),
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
        sa.PrimaryKeyConstraint("symbol", "timeframe", "open_time", name="pk_btc_candles"),
    )
    op.create_index("ix_btc_candles_created_at", "btc_candles", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_btc_candles_created_at", table_name="btc_candles")
    op.drop_table("btc_candles")
