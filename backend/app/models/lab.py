"""V6 Forward Strategy Lab — twenty independently accounted $1,000 portfolios.

Research simulation, never money. Nothing here may be imported by the paper,
karthik or real-wallet packages, and nothing here writes to their tables; a
source-parsing test enforces the boundary, as it does for the Arena.

The decision ledger is the point of the structure. Every token that reaches a
strategy's checkpoint produces a row for THAT strategy — including the skips,
with the reason — written once and never rewritten once the outcome arrives.
What a strategy refused to buy is evidence exactly as much as what it bought.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

MONEY = Numeric(24, 4)
PRICE = Numeric(38, 18)
QTY = Numeric(48, 18)
MULT = Numeric(20, 6)

ROUTE_STATES = ("BUY_OK_SELL_OK", "BUY_OK_SELL_FAILED", "BUY_FAILED", "ROUTE_UNKNOWN")


class LabTournament(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """The singleton run. `valid_from` is the contamination boundary and can
    never move; the 24-hour snapshot instant is derived from it at activation
    and persisted, so the timer survives restarts and is never extended for
    downtime (mission §15)."""

    __tablename__ = "lab_tournaments"

    spec_version: Mapped[str] = mapped_column(String(16), nullable=False)
    #: SHA-256 of the frozen registry. A tick whose spec no longer hashes to
    #: this stops rather than scoring against drifted rules.
    spec_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    snapshot_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    snapshot_taken_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="active")
    protocol_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("uq_lab_tournament_singleton", "spec_version", unique=True),
    )


class LabStrategy(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One virtual portfolio and its frozen rules, copied in at activation."""

    __tablename__ = "lab_strategies"

    tournament_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("lab_tournaments.id", ondelete="CASCADE"), nullable=False
    )
    strategy_id: Mapped[str] = mapped_column(String(8), nullable=False)
    name: Mapped[str] = mapped_column(String(32), nullable=False)
    version: Mapped[str] = mapped_column(String(16), nullable=False)
    spec_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    #: NULL for the cash control, which has no checkpoint because it never acts.
    checkpoint_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    size_usd: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    max_concurrent: Mapped[int] = mapped_column(Integer, nullable=False)
    max_exposure_usd: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    #: The whole frozen specification as data, so the record is readable
    #: without the code that produced it.
    rules: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    starting_equity: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    cash: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    peak_equity: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="active")
    failed_reason: Mapped[str | None] = mapped_column(String(48), nullable=True)
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("tournament_id", "strategy_id", name="uq_lab_strategy_once"),
        CheckConstraint("status IN ('active','failed')", name="ck_lab_strategy_status"),
    )


