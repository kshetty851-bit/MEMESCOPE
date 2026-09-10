"""Crypto Trend Lab, phase 3.1: `ct_universe_snapshots`. Purely additive;
parented to 0060 on `karthik-hq`."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# 32 characters at most: alembic_version.version_num is varchar(32).
revision: str = "0061_crypto_trend_snapshots"
down_revision: str = "0060_crypto_trend_replay_runs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ct_universe_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True),
                  server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("symbols", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", name="uq_ct_universe_snapshots_name"),
    )


def downgrade() -> None:
    op.drop_table("ct_universe_snapshots")
