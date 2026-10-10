"""Forex Strategy Lab tables. Research and paper only.

Every table is prefixed `forex_`: an older `fx_candles` table existed and was
dropped in migration 0103, and a shared prefix would make the two easy to mix
up in a query or a migration.

* `forex_candles` is the market record. PK (symbol, timeframe, open_time) makes
  an import idempotent, and the repository inserts with `ON CONFLICT DO NOTHING`
  so a stored candle is never overwritten - a backtest that read yesterday's
  data must read the same data tomorrow.
* `forex_fetch_days` is the download cache. A day fetched OK (or answered empty
  by the feed) is never fetched again; a failed day is retried.
* `forex_strategy_versions` are immutable: a saved config is never edited, a new
  version is written instead, so a run can always name the exact config it used.
* `forex_runs` keep the request, the config actually run, the data fingerprint
  and the result. Result JSON stores stable CODES only; prose is rendered when a
  run is read (CLAUDE.md: rewording is a deploy, not a migration).

`created_by` is a bare UUID, not a foreign key: in local development the
auth bypass signs requests as a synthetic principal that is never persisted, and
a constraint would refuse every write it makes.

Prices are NUMERIC(12,6), never float, at rest.
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
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    desc,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin

_PRICE = Numeric(12, 6)
_VOLUME = Numeric(20, 4)


class ForexImportBatch(TimestampMixin, Base):
    __tablename__ = "forex_import_batches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(8), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    filename: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    rows_total: Mapped[int] = mapped_column(Integer, nullable=False)
    rows_accepted: Mapped[int] = mapped_column(Integer, nullable=False)
    rows_inserted: Mapped[int] = mapped_column(Integer, nullable=False)
    rows_existing: Mapped[int] = mapped_column(Integer, nullable=False)
    error_count: Mapped[int] = mapped_column(Integer, nullable=False)
    #: At most 50 `{line, message}` entries; `error_count` is the true total.
    errors: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    detected_format: Mapped[str] = mapped_column(String(16), nullable=False)
    start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    quality: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    #: Stable note codes, e.g. `histdata_est_fixed_utc_minus_5`.
    notes: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(PgUUID(as_uuid=True))


class ForexCandle(TimestampMixin, Base):
    __tablename__ = "forex_candles"

    symbol: Mapped[str] = mapped_column(String(16), primary_key=True)
    timeframe: Mapped[str] = mapped_column(String(8), primary_key=True)
    #: The candle's start, UTC.
    open_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    open: Mapped[Decimal] = mapped_column(_PRICE, nullable=False)
    high: Mapped[Decimal] = mapped_column(_PRICE, nullable=False)
    low: Mapped[Decimal] = mapped_column(_PRICE, nullable=False)
    close: Mapped[Decimal] = mapped_column(_PRICE, nullable=False)
    #: Tick volume where the source has it, 0 where it does not - never estimated.
    volume: Mapped[Decimal] = mapped_column(_VOLUME, nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    import_batch_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("forex_import_batches.id", ondelete="SET NULL")
    )


class ForexFetchDay(TimestampMixin, Base):
    __tablename__ = "forex_fetch_days"

    provider: Mapped[str] = mapped_column(String(32), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(16), primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    ok: Mapped[bool] = mapped_column(Boolean, nullable=False)
    #: The feed answered, and had no candles for the day (weekend, holiday).
    empty: Mapped[bool] = mapped_column(Boolean, nullable=False)
    candles: Mapped[int] = mapped_column(Integer, nullable=False)
    error: Mapped[str | None] = mapped_column(String(256))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ForexStrategyVersion(TimestampMixin, Base):
    __tablename__ = "forex_strategy_versions"
    __table_args__ = (
        UniqueConstraint("name", "version", name="uq_forex_strategy_versions_name_version"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    strategy: Mapped[str] = mapped_column(String(32), nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(PgUUID(as_uuid=True))


class ForexRun(TimestampMixin, Base):
    __tablename__ = "forex_runs"
    __table_args__ = (
        Index("ix_forex_runs_kind_created", "kind", desc("created_at"), desc("id")),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    message: Mapped[str | None] = mapped_column(String(256))
    name: Mapped[str | None] = mapped_column(String(120))
    strategy_version_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("forex_strategy_versions.id", ondelete="SET NULL")
    )
    #: The config actually run, verbatim (null for fetch / compare).
    config: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    #: The request as received: window, options, extra configs.
    request: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    data_fingerprint: Mapped[str | None] = mapped_column(String(64))
    config_version: Mapped[int] = mapped_column(Integer, nullable=False)
    app_version: Mapped[str] = mapped_column(String(32), nullable=False)
    summary: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(PgUUID(as_uuid=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
