"""Delivery log for the daily paper-wallet report.

The partial unique index is the feature, not the table. The report beat runs
every fifteen minutes so a failed send retries without waiting a day, which
means the same (kind, date, recipient) is evaluated dozens of times — and the
index on `status = 'sent'` is the only thing that makes that safe.

Failures and skips are deliberately outside the index: they may repeat, and
each attempt is worth keeping.

Revision ID: 0026_report_deliveries
Revises: 0025_execution_evidence_and_fees
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0026_report_deliveries"
down_revision: str | None = "0025_execution_evidence_and_fees"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "report_deliveries",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("report_date", sa.Date(), nullable=False),
        sa.Column("recipient", sa.String(320), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column(
            "attempted_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider_message_id", sa.String(255), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "uq_report_delivery_sent_once",
        "report_deliveries",
        ["kind", "report_date", "recipient"],
        unique=True,
        postgresql_where=sa.text("status = 'sent'"),
    )
    op.create_index("ix_report_delivery_date", "report_deliveries", ["report_date"])


def downgrade() -> None:
    op.drop_index("ix_report_delivery_date", table_name="report_deliveries")
    op.drop_index("uq_report_delivery_sent_once", table_name="report_deliveries")
    op.drop_table("report_deliveries")
