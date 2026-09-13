"""The lab's own three tables. Prefix `fx_`.

On the PLATFORM's `Base`, for the reason the Rafiq and crypto_trend labs
document: a separate metadata makes `alembic revision --autogenerate` emit
`drop_table` for tables it can see in the database and not in the model tree.
Sharing the metadata is what makes the schema tool agree with the schema.

`server_default` is declared wherever the migration sets one, so the two do not
show up as drift.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Index,
    Integer,
    Numeric,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

#: Dukascopy quotes EUR/USD to 5 decimals. 12/6 leaves room for a pair that
#: is not EUR/USD without ever losing a point of an FX quote.
_PRICE = Numeric(12, 6)


class FxCandle(Base):
    """One minute of bid/ask OHLC, aggregated from ticks.

    The primary key is (symbol, minute), so re-ingesting an hour overwrites
    rather than duplicates — which is the whole of what makes the loader
    idempotent.

    Bid and ask are kept apart rather than stored as mid + spread. The
    integrity check asserts `bid <= ask` on every row, and that assertion is
    only worth making on the numbers that were actually observed.
    """

    __tablename__ = "fx_candles"
    __table_args__ = (
        Index("ix_fx_candles_minute", "minute"),
    )

    symbol: Mapped[str] = mapped_column(String(16), primary_key=True)
    minute: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True
    )
    bid_open: Mapped[float] = mapped_column(_PRICE, nullable=False)
    bid_high: Mapped[float] = mapped_column(_PRICE, nullable=False)
    bid_low: Mapped[float] = mapped_column(_PRICE, nullable=False)
    bid_close: Mapped[float] = mapped_column(_PRICE, nullable=False)
    ask_open: Mapped[float] = mapped_column(_PRICE, nullable=False)
    ask_high: Mapped[float] = mapped_column(_PRICE, nullable=False)
    ask_low: Mapped[float] = mapped_column(_PRICE, nullable=False)
    ask_close: Mapped[float] = mapped_column(_PRICE, nullable=False)
    #: Ticks observed in the minute. Zero is impossible — a minute with no tick
    #: has no row at all, which is what makes the gap check meaningful.
    ticks: Mapped[int] = mapped_column(Integer, nullable=False)


class FxIngestHour(Base):
    """One row per Dukascopy hour-file, written after its candles commit.

    This is the resume log. `ok=false` with an `error` is a file that failed
    every retry; the next run picks exactly those up again, so a pass that
    loses 17% of its requests to the CDN's 503s costs a second pass, not a
    restart. `empty=true` is a file the feed genuinely serves as zero bytes —
    a market holiday or a dead weekend hour — and is never retried.
    """

    __tablename__ = "fx_ingest_hours"
    __table_args__ = (
        Index("ix_fx_ingest_hours_ok", "symbol", "ok"),
    )

    symbol: Mapped[str] = mapped_column(String(16), primary_key=True)
    hour_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True
    )
    ok: Mapped[bool] = mapped_column(Boolean, nullable=False)
    empty: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    tick_count: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=text("0")
    )
    candle_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    error: Mapped[str | None] = mapped_column(String(256), nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class FxSweepRun(Base):
    """One parameter sweep, whole, with its verdict. Immutable once written.

    The dashboard reads this and nothing else. A backtest result is a thing
    computed once from a frozen dataset by an operator command, not something a
    page recomputes on load — a browser that could re-run the sweep with a
    different gate would be a second, unpublished experiment competing with the
    pre-registered one.

    The whole sweep lives in one JSONB document rather than a row per
    configuration, because it is only ever read as one document: twenty-seven
    configurations, their per-year P&L and the baselines are a single answer to
    a single question, and splitting them would be three joins to rebuild one
    page.
    """

    __tablename__ = "fx_sweep_runs"
    __table_args__ = (Index("ix_fx_sweep_runs_created", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    symbol: Mapped[str] = mapped_column(String(16), nullable=False)
    #: The window the replay actually covered, which is not necessarily the
    #: window the brief asked for — the page says so when they differ.
    first_minute: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_minute: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    candles: Mapped[int] = mapped_column(BigInteger, nullable=False)
    git_sha: Mapped[str | None] = mapped_column(String(40))

    #: The name of the best configuration by profit factor, and whether it
    #: cleared the gate stated before the sweep ran.
    best_config: Mapped[str] = mapped_column(String(32), nullable=False)
    gate_passed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    #: The sweep document: every configuration, the baselines, the gate's five
    #: checks, and the integrity check that gated it.
    result: Mapped[dict] = mapped_column(JSONB, nullable=False)
