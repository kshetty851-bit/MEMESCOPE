"""Checkpoint alignment for research quotes. Additive only.

The V5 protocol fixes decision checkpoints at 5/10/20/30/45/60 minutes after
nursery entry, and its first research question is whether two-sided
executability can be predicted AT the decision moment. A randomly sampled
quote cannot answer that; a quote stamped with the checkpoint it belongs to
can.

Revision ID: 0047_quote_checkpoints
Revises: 0046_rpc_provenance
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0047_quote_checkpoints"
down_revision = "0046_rpc_provenance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "research_quotes", sa.Column("checkpoint_minutes", sa.Integer(), nullable=True)
    )
    op.create_index(
        "ix_research_quotes_mint_checkpoint",
        "research_quotes",
        ["mint_address", "checkpoint_minutes"],
    )


def downgrade() -> None:
    op.drop_index("ix_research_quotes_mint_checkpoint", table_name="research_quotes")
    op.drop_column("research_quotes", "checkpoint_minutes")
