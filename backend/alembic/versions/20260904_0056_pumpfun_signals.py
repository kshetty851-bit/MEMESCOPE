"""pumpfun_signals — the copy lab's audit trail

Additive only: one new table. The copy lab stores its positions, strategy and
equity in the Lab's own tables under a tournament of its own; the concept the
Lab has no equivalent for is "somebody else traded, and here is what we did
about it".

Revision ID: 0056_pumpfun_signals
Revises: 0055_compound_cycles
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PgUUID

revision = "0056_pumpfun_signals"
down_revision = "0055_compound_cycles"
branch_labels = None
depends_on = None

MONEY = sa.Numeric(24, 4)


def upgrade() -> None:
    op.create_table(
        "pumpfun_signals",
        sa.Column("id", PgUUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tournament_id", PgUUID(as_uuid=True),
                  sa.ForeignKey("lab_tournaments.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("signature", sa.String(96), nullable=False),
        sa.Column("mint_address", sa.String(64), nullable=False),
        sa.Column("side", sa.String(4), nullable=False),
        sa.Column("leader_sol", MONEY, nullable=True),
        sa.Column("leader_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("acted", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("outcome", sa.String(32), nullable=False),
        sa.Column("position_id", PgUUID(as_uuid=True),
                  sa.ForeignKey("lab_positions.id", ondelete="SET NULL"),
                  nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
    )
    # THE guard that makes the poll safe to overlap: one leader transaction can
    # only ever produce one of our trades. A check in the tick would not hold,
    # because two ticks can read before either writes.
    op.create_unique_constraint("uq_pumpfun_signature", "pumpfun_signals",
                                ["signature"])
    op.create_index("ix_pumpfun_signal_seen", "pumpfun_signals",
                    ["tournament_id", "seen_at"])
    op.create_index("ix_pumpfun_signal_mint", "pumpfun_signals", ["mint_address"])


def downgrade() -> None:
    op.drop_index("ix_pumpfun_signal_mint", table_name="pumpfun_signals")
    op.drop_index("ix_pumpfun_signal_seen", table_name="pumpfun_signals")
    op.drop_constraint("uq_pumpfun_signature", "pumpfun_signals", type_="unique")
    op.drop_table("pumpfun_signals")
