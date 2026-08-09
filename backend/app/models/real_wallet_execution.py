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
    wallet_public_key: Mapped[str | None] = mapped_column(String(44))
    strategy_id: Mapped[str | None] = mapped_column(String(64))
    strategy_version: Mapped[str | None] = mapped_column(String(32))
    entry_safety_evaluation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("real_wallet_safety_evaluations.id")
    )
    entry_transaction_signature: Mapped[str | None] = mapped_column(String(128))
    entry_actual_input_amount: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    entry_actual_output_amount: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    exit_intent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("real_wallet_live_intents.id")
    )
    exit_transaction_signature: Mapped[str | None] = mapped_column(String(128))
    exit_actual_output_amount: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    exit_reason: Mapped[str | None] = mapped_column(String(64))
    realised_gross_pnl_usd: Mapped[Decimal | None] = mapped_column(Numeric(24, 4))
    realised_net_pnl_usd: Mapped[Decimal | None] = mapped_column(Numeric(24, 4))

    __table_args__ = (
        UniqueConstraint(
            "entry_transaction_signature", name="uq_real_position_entry_signature"
        ),
        UniqueConstraint("exit_transaction_signature", name="uq_real_position_exit_signature"),
    )


class RealWalletLiveIntent(Base, UUIDPrimaryKeyMixin):
    """Future-real execution intent; separate from dry-run evidence and paper."""

    __tablename__ = "real_wallet_live_intents"

    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False, unique=True)
    mint_address: Mapped[str] = mapped_column(String(44), nullable=False)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False, default="created")
    strategy_id: Mapped[str] = mapped_column(String(64), nullable=False)
    strategy_version: Mapped[str] = mapped_column(String(32), nullable=False)
    wallet_public_key: Mapped[str] = mapped_column(String(44), nullable=False)
    position_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("real_wallet_positions.id", use_alter=True),
    )
    safety_evaluation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("real_wallet_safety_evaluations.id")
    )
    requested_usd: Mapped[Decimal | None] = mapped_column(Numeric(24, 4))
    requested_token_quantity: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    jupiter_request_id: Mapped[str | None] = mapped_column(String(128), unique=True)
    order_evidence: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    order_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    transaction_signature: Mapped[str | None] = mapped_column(String(128), unique=True)
    failure_reason: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("ix_real_wallet_live_intent_state", "state"),
        Index("ix_real_wallet_live_intent_mint", "mint_address"),
    )


class RealWalletExecutionEvent(Base, UUIDPrimaryKeyMixin):
    """Append-only state-transition evidence for a live intent."""

    __tablename__ = "real_wallet_execution_events"

    intent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("real_wallet_live_intents.id"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (Index("ix_real_wallet_execution_event_intent", "intent_id"),)


class RealWalletKillSwitch(Base, UUIDPrimaryKeyMixin):
    """Persisted fail-closed kill switches; never a browser control surface."""

    __tablename__ = "real_wallet_kill_switches"

    kind: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    active: Mapped[bool] = mapped_column(nullable=False, default=False, server_default="false")
    reason: Mapped[str | None] = mapped_column(String(256))
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
