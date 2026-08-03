"""Bonding curve observations.

One new table, additive. Nothing existing is touched, so the scanner,
enrichment, scoring, the Radar and the Opportunity Engine are unaffected and
this applies while they run.

`token_curve_snapshots` is append-only, mirroring `token_market_snapshots`.
The two record different things from different sources — DexScreener reports a
*pair*, this records the *curve* — and Sprint 7 measured that the first cannot
stand in for the second: `market_cap` on a bonding-curve pair identified 5 of
386 observed graduations (ARCHITECTURE_DECISIONS.md §14a). This table is the
input that closes that gap.

**Only raw account fields are stored.** Curve progress is derived at read time
in `services/curve/state.py`, because a derived column is one that can drift
from its source — and because the derivation may need correcting once the
account layout is confirmed against a live read, which the exhausted Helius
quota currently prevents.

`NUMERIC(20, 0)` rather than `BIGINT`: these are unsigned 64-bit on-chain
values, and `u64` runs past what a signed `bigint` holds. Today's values fit
either way; the type is chosen so a protocol change cannot silently corrupt a
row.

Revision ID: 0009_curve
Revises: 0008_opportunity
Create Date: 2026-08-03 12:20:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_curve"
down_revision: str | None = "0008_opportunity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Unsigned 64-bit, exactly.
_U64 = sa.Numeric(precision=20, scale=0)


def upgrade() -> None:
    op.create_table(
        "token_curve_snapshots",
        sa.Column(
            "id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("token_id", sa.UUID(), nullable=False),
        sa.Column("mint_address", sa.String(length=44), nullable=False),
        sa.Column(
            "captured_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("virtual_token_reserves", _U64, nullable=False),
        sa.Column("virtual_sol_reserves", _U64, nullable=False),
        sa.Column("real_token_reserves", _U64, nullable=False),
        sa.Column("real_sol_reserves", _U64, nullable=False),
        sa.Column("token_total_supply", _U64, nullable=False),
        sa.Column("complete", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["token_id"],
            ["discovered_tokens.id"],
            name="fk_token_curve_snapshots_token_id_discovered_tokens",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_token_curve_snapshots"),
        # The curve account changes on-chain, not on our clock. Two reads landing
        # in the same instant would record one state twice and inflate a series
        # the near-graduation provider reads as movement.
        sa.UniqueConstraint(
            "mint_address", "captured_at", name="uq_curve_snapshots_mint_captured"
        ),
    )
    op.create_index(
        "ix_curve_snapshots_mint_captured",
        "token_curve_snapshots",
        ["mint_address", sa.text("captured_at DESC")],
        unique=False,
    )
    # Partial: "which curves completed recently" is the graduation question, and
    # completed rows are a small minority of the table.
    op.create_index(
        "ix_curve_snapshots_complete",
        "token_curve_snapshots",
        [sa.text("captured_at DESC")],
        unique=False,
        postgresql_where=sa.text("complete"),
    )


def downgrade() -> None:
    op.drop_index("ix_curve_snapshots_complete", table_name="token_curve_snapshots")
    op.drop_index(
        "ix_curve_snapshots_mint_captured", table_name="token_curve_snapshots"
    )
    op.drop_table("token_curve_snapshots")
