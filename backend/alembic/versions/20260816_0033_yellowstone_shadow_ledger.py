"""Additive Yellowstone shadow observations and durable replay checkpoints."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0033_yellowstone_shadow_ledger"
down_revision = "0032_remove_shadow"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "discovery_source_observations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("provider_name", sa.String(64), nullable=False),
        sa.Column("mint_address", sa.String(44), nullable=False),
        sa.Column("signature", sa.String(88), nullable=False),
        sa.Column("slot", sa.BigInteger(), nullable=False),
        sa.Column("program", sa.String(44)),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("provider_timestamp", sa.DateTime(timezone=True)),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("replayed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("reconnect_generation", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("provider_sequence", sa.BigInteger()),
        sa.UniqueConstraint("source", "signature", "mint_address", name="uq_discovery_observation"),
    )
    op.create_index("ix_discovery_observation_mint_observed", "discovery_source_observations", ["mint_address", "observed_at"])
    op.create_index("ix_discovery_observation_source_slot", "discovery_source_observations", ["source", "slot"])
    op.create_index("ix_discovery_source_observations_source", "discovery_source_observations", ["source"])
    op.create_table(
        "yellowstone_stream_checkpoints",
        sa.Column("stream_name", sa.String(64), primary_key=True),
        sa.Column("last_durable_slot", sa.BigInteger()),
        sa.Column("last_durable_signature", sa.String(88)),
        sa.Column("last_message_at", sa.DateTime(timezone=True)),
        sa.Column("reconnect_generation", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("connected", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("last_error", sa.String(500)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )


def downgrade() -> None:
    op.drop_table("yellowstone_stream_checkpoints")
    op.drop_table("discovery_source_observations")
