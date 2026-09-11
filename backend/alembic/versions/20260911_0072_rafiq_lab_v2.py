"""Rafiq Lab v2: legs, the entry gate's instrumentation, and its rejection counters.

## What this changes, and what it does not

Three additive columns on `rafiq_lab_positions`, one widened column on
`rafiq_lab_strategies`, one relaxed unique constraint, one nullable column, and
one new table. Nothing else in the database is touched, and a deployment that
runs this and never sets `RAFIQ_LAB_ENABLED` is unaffected in every table that
existed before it.

## `leg`, and why the unique key had to change

v1 held one position per token per strategy, forever, in the database rather
than in code — which is what made a retried task and two concurrent ticks
collapse to one entry instead of two. C2 deliberately opens TWO rows per token
(half with a +30% target, half with none, trailing), so that key now carries
`leg`. It still holds the exactly-once guarantee; it just holds it per leg.

Existing rows backfill to `leg = 1`, which is what they were.

## `target_price` becomes nullable

D2 has no take profit at all, and neither does C2's second leg. That is a rule,
not a missing value: those positions can only leave on the stop, the trail or
the hold. A sentinel target of "infinity" would have kept the column NOT NULL
and put a number nobody chose into the record.

## The counters, and why they are counters

`rafiq_lab_gate_rejections` is one row per (strategy, reason), incremented in
place. The v2 gate refuses roughly three quarters of the stream, on every tick,
for every book; a row per rejection would be millions of rows nobody reads. The
question a read-out actually asks is "how often, and for which condition",
which a counter answers exactly.

## This migration does NOT delete v1's books

The v1 rows are a different experiment under the same table names, and removing
them is an operational step taken deliberately with an archive in hand — not
something a schema migration should do silently on whatever database it meets.
`service.activate()` refuses to run against a ledger holding unknown codes, so
a deployment that skips the removal stops loudly instead of trading into it.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0072_rafiq_lab_v2"
down_revision: str = "0071_graduation_features"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- books: `A2` does not fit String(2) ---------------------------------
    op.alter_column("rafiq_lab_strategies", "code",
                    existing_type=sa.String(length=2), type_=sa.String(length=4),
                    existing_nullable=False)

    # --- positions ----------------------------------------------------------
    op.add_column("rafiq_lab_positions",
                  sa.Column("leg", sa.Integer(), nullable=False,
                            server_default=sa.text("1")))
    op.add_column("rafiq_lab_positions",
                  sa.Column("entry_market_cap_usd", sa.Numeric(24, 4), nullable=True))
    op.add_column("rafiq_lab_positions",
                  sa.Column("entry_price_impact_pct", sa.Numeric(10, 4), nullable=True))
    op.add_column("rafiq_lab_positions",
                  sa.Column("exit_price_impact_pct", sa.Numeric(10, 4), nullable=True))
    op.alter_column("rafiq_lab_positions", "target_price",
                    existing_type=sa.Numeric(38, 18), nullable=True)

    op.drop_constraint("uq_rafiq_lab_positions_strategy_mint",
                       "rafiq_lab_positions", type_="unique")
    op.create_unique_constraint("uq_rafiq_lab_positions_strategy_mint_leg",
                                "rafiq_lab_positions",
                                ["strategy_id", "mint_address", "leg"])

    # --- the gate's own record ----------------------------------------------
    op.create_table(
        "rafiq_lab_gate_rejections",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True),
                  primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("strategy_id", sa.dialects.postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("rafiq_lab_strategies.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("reason", sa.String(length=48), nullable=False),
        sa.Column("rejections", sa.Integer(), nullable=False,
                  server_default=sa.text("0")),
        sa.Column("last_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.UniqueConstraint("strategy_id", "reason",
                            name="uq_rafiq_lab_gate_rejections_strategy_reason"),
    )


def downgrade() -> None:
    op.drop_table("rafiq_lab_gate_rejections")

    op.drop_constraint("uq_rafiq_lab_positions_strategy_mint_leg",
                       "rafiq_lab_positions", type_="unique")
    # Only restorable while at most one leg per (strategy, mint) survives —
    # true of v1's rows, and of v2's for every book but C2. Downgrading a
    # database that has run C2 will fail here, loudly, which is correct: the
    # old key cannot describe the rows that exist.
    op.create_unique_constraint("uq_rafiq_lab_positions_strategy_mint",
                                "rafiq_lab_positions",
                                ["strategy_id", "mint_address"])

    # A NOT NULL target cannot describe a book that has none, so any such row
    # is dropped rather than given an invented target.
    op.execute("DELETE FROM rafiq_lab_positions WHERE target_price IS NULL")
    op.alter_column("rafiq_lab_positions", "target_price",
                    existing_type=sa.Numeric(38, 18), nullable=False)

    op.drop_column("rafiq_lab_positions", "exit_price_impact_pct")
    op.drop_column("rafiq_lab_positions", "entry_price_impact_pct")
    op.drop_column("rafiq_lab_positions", "entry_market_cap_usd")
    op.drop_column("rafiq_lab_positions", "leg")

    op.alter_column("rafiq_lab_strategies", "code",
                    existing_type=sa.String(length=4), type_=sa.String(length=2),
                    existing_nullable=False)
