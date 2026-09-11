"""Graduation Lab: `grad_features`, one row per graduated token.

Purely additive — one new table, no ALTER and no index on anything that already
existed. A database that runs this and never sets `LAB_GRADUATION_ENABLED` is
byte-identical in every table that existed before it.

Written by `app/labs/graduation/features.py` from the five recorded tables.
Phase 3 reads it; nothing in this lab does.

## Why it is wide rather than long

Four checkpoint blocks of nine columns, not four rows a token. Phase 3 tests
ENTRY LEVELS, so "the velocity at 90 for tokens that also cleared 80" has to be
one predicate on one row. A long table would make every such question a
self-join, and the shape of the question is fixed — there will never be a
fifth level, because 100 is graduation itself.

## Null is not zero anywhere in this table

A checkpoint never reached nulls its whole block rather than dropping the
token: "reached 70 and died" is the row a strategy most needs, and dropping it
would condition the sample on success. Outcomes null together when
post-graduation coverage falls under the floor, and
`postgrad_minutes_covered` is written either way so a null always says why.

Parented to 0070.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# 32 characters at most: alembic_version.version_num is varchar(32).
revision: str = "0071_graduation_features"
down_revision: str = "0070_graduation_rpc"
branch_labels = None
depends_on = None

_ADDRESS = sa.String(64)
_QUOTE = sa.Numeric(30, 9)
_USD = sa.Numeric(24, 8)
#: Minutes, to a thousandth.
_MIN = sa.Numeric(10, 3)
#: Progress POINTS per minute: room above 100, precision below 1.
_VEL = sa.Numeric(12, 6)
#: A return as a FRACTION of the open. Ten integer digits, because a
#: memecoin's first hour is not bounded by good sense.
_RET = sa.Numeric(18, 8)


def upgrade() -> None:
    op.create_table(
        "grad_features",
        sa.Column("mint", _ADDRESS, nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        # The EARLIER of the two independent graduation signals: the websocket
        # migration message, and the chain's own `complete` flag.
        sa.Column("graduated_at", sa.DateTime(timezone=True), nullable=False),
        # Null for a token the migration feed reported that this lab never
        # watched — outcomes, no features. A useful control, not a defect.
        sa.Column("launch_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("quote_currency", sa.String(8), nullable=True),
        sa.Column("curve_sample_count", sa.Integer(), nullable=False,
                  server_default=sa.text("0")),
        # --- the 70% checkpoint: all nine null together when never reached ---
        sa.Column("f70_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("f70_minutes_since_launch", _MIN, nullable=True),
        sa.Column("f70_minutes_from_70", _MIN, nullable=True),
        sa.Column("f70_velocity_5m", _VEL, nullable=True),
        sa.Column("f70_velocity_15m", _VEL, nullable=True),
        sa.Column("f70_changes_15m", sa.Integer(), nullable=True),
        sa.Column("f70_stall_count", sa.Integer(), nullable=True),
        sa.Column("f70_market_cap_quote", _QUOTE, nullable=True),
        sa.Column("f70_retrace_flag", sa.Boolean(), nullable=True),
        # --- the 80% checkpoint: all nine null together when never reached ---
        sa.Column("f80_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("f80_minutes_since_launch", _MIN, nullable=True),
        sa.Column("f80_minutes_from_70", _MIN, nullable=True),
        sa.Column("f80_velocity_5m", _VEL, nullable=True),
        sa.Column("f80_velocity_15m", _VEL, nullable=True),
        sa.Column("f80_changes_15m", sa.Integer(), nullable=True),
        sa.Column("f80_stall_count", sa.Integer(), nullable=True),
        sa.Column("f80_market_cap_quote", _QUOTE, nullable=True),
        sa.Column("f80_retrace_flag", sa.Boolean(), nullable=True),
        # --- the 90% checkpoint: all nine null together when never reached ---
        sa.Column("f90_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("f90_minutes_since_launch", _MIN, nullable=True),
        sa.Column("f90_minutes_from_70", _MIN, nullable=True),
        sa.Column("f90_velocity_5m", _VEL, nullable=True),
        sa.Column("f90_velocity_15m", _VEL, nullable=True),
        sa.Column("f90_changes_15m", sa.Integer(), nullable=True),
        sa.Column("f90_stall_count", sa.Integer(), nullable=True),
        sa.Column("f90_market_cap_quote", _QUOTE, nullable=True),
        sa.Column("f90_retrace_flag", sa.Boolean(), nullable=True),
        # --- the 95% checkpoint: all nine null together when never reached ---
        sa.Column("f95_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("f95_minutes_since_launch", _MIN, nullable=True),
        sa.Column("f95_minutes_from_70", _MIN, nullable=True),
        sa.Column("f95_velocity_5m", _VEL, nullable=True),
        sa.Column("f95_velocity_15m", _VEL, nullable=True),
        sa.Column("f95_changes_15m", sa.Integer(), nullable=True),
        sa.Column("f95_stall_count", sa.Integer(), nullable=True),
        sa.Column("f95_market_cap_quote", _QUOTE, nullable=True),
        sa.Column("f95_retrace_flag", sa.Boolean(), nullable=True),

        # --- outcomes, relative to the pool open -------------------------
        # The FIRST post-graduation price: the earliest price anything could
        # actually have been bought at, and the denominator of every return.
        sa.Column("open_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("open_price_usd", _USD, nullable=True),
        sa.Column("postgrad_minutes_covered", sa.Integer(), nullable=True),
        sa.Column("sample_gap_flag", sa.Boolean(), nullable=True),
        sa.Column("backfilled_samples", sa.Integer(), nullable=True),
        sa.Column("migration_lag_min", _MIN, nullable=True),
        sa.Column("outcome_ok", sa.Boolean(), nullable=False,
                  server_default=sa.false()),
        sa.Column("return_2m", _RET, nullable=True),
        sa.Column("return_5m", _RET, nullable=True),
        sa.Column("return_15m", _RET, nullable=True),
        sa.Column("return_30m", _RET, nullable=True),
        sa.Column("return_60m", _RET, nullable=True),
        sa.Column("max_return_60m", _RET, nullable=True),
        # From a RUNNING peak, not from the open.
        sa.Column("max_drawdown_60m", _RET, nullable=True),
        sa.Column("minutes_to_peak", _MIN, nullable=True),
        sa.PrimaryKeyConstraint("mint", name="pk_grad_features"),
    )
    op.create_index("ix_grad_features_graduated_at", "grad_features",
                    ["graduated_at"])
    op.create_index("ix_grad_features_outcome_ok", "grad_features",
                    ["outcome_ok"])


def downgrade() -> None:
    op.drop_table("grad_features")
