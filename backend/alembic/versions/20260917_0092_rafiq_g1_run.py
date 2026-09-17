"""Rafiq Lab G1: runs, a partial-sale position, the ratchet's memory.

* `lab_run_id` on strategies, positions and daily state. Every existing row is
  backfilled to `F2-and-earlier`; G1's rows are written as `G1-2026-09-17`.
  The strategies' unique key moves from `code` to `(lab_run_id, code)`, so a
  new run is new rows and an archived config row is never rewritten.
* On positions: G1's partial-sale bookkeeping (`scaled_out`, `fraction_open`,
  `realised_usd`, `scaled_out_at`, `scale_out_price`), the parameters an
  entry was opened under (`abandon_gain`, `size_multiplier`), and
  `last_mark_liquidity_usd` for mark-to-pool valuation. The defaults describe
  every existing row exactly: one sale, whole position, nothing realised early.
* Two tables: `rafiq_lab_run_state` (the ratchet's high-water mark and floor,
  which must survive a restart) and `rafiq_lab_adjustments` (every floor move,
  and later every learned parameter change).

Nothing is deleted and no existing value changes.

Revision ID: 0092_rafiq_g1_run
Revises: 0091_real_wallet_ticket
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0092_rafiq_g1_run"
down_revision: str = "0091_real_wallet_ticket"
branch_labels = None
depends_on = None

ARCHIVED = "F2-and-earlier"
_RUN_TABLES = ("rafiq_lab_strategies", "rafiq_lab_positions", "rafiq_lab_daily_state")


def _position_columns() -> list[sa.Column]:
    return [
        sa.Column("last_mark_liquidity_usd", sa.Numeric(24, 4)),
        sa.Column("scaled_out", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("fraction_open", sa.Numeric(10, 4), nullable=False,
                  server_default=sa.text("1")),
        sa.Column("realised_usd", sa.Numeric(24, 4), nullable=False,
                  server_default=sa.text("0")),
        sa.Column("scaled_out_at", sa.DateTime(timezone=True)),
        sa.Column("scale_out_price", sa.Numeric(38, 18)),
        sa.Column("abandon_gain", sa.Numeric(10, 4)),
        sa.Column("size_multiplier", sa.Numeric(10, 4)),
    ]


def upgrade() -> None:
    for table in _RUN_TABLES:
        # Backfilled by the default, which is then dropped: a row written
        # without a run must fail, not quietly join the archive.
        op.add_column(table, sa.Column("lab_run_id", sa.String(32), nullable=False,
                                       server_default=ARCHIVED))
        op.alter_column(table, "lab_run_id", server_default=None)

    op.drop_constraint("uq_rafiq_lab_strategies_code", "rafiq_lab_strategies",
                       type_="unique")
    op.create_unique_constraint("uq_rafiq_lab_strategies_run_code",
                                "rafiq_lab_strategies", ["lab_run_id", "code"])

    for column in _position_columns():
        op.add_column("rafiq_lab_positions", column)

    op.create_table(
        "rafiq_lab_run_state",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("lab_run_id", sa.String(32), nullable=False),
        sa.Column("ratchet_high_water", sa.Numeric(24, 4), nullable=False),
        sa.Column("ratchet_floor", sa.Numeric(24, 4), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.UniqueConstraint("lab_run_id", name="uq_rafiq_lab_run_state_run"),
    )
    op.create_table(
        "rafiq_lab_adjustments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("lab_run_id", sa.String(32), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("parameter", sa.String(48), nullable=False),
        sa.Column("old_value", sa.Numeric(24, 6), nullable=False),
        sa.Column("new_value", sa.Numeric(24, 6), nullable=False),
        sa.Column("sample_size", sa.Integer()),
        sa.Column("z_score", sa.Numeric(10, 3)),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
    )
    op.create_index("ix_rafiq_lab_adjustments_run_at", "rafiq_lab_adjustments",
                    ["lab_run_id", "at"])


def downgrade() -> None:
    op.drop_index("ix_rafiq_lab_adjustments_run_at", table_name="rafiq_lab_adjustments")
    op.drop_table("rafiq_lab_adjustments")
    op.drop_table("rafiq_lab_run_state")
    for column in reversed(_position_columns()):
        op.drop_column("rafiq_lab_positions", column.name)
    op.drop_constraint("uq_rafiq_lab_strategies_run_code", "rafiq_lab_strategies",
                       type_="unique")
    # Fails, deliberately, if a code now exists in two runs: collapsing them
    # would put two books under one name.
    op.create_unique_constraint("uq_rafiq_lab_strategies_code",
                                "rafiq_lab_strategies", ["code"])
    for table in reversed(_RUN_TABLES):
        op.drop_column(table, "lab_run_id")
