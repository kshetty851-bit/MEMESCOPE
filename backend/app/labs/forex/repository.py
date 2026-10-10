"""Forex lab persistence. Flushes, never commits - the caller owns the transaction.

## A stored candle is never overwritten

A backtest that read yesterday's candles must read the same candles tomorrow, or
a result could change under a run that recorded its data fingerprint. So the
insert is `ON CONFLICT (symbol, timeframe, open_time) DO NOTHING`: the database,
not a check-then-insert, is the guarantee, and re-importing a file reports the
rows that already existed instead of replacing them.

Prices go in as `Decimal` built from the float's shortest repr, so a quote
`1.08521` is stored as `1.08521`, never as a float expansion.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, desc, func, select, update
from sqlalchemy import true as sa_true
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer

from app.labs.forex.types import Candle
from app.models.forex import (
    ForexCandle,
    ForexFetchDay,
    ForexImportBatch,
    ForexRun,
    ForexStrategyVersion,
)

#: Rows built into dicts at a time; bounds memory on a multi-million-row file.
INSERT_CHUNK = 20_000
STALE_AFTER = timedelta(minutes=30)
LIST_IMPORTS = 50

_CANDLE_COLUMNS = (
    ForexCandle.open_time,
    ForexCandle.open,
    ForexCandle.high,
    ForexCandle.low,
    ForexCandle.close,
    ForexCandle.volume,
)


def _dec(x: float) -> Decimal:
    return Decimal(repr(x))


# --------------------------------------------------------------------------
# Candles
# --------------------------------------------------------------------------


async def insert_candles(
    session: AsyncSession,
    candles: Sequence[Candle],
    *,
    symbol: str,
    timeframe: str,
    source: str,
    batch_id: int | None = None,
) -> int:
    """Insert candles that are not stored yet. Returns the rows INSERTED.

    Existing rows are left exactly as they are and are not counted, so
    `len(candles) - inserted` is the number that already existed.
    """
    # One statement, many parameter sets: SQLAlchemy compiles it once and batches
    # the rows itself. A multi-row VALUES list recompiled a 20,000-parameter
    # statement per chunk and was five times slower on the same rows.
    stmt = (
        pg_insert(ForexCandle)
        .on_conflict_do_nothing(index_elements=["symbol", "timeframe", "open_time"])
        .returning(ForexCandle.open_time)
    )
    inserted = 0
    for i in range(0, len(candles), INSERT_CHUNK):
        values = [
            {
                "symbol": symbol,
                "timeframe": timeframe,
                "open_time": c.open_time,
                "open": _dec(c.open),
                "high": _dec(c.high),
                "low": _dec(c.low),
                "close": _dec(c.close),
                "volume": _dec(c.volume),
                "source": source,
                "import_batch_id": batch_id,
            }
            for c in candles[i : i + INSERT_CHUNK]
        ]
        inserted += len((await session.execute(stmt, values)).all())
    await session.flush()
    return inserted


def _candle(row: Any) -> Candle:
    return Candle(
        open_time=row[0],
        open=float(row[1]),
        high=float(row[2]),
        low=float(row[3]),
        close=float(row[4]),
        volume=float(row[5]),
    )


async def load_candles(
    session: AsyncSession, symbol: str, timeframe: str, start: datetime, end: datetime
) -> list[Candle]:
    """Candles with start <= open_time < end, ASCENDING.

    The ORDER BY is total (open_time is unique within symbol and timeframe), so
    nothing here can starve or repeat.
    """
    stmt = (
        select(*_CANDLE_COLUMNS)
        .where(
            ForexCandle.symbol == symbol,
            ForexCandle.timeframe == timeframe,
            ForexCandle.open_time >= start,
            ForexCandle.open_time < end,
        )
        .order_by(ForexCandle.open_time.asc())
    )
    return [_candle(r) for r in (await session.execute(stmt)).all()]


async def count_candles(
    session: AsyncSession, symbol: str, timeframe: str, start: datetime, end: datetime
) -> int:
    stmt = select(func.count()).where(
        ForexCandle.symbol == symbol,
        ForexCandle.timeframe == timeframe,
        ForexCandle.open_time >= start,
        ForexCandle.open_time < end,
    )
    return int((await session.execute(stmt)).scalar_one())


async def sources_in_range(
    session: AsyncSession, symbol: str, timeframe: str, start: datetime, end: datetime
) -> list[str]:
    stmt = (
        select(ForexCandle.source)
        .where(
            ForexCandle.symbol == symbol,
            ForexCandle.timeframe == timeframe,
            ForexCandle.open_time >= start,
            ForexCandle.open_time < end,
        )
        .distinct()
        .order_by(ForexCandle.source)
    )
    return [r[0] for r in (await session.execute(stmt)).all()]


async def bounds(
    session: AsyncSession, symbol: str, timeframe: str
) -> tuple[datetime, datetime] | None:
    """First and last stored open_time, or None. Two index probes, no scan."""
    base = (ForexCandle.symbol == symbol, ForexCandle.timeframe == timeframe)
    first = (
        await session.execute(
            select(ForexCandle.open_time)
            .where(*base)
            .order_by(ForexCandle.open_time.asc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if first is None:
        return None
    last = (
        await session.execute(
            select(ForexCandle.open_time)
            .where(*base)
            .order_by(ForexCandle.open_time.desc())
            .limit(1)
        )
    ).scalar_one()
    return first, last


async def datasets(session: AsyncSession) -> list[dict[str, Any]]:
    """One row per (symbol, timeframe): bar count, first, last, sources."""
    stmt = (
        select(
            ForexCandle.symbol,
            ForexCandle.timeframe,
            func.count().label("bars"),
            func.min(ForexCandle.open_time).label("start"),
            func.max(ForexCandle.open_time).label("end"),
            func.array_agg(func.distinct(ForexCandle.source)).label("sources"),
        )
        .group_by(ForexCandle.symbol, ForexCandle.timeframe)
        .order_by(ForexCandle.symbol, ForexCandle.timeframe)
    )
    return [
        {
            "symbol": r.symbol,
            "timeframe": r.timeframe,
            "bars": int(r.bars),
            "start": r.start,
            "end": r.end,
            "sources": sorted(r.sources),
        }
        for r in (await session.execute(stmt)).all()
    ]


# --------------------------------------------------------------------------
# Import batches
# --------------------------------------------------------------------------


async def add_import_batch(session: AsyncSession, **fields: Any) -> ForexImportBatch:
    row = ForexImportBatch(**fields)
    session.add(row)
    await session.flush()
    return row


async def latest_import_batches(
    session: AsyncSession, limit: int = LIST_IMPORTS
) -> list[ForexImportBatch]:
    stmt = (
        select(ForexImportBatch)
        .order_by(desc(ForexImportBatch.created_at), desc(ForexImportBatch.id))
        .limit(limit)
    )
    return list((await session.execute(stmt)).scalars().all())


# --------------------------------------------------------------------------
# Download cache
# --------------------------------------------------------------------------


async def fetch_days(
    session: AsyncSession, provider: str, symbol: str, start: date, end: date
) -> dict[date, ForexFetchDay]:
    stmt = select(ForexFetchDay).where(
        ForexFetchDay.provider == provider,
        ForexFetchDay.symbol == symbol,
        ForexFetchDay.day >= start,
        ForexFetchDay.day <= end,
    )
    return {r.day: r for r in (await session.execute(stmt)).scalars().all()}


async def record_fetch_day(
    session: AsyncSession,
    *,
    provider: str,
    symbol: str,
    day: date,
    ok: bool,
    empty: bool,
    candles: int,
    error: str | None,
    fetched_at: datetime,
) -> None:
    """Write the outcome for a day. A failed day is overwritten by its retry."""
    insert_stmt = pg_insert(ForexFetchDay).values(
        provider=provider,
        symbol=symbol,
        day=day,
        ok=ok,
        empty=empty,
        candles=candles,
        error=None if error is None else error[:256],
        fetched_at=fetched_at,
    )
    stmt = insert_stmt.on_conflict_do_update(
        index_elements=["provider", "symbol", "day"],
        set_={
            "ok": insert_stmt.excluded.ok,
            "empty": insert_stmt.excluded.empty,
            "candles": insert_stmt.excluded.candles,
            "error": insert_stmt.excluded.error,
            "fetched_at": insert_stmt.excluded.fetched_at,
            "updated_at": func.now(),
        },
    )
    await session.execute(stmt)
    await session.flush()


async def fetch_summary(
    session: AsyncSession, provider: str, symbol: str | None = None
) -> dict[str, Any] | None:
    stmt = select(
        func.count().filter(and_(ForexFetchDay.ok.is_(True), ForexFetchDay.empty.is_(False))),
        func.count().filter(and_(ForexFetchDay.ok.is_(True), ForexFetchDay.empty.is_(True))),
        func.count().filter(ForexFetchDay.ok.is_(False)),
        func.min(ForexFetchDay.day),
        func.max(ForexFetchDay.day),
    ).where(ForexFetchDay.provider == provider)
    if symbol is not None:
        stmt = stmt.where(ForexFetchDay.symbol == symbol)
    ok, empty, failed, first, last = (await session.execute(stmt)).one()
    if not (ok or empty or failed):
        return None
    return {
        "provider": provider,
        "days_ok": int(ok),
        "days_empty": int(empty),
        "days_failed": int(failed),
        "first_day": first,
        "last_day": last,
    }


# --------------------------------------------------------------------------
# Strategy versions (immutable)
# --------------------------------------------------------------------------


async def add_version(
    session: AsyncSession,
    *,
    name: str,
    strategy: str,
    config: dict[str, Any],
    notes: str | None,
    created_by: Any,
) -> ForexStrategyVersion:
    """Write the next version of `name`. Versions are never edited.

    The number is computed inside the INSERT, so two writers cannot both read
    the same maximum first; if they still collide the unique index refuses the
    loser, which retries once under a savepoint.
    """
    for attempt in range(3):
        next_no = (
            select(func.coalesce(func.max(ForexStrategyVersion.version), 0) + 1)
            .where(ForexStrategyVersion.name == name)
            .scalar_subquery()
        )
        stmt = (
            pg_insert(ForexStrategyVersion)
            .values(
                name=name,
                version=next_no,
                strategy=strategy,
                config=config,
                notes=notes,
                created_by=created_by,
            )
            .returning(ForexStrategyVersion.id)
        )
        try:
            async with session.begin_nested():
                new_id = (await session.execute(stmt)).scalar_one()
        except IntegrityError:
            if attempt == 2:
                raise
            continue
        row = await session.get(ForexStrategyVersion, new_id, populate_existing=True)
        assert row is not None
        return row
    raise AssertionError("unreachable")  # pragma: no cover


async def get_version(session: AsyncSession, version_id: int) -> ForexStrategyVersion | None:
    return await session.get(ForexStrategyVersion, version_id)


async def list_versions(session: AsyncSession, limit: int = 200) -> list[ForexStrategyVersion]:
    stmt = (
        select(ForexStrategyVersion)
        .order_by(
            ForexStrategyVersion.name.asc(),
            desc(ForexStrategyVersion.version),
            desc(ForexStrategyVersion.id),
        )
        .limit(limit)
    )
    return list((await session.execute(stmt)).scalars().all())


# --------------------------------------------------------------------------
# Runs
# --------------------------------------------------------------------------


async def add_run(session: AsyncSession, **fields: Any) -> ForexRun:
    row = ForexRun(**fields)
    session.add(row)
    await session.flush()
    await session.refresh(row)
    return row


async def get_run(
    session: AsyncSession, run_id: int, *, with_result: bool = True
) -> ForexRun | None:
    stmt = select(ForexRun).where(ForexRun.id == run_id)
    if not with_result:
        stmt = stmt.options(defer(ForexRun.result))
    # populate_existing: a background task commits progress on another session.
    stmt = stmt.execution_options(populate_existing=True)
    return (await session.execute(stmt)).scalar_one_or_none()


async def list_runs(session: AsyncSession, *, kind: str | None, limit: int) -> list[ForexRun]:
    """Newest first, tiebroken by id so equal timestamps cannot reorder or starve."""
    stmt = select(ForexRun).options(defer(ForexRun.result))
    if kind is not None:
        stmt = stmt.where(ForexRun.kind == kind)
    stmt = stmt.order_by(desc(ForexRun.created_at), desc(ForexRun.id)).limit(limit)
    stmt = stmt.execution_options(populate_existing=True)
    return list((await session.execute(stmt)).scalars().all())


async def fail_stale_runs(
    session: AsyncSession, *, now: datetime, live: set[int], message: str
) -> int:
    """Mark queued / running runs this process is not running, and that have not
    been touched for `STALE_AFTER`, as failed. Their worker died with a deploy."""
    stmt = (
        update(ForexRun)
        .where(
            ForexRun.status.in_(("queued", "running")),
            ForexRun.updated_at < now - STALE_AFTER,
            ForexRun.id.not_in(live) if live else sa_true(),
        )
        .values(status="failed", error=message, finished_at=now, message=None)
        .returning(ForexRun.id)
    )
    n = len((await session.execute(stmt)).all())
    await session.flush()
    return n
