"""Persist Yellowstone shadow health counters for the read-only ops view."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0034_yellowstone_shadow_metrics"
down_revision = "0033_yellowstone_shadow_ledger"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "yellowstone_stream_checkpoints",
        sa.Column("last_received_slot", sa.BigInteger(), nullable=True),
    )
    for column in (
        "messages_received",
        "matching_pumpfun_events",
        "unique_mints",
        "duplicates",
        "replays",
        "errors",
    ):
        op.add_column(
            "yellowstone_stream_checkpoints",
            sa.Column(column, sa.Integer(), nullable=False, server_default=sa.text("0")),
        )


def downgrade() -> None:
    for column in (
        "errors",
        "replays",
        "duplicates",
        "unique_mints",
        "matching_pumpfun_events",
        "messages_received",
    ):
        op.drop_column("yellowstone_stream_checkpoints", column)
    op.drop_column("yellowstone_stream_checkpoints", "last_received_slot")
