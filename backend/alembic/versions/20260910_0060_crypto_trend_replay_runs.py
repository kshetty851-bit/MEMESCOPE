"""Crypto Trend Lab, phase 3: `ct_replay_runs`. Purely additive; parented
to 0059 on `karthik-hq`."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0060_crypto_trend_replay_runs"
down_revision: str = "0059_crypto_trend_structure_veto"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ct_replay_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True),
                  server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("label", sa.String(64), nullable=True),
        sa.Column("params", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("summary", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("trades", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ct_replay_runs_created_at", "ct_replay_runs", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_ct_replay_runs_created_at", table_name="ct_replay_runs")
    op.drop_table("ct_replay_runs")
