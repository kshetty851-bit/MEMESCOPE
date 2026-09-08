"""pumpfun_graduations + marks — graduation stamped as it happens

Additive only: two new tables, nothing existing altered.

pump.fun exposes `complete` but no graduation timestamp, so "what happens in
the hour after graduation" cannot be answered from a snapshot — every attempt
ends up bucketing by CREATION age, which is a different thing. These tables
hold OUR stamp of the event and the follow-up readings measured against it.

Revision ID: 0058_pumpfun_graduations
Revises: 0057_pumpfun_social
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PgUUID

revision = "0058_pumpfun_graduations"
down_revision = "0057_pumpfun_social"
branch_labels = None
depends_on = None

#: Wide on purpose. pump.fun has returned market caps above 10^20; the
#: collector rejects those as unknown rather than clamping, and the column is
#: not the place to discover that.
MCAP = sa.Numeric(30, 4)


def upgrade() -> None:
    op.create_table(
        "pumpfun_graduations",
        sa.Column("id", PgUUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("mint_address", sa.String(64), nullable=False),
        sa.Column("first_seen_complete_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at_source", sa.DateTime(timezone=True), nullable=True),
        sa.Column("mcap_usd_at_graduation", MCAP, nullable=True),
        sa.Column("ath_mcap_usd_at_graduation", MCAP, nullable=True),
        sa.Column("reply_count_at_graduation", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        # One row per coin, forever: the stamp is the FIRST sighting and a
        # second one would overwrite the only thing this table exists to record.
        sa.UniqueConstraint("mint_address", name="uq_pumpfun_graduation_mint"),
    )
    op.create_index("ix_pumpfun_graduations_seen", "pumpfun_graduations",
                    [sa.text("first_seen_complete_at DESC")])

    op.create_table(
        "pumpfun_graduation_marks",
        sa.Column("id", PgUUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("graduation_id", PgUUID(as_uuid=True),
                  sa.ForeignKey("pumpfun_graduations.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("mint_address", sa.String(64), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("minutes_since", sa.BigInteger(), nullable=False),
        sa.Column("mcap_usd", MCAP, nullable=True),
        sa.Column("ath_mcap_usd", MCAP, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        # One reading per coin per target age, so a retry cannot double-count.
        sa.UniqueConstraint("graduation_id", "minutes_since",
                            name="uq_graduation_mark_once"),
    )
    op.create_index("ix_graduation_marks_mint", "pumpfun_graduation_marks",
                    ["mint_address", sa.text("observed_at DESC")])


def downgrade() -> None:
    op.drop_index("ix_graduation_marks_mint", table_name="pumpfun_graduation_marks")
    op.drop_table("pumpfun_graduation_marks")
    op.drop_index("ix_pumpfun_graduations_seen", table_name="pumpfun_graduations")
    op.drop_table("pumpfun_graduations")
