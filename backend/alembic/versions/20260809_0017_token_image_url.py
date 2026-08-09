"""cache token image url

Revision ID: 0017_token_image_url
Revises: 0016_paper_shadow_wallets
Create Date: 2026-08-09 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0017_token_image_url"
down_revision = "0016_paper_shadow_wallets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "discovered_tokens",
        sa.Column("image_url", sa.String(length=2048), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("discovered_tokens", "image_url")
