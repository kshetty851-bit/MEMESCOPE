"""Add discovered_tokens for the Solana token discovery engine

Revision ID: 0002_discovered_tokens
Revises: 0001_initial
Create Date: 2026-07-27
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_discovered_tokens"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    metadata_status = postgresql.ENUM(
        "pending", "resolved", "failed", name="metadata_status", create_type=False
    )
    metadata_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "discovered_tokens",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("mint_address", sa.String(length=44), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=True),
        sa.Column("symbol", sa.String(length=64), nullable=True),
        sa.Column("decimals", sa.Integer(), nullable=True),
        sa.Column("metadata_uri", sa.String(length=2048), nullable=True),
        sa.Column("creator_address", sa.String(length=44), nullable=True),
        sa.Column("signature", sa.String(length=88), nullable=False),
        # Solana slots already exceed the 32-bit range.
        sa.Column("slot", sa.BigInteger(), nullable=False),
        sa.Column("block_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "discovered_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("source_program", sa.String(length=44), nullable=True),
        sa.Column(
            "metadata_status", metadata_status, server_default="pending", nullable=False
        ),
        sa.Column("metadata_attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_discovered_tokens"),
    )

    # The unique index is what makes ingestion idempotent.
    op.create_index(
        "ix_discovered_tokens_mint_address", "discovered_tokens", ["mint_address"], unique=True
    )
    op.create_index("ix_discovered_tokens_signature", "discovered_tokens", ["signature"])
    op.create_index("ix_discovered_tokens_slot", "discovered_tokens", ["slot"])
    op.create_index("ix_discovered_tokens_block_time", "discovered_tokens", ["block_time"])
    op.create_index("ix_discovered_tokens_discovered_at", "discovered_tokens", ["discovered_at"])
    op.create_index(
        "ix_discovered_tokens_creator_address", "discovered_tokens", ["creator_address"]
    )
    op.create_index("ix_discovered_tokens_source_program", "discovered_tokens", ["source_program"])
    op.create_index("ix_discovered_tokens_created_at", "discovered_tokens", ["created_at"])

    # Serves the live feed, which is always "newest first".
    op.create_index(
        "ix_discovered_tokens_discovered_at_desc",
        "discovered_tokens",
        [sa.text("discovered_at DESC")],
    )
    # Serves the metadata retry sweep.
    op.create_index(
        "ix_discovered_tokens_status_discovered",
        "discovered_tokens",
        ["metadata_status", "discovered_at"],
    )


def downgrade() -> None:
    op.drop_table("discovered_tokens")
    op.execute("DROP TYPE IF EXISTS metadata_status")
