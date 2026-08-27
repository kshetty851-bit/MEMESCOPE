"""Provider provenance on holder snapshots. Additive only.

Research-critical rows must say which node answered, how fast, and whether the
answer came from a fallback — so provider data is never silently combined.

Revision ID: 0046_rpc_provenance
Revises: 0045_v4_phase2
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0046_rpc_provenance"
down_revision = "0045_v4_phase2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("holder_snapshots", sa.Column("rpc_latency_ms", sa.Integer(), nullable=True))
    op.add_column(
        "holder_snapshots", sa.Column("rpc_fallback_used", sa.Boolean(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("holder_snapshots", "rpc_fallback_used")
    op.drop_column("holder_snapshots", "rpc_latency_ms")
