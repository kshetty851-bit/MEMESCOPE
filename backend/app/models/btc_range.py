"""BTC Range Lab candles. One row per (symbol, timeframe, open_time).

A closed candle is immutable: the live paper book is a replay over stored
closed candles, so a candle that could change after it closed would let the
record rewrite itself. The repository enforces that with
`ON CONFLICT ... DO UPDATE ... WHERE is_closed IS false`; the table only
carries the columns that make it expressible.

`is_closed` is stored, not derived from `close_time < now()`, because the
decision was made once at ingest time with an explicit `now`, and a row must
not flip state just because it is read later.

Money-like figures are NUMERIC(24,8) - Binance quotes eight decimals - never
float.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin

_PRICE = Numeric(24, 8)


class BtcCandle(TimestampMixin, Base):
    __tablename__ = "btc_candles"

    symbol: Mapped[str] = mapped_column(String(16), primary_key=True)
    timeframe: Mapped[str] = mapped_column(String(8), primary_key=True)
    #: The candle's start, UTC.
    open_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    open: Mapped[Decimal] = mapped_column(_PRICE, nullable=False)
    high: Mapped[Decimal] = mapped_column(_PRICE, nullable=False)
    low: Mapped[Decimal] = mapped_column(_PRICE, nullable=False)
    close: Mapped[Decimal] = mapped_column(_PRICE, nullable=False)
    volume: Mapped[Decimal] = mapped_column(_PRICE, nullable=False)
    is_closed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    #: The candle's last millisecond, UTC.
    close_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
