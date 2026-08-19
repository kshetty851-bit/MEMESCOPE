"""Add explicit paper-wallet resume provenance and watermark."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0035_resume_generation_2"
down_revision = "0034_yellowstone_shadow_metrics"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("paper_wallets", sa.Column("resume_watermark_at", sa.DateTime(timezone=True)))
    op.add_column("paper_wallets", sa.Column("resumed_at", sa.DateTime(timezone=True)))
    op.add_column("paper_wallets", sa.Column("restored_archive_at", sa.DateTime(timezone=True)))
    op.add_column("paper_wallets", sa.Column("restored_archive_reason", sa.Text()))


def downgrade() -> None:
    op.drop_column("paper_wallets", "restored_archive_reason")
    op.drop_column("paper_wallets", "restored_archive_at")
    op.drop_column("paper_wallets", "resumed_at")
    op.drop_column("paper_wallets", "resume_watermark_at")
