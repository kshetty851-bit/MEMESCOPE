"""Rafiq Lab: three new tables. Nothing existing is touched.

`rafiq_lab_*`, not `rafiq_*`. The bare `rafiq_` prefix already belongs to the
unmerged `rafiq-wallet` branch (`rafiq_wallets`, `rafiq_positions`, ...), and
two subsystems fighting over a table name is a merge conflict that only shows
up in production.

Purely additive: no ALTER, no DROP, no index on an existing table. A database
that runs this migration and never enables `RAFIQ_LAB_ENABLED` is byte-identical
in every table that existed before it, and a test asserts exactly that.

Numbered 0063 on this branch and 0056 on `karthik-hq`, because the two chains
forked at 0053 and this lab was written on the other side of the fork. The two
files create the same three tables. **If `karthik-hq` is ever merged here, keep
one and delete the other** — running both would try to create `rafiq_lab_*`
twice.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0063_rafiq_lab"
down_revision: str = "0062_lab_decision_per_checkpoint"
branch_labels = None
depends_on = None

_PRICE = sa.Numeric(38, 18)
_MONEY = sa.Numeric(24, 4)
_QUANTITY = sa.Numeric(48, 18)


def upgrade() -> None:
    op.create_table(
        "rafiq_lab_strategies",
        sa.Column("id", postgresql.UUID(as_uuid=True),
                  server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("code", sa.String(2), nullable=False),
        sa.Column("lane", sa.String(48), nullable=False),
        sa.Column("starting_equity", _MONEY, nullable=False),
        sa.Column("profile_digest", sa.String(64), nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", name="uq_rafiq_lab_strategies_code"),
    )
    op.create_index("ix_rafiq_lab_strategies_created_at", "rafiq_lab_strategies",
                    ["created_at"])

    op.create_table(
        "rafiq_lab_positions",
        sa.Column("id", postgresql.UUID(as_uuid=True),
                  server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("strategy_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("mint_address", sa.String(44), nullable=False),
        sa.Column("symbol", sa.String(32), nullable=True),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("entry_price", _PRICE, nullable=False),
        sa.Column("entry_observed_price", _PRICE, nullable=False),
        sa.Column("quantity", _QUANTITY, nullable=False),
        sa.Column("cost_basis", _MONEY, nullable=False),
        sa.Column("entry_liquidity_usd", _MONEY, nullable=True),
        sa.Column("stop_price", _PRICE, nullable=False),
        sa.Column("target_price", _PRICE, nullable=False),
        sa.Column("stop_pct", sa.Numeric(10, 4), nullable=False),
        sa.Column("trailing_frac", sa.Numeric(10, 4), nullable=True),
        sa.Column("max_hold_seconds", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False,
                  server_default=sa.text("'open'")),
        sa.Column("peak_price", _PRICE, nullable=False),
        sa.Column("last_evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_mark_price", _PRICE, nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("exit_price", _PRICE, nullable=True),
        sa.Column("exit_observed_price", _PRICE, nullable=True),
        sa.Column("exit_proceeds_usd", _MONEY, nullable=True),
        sa.Column("exit_reason", sa.String(16), nullable=True),
        sa.Column("exit_evidence", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["strategy_id"], ["rafiq_lab_strategies.id"],
                                ondelete="CASCADE"),
        # Exactly-once, held by the database: a retried task, a restarted
        # worker and two concurrent ticks all collapse to one position.
        sa.UniqueConstraint("strategy_id", "mint_address",
                            name="uq_rafiq_lab_positions_strategy_mint"),
    )
    op.create_index("ix_rafiq_lab_positions_open", "rafiq_lab_positions",
                    ["strategy_id", "last_evaluated_at"],
                    postgresql_where=sa.text("status = 'open'"))
    op.create_index("ix_rafiq_lab_positions_closed_at", "rafiq_lab_positions",
                    ["strategy_id", "closed_at"])

    op.create_table(
        "rafiq_lab_daily_state",
        sa.Column("id", postgresql.UUID(as_uuid=True),
                  server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("strategy_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("day_open_equity", _MONEY, nullable=False),
        sa.Column("realised_today", _MONEY, nullable=False,
                  server_default=sa.text("0")),
        sa.Column("halted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("halted_reason", sa.Text(), nullable=True),
        sa.Column("halted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["strategy_id"], ["rafiq_lab_strategies.id"],
                                ondelete="CASCADE"),
        sa.UniqueConstraint("strategy_id", "day",
                            name="uq_rafiq_lab_daily_state_day"),
    )


def downgrade() -> None:
    op.drop_table("rafiq_lab_daily_state")
    op.drop_index("ix_rafiq_lab_positions_closed_at", table_name="rafiq_lab_positions")
    op.drop_index("ix_rafiq_lab_positions_open", table_name="rafiq_lab_positions")
    op.drop_table("rafiq_lab_positions")
    op.drop_index("ix_rafiq_lab_strategies_created_at",
                  table_name="rafiq_lab_strategies")
    op.drop_table("rafiq_lab_strategies")
