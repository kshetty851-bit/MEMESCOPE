"""The lab's own four tables. Prefix `ct_`.

On the PLATFORM's `Base`, for the reason the Rafiq lab documents: a separate
metadata makes `alembic revision --autogenerate` emit `drop_table` for tables
it can see in the database and not in the model tree. Sharing the metadata
is what makes the schema tool agree with the schema.

`server_default` is declared wherever the migration sets one, so the two do
not show up as drift.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    false,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

#: Binance quotes these contracts to at most 8 decimals.
_PRICE = Numeric(24, 8)
_VOLUME = Numeric(30, 8)


class CtUniverseMember(Base):
    """One coin in the universe. Never deleted: leaving the top-20 sets
    `removed_at`, and re-entering clears it, so the record shows every
    membership change without a second table."""

    __tablename__ = "ct_universe"
    __table_args__ = (
        UniqueConstraint("coingecko_id", name="uq_ct_universe_coingecko_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    coingecko_id: Mapped[str] = mapped_column(String(64), nullable=False)
    ticker: Mapped[str] = mapped_column(String(16), nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    binance_symbol: Mapped[str] = mapped_column(String(24), nullable=False)
    #: Position within the universe, 1-based, contiguous.
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    #: CoinGecko's own rank, which includes the coins this lab excludes.
    market_cap_rank: Mapped[int | None] = mapped_column(Integer)
    market_cap_usd: Mapped[Decimal | None] = mapped_column(Numeric(24, 2))
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    refreshed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CtCandle(Base):
    """One closed OHLCV candle. The unique constraint is what makes the poll
    idempotent: the same candle upserted twice is one row."""

    __tablename__ = "ct_candles"
    __table_args__ = (
        UniqueConstraint("symbol", "timeframe", "open_time",
                         name="uq_ct_candles_symbol_timeframe_open_time"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    symbol: Mapped[str] = mapped_column(String(24), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(4), nullable=False)
    open_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    open: Mapped[Decimal] = mapped_column(_PRICE, nullable=False)
    high: Mapped[Decimal] = mapped_column(_PRICE, nullable=False)
    low: Mapped[Decimal] = mapped_column(_PRICE, nullable=False)
    close: Mapped[Decimal] = mapped_column(_PRICE, nullable=False)
    volume: Mapped[Decimal] = mapped_column(_VOLUME, nullable=False)
    close_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CtFunding(Base):
    """One row per symbol per funding interval, keyed on the interval's
    settlement time. Binance's `lastFundingRate` only moves at settlement, so
    a row per refresh would be the same number 480 times; a row per interval
    is the history a later phase's short-side cost model actually needs."""

    __tablename__ = "ct_funding"
    __table_args__ = (
        UniqueConstraint("symbol", "next_funding_time",
                         name="uq_ct_funding_symbol_next_funding_time"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    symbol: Mapped[str] = mapped_column(String(24), nullable=False)
    funding_rate: Mapped[Decimal] = mapped_column(Numeric(12, 8), nullable=False)
    mark_price: Mapped[Decimal | None] = mapped_column(_PRICE)
    next_funding_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CtRun(Base):
    """What one tick did, so `data_health()` can report errors that happened
    in a worker process the API never sees. Pruned to `RUN_HISTORY` rows."""

    __tablename__ = "ct_runs"
    __table_args__ = (Index("ix_ct_runs_started_at", "started_at"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    universe_refreshed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    candles_upserted: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    funding_upserted: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    requests: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    #: Coins in the top-30 with no Binance perp, as `{coingecko_id, ticker, tried}`.
    skipped: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    errors: Mapped[list[str] | None] = mapped_column(JSONB)
