"""Crypto Trend Lab, phase 2: two new `ct_*` tables for the trend engine.

Purely additive, like 0057: no ALTER, no DROP, no index on an existing
table. Parented to 0057 on `karthik-hq`.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0058_crypto_trend_engine"
down_revision: str = "0057_crypto_trend_lab"
branch_labels = None
depends_on = None

_PRICE = sa.Numeric(24, 8)


def _uuid_pk() -> sa.Column:
    return sa.Column("id", postgresql.UUID(as_uuid=True),
                     server_default=sa.text("gen_random_uuid()"), nullable=False)


def upgrade() -> None:
    op.create_table(
        "ct_trend_state",
        _uuid_pk(),
        sa.Column("symbol", sa.String(24), nullable=False),
        sa.Column("timeframe", sa.String(4), nullable=False),
        sa.Column("bar_close_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("direction", sa.String(5), nullable=False),
        sa.Column("strength", sa.Integer(), nullable=False),
        sa.Column("slope", sa.Numeric(12, 6), nullable=False),
        sa.Column("atr_pct", sa.Numeric(12, 6), nullable=False),
        sa.Column("bars_in_state", sa.Integer(), nullable=False),
        sa.Column("ema_fast", _PRICE, nullable=False),
        sa.Column("ema_slow", _PRICE, nullable=False),
        sa.Column("ema_trend", _PRICE, nullable=True),
        sa.Column("adx", sa.Numeric(10, 4), nullable=False),
        sa.Column("structure", sa.String(8), nullable=False),
        sa.Column("close", _PRICE, nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("symbol", "timeframe", "bar_close_time",
                            name="uq_ct_trend_state_symbol_timeframe_bar_close_time"),
    )

    op.create_table(
        "ct_regime",
        _uuid_pk(),
        sa.Column("bar_close_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("coins", sa.Integer(), nullable=False),
        sa.Column("breadth_up", sa.Numeric(6, 4), nullable=False),
        sa.Column("breadth_down", sa.Numeric(6, 4), nullable=False),
        sa.Column("btc_direction", sa.String(5), nullable=True),
        sa.Column("eth_direction", sa.String(5), nullable=True),
        sa.Column("regime", sa.String(8), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("bar_close_time", name="uq_ct_regime_bar_close_time"),
    )


def downgrade() -> None:
    op.drop_table("ct_regime")
    op.drop_table("ct_trend_state")
