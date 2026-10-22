"""Long-watch Lab tables (2026-10-22). Paper only: no wallet reads or writes."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import BigInteger, DateTime, Index, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

MONEY = Numeric(24, 4)
PRICE = Numeric(38, 18)


class LongwatchReading(Base):
    """One coin's DexScreener reading, every 10 minutes for 48 hours after it graduates."""

    __tablename__ = "longwatch_readings"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    mint: Mapped[str] = mapped_column(String(64), nullable=False)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    pair: Mapped[str | None] = mapped_column(String(64))
    price_usd: Mapped[Decimal | None] = mapped_column(PRICE)
    liquidity_usd: Mapped[Decimal | None] = mapped_column(MONEY)
    fdv: Mapped[Decimal | None] = mapped_column(MONEY)
    volume_h1: Mapped[Decimal | None] = mapped_column(MONEY)
    buys_h1: Mapped[int | None] = mapped_column(Integer)
    sells_h1: Mapped[int | None] = mapped_column(Integer)

    __table_args__ = (Index("ix_longwatch_readings_mint_ts", "mint", "ts"),
                      Index("ix_longwatch_readings_ts", "ts"))


class LongwatchBook(Base):
    __tablename__ = "longwatch_books"

    book: Mapped[str] = mapped_column(String(16), primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    cash_usd: Mapped[Decimal] = mapped_column(MONEY, nullable=False)


class LongwatchPosition(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "longwatch_positions"

    book: Mapped[str] = mapped_column(String(16), nullable=False)
    mint: Mapped[str] = mapped_column(String(64), nullable=False)
    symbol: Mapped[str | None] = mapped_column(String(64))
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    entry_price: Mapped[Decimal] = mapped_column(PRICE, nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(48, 18), nullable=False)
    spent_usd: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    peak_price: Mapped[Decimal] = mapped_column(PRICE, nullable=False)
    last_price: Mapped[Decimal | None] = mapped_column(PRICE)
    last_liquidity_usd: Mapped[Decimal | None] = mapped_column(MONEY)
    status: Mapped[str] = mapped_column(String(8), nullable=False, default="open")
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    exit_price: Mapped[Decimal | None] = mapped_column(PRICE)
    proceeds_usd: Mapped[Decimal | None] = mapped_column(MONEY)
    reason: Mapped[str | None] = mapped_column(String(32))
    trigger: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    __table_args__ = (Index("ix_longwatch_positions_book_status", "book", "status"),
                      Index("ix_longwatch_positions_book_mint", "book", "mint", unique=True))
