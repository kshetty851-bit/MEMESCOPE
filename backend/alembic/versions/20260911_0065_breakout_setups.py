"""Breakout Lab phase 2: three new `bo_*` tables for setup detection.

Purely additive: no ALTER, no DROP, no index on an existing table. A database
that runs this migration and never enables `BREAKOUT_LAB_ENABLED` is
byte-identical in every table that existed before it, and a test asserts that.

`bo_episodes` carries a PARTIAL unique index — one OPEN episode per token,
closed ones unconstrained, because a token may run at the same level many
times. That is the one shape here a reader might not expect.

Parented to 0064_breakout_lab.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# 32 characters at most: alembic_version.version_num is varchar(32).
revision: str = "0065_breakout_setups"
down_revision: str = "0064_breakout_lab"
branch_labels = None
depends_on = None

_ADDRESS = sa.String(64)
_PRICE = sa.Numeric(36, 18)
_USD = sa.Numeric(24, 2)
_PCT = sa.Numeric(16, 4)


def upgrade() -> None:
    op.create_table(
        "bo_levels",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("mint", _ADDRESS, nullable=False),
        sa.Column("clusters", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("nearest_resistance", _PRICE, nullable=True),
        sa.Column("atr", _PRICE, nullable=True),
        sa.Column("atr_fast", _PRICE, nullable=True),
        sa.Column("atr_slow", _PRICE, nullable=True),
        sa.Column("volume_mean", _USD, nullable=True),
        sa.Column("high_range", _PRICE, nullable=True),
        sa.Column("low_range", _PRICE, nullable=True),
        sa.Column("close", _PRICE, nullable=False),
        sa.Column("daily_bars", sa.Integer(), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("mint", name="uq_bo_levels_mint"),
    )

    op.create_table(
        "bo_setup_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("mint", _ADDRESS, nullable=False),
        sa.Column("bar_close_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("components", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("price", _PRICE, nullable=False),
        sa.Column("resistance", _PRICE, nullable=True),
        sa.Column("distance_pct", sa.Numeric(12, 4), nullable=True),
        sa.Column("hourly_missing", sa.Boolean(), nullable=False,
                  server_default=sa.false()),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        # Keyed on the BAR: re-running a pass rewrites rather than duplicates.
        sa.UniqueConstraint("mint", "bar_close_time",
                            name="uq_bo_setup_snapshots_mint_bar"),
    )
    op.create_index("ix_bo_setup_snapshots_bar", "bo_setup_snapshots", ["bar_close_time"])

    op.create_table(
        "bo_episodes",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("mint", _ADDRESS, nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("first_pre_breakout_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("close_reason", sa.String(16), nullable=True),
        sa.Column("entry_ref_price", _PRICE, nullable=True),
        sa.Column("resistance_at_open", _PRICE, nullable=True),
        sa.Column("peak_price", _PRICE, nullable=True),
        sa.Column("min_price", _PRICE, nullable=True),
        # Filled by the daily outcomes pass, 72h later — never by the pass
        # that wrote the rest of the row.
        sa.Column("max_gain_pct_from_ref", _PCT, nullable=True),
        sa.Column("max_loss_pct_from_ref", _PCT, nullable=True),
        sa.Column("pct_at_24h", _PCT, nullable=True),
        sa.Column("pct_at_72h", _PCT, nullable=True),
        sa.Column("trail25_result_pct", _PCT, nullable=True),
        sa.Column("outcome_gappy", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("outcome_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    # PARTIAL: one OPEN episode per token, any number of closed ones.
    op.create_index("uq_bo_episodes_open_mint", "bo_episodes", ["mint"], unique=True,
                    postgresql_where=sa.text("closed_at IS NULL"))
    op.create_index("ix_bo_episodes_opened_at", "bo_episodes", ["opened_at"])


def downgrade() -> None:
    op.drop_index("ix_bo_episodes_opened_at", table_name="bo_episodes")
    op.drop_index("uq_bo_episodes_open_mint", table_name="bo_episodes")
    op.drop_table("bo_episodes")
    op.drop_index("ix_bo_setup_snapshots_bar", table_name="bo_setup_snapshots")
    op.drop_table("bo_setup_snapshots")
    op.drop_table("bo_levels")
