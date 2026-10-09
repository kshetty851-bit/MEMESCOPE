"""Candle persistence. Flushes, never commits - the caller owns the transaction.

## A closed candle is immutable

The live paper book is a replay over stored closed candles. If re-ingesting
could change one, the record could rewrite itself - a trade that stopped out
yesterday could quietly become a winner because the source revised a print. So
the upsert is `ON CONFLICT (symbol, timeframe, open_time) DO UPDATE ... WHERE
btc_candles.is_closed IS false`: a row that is already closed is left exactly
as it is, whatever arrives later, and a still-forming row is refreshed until
the payload that closes it overwrites it for the last time.

The guarantee is the database's, not a check-then-insert. The predicate is
written with `is_(False)` so it compiles to `IS false`, the same form the
partial-index trap in CLAUDE.md warns about; there is no index to match here,
but keeping one spelling means nobody has to reason about two.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.labs.btc_range.source import Kline
from app.labs.btc_range.types import SYMBOL, TIMEFRAME, Candle
from app.models.btc_range import BtcCandle

_COLUMNS = (
    BtcCandle.open_time,
    BtcCandle.open,
    BtcCandle.high,
    BtcCandle.low,
    BtcCandle.close,
    BtcCandle.volume,
)


def _candle(row: tuple) -> Candle:  # type: ignore[type-arg]
    return Candle(
        open_time=row[0], open=row[1], high=row[2], low=row[3], close=row[4], volume=row[5]
    )


async def upsert_candles(session: AsyncSession, rows: Sequence[Kline]) -> int:
    """Insert new candles and refresh forming ones. Returns rows WRITTEN.

    A conflicting row that is already closed is skipped by the `WHERE`, so it
    is not counted: re-ingesting a page of history returns 0, which is the
    property the caller (and the tests) rely on.

    If a batch names the same candle twice the LAST one wins - Postgres refuses
    a single statement that would touch a row twice.
    """
    by_open_time: dict[datetime, Kline] = {}
    for row in rows:
        by_open_time[row.candle.open_time] = row
    if not by_open_time:
        return 0

    values = [
        {
            "symbol": SYMBOL,
            "timeframe": TIMEFRAME,
            "open_time": k.candle.open_time,
            "open": k.candle.open,
            "high": k.candle.high,
            "low": k.candle.low,
            "close": k.candle.close,
            "volume": k.candle.volume,
            "is_closed": k.is_closed,
            "close_time": k.close_time,
        }
        for k in by_open_time.values()
    ]
    insert_stmt = pg_insert(BtcCandle).values(values)
    stmt = insert_stmt.on_conflict_do_update(
        index_elements=[BtcCandle.symbol, BtcCandle.timeframe, BtcCandle.open_time],
        set_={
            "open": insert_stmt.excluded.open,
            "high": insert_stmt.excluded.high,
            "low": insert_stmt.excluded.low,
            "close": insert_stmt.excluded.close,
            "volume": insert_stmt.excluded.volume,
            "is_closed": insert_stmt.excluded.is_closed,
            "close_time": insert_stmt.excluded.close_time,
            "updated_at": func.now(),
        },
        where=BtcCandle.is_closed.is_(False),
    ).returning(BtcCandle.open_time)
    result = await session.execute(stmt)
    written = len(result.all())
    await session.flush()
    return written


async def closed_candles(
    session: AsyncSession,
    *,
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int | None = None,
    newest: bool = False,
) -> list[Candle]:
    """Closed candles, ASCENDING by open time.

    `start` is inclusive and `end` exclusive on `open_time`. With `limit`,
    `newest=False` takes the oldest N and `newest=True` the newest N; either
    way the result is returned ascending. The ORDER BY is total (open_time is
    unique within the symbol/timeframe), so a LIMIT can never starve.
    """
    stmt = select(*_COLUMNS).where(
        BtcCandle.symbol == SYMBOL,
        BtcCandle.timeframe == TIMEFRAME,
        BtcCandle.is_closed.is_(True),
    )
    if start is not None:
        stmt = stmt.where(BtcCandle.open_time >= start)
    if end is not None:
        stmt = stmt.where(BtcCandle.open_time < end)
    stmt = stmt.order_by(BtcCandle.open_time.desc() if newest else BtcCandle.open_time.asc())
    if limit is not None:
        stmt = stmt.limit(limit)
    rows = [_candle(tuple(r)) for r in (await session.execute(stmt)).all()]
    if newest:
        rows.reverse()
    return rows


async def latest_candle(session: AsyncSession) -> tuple[Candle, bool] | None:
    """The newest row of ANY state, with whether it is closed.

    For the dashboard's current price: the forming candle's close is the latest
    trade price. The engine never reads this - it sees closed candles only.
    """
    stmt = (
        select(*_COLUMNS, BtcCandle.is_closed)
        .where(BtcCandle.symbol == SYMBOL, BtcCandle.timeframe == TIMEFRAME)
        .order_by(BtcCandle.open_time.desc())
        .limit(1)
    )
    row = (await session.execute(stmt)).first()
    if row is None:
        return None
    return _candle(tuple(row)), bool(row[6])


async def stats(session: AsyncSession) -> tuple[int, datetime | None, datetime | None]:
    """(closed count, first closed open_time, last closed open_time).

    One row per 15 minutes, so a count over the table is cheap; it is not the
    unconditional `count(*)` on a hot endpoint the notes warn about.
    """
    stmt = select(
        func.count(), func.min(BtcCandle.open_time), func.max(BtcCandle.open_time)
    ).where(
        BtcCandle.symbol == SYMBOL,
        BtcCandle.timeframe == TIMEFRAME,
        BtcCandle.is_closed.is_(True),
    )
    count, first, last = (await session.execute(stmt)).one()
    return int(count), first, last


async def monthly_bars(session: AsyncSession, *, start: datetime) -> list[tuple]:  # type: ignore[type-arg]
    """(month start, open, close, high, low) per UTC month from `start`, over
    every stored candle including the forming one, ascending. The monthly book
    (`monthly.py`) needs nothing finer: it enters at the open and holds."""
    from sqlalchemy import text

    rows = await session.execute(text("""
        select date_trunc('month', open_time) as m,
               (array_agg(open order by open_time))[1],
               (array_agg(close order by open_time desc))[1],
               max(high), min(low)
        from btc_candles
        where symbol = :s and timeframe = :tf and open_time >= :start
        group by 1 order by 1"""), {"s": SYMBOL, "tf": TIMEFRAME, "start": start})
    return [tuple(r) for r in rows.all()]
