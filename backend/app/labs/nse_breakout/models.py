"""The lab's own tables. Prefix `bt_`.

On the PLATFORM's `Base`, for the reason every other lab here documents: a
separate metadata makes `alembic revision --autogenerate` emit `drop_table`
for tables it can see in the database and not in the model tree.

`server_default` is declared wherever the migration sets one, so the two do
not show up as drift. Nullable JSONB uses `none_as_null` so a Python `None`
becomes SQL NULL rather than the JSON scalar `null` — the Solana lab learned
that one the hard way, on a `jsonb_array_length` that failed on every clean
run.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    false,
    func,
    text,
    true,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

_JSONB = JSONB(none_as_null=True)
#: Indian equities trade from a few rupees to ~1,50,000 (MRF). Four decimals
#: is more than the exchange quotes.
_PRICE = Numeric(18, 4)
#: Turnover in rupees: a large-cap day is ~1e10, so this has room.
_INR = Numeric(24, 2)
_SYMBOL = String(32)


class BtUniverseMember(Base):
    """One NSE equity under watch, keyed on its trading symbol.

    Never deleted. A symbol that stops qualifying has `active` cleared with a
    reason; a renamed or merged symbol simply stops appearing in the bhavcopy
    and goes inactive, while the new symbol arrives as its own row — which is
    the pre-decided rule and also the only thing the data supports, since the
    exchange file carries no rename linkage.
    """

    __tablename__ = "bt_universe"
    __table_args__ = (
        UniqueConstraint("symbol", name="uq_bt_universe_symbol"),
        Index("ix_bt_universe_active_turnover", "active", "turnover_20d"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    symbol: Mapped[str] = mapped_column(_SYMBOL, nullable=False)
    name: Mapped[str | None] = mapped_column(String(128))
    isin: Mapped[str | None] = mapped_column(String(16))
    #: `EQ` or `BE`. Kept so a later phase can treat trade-for-trade names
    #: differently without re-deriving it.
    series: Mapped[str] = mapped_column(String(4), nullable=False)
    last_close: Mapped[Decimal | None] = mapped_column(_PRICE)
    #: 20-day MEDIAN turnover, the liquidity gate. Median so one block deal
    #: cannot qualify an otherwise untradeable name.
    turnover_20d: Mapped[Decimal | None] = mapped_column(_INR)
    bars: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    first_seen: Mapped[date] = mapped_column(Date, nullable=False)
    last_seen: Mapped[date] = mapped_column(Date, nullable=False)
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=true()
    )
    #: `price` | `turnover` | `series` | `absent` — why it is not active.
    #: `pending` is the identity pass's placeholder, replaced by
    #: `rebuild_universe` inside the same transaction.
    inactive_reason: Mapped[str | None] = mapped_column(String(16))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class BtCandle(Base):
    """One daily bar. The unique constraint is what makes ingest idempotent:
    the same trading day re-ingested is the same rows."""

    __tablename__ = "bt_candles"
    __table_args__ = (
        UniqueConstraint("symbol", "date", name="uq_bt_candles_symbol_date"),
        Index("ix_bt_candles_date", "date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    symbol: Mapped[str] = mapped_column(_SYMBOL, nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    open: Mapped[Decimal] = mapped_column(_PRICE, nullable=False)
    high: Mapped[Decimal] = mapped_column(_PRICE, nullable=False)
    low: Mapped[Decimal] = mapped_column(_PRICE, nullable=False)
    close: Mapped[Decimal] = mapped_column(_PRICE, nullable=False)
    volume: Mapped[int] = mapped_column(Numeric(20, 0), nullable=False)
    turnover: Mapped[Decimal | None] = mapped_column(_INR)
    #: FALSE for every bhavcopy bar — the exchange file is unadjusted and the
    #: only corroboration source for corporate actions (yfinance) answered 429
    #: to every request from this host. Kept as a column so a later phase with
    #: an adjustment source does not need a migration.
    adjusted: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    #: A >`SPLIT_GAP_PCT` overnight gap. Flagged, never corrected: silently
    #: "fixing" a price with no corroboration invents data, and a split that
    #: is merely marked stays visible in the health route.
    suspect_gap: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )


class BtIndexClose(Base):
    """Nifty 50's daily close, from the exchange's own index file — what the
    relative-return columns are measured against."""

    __tablename__ = "bt_index_closes"
    __table_args__ = (
        UniqueConstraint("index_name", "date", name="uq_bt_index_closes_name_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    index_name: Mapped[str] = mapped_column(String(32), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    close: Mapped[Decimal] = mapped_column(_PRICE, nullable=False)


class BtIngestDay(Base):
    """One trading day's ingest, so a backfill is resumable and a missing file
    is a recorded fact rather than a silent hole.

    A day is only `ok` once its bars are committed. The backfill resumes from
    the days this table does not have, which is what makes it safe to kill.
    """

    __tablename__ = "bt_ingest_days"
    __table_args__ = (UniqueConstraint("date", name="uq_bt_ingest_days_date"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    date: Mapped[date] = mapped_column(Date, nullable=False)
    #: `ok` | `missing` (holiday or not published) | `failed`
    status: Mapped[str] = mapped_column(String(8), nullable=False)
    rows: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    symbols: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    failures: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    last_error: Mapped[str | None] = mapped_column(Text)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class BtRun(Base):
    """What one pass did, so the health route can report failures that
    happened in a worker the API never sees."""

    __tablename__ = "bt_runs"
    __table_args__ = (Index("ix_bt_runs_started_at", "started_at"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    #: `ingest` | `backfill` | `universe` | `levels` | `outcomes` | `replay`
    phase: Mapped[str] = mapped_column(String(16), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    days: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    rows: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    symbols: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    detail: Mapped[dict[str, Any] | None] = mapped_column(_JSONB)
    errors: Mapped[list[str] | None] = mapped_column(_JSONB)
