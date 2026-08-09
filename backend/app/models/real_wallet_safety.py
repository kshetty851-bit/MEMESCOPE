"""Append-only, read-only safety decisions for a future real-wallet executor.

This table records a decision, never an order.  It deliberately has no wallet
address, signer, transaction, or signature field: the safety layer must remain
usable and testable without possessing credentials or being able to trade.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import DateTime, Index, Numeric, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPrimaryKeyMixin


class RealWalletSafetyEvaluation(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "real_wallet_safety_evaluations"

    mint_address: Mapped[str] = mapped_column(String(44), index=True, nullable=False)
    decision: Mapped[str] = mapped_column(String(8), index=True, nullable=False)
    evaluated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
    trade_size_usd: Mapped[Decimal] = mapped_column(Numeric(24, 4), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    reason_codes: Mapped[list[str]] = mapped_column(JSONB, nullable=False)

    market_snapshot_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    market_age_seconds: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    market_price_usd: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    liquidity_usd: Mapped[Decimal | None] = mapped_column(Numeric(24, 4))
    buy_price_impact_pct: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    sell_price_impact_pct: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    round_trip_loss_usd: Mapped[Decimal | None] = mapped_column(Numeric(24, 4))
    round_trip_loss_pct: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    position_liquidity_ratio: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    token_program: Mapped[str | None] = mapped_column(String(44))
    mint_authority_active: Mapped[bool | None] = mapped_column()
    freeze_authority_active: Mapped[bool | None] = mapped_column()
    token_extensions: Mapped[list[int] | None] = mapped_column(JSONB)

    # Full immutable supporting facts. JSON contains primitive-only quote/RPC
    # data, so review never has to trust a browser or fetch a later quote.
    provenance: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    buy_quote: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    sell_quote: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    token_configuration: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    __table_args__ = (
        Index(
            "ix_real_wallet_safety_mint_evaluated_desc",
            "mint_address",
            evaluated_at.desc(),
        ),
    )
