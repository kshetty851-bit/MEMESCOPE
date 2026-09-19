"""The Momentum Lab's five `mom_*` tables. New tables only; nothing existing
is touched.

Revision ID: 0099_momentum_lab
Revises: 0098_grad_operators
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0099_momentum_lab"
down_revision: str = "0098_grad_operators"
branch_labels = None
depends_on = None

_PRICE = sa.Numeric(36, 18)
_USD = sa.Numeric(24, 4)
_TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "mom_pairs",
        sa.Column("pair_address", sa.String(64), primary_key=True),
        sa.Column("mint", sa.String(64), nullable=False),
        sa.Column("symbol", sa.String(32)),
        sa.Column("dex_id", sa.String(32)),
        sa.Column("quote_mint", sa.String(64), nullable=False),
        sa.Column("born_at", _TS, nullable=False),
        sa.Column("status", sa.String(12), nullable=False, server_default="active"),
        sa.Column("drop_reason", sa.String(24)),
        sa.Column("lists", postgresql.ARRAY(sa.String(24))),
        sa.Column("admitted_at", _TS, nullable=False),
        sa.Column("listed_at", _TS, nullable=False),
        sa.Column("last_price", _PRICE),
        sa.Column("last_sample_at", _TS),
        sa.Column("liquidity_usd", _USD),
        sa.Column("volume_h24", _USD),
        sa.Column("change_h1", sa.Numeric(12, 4)),
        sa.Column("glitches", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index("ix_mom_pairs_mint", "mom_pairs", ["mint"])
    op.create_index("ix_mom_pairs_status", "mom_pairs", ["status"])

    op.create_table(
        "mom_candles",
        sa.Column("pair_address", sa.String(64), primary_key=True),
        sa.Column("start", _TS, primary_key=True),
        sa.Column("open", _PRICE, nullable=False),
        sa.Column("high", _PRICE, nullable=False),
        sa.Column("low", _PRICE, nullable=False),
        sa.Column("close", _PRICE, nullable=False),
        sa.Column("volume_usd", _USD),
        sa.Column("buys", sa.Integer()),
        sa.Column("sells", sa.Integer()),
        sa.Column("volume_h24", _USD),
        sa.Column("liquidity_usd", _USD),
        sa.Column("change_h24", sa.Numeric(12, 4)),
        sa.Column("samples", sa.Integer(), nullable=False, server_default="1"),
    )

    op.create_table(
        "mom_closes",
        sa.Column("tf", sa.String(4), primary_key=True),
        sa.Column("start", _TS, primary_key=True),
        sa.Column("evaluated_at", _TS, nullable=False),
        sa.Column("eligible", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("green", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("fired", postgresql.JSONB(), nullable=False, server_default="{}"),
    )

    op.create_table(
        "mom_signals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("pair_address", sa.String(64), nullable=False),
        sa.Column("mint", sa.String(64), nullable=False),
        sa.Column("symbol", sa.String(32)),
        sa.Column("tf", sa.String(5), nullable=False),
        sa.Column("start", _TS, nullable=False),
        sa.Column("at", _TS, nullable=False),
        sa.Column("arms", postgresql.ARRAY(sa.String(32)), nullable=False),
        sa.Column("features", postgresql.JSONB(), nullable=False),
    )
    op.create_index("ix_mom_signals_at", "mom_signals", ["at"])

    op.create_table(
        "mom_positions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("arm", sa.String(32), nullable=False),
        sa.Column("pair_address", sa.String(64), nullable=False),
        sa.Column("mint", sa.String(64), nullable=False),
        sa.Column("symbol", sa.String(32)),
        sa.Column("dex_id", sa.String(32)),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("signal_tf", sa.String(5), nullable=False),
        sa.Column("signal_start", _TS, nullable=False),
        sa.Column("signal_open", _PRICE, nullable=False),
        sa.Column("signal_high", _PRICE, nullable=False),
        sa.Column("signal_low", _PRICE, nullable=False),
        sa.Column("signal_close", _PRICE, nullable=False),
        sa.Column("features", postgresql.JSONB()),
        sa.Column("decided_at", _TS, nullable=False),
        sa.Column("trigger_below", _PRICE),
        sa.Column("expires_at", _TS),
        sa.Column("opened_at", _TS),
        sa.Column("open_price", _PRICE),
        sa.Column("open_fill", _PRICE),
        sa.Column("notional_usd", sa.Numeric(18, 2), nullable=False),
        sa.Column("tokens", sa.Numeric(38, 12)),
        sa.Column("fee_bps", sa.Integer()),
        sa.Column("liq_open_usd", _USD),
        sa.Column("impact_open", sa.Numeric(18, 8)),
        sa.Column("stop_price", _PRICE),
        sa.Column("target_price", _PRICE),
        sa.Column("peak_price", _PRICE),
        sa.Column("scaled_at", _TS),
        sa.Column("scaled_usd", sa.Numeric(18, 6)),
        sa.Column("exit_reason", sa.String(16)),
        sa.Column("exit_decided_at", _TS),
        sa.Column("closed_at", _TS),
        sa.Column("close_price", _PRICE),
        sa.Column("close_fill", _PRICE),
        sa.Column("liq_close_usd", _USD),
        sa.Column("impact_close", sa.Numeric(18, 8)),
        sa.Column("net_return", sa.Numeric(18, 8)),
        sa.Column("pnl_usd", sa.Numeric(18, 2)),
    )
    op.create_index("ix_mom_positions_live", "mom_positions", ["status"],
                    postgresql_where=sa.text("status <> 'closed' AND status <> 'unfilled'"))
    op.create_index("ix_mom_positions_arm", "mom_positions", ["arm", "closed_at"])


def downgrade() -> None:
    for table in ("mom_positions", "mom_signals", "mom_closes", "mom_candles", "mom_pairs"):
        op.drop_table(table)
