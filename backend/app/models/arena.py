"""V5 Forward Strategy Arena — research simulation, never money.

Five independently accounted $1,000 virtual portfolios. Nothing here may be
imported by the paper wallet, the Karthik wallet or the real wallet, and
nothing here writes to their tables: an Arena failure must never be able to
disturb production accounting. A test parses this package's source and fails
if that boundary is crossed.

The decision ledger is the point of the whole structure. Every eligible token
produces a row for EVERY candidate — including the ones that skipped it, with
the reason — written once and never rewritten after the outcome arrives. What
a strategy refused to buy is evidence exactly as much as what it bought.
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
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

MONEY = Numeric(24, 4)
PRICE = Numeric(38, 18)
QTY = Numeric(48, 18)

#: Route outcome vocabulary. `BUY_OK_SELL_FAILED` is the case the Arena exists
#: to price: a token that could be bought and not sold is not a winner.
ROUTE_STATES = ("BUY_OK_SELL_OK", "BUY_OK_SELL_FAILED", "BUY_FAILED", "ROUTE_UNKNOWN")


class ArenaCandidate(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One virtual portfolio, its frozen rule version, and its cash."""

    __tablename__ = "arena_candidates"

    code: Mapped[str] = mapped_column(String(2), nullable=False)
    name: Mapped[str] = mapped_column(String(48), nullable=False)
    #: Changing any rule means a new version whose record starts at zero.
    version: Mapped[str] = mapped_column(String(16), nullable=False)
    #: Tokens whose checkpoint precedes this instant are contaminated and
    #: are never scored (see protocol §0).
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    starting_equity: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    cash: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    #: 'active' | 'failed'. A failed candidate stops opening positions, keeps
    #: settling open ones, and is never replaced by an optimised successor.
    status: Mapped[str] = mapped_column(String(12), nullable=False, server_default="active")
    failed_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: Running peak equity, for a drawdown that cannot be recomputed favourably.
    peak_equity: Mapped[Decimal] = mapped_column(MONEY, nullable=False)

    __table_args__ = (
        UniqueConstraint("code", "version", name="uq_arena_candidate_code_version"),
        CheckConstraint("status IN ('active','failed')", name="ck_arena_candidate_status"),
    )


class ArenaDecision(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One candidate's verdict on one token at its checkpoint. Written once."""

    __tablename__ = "arena_decisions"

    candidate_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("arena_candidates.id", ondelete="CASCADE"), nullable=False
    )
    mint_address: Mapped[str] = mapped_column(String(44), nullable=False)
    token_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("discovered_tokens.id", ondelete="CASCADE"), nullable=True
    )
    #: The instant the rules were evaluated against — the PIT boundary.
    checkpoint_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    checkpoint_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    eligible: Mapped[bool] = mapped_column(Boolean, nullable=False)
    #: First failing condition, or the operational reason no position opened.
    skip_reason: Mapped[str | None] = mapped_column(String(48), nullable=True)
    #: Exactly the values the rules read. Auditable, never recomputed later.
    features: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    route_state: Mapped[str | None] = mapped_column(String(20), nullable=True)
    quoted_impact_pct: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)

    __table_args__ = (
        UniqueConstraint("candidate_id", "mint_address", name="uq_arena_decision_once"),
        CheckConstraint(
            "route_state IS NULL OR route_state IN "
            "('BUY_OK_SELL_OK','BUY_OK_SELL_FAILED','BUY_FAILED','ROUTE_UNKNOWN')",
            name="ck_arena_decision_route",
        ),
        Index("ix_arena_decisions_candidate_checkpoint", "candidate_id", "checkpoint_at"),
    )


class ArenaPosition(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A virtual position. Capital is tied up until its frozen exit fires."""

    __tablename__ = "arena_positions"

    candidate_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("arena_candidates.id", ondelete="CASCADE"), nullable=False
    )
    decision_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("arena_decisions.id", ondelete="CASCADE"), nullable=False
    )
    mint_address: Mapped[str] = mapped_column(String(44), nullable=False)
    token_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("discovered_tokens.id", ondelete="CASCADE"), nullable=True
    )
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    entry_price: Mapped[Decimal] = mapped_column(PRICE, nullable=False)
    size_usd: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    quantity: Mapped[Decimal] = mapped_column(QTY, nullable=False)
    target_price: Mapped[Decimal] = mapped_column(PRICE, nullable=False)
    entry_impact_pct: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    entry_source: Mapped[str] = mapped_column(String(16), nullable=False)

    status: Mapped[str] = mapped_column(String(8), nullable=False, server_default="open")
    peak_multiple: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), nullable=True)
    last_evaluated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    exit_price: Mapped[Decimal | None] = mapped_column(PRICE, nullable=True)
    exit_proceeds_usd: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    #: target_1_5x | sell_route_lost | time_6h | dead_zero
    exit_reason: Mapped[str | None] = mapped_column(String(24), nullable=True)
    route_state: Mapped[str | None] = mapped_column(String(20), nullable=True)
    #: Secondary diagnostics only. Never used to re-select the exit.
    reached_125: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    reached_150: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    reached_200: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")

    __table_args__ = (
        UniqueConstraint("candidate_id", "mint_address", name="uq_arena_position_once"),
        CheckConstraint("status IN ('open','closed')", name="ck_arena_position_status"),
        Index("ix_arena_positions_candidate_status", "candidate_id", "status"),
    )
