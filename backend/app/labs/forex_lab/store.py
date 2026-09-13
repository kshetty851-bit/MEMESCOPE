"""The read side of the data layer, and the integrity check that gates the sweep.

Everything downstream reads candles through here. The engine does not — it
takes a candle iterator and knows nothing about Postgres, which is the point.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.labs.forex_lab import config, market
from app.labs.forex_lab.models import FxCandle, FxIngestHour

#: Minutes the FX market is open in a full week: Sunday 22:00 UTC to Friday
#: 22:00 UTC, less nothing. 5 x 24 x 60 = 7,200.
_MINUTES_PER_FULL_WEEK = 5 * 24 * 60


async def status(session: AsyncSession, symbol: str = config.SYMBOL) -> dict[str, Any]:
    """What is loaded, and what the loader still owes."""
    total, first, last = (
        await session.execute(
            select(func.count(), func.min(FxCandle.minute), func.max(FxCandle.minute)).where(
                FxCandle.symbol == symbol
            )
        )
    ).one()
    hours = dict(
        (
            await session.execute(
                select(FxIngestHour.ok, func.count())
                .where(FxIngestHour.symbol == symbol)
                .group_by(FxIngestHour.ok)
            )
        ).all()
    )
    per_year = [
        {"year": int(y), "candles": int(n)}
        for y, n in (
            await session.execute(
                select(func.extract("year", FxCandle.minute), func.count())
                .where(FxCandle.symbol == symbol)
                .group_by(func.extract("year", FxCandle.minute))
                .order_by(func.extract("year", FxCandle.minute))
            )
        ).all()
    ]
    return {
        "symbol": symbol,
        "candles": int(total or 0),
        "first_minute": first,
        "last_minute": last,
        "hours_ok": int(hours.get(True, 0)),
        "hours_failed": int(hours.get(False, 0)),
        "per_year": per_year,
    }


async def iter_candles(
    session: AsyncSession,
    symbol: str = config.SYMBOL,
    start: datetime | None = None,
    end: datetime | None = None,
    chunk: int = 200_000,
) -> AsyncIterator[tuple]:
    """Every candle in order, as plain tuples, streamed in chunks.

    Tuples rather than ORM objects, and chunks rather than one query, because
    the sweep replays six and a half years of minutes twenty-seven times and
    neither the identity map nor a 2.4M-row result set earns its memory.
    """
    cursor, first = start, True
    while True:
        q = (
            select(
                FxCandle.minute,
                FxCandle.bid_open,
                FxCandle.bid_high,
                FxCandle.bid_low,
                FxCandle.bid_close,
                FxCandle.ask_open,
                FxCandle.ask_high,
                FxCandle.ask_low,
                FxCandle.ask_close,
            )
            .where(FxCandle.symbol == symbol)
            .order_by(FxCandle.minute)
            .limit(chunk)
        )
        if cursor is not None:
            # Inclusive on the first page (the caller asked to start AT `start`),
            # exclusive on every page after it (that row has been yielded).
            q = (
                q.where(FxCandle.minute >= cursor)
                if first
                else q.where(FxCandle.minute > cursor)
            )
        if end is not None:
            q = q.where(FxCandle.minute < end)
        rows = (await session.execute(q)).all()
        if not rows:
            return
        for r in rows:
            yield r
        cursor, first = rows[-1][0], False
        if len(rows) < chunk:
            return


def _gap_is_the_weekend(prev: datetime, nxt: datetime) -> bool:
    """Whether a gap is the market being shut rather than the loader dropping
    something.

    Asked of the FIRST MISSING minute, not of the last candle before it. The
    last tick of the week lands somewhere in 20:5x or 21:5x on Friday, which is
    not itself in the closed window — testing that one instead reports every
    single weekend in the dataset as a hole.
    """
    return not market.is_open(prev + timedelta(minutes=1))


async def integrity_check(
    session: AsyncSession, symbol: str = config.SYMBOL
) -> dict[str, Any]:
    """The three checks the brief names, run against what is actually stored.

    1. no gap longer than an hour outside a weekend;
    2. bid <= ask on every row;
    3. per-year candle count within 5% of what a full year of open market
       would produce.

    A holiday is a gap, and a real one — 25 December is genuinely missing from
    the tape. Gaps that start on a recognised market holiday are reported
    separately from the ones that are not, because only the second kind says
    the loader dropped something.
    """
    # --- 2. bid <= ask, on all four points -----------------------------------
    crossed = (
        await session.execute(
            select(func.count()).where(
                FxCandle.symbol == symbol,
                (FxCandle.bid_open > FxCandle.ask_open)
                | (FxCandle.bid_high > FxCandle.ask_high)
                | (FxCandle.bid_low > FxCandle.ask_low)
                | (FxCandle.bid_close > FxCandle.ask_close),
            )
        )
    ).scalar_one()

    # --- 1. gaps --------------------------------------------------------------
    gaps: list[dict] = []
    prev: datetime | None = None
    limit = timedelta(minutes=config.MAX_GAP_MINUTES)
    async for row in iter_candles(session, symbol):
        m = row[0]
        if prev is not None and m - prev > limit and not _gap_is_the_weekend(prev, m):
            gaps.append(
                {
                    "from": prev.isoformat(),
                    "to": m.isoformat(),
                    "minutes": int((m - prev).total_seconds() // 60),
                    "holiday": market.holiday_name(prev, m),
                }
            )
        prev = m
    unexplained = [g for g in gaps if g["holiday"] is None]

    # --- 3. per-year counts ---------------------------------------------------
    st = await status(session, symbol)
    years = []
    for row in st["per_year"]:
        y = row["year"]
        expected = _expected_minutes(y)
        ratio = row["candles"] / expected if expected else 0.0
        years.append(
            {
                "year": y,
                "candles": row["candles"],
                "expected": expected,
                "ratio": round(ratio, 4),
                "within_tolerance": abs(1 - ratio) <= config.CANDLE_COUNT_TOLERANCE,
            }
        )

    passed = (
        crossed == 0
        and not unexplained
        and all(y["within_tolerance"] for y in years)
        and st["hours_failed"] == 0
    )
    return {
        "passed": passed,
        "candles": st["candles"],
        "first_minute": st["first_minute"],
        "last_minute": st["last_minute"],
        "hours_failed": st["hours_failed"],
        "crossed_quotes": int(crossed),
        "gaps_total": len(gaps),
        "gaps_unexplained": len(unexplained),
        "gaps_worst": sorted(unexplained, key=lambda g: -g["minutes"])[:10],
        "gaps_holiday_sample": [g for g in gaps if g["holiday"]][:5],
        "years": years,
    }


def _expected_minutes(year: int) -> int:
    """Minutes of open market in a year, clipped to the backtest window.

    Delegated to `market.py` so the count and the planner cannot disagree: an
    expected count computed from a different definition of "open" than the one
    that decided which hours to download is a check that measures its own
    assumptions.
    """
    return market.open_minutes_in_year(year, config.START, config.END)