class LabDecision(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One strategy's verdict on one token at its own checkpoint. Written once.

    A strategy sees only what existed at `checkpoint_at`; `snapshot_ids` names
    the exact common observations the features were computed from, so any
    decision can be replayed against the same rows that produced it.
    """

    __tablename__ = "lab_decisions"

    strategy_row_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("lab_strategies.id", ondelete="CASCADE"), nullable=False
    )
    strategy_id: Mapped[str] = mapped_column(String(8), nullable=False)
    mint_address: Mapped[str] = mapped_column(String(44), nullable=False)
    token_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("discovered_tokens.id", ondelete="CASCADE"), nullable=True
    )
    checkpoint_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    checkpoint_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    eligible: Mapped[bool] = mapped_column(Boolean, nullable=False)
    skip_reason: Mapped[str | None] = mapped_column(String(48), nullable=True)
    #: Exactly the values the rules read. Auditable, never recomputed later.
    features: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    snapshot_ids: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    route_state: Mapped[str | None] = mapped_column(String(20), nullable=True)
    quoted_impact_pct: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    requested_size_usd: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)

    __table_args__ = (
        UniqueConstraint("strategy_row_id", "mint_address", name="uq_lab_decision_once"),
        CheckConstraint(
            "route_state IS NULL OR route_state IN "
            "('BUY_OK_SELL_OK','BUY_OK_SELL_FAILED','BUY_FAILED','ROUTE_UNKNOWN')",
            name="ck_lab_decision_route",
        ),
        Index("ix_lab_decisions_strategy_checkpoint", "strategy_row_id", "checkpoint_at"),
        Index("ix_lab_decisions_mint", "mint_address"),
    )


class LabPosition(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A virtual position. Capital is tied up until its own frozen exit fires.

    `quantity_remaining` and `banked_proceeds` exist because V6-19 sells half at
    1.25x and runs the rest to 2x: P&L is banked plus remaining, while every
    LEVEL trigger is measured on the executable multiple of the ORIGINAL size.
    """

    __tablename__ = "lab_positions"

    strategy_row_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("lab_strategies.id", ondelete="CASCADE"), nullable=False
    )
    strategy_id: Mapped[str] = mapped_column(String(8), nullable=False)
    decision_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("lab_decisions.id", ondelete="CASCADE"), nullable=False
    )
    mint_address: Mapped[str] = mapped_column(String(44), nullable=False)
    token_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("discovered_tokens.id", ondelete="CASCADE"), nullable=True
    )
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    entry_price: Mapped[Decimal] = mapped_column(PRICE, nullable=False)
    entry_liquidity_usd: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    size_usd: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    quantity: Mapped[Decimal] = mapped_column(QTY, nullable=False)
    quantity_remaining: Mapped[Decimal] = mapped_column(QTY, nullable=False)
    banked_proceeds_usd: Mapped[Decimal] = mapped_column(MONEY, nullable=False,
                                                         server_default="0")
    entry_impact_pct: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    entry_source: Mapped[str] = mapped_column(String(16), nullable=False)

    status: Mapped[str] = mapped_column(String(8), nullable=False, server_default="open")
    peak_exec_multiple: Mapped[Decimal] = mapped_column(MULT, nullable=False, server_default="1")
    last_exec_multiple: Mapped[Decimal | None] = mapped_column(MULT, nullable=True)
    #: Executable open value at the last mark — never the deployed cost.
    last_open_value_usd: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    break_even_armed: Mapped[bool] = mapped_column(Boolean, nullable=False,
                                                    server_default="false")
    partial_done: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    partial_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    flat_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_evaluated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True),
                                                               nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    exit_price: Mapped[Decimal | None] = mapped_column(PRICE, nullable=True)
    exit_proceeds_usd: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    exit_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    route_state: Mapped[str | None] = mapped_column(String(20), nullable=True)
    reached_125: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    reached_150: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    reached_200: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    #: Executable value at the 24h boundary, stamped once (mission §24).
    snapshot_value_usd: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)

    __table_args__ = (
        UniqueConstraint("strategy_row_id", "mint_address", name="uq_lab_position_once"),
        CheckConstraint("status IN ('open','closed')", name="ck_lab_position_status"),
        Index("ix_lab_positions_open", "strategy_row_id", "status"),
    )


class LabEquityPoint(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One mark of one strategy's book. Equity is cash + EXECUTABLE open value,
    never cash + deployed cost — the distinction the Arena UI already makes."""

    __tablename__ = "lab_equity_points"

    strategy_row_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("lab_strategies.id", ondelete="CASCADE"), nullable=False
    )
    strategy_id: Mapped[str] = mapped_column(String(8), nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    cash: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    deployed_cost: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    open_value: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    equity: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    open_positions: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    __table_args__ = (
        Index("ix_lab_equity_strategy_at", "strategy_row_id", "captured_at"),
    )


class LabSnapshot(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """An immutable leaderboard, frozen at a boundary. Written once per label."""

    __tablename__ = "lab_snapshots"

    tournament_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("lab_tournaments.id", ondelete="CASCADE"), nullable=False
    )
    #: 24H | 48H | 72H | 7D | 14D | 21D | TRADES_25 | TRADES_50 | ...
    label: Mapped[str] = mapped_column(String(24), nullable=False)
    boundary_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    taken_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    elapsed_hours: Mapped[float] = mapped_column(Float, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    __table_args__ = (
        UniqueConstraint("tournament_id", "label", name="uq_lab_snapshot_once"),
    )
