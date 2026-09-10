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


class CtTrendState(Base):
    """Per-coin trend state on one timeframe, ONE ROW PER CLOSED BAR.

    Keyed on the bar it was computed from, so the every-minute recompute
    between closes rewrites the same row instead of adding one: 24 rows a
    day on 1h, 6 on 4h, per symbol. `computed_at` says when it was last
    written; `bar_close_time` says what it describes.
    """

    __tablename__ = "ct_trend_state"
    __table_args__ = (
        UniqueConstraint("symbol", "timeframe", "bar_close_time",
                         name="uq_ct_trend_state_symbol_timeframe_bar_close_time"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    symbol: Mapped[str] = mapped_column(String(24), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(4), nullable=False)
    bar_close_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    #: `UP` | `DOWN` | `FLAT`
    direction: Mapped[str] = mapped_column(String(5), nullable=False)
    strength: Mapped[int] = mapped_column(Integer, nullable=False)
    #: EMA_slow's change over SLOPE_BARS bars, percent, signed.
    slope: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False)
    #: ATR as a percentage of the close.
    atr_pct: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False)
    bars_in_state: Mapped[int] = mapped_column(Integer, nullable=False)
    ema_fast: Mapped[Decimal] = mapped_column(_PRICE, nullable=False)
    ema_slow: Mapped[Decimal] = mapped_column(_PRICE, nullable=False)
    #: Null until EMA_TREND bars exist for the contract.
    ema_trend: Mapped[Decimal | None] = mapped_column(_PRICE)
    adx: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)
    #: `HH_HL` | `LH_LL` | `MIXED`
    structure: Mapped[str] = mapped_column(String(8), nullable=False)
    #: True when the averages and ADX read a trend that the most recent swing
    #: refused — the state is FLAT because of structure, not despite it.
    structure_veto: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    close: Mapped[Decimal] = mapped_column(_PRICE, nullable=False)


class CtRegime(Base):
    """Market-wide regime, one row per bar close across the universe."""

    __tablename__ = "ct_regime"
    __table_args__ = (
        UniqueConstraint("bar_close_time", name="uq_ct_regime_bar_close_time"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    bar_close_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    #: Coins with a 4h state — the breadth denominator.
    coins: Mapped[int] = mapped_column(Integer, nullable=False)
    breadth_up: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False)
    breadth_down: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False)
    btc_direction: Mapped[str | None] = mapped_column(String(5))
    eth_direction: Mapped[str | None] = mapped_column(String(5))
    #: `RISK_ON` | `RISK_OFF` | `CHOP`
    regime: Mapped[str] = mapped_column(String(8), nullable=False)


class CtReplayRun(Base):
    """One replay: its window, its parameters and its summary, so a result
    survives the shell it was printed in. Trade lists go to the lab's
    output folder, not here."""

    __tablename__ = "ct_replay_runs"
    __table_args__ = (Index("ix_ct_replay_runs_created_at", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    label: Mapped[str | None] = mapped_column(String(64))
    #: The overrides applied on top of `config.py`; empty for a default run.
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    summary: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    trades: Mapped[int] = mapped_column(Integer, nullable=False)


class CtUniverseSnapshot(Base):
    """A universe frozen at a past date, for out-of-sample replays: the
    top-20 by market cap AS OF `as_of`, among coins with a Binance perp
    today. `symbols` is a list of `{symbol, coingecko_id, ticker, name,
    market_cap_usd, rank}`."""

    __tablename__ = "ct_universe_snapshots"
    __table_args__ = (UniqueConstraint("name", name="uq_ct_universe_snapshots_name"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    symbols: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
