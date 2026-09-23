"""Robinhood Chain recorder: locks and samples.

Two tables, read by nothing else. The unique constraint on (tx_hash,
log_index) is what lets the recorder re-read an overlapping block window every
pass — without it that overlap duplicates every row it sees twice.

Revision ID: 0101_rhood_recorder
Revises: 0100_rafiqv2_lab
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0101_rhood_recorder"
down_revision: str = "0100_rafiqv2_lab"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rhood_locks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("block_number", sa.BigInteger(), nullable=False),
        sa.Column("block_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("tx_hash", sa.String(length=80), nullable=False),
        sa.Column("log_index", sa.BigInteger(), nullable=False),
        sa.Column("token", sa.String(length=64), nullable=False),
        sa.Column("quote", sa.String(length=64)),
        sa.Column("symbol", sa.String(length=64)),
        sa.Column("name", sa.String(length=128)),
        sa.Column("pair_created_at", sa.DateTime(timezone=True)),
        sa.Column("pair_address", sa.String(length=64)),
        sa.Column("pairs_seen", sa.BigInteger()),
        sa.Column("seen_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("priced", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.UniqueConstraint("tx_hash", "log_index", name="uq_rhood_locks_event"),
    )
    op.create_index("ix_rhood_locks_seen", "rhood_locks", ["seen_at"])
    op.create_index("ix_rhood_locks_token", "rhood_locks", ["token"])

    op.create_table(
        "rhood_samples",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("token", sa.String(length=64), nullable=False),
        sa.Column("pair_address", sa.String(length=64)),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("price_usd", sa.Numeric(40, 18)),
        sa.Column("price_native", sa.Numeric(40, 18)),
        sa.Column("liquidity_usd", sa.Numeric(20, 2)),
        sa.Column("fdv", sa.Numeric(20, 2)),
        sa.Column("volume_m5_usd", sa.Numeric(20, 2)),
        sa.Column("txns_m5_buys", sa.BigInteger()),
        sa.Column("txns_m5_sells", sa.BigInteger()),
    )
    op.create_index("ix_rhood_samples_token_ts", "rhood_samples", ["token", "ts"])


def downgrade() -> None:
    op.drop_index("ix_rhood_samples_token_ts", table_name="rhood_samples")
    op.drop_table("rhood_samples")
    op.drop_index("ix_rhood_locks_token", table_name="rhood_locks")
    op.drop_index("ix_rhood_locks_seen", table_name="rhood_locks")
    op.drop_table("rhood_locks")
