"""compound_cycles — the Compound Lab's wallet-target ledger

Additive only: one new table, no change to any existing one. The Compound Lab
runs on the Lab's engine and stores its positions, strategies and equity marks
in the Lab's own tables under a tournament row of its own, so the only thing
that needs new storage is the concept the Lab does not have — a target on the
wallet rather than on a position.

Revision ID: 0055_compound_cycles
Revises: 0054_token_delisted_at
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PgUUID

revision = "0055_compound_cycles"
down_revision = "0054_token_delisted_at"
branch_labels = None
depends_on = None

MONEY = sa.Numeric(24, 4)


def upgrade() -> None:
    op.create_table(
        "compound_cycles",
        sa.Column("id", PgUUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tournament_id", PgUUID(as_uuid=True),
                  sa.ForeignKey("lab_tournaments.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("strategy_row_id", PgUUID(as_uuid=True),
                  sa.ForeignKey("lab_strategies.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("cycle_no", sa.Integer(), nullable=False),
        sa.Column("base_usd", MONEY, nullable=False),
        sa.Column("target_usd", MONEY, nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reached_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("equity_at_target", MONEY, nullable=True),
        sa.Column("realised_equity", MONEY, nullable=True),
        sa.Column("positions_closed", sa.Integer(), nullable=False,
                  server_default="0"),
        sa.Column("outcome", sa.String(24), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
    )
    # One row per cycle number per wallet. This is the guard that makes the
    # ratchet safe to re-run: a tick that opens cycle 3 twice would otherwise
    # give the wallet two bases and the second would win silently.
    op.create_index("ix_compound_cycle_no", "compound_cycles",
                    ["strategy_row_id", "cycle_no"], unique=True)
    op.create_index("ix_compound_cycle_open", "compound_cycles",
                    ["strategy_row_id", "reached_at"])


def downgrade() -> None:
    op.drop_index("ix_compound_cycle_open", table_name="compound_cycles")
    op.drop_index("ix_compound_cycle_no", table_name="compound_cycles")
    op.drop_table("compound_cycles")
