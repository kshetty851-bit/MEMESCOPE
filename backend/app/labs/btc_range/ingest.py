"""Fetch candles from the source and store them.

Both entry points page FORWARD from a start time and stop at the first short
page, which is how Binance signals "that was the present". Forward paging is
resumable: each page is upserted before the next is requested, so an outage
half way loses nothing already written, and the next run continues from the
last closed candle.

Neither function commits - the caller owns the transaction.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.labs.btc_range import repository
from app.labs.btc_range.source import MAX_LIMIT, KlineSource
from app.labs.btc_range.types import TIMEFRAME_SECONDS

logger = get_logger(__name__)

STEP = timedelta(seconds=TIMEFRAME_SECONDS)
#: A routine catch-up is a minute or two behind; three pages is 31 days and
#: bounds the work if the worker was down for a long weekend.
MAX_PAGES_LATEST = 3
#: First run on an empty table: enough closed candles for the default 96-candle
#: lookback with room to spare, small enough to be one request.
DEFAULT_WINDOW = timedelta(days=2)


@dataclass(frozen=True, slots=True)
class IngestResult:
    pages: int
    #: Rows the source returned.
    fetched: int
    #: Rows inserted or refreshed. A closed candle already stored is not
    #: written, so re-ingesting history gives 0.
    written: int


def _floor(at: datetime) -> datetime:
    return datetime.fromtimestamp(
        int(at.timestamp()) // TIMEFRAME_SECONDS * TIMEFRAME_SECONDS, tz=at.tzinfo
    )


async def _page_forward(
    session: AsyncSession,
    client: KlineSource,
    *,
    start: datetime,
    now: datetime,
    max_pages: int,
) -> IngestResult:
    cursor = start
    pages = fetched = written = 0
    while pages < max_pages and cursor <= now:
        page = await client.fetch_klines(start=cursor, limit=MAX_LIMIT, now=now)
        pages += 1
        fetched += len(page)
        written += await repository.upsert_candles(session, page)
        if len(page) < MAX_LIMIT:
            break
        # Resume after the last candle returned. Guard against a source that
        # ignores startTime and would otherwise hand back the same page for ever.
        advanced = page[-1].candle.open_time + STEP
        if advanced <= cursor:
            logger.warning("btc_range_ingest_no_progress", cursor=cursor.isoformat())
            break
        cursor = advanced
    return IngestResult(pages=pages, fetched=fetched, written=written)


async def ingest_latest(
    session: AsyncSession, client: KlineSource, *, now: datetime
) -> IngestResult:
    """Catch up from the last stored closed candle (or a small default window).

    Starting at the candle AFTER the last closed one means the still-forming
    candle is re-read and refreshed on every run, and closes for the last time
    in the run that sees its `close_time` pass.
    """
    _count, _first, last_closed = await repository.stats(session)
    start = last_closed + STEP if last_closed is not None else _floor(now) - DEFAULT_WINDOW
    result = await _page_forward(
        session, client, start=start, now=now, max_pages=MAX_PAGES_LATEST
    )
    logger.info(
        "btc_range_ingested",
        pages=result.pages,
        fetched=result.fetched,
        written=result.written,
        resumed_from=start.isoformat(),
    )
    return result


async def backfill(
    session: AsyncSession, client: KlineSource, *, days: int, now: datetime
) -> IngestResult:
    """Fetch `days` of history up to `now`. Idempotent: closed candles already
    stored are untouched, so it can be re-run or widened freely."""
    if days < 1:
        raise ValueError(f"days must be >= 1, got {days}")
    start = _floor(now) - timedelta(days=days)
    expected = days * 86400 // TIMEFRAME_SECONDS
    result = await _page_forward(
        session,
        client,
        start=start,
        now=now,
        max_pages=math.ceil(expected / MAX_LIMIT) + 2,
    )
    logger.info(
        "btc_range_backfilled",
        days=days,
        pages=result.pages,
        fetched=result.fetched,
        written=result.written,
    )
    return result
