"""Paper Wallet Jupiter execution model metadata.

Sprint 39. Future paper trades capture the Jupiter route quote used at entry
and exit, while historical rows remain untouched. Every column added here is
nullable and has no server default: a legacy row with null execution fields is
still the exact row it was before this migration.

Revision ID: 0015_jupiter_execution_model
Revises: 0014_paper_manual_sell
Create Date: 2026-08-08 20:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0015_jupiter_execution_model"
down_revision: str | None = "0014_paper_manual_sell"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PRICE = sa.Numeric(precision=38, scale=18)
MONEY = sa.Numeric(precision=24, scale=4)
PCT = sa.Numeric(precision=20, scale=4)
JSONB = postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite")


def _add_execution_columns(
    table: str,
    *,
    include_model: bool,
    include_summary: bool,
    include_side_status: bool,
) -> None:
    if include_model:
        op.add_column(table, sa.Column("execution_model_version", sa.String(length=64)))
    op.add_column(table, sa.Column("entry_execution_model_version", sa.String(length=64)))
    op.add_column(table, sa.Column("exit_execution_model_version", sa.String(length=64)))
    op.add_column(table, sa.Column("entry_execution_quote", JSONB))
    op.add_column(table, sa.Column("exit_execution_quote", JSONB))
    op.add_column(table, sa.Column("entry_execution_quoted_at", sa.DateTime(timezone=True)))
    op.add_column(table, sa.Column("exit_execution_quoted_at", sa.DateTime(timezone=True)))
    op.add_column(table, sa.Column("entry_execution_context_slot", sa.Integer()))
    op.add_column(table, sa.Column("exit_execution_context_slot", sa.Integer()))
    op.add_column(table, sa.Column("entry_execution_price_impact_pct", PCT))
    op.add_column(table, sa.Column("exit_execution_price_impact_pct", PCT))
    op.add_column(table, sa.Column("entry_execution_fee_usd", MONEY))
    op.add_column(table, sa.Column("exit_execution_fee_usd", MONEY))
    op.add_column(table, sa.Column("entry_execution_route", sa.Text()))
    op.add_column(table, sa.Column("exit_execution_route", sa.Text()))
    if include_side_status:
        op.add_column(table, sa.Column("entry_execution_confidence", sa.String(length=32)))
        op.add_column(table, sa.Column("entry_execution_fallback_reason", sa.Text()))
        op.add_column(table, sa.Column("exit_execution_confidence", sa.String(length=32)))
        op.add_column(table, sa.Column("exit_execution_fallback_reason", sa.Text()))
    if include_summary:
        op.add_column(table, sa.Column("execution_confidence", sa.String(length=32)))
        op.add_column(table, sa.Column("execution_fallback_reason", sa.Text()))


def _drop_execution_columns(
    table: str,
    *,
    include_model: bool,
    include_summary: bool,
    include_side_status: bool,
) -> None:
    if include_summary:
        _drop_column_if_exists(table, "execution_fallback_reason")
        _drop_column_if_exists(table, "execution_confidence")
    _drop_column_if_exists(table, "exit_execution_fallback_reason")
    _drop_column_if_exists(table, "exit_execution_confidence")
    _drop_column_if_exists(table, "entry_execution_fallback_reason")
    _drop_column_if_exists(table, "entry_execution_confidence")
    _drop_column_if_exists(table, "exit_execution_route")
    _drop_column_if_exists(table, "entry_execution_route")
    _drop_column_if_exists(table, "exit_execution_fee_usd")
    _drop_column_if_exists(table, "entry_execution_fee_usd")
    _drop_column_if_exists(table, "exit_execution_price_impact_pct")
    _drop_column_if_exists(table, "entry_execution_price_impact_pct")
    _drop_column_if_exists(table, "exit_execution_context_slot")
    _drop_column_if_exists(table, "entry_execution_context_slot")
    _drop_column_if_exists(table, "exit_execution_quoted_at")
    _drop_column_if_exists(table, "entry_execution_quoted_at")
    _drop_column_if_exists(table, "exit_execution_quote")
    _drop_column_if_exists(table, "entry_execution_quote")
    _drop_column_if_exists(table, "exit_execution_model_version")
    _drop_column_if_exists(table, "entry_execution_model_version")
    if include_model:
        _drop_column_if_exists(table, "execution_model_version")


def _drop_column_if_exists(table: str, column: str) -> None:
    op.execute(sa.text(f"ALTER TABLE {table} DROP COLUMN IF EXISTS {column}"))


def upgrade() -> None:
    op.add_column("paper_positions", sa.Column("entry_observed_price", PRICE))
    op.add_column("paper_positions", sa.Column("exit_observed_price", PRICE))
    _add_execution_columns(
        "paper_positions",
        include_model=False,
        include_summary=False,
        include_side_status=True,
    )

    op.add_column("paper_trade_audit", sa.Column("entry_observed_price", PRICE))
    op.add_column("paper_trade_audit", sa.Column("exit_observed_price", PRICE))
    _add_execution_columns(
        "paper_trade_audit",
        include_model=True,
        include_summary=True,
        include_side_status=False,
    )


def downgrade() -> None:
    _drop_execution_columns(
        "paper_trade_audit",
        include_model=True,
        include_summary=True,
        include_side_status=False,
    )
    _drop_column_if_exists("paper_trade_audit", "exit_observed_price")
    _drop_column_if_exists("paper_trade_audit", "entry_observed_price")

    _drop_execution_columns(
        "paper_positions",
        include_model=False,
        include_summary=False,
        include_side_status=True,
    )
    _drop_column_if_exists("paper_positions", "exit_observed_price")
    _drop_column_if_exists("paper_positions", "entry_observed_price")
