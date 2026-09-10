"""Crypto Trend Lab, phase 2.1: `ct_trend_state.structure_veto`.

One additive column with a server default, so existing rows read False and
nothing else changes. Parented to 0058 on `karthik-hq`.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0059_crypto_trend_structure_veto"
down_revision: str = "0058_crypto_trend_engine"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ct_trend_state", sa.Column("structure_veto", sa.Boolean(), nullable=False,
                                              server_default=sa.false()))


def downgrade() -> None:
    op.drop_column("ct_trend_state", "structure_veto")
