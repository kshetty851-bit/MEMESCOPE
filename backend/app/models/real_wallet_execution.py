"""Append-only dry-run evidence, kept completely separate from Paper Wallet."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Numeric, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPrimaryKeyMixin


class RealWalletExecutionIntent(Base, UUIDPrimaryKeyMixin):
    """One immutable autonomous decision attempt; never a submitted trade."""

    __tablename__ = "real_wallet_execution_intents"

    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    mint_address: Mapped[str] = mapped_column(String(44), nullable=False)
    symbol: Mapped[str | None] = mapped_column(String(64))
    side: Mapped[str] = mapped_column(String(8), nullable=False, default="BUY")
    mode: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    strategy_id: Mapped[str] = mapped_column(String(64), nullable=False)
    strategy_version: Mapped[str] = mapped_column(String(32), nullable=False)
    radar_rank: Mapped[int] = mapped_column(nullable=False)
    signal_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    requested_usd: Mapped[Decimal] = mapped_column(Numeric(24, 4), nullable=False)
    safety_evaluation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("real_wallet_safety_evaluations.id")
    )
    safety_decision: Mapped[str | None] = mapped_column(String(8))
    reason_codes: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    liquidity_usd: Mapped[Decimal | None] = mapped_column(Numeric(24, 4))
    buy_impact_pct: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    sell_impact_pct: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    round_trip_loss_pct: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    buy_order: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    sell_order: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_real_wallet_execution_intent_key"),
        Index("ix_real_wallet_execution_intent_evaluated", "evaluated_at"),
        Index("ix_real_wallet_execution_intent_status", "status"),
    )


class RealWalletPosition(Base, UUIDPrimaryKeyMixin):
    """Reserved real-position ledger. Dry-run never creates one of these rows."""

    __tablename__ = "real_wallet_positions"

    mint_address: Mapped[str] = mapped_column(String(44), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    opened_intent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("real_wallet_execution_intents.id"), nullable=False
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    entry_price_usd: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
