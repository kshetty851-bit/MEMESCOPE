"""Family shares of the real wallet: members, their ledger, their slice of each order.

Adds three tables and nothing else; no existing table changes. The three members
are created SWITCHED OFF, so the real wallet's orders are exactly what they were
until the owner turns someone on and records money for them.

Revision ID: 0102_real_wallet_family
Revises: 0101_rhood_recorder
Create Date: 2026-09-24
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0102_real_wallet_family"
down_revision: str = "0101_rhood_recorder"
branch_labels = None
depends_on = None

MEMBERS = ("JAYA", "ASHA", "APOORVA")


def upgrade() -> None:
    members = op.create_table(
        "real_wallet_family_members",
        sa.Column("name", sa.String(16), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("ticket_usd", sa.Numeric(12, 2), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_by", sa.String(120)),
    )
    op.create_table(
        "real_wallet_family_ledger",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("member", sa.String(16),
                  sa.ForeignKey("real_wallet_family_members.name"), nullable=False),
        sa.Column("kind", sa.String(12), nullable=False),
        sa.Column("amount_usd", sa.Numeric(12, 2), nullable=False),
        sa.Column("note", sa.String(200)),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("actor", sa.String(120)),
        sa.CheckConstraint("kind in ('deposit', 'withdrawal')",
                           name="ck_real_wallet_family_ledger_kind"),
        sa.CheckConstraint("amount_usd > 0", name="ck_real_wallet_family_ledger_positive"),
    )
    op.create_index("ix_real_wallet_family_ledger_member",
                    "real_wallet_family_ledger", ["member"])
    op.create_table(
        "real_wallet_family_allocations",
        sa.Column("intent_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("real_wallet_live_intents.id"), primary_key=True),
        sa.Column("member", sa.String(16),
                  sa.ForeignKey("real_wallet_family_members.name"), primary_key=True),
        sa.Column("amount_usd", sa.Numeric(12, 2), nullable=False),
        sa.CheckConstraint("amount_usd > 0", name="ck_real_wallet_family_alloc_positive"),
    )
    op.bulk_insert(members, [{"name": n, "enabled": False, "ticket_usd": 25,
                              "updated_by": "migration 0102"} for n in MEMBERS])


def downgrade() -> None:
    op.drop_table("real_wallet_family_allocations")
    op.drop_index("ix_real_wallet_family_ledger_member", "real_wallet_family_ledger")
    op.drop_table("real_wallet_family_ledger")
    op.drop_table("real_wallet_family_members")
