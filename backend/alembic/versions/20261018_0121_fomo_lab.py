"""FOMO Lab's isolated roster, signal ledger and $500 paper book.

Revision ID: 0121_fomo_lab
Revises: 0120_push_alerts
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0121_fomo_lab"
down_revision = "0120_push_alerts"
branch_labels = None
depends_on = None


def _id() -> sa.Column:
    return sa.Column(
        "id",
        postgresql.UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    ]


def upgrade() -> None:
    at = sa.DateTime(timezone=True)
    money = sa.Numeric(24, 4)
    addr = sa.String(64)
    op.create_table(
        "fomo_books",
        _id(),
        sa.Column("started_at", at, nullable=False),
        sa.Column("cash_usd", money, nullable=False),
        sa.Column("roster_at", at),
        sa.Column("source_captured_at", at),
        sa.Column("feed_at", at),
        sa.Column("feed_error", sa.String(128)),
        *_timestamps(),
    )
    op.create_index("ix_fomo_books_created_at", "fomo_books", ["created_at"])

    op.create_table(
        "fomo_leaders",
        _id(),
        sa.Column(
            "book_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("fomo_books.id"),
            nullable=False,
        ),
        sa.Column("user_id", sa.String(80), nullable=False),
        sa.Column("handle", sa.String(100), nullable=False),
        sa.Column("wallet", addr, nullable=False),
        sa.Column("rank", sa.Integer, nullable=False),
        sa.Column("pnl_24h_usd", money),
        sa.Column("active", sa.Boolean, nullable=False),
        sa.Column("follow_from", at, nullable=False),
        sa.Column("ranked_at", at, nullable=False),
        *_timestamps(),
        sa.UniqueConstraint("book_id", "user_id", name="uq_fomo_leader_user"),
    )
    op.create_index("ix_fomo_leaders_created_at", "fomo_leaders", ["created_at"])
    op.create_index("ix_fomo_leader_active", "fomo_leaders", ["book_id", "active", "rank"])

    op.create_table(
        "fomo_positions",
        _id(),
        sa.Column(
            "book_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("fomo_books.id"),
            nullable=False,
        ),
        sa.Column("leader_wallet", addr, nullable=False),
        sa.Column("mint", addr, nullable=False),
        sa.Column("buy_signature", sa.String(96), nullable=False),
        sa.Column("leader_bought_at", at, nullable=False),
        sa.Column("opened_at", at, nullable=False),
        sa.Column("entry_price_usd", sa.Numeric(38, 18), nullable=False),
        sa.Column("quantity", sa.Numeric(48, 18), nullable=False),
        sa.Column("spent_usd", money, nullable=False),
        sa.Column("status", sa.String(8), nullable=False),
        sa.Column("closed_at", at),
        sa.Column("exit_price_usd", sa.Numeric(38, 18)),
        sa.Column("proceeds_usd", money),
        sa.Column("last_value_usd", money),
        sa.Column("last_mark_at", at),
        *_timestamps(),
        sa.UniqueConstraint(
            "book_id", "leader_wallet", "buy_signature", "mint", name="uq_fomo_position_buy"
        ),
    )
    op.create_index("ix_fomo_positions_created_at", "fomo_positions", ["created_at"])
    op.create_index(
        "ix_fomo_position_open",
        "fomo_positions",
        ["book_id", "status", "leader_wallet", "mint"],
    )

    op.create_table(
        "fomo_signals",
        _id(),
        sa.Column(
            "book_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("fomo_books.id"),
            nullable=False,
        ),
        sa.Column("leader_wallet", addr, nullable=False),
        sa.Column("signature", sa.String(96), nullable=False),
        sa.Column("mint", addr, nullable=False),
        sa.Column("side", sa.String(4), nullable=False),
        sa.Column("traded_at", at, nullable=False),
        sa.Column("seen_at", at, nullable=False),
        sa.Column("outcome", sa.String(40), nullable=False),
        sa.Column(
            "position_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("fomo_positions.id")
        ),
        *_timestamps(),
        sa.UniqueConstraint(
            "book_id", "leader_wallet", "signature", "mint", name="uq_fomo_signal_once"
        ),
    )
    op.create_index("ix_fomo_signals_created_at", "fomo_signals", ["created_at"])
    op.create_index("ix_fomo_signal_recent", "fomo_signals", ["book_id", "seen_at"])


def downgrade() -> None:
    for table in ("fomo_signals", "fomo_positions", "fomo_leaders", "fomo_books"):
        op.drop_table(table)
