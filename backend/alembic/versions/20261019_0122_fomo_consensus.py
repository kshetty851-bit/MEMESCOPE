"""FOMO Lab's second book: fomo_books.kind ("main" or "consensus").

Revision ID: 0122_fomo_consensus
Revises: 0121_fomo_lab
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0122_fomo_consensus"
down_revision = "0121_fomo_lab"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("fomo_books", sa.Column("kind", sa.String(16), nullable=False,
                                          server_default="main"))


def downgrade() -> None:
    op.drop_column("fomo_books", "kind")
