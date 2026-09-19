"""Rafiqv2: six books on one engine, beside the Rafiq Lab.

Three new tables, nothing existing changes: `rafiqv2_books` (one row per book,
with its mechanism state as JSON), `rafiqv2_positions` and
`rafiqv2_adjustments` (every learned change and every halt).

Revision ID: 0100_rafiqv2_lab
Revises: 0099_momentum_lab
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0100_rafiqv2_lab"
down_revision: str = "0099_momentum_lab"
branch_labels = None
depends_on = None

_UUID = postgresql.UUID(as_uuid=True)
_PRICE = sa.Numeric(38, 18)
_MONEY = sa.Numeric(24, 4)
_RATIO = sa.Numeric(10, 4)


def _id() -> sa.Column:
    return sa.Column("id", _UUID, primary_key=True,
                     server_default=sa.text("gen_random_uuid()"))


def _stamp(name: str) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=False,
                     server_default=sa.text("now()"))


def _book_fk() -> sa.Column:
    return sa.Column("book_id", _UUID,
                     sa.ForeignKey("rafiqv2_books.id", ondelete="CASCADE"), nullable=False)


def upgrade() -> None:
    op.create_table(
        "rafiqv2_books",
        _id(),
        sa.Column("code", sa.String(4), nullable=False, unique=True),
        sa.Column("starting_equity", _MONEY, nullable=False),
        sa.Column("config_digest", sa.String(64), nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("state", postgresql.JSONB(astext_type=sa.Text()), nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        _stamp("created_at"),
        _stamp("updated_at"),
    )
    op.create_table(
        "rafiqv2_positions",
        _id(),
        _book_fk(),
        sa.Column("mint_address", sa.String(44), nullable=False),
        sa.Column("token_id", _UUID, nullable=False),
        sa.Column("symbol", sa.String(64)),
        sa.Column("detected_at", sa.DateTime(timezone=True)),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("entry_price", _PRICE, nullable=False),
        sa.Column("entry_observed_price", _PRICE, nullable=False),
        sa.Column("quantity", sa.Numeric(48, 18), nullable=False),
        sa.Column("cost_basis", _MONEY, nullable=False),
        sa.Column("entry_liquidity_usd", _MONEY),
        sa.Column("entry_market_cap_usd", _MONEY),
        sa.Column("entry_impact_pct", _RATIO),
        sa.Column("entry_score", _RATIO),
        sa.Column("entry_top10_holder_pct", sa.Numeric(9, 4)),
        sa.Column("entry_lp_locked", sa.Boolean()),
        sa.Column("entry_features_error", sa.String(64)),
        sa.Column("rug_strictness", _RATIO, nullable=False),
        sa.Column("lock_giveback", _RATIO, nullable=False),
        sa.Column("size_multiplier", _RATIO, nullable=False),
        sa.Column("status", sa.String(8), nullable=False, server_default=sa.text("'open'")),
        sa.Column("peak_price", _PRICE, nullable=False),
        sa.Column("last_mark_price", _PRICE),
        sa.Column("last_mark_liquidity_usd", _MONEY),
        sa.Column("last_evaluated_at", sa.DateTime(timezone=True)),
        sa.Column("scaled_out", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("scaled_out_at", sa.DateTime(timezone=True)),
        sa.Column("scale_out_price", _PRICE),
        sa.Column("fraction_open", _RATIO, nullable=False, server_default=sa.text("1")),
        sa.Column("realised_usd", _MONEY, nullable=False, server_default=sa.text("0")),
        sa.Column("closed_at", sa.DateTime(timezone=True)),
        sa.Column("exit_price", _PRICE),
        sa.Column("exit_proceeds_usd", _MONEY),
        sa.Column("exit_reason", sa.String(16)),
        sa.Column("exit_evidence", sa.Text()),
        sa.Column("died", sa.Boolean()),
        sa.Column("forward_peak_multiple", sa.Numeric(18, 6)),
        sa.Column("learning_recorded_at", sa.DateTime(timezone=True)),
        _stamp("created_at"),
        _stamp("updated_at"),
        sa.UniqueConstraint("book_id", "mint_address", name="uq_rafiqv2_positions_book_mint"),
    )
    op.create_index("ix_rafiqv2_positions_book_status", "rafiqv2_positions",
                    ["book_id", "status"])
    op.create_index("ix_rafiqv2_positions_book_closed_at", "rafiqv2_positions",
                    ["book_id", "closed_at"])
    op.create_table(
        "rafiqv2_adjustments",
        _id(),
        _book_fk(),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("parameter", sa.String(32), nullable=False),
        sa.Column("old_value", sa.Numeric(24, 6), nullable=False),
        sa.Column("new_value", sa.Numeric(24, 6), nullable=False),
        sa.Column("sample_size", sa.Integer()),
        sa.Column("z_score", sa.Numeric(10, 3)),
        sa.Column("reason", sa.Text(), nullable=False),
        _stamp("created_at"),
    )
    op.create_index("ix_rafiqv2_adjustments_book_at", "rafiqv2_adjustments",
                    ["book_id", "at"])


def downgrade() -> None:
    op.drop_table("rafiqv2_adjustments")
    op.drop_table("rafiqv2_positions")
    op.drop_table("rafiqv2_books")
