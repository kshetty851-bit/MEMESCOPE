"""OHLCV rows -> stored candles, and the budgeted refresh that fetches them.

The top half is pure: parsing, the forming-bar cut, interval maths, gaps.
The bottom half is the sync — what to ask for, in what order, and when to
stop.

**The queue carries itself.** The brief asks for a refresh ordered by 24h
volume whose remainder carries to the next tick. No queue is stored: a token
is due a fetch exactly when its newest stored bar is older than the last
CLOSED bar, so a token fetched this tick drops out of the queue and one that
was not fetched is still in it. Ordering the due list by volume therefore
covers the most liquid names first and leaves the rest for the next tick,
which is the carry. A stored queue would be a second source of truth for a
fact `MAX(open_time)` already answers.
"""

from __future__ import annotations

import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from itertools import pairwise
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.labs.breakout import config
from app.labs.breakout.models import BoCandle, BoRun, BoUniverseMember
from app.labs.breakout.sources import BreakoutSource, BudgetExhaustedError

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class Candle:
    mint: str
    pool_address: str
    timeframe: str
    open_time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume_usd: Decimal | None
    close_time: datetime


# --- pure ---------------------------------------------------------------------

def interval(timeframe: str) -> timedelta:
    return timedelta(seconds=config.INTERVAL_SECONDS[timeframe])


def last_closed_open(timeframe: str, now: datetime) -> datetime:
    """The open time of the newest bar that has FINISHED.

    The bar covering `now` is still forming, so the last closed one opened an
    interval before it.
    """
    seconds = config.INTERVAL_SECONDS[timeframe]
    current = (int(now.timestamp()) // seconds) * seconds
    return datetime.fromtimestamp(current - seconds, tz=UTC)


def _decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    return result if result.is_finite() else None


def parse_ohlcv(
    mint: str, pool: str, timeframe: str, rows: Iterable[Sequence[Any]], *, now: datetime,
) -> list[Candle]:
    """GeckoTerminal OHLCV rows, keeping only bars that have CLOSED.

    Rows are `[open_ts_seconds, o, h, l, c, volume_usd]`, newest first. The
    newest is the bar currently forming — storing it would write a close that
    is still moving — so the cut is `open_time + interval <= now`. The
    returned list is oldest first.

    A row with a missing or non-numeric price is dropped rather than stored as
    zero: a zero low would sit under every future support level for ever.
    """
    step = interval(timeframe)
    candles: list[Candle] = []
    for row in rows:
        if len(row) < 5:
            continue
        try:
            open_time = datetime.fromtimestamp(int(row[0]), tz=UTC)
        except (TypeError, ValueError, OSError, OverflowError):
            continue
        close_time = open_time + step
        if close_time > now:
            continue
        prices = [_decimal(row[i]) for i in (1, 2, 3, 4)]
        if any(p is None for p in prices):
            continue
        o, h, low, c = prices
        candles.append(Candle(
            mint=mint, pool_address=pool, timeframe=timeframe, open_time=open_time,
            open=o, high=h, low=low, close=c,  # type: ignore[arg-type]
            volume_usd=_decimal(row[5]) if len(row) > 5 else None,
            close_time=close_time,
        ))
    candles.sort(key=lambda c: c.open_time)
    return candles


def find_gaps(
    open_times: Iterable[datetime], step: timedelta,
) -> list[tuple[datetime, datetime]]:
    """Ranges of missing bars between stored ones, as
    `(first_missing_open, last_missing_open)`. Order of input is free."""
    times = sorted(set(open_times))
    return [
        (previous + step, following - step)
        for previous, following in pairwise(times)
        if following - previous > step
    ]


def due_timeframes(now: datetime) -> tuple[str, ...]:
    """Which timeframes this tick may fetch.

    `hour` always. `day` only after `DAY_REFRESH_AFTER_MINUTE` past midnight
    UTC — the bar closes at 00:00 and GeckoTerminal needs a moment to publish
    it, and a tick at 00:00:30 would otherwise spend a call per token to be
    told nothing new has closed. Every later tick in the day sees no missing
    daily bar and sends nothing anyway.
    """
    if now.hour == 0 and now.minute < config.DAY_REFRESH_AFTER_MINUTE:
        return ("hour",)
    return config.TIMEFRAMES


# --- the sync -----------------------------------------------------------------

class BreakoutCandles:
    def __init__(self, session: AsyncSession, source: BreakoutSource) -> None:
        self._session = session
        self._source = source

    async def refresh(self, now: datetime, *,
                      deadline_seconds: float = config.TICK_DEADLINE_SECONDS,
                      ) -> dict[str, Any]:
        """One candle pass over the active universe, most liquid first.

        Stops on the deadline or the call budget and reports what it did not
        reach. Each token's work runs in its own savepoint: one token failing
        costs that token this tick and nothing else.
        """
        started = now
        stop_at = time.monotonic() + deadline_seconds
        members = list((await self._session.execute(
            select(BoUniverseMember)
            .where(BoUniverseMember.active.is_(True))
            .order_by(BoUniverseMember.volume_24h_usd.desc().nullslast(),
                      BoUniverseMember.mint)
        )).scalars())

        timeframes = due_timeframes(now)
        stored = refreshed = 0
        errors: list[str] = []
        carried = 0
        for index, member in enumerate(members):
            if time.monotonic() >= stop_at:
                carried = len(members) - index
                logger.info("breakout_candles_deadline", carried=carried)
                break
            spent = False
            try:
                async with self._session.begin_nested():
                    got = 0
                    for timeframe in timeframes:
                        try:
                            got += await self.sync(member, timeframe, now)
                        except BudgetExhaustedError:
                            # Caught INSIDE the savepoint, so the bars already
                            # fetched for this token are kept. Rolling them
                            # back would throw away calls that are exactly what
                            # just ran out.
                            spent = True
                            break
                    if got:
                        refreshed += 1
                    stored += got
                    await self._clear_failures(member)
            except Exception as exc:
                logger.warning("breakout_token_failed", mint=member.mint, error=repr(exc))
                errors.append(f"{member.mint}: {exc!r}")
                # Its own transaction: the savepoint above has been rolled
                # back, so the counter must be written outside it.
                await self._count_failure(member, repr(exc))
            if spent:
                # This token counts as carried: whatever timeframe the budget
                # cut short is still missing, so it is still in the queue.
                carried = len(members) - index
                logger.info("breakout_candles_budget_spent", carried=carried)
                break

        pruned = await self.prune()
        self._session.add(BoRun(
            phase="candles", started_at=started, finished_at=datetime.now(UTC),
            universe_size=len(members), candles_upserted=stored,
            tokens_refreshed=refreshed, tokens_carried=carried,
            requests=dict(self._source.requests), errors=errors or None,
        ))
        await self._session.flush()  # the new row must exist before prune counts
        await self.prune_runs()
        return {"phase": "candles", "universe_size": len(members),
                "timeframes": list(timeframes), "candles_upserted": stored,
                "candles_pruned": pruned, "tokens_refreshed": refreshed,
                "tokens_carried": carried,
                "requests": dict(self._source.requests), "errors": errors}

    async def sync(self, member: BoUniverseMember, timeframe: str, now: datetime) -> int:
        """Fetch only what is missing for one token and timeframe.

        Two directions, and neither is sent unless it is needed:

        * **forward** — the bars that have closed since the newest stored one.
          Nothing is sent when that count is zero, which is most ticks for
          `hour` and every tick but one a day for `day`.
        * **backward** — pages of older bars until the timeframe's window is
          full or the pool's history runs out, at most
          `BACKFILL_PAGES_PER_TICK` a tick so one deep backfill cannot eat the
          budget. Resumable by construction: the next tick sees the same short
          history and continues.
        """
        newest, oldest, count = await self._coverage(member.mint, timeframe)
        step = interval(timeframe)
        stored = 0

        missing = (0 if newest is None
                   else int((last_closed_open(timeframe, now) - newest) / step))
        if newest is None or missing > 0:
            limit = config.OHLCV_LIMIT if newest is None else min(
                config.OHLCV_LIMIT, missing + 1)
            rows = await self._source.gecko_ohlcv(member.pool_address, timeframe,
                                                  limit=limit)
            stored += await self.upsert(parse_ohlcv(member.mint, member.pool_address,
                                                    timeframe, rows, now=now))
            newest, oldest, count = await self._coverage(member.mint, timeframe)

        want = config.candle_window(timeframe)
        for _ in range(config.BACKFILL_PAGES_PER_TICK):
            if count >= want or oldest is None:
                break
            # Ask only for what the window still wants, plus the one bar
            # `before_timestamp` repeats — 54 bars were fetched and pruned in
            # the same tick before this, which is work for nothing.
            rows = await self._source.gecko_ohlcv(
                member.pool_address, timeframe, limit=want - count + 1,
                before=int(oldest.timestamp()))
            stored += await self.upsert(parse_ohlcv(member.mint, member.pool_address,
                                                    timeframe, rows, now=now))
            previous = oldest
            newest, oldest, count = await self._coverage(member.mint, timeframe)
            # `before_timestamp` is inclusive, so a page that reaches the
            # pool's first bar comes back with only bars already held. No
            # progress means there is no more history: never spin.
            if oldest is None or oldest >= previous:
                break
        return stored

    async def _coverage(
        self, mint: str, timeframe: str,
    ) -> tuple[datetime | None, datetime | None, int]:
        """`(newest open, oldest open, count)` for one token and timeframe."""
        row = (await self._session.execute(
            select(func.max(BoCandle.open_time), func.min(BoCandle.open_time),
                   func.count())
            .where(BoCandle.mint == mint, BoCandle.timeframe == timeframe)
        )).one()
        return row[0], row[1], row[2] or 0

    async def upsert(self, candles: list[Candle]) -> int:
        if not candles:
            return 0
        stmt = pg_insert(BoCandle).values([{
            "mint": c.mint, "pool_address": c.pool_address, "timeframe": c.timeframe,
            "open_time": c.open_time, "open": c.open, "high": c.high, "low": c.low,
            "close": c.close, "volume_usd": c.volume_usd, "close_time": c.close_time,
        } for c in candles])
        await self._session.execute(stmt.on_conflict_do_update(
            constraint="uq_bo_candles_mint_timeframe_open_time",
            set_={k: getattr(stmt.excluded, k)
                  for k in ("pool_address", "open", "high", "low", "close",
                            "volume_usd", "close_time")},
        ))
        return len(candles)

    async def prune(self) -> int:
        """Keep the newest `candle_window(timeframe)` bars per token, per
        timeframe, over the timeframes actually PRESENT."""
        present = list((await self._session.execute(
            select(BoCandle.timeframe).distinct())).scalars())
        pruned = 0
        for timeframe in present:
            ranked = select(
                BoCandle.id,
                func.row_number().over(
                    partition_by=BoCandle.mint, order_by=BoCandle.open_time.desc(),
                ).label("rn"),
            ).where(BoCandle.timeframe == timeframe).subquery()
            stale = select(ranked.c.id).where(ranked.c.rn > config.candle_window(timeframe))
            result = await self._session.execute(
                delete(BoCandle).where(BoCandle.id.in_(stale)))
            pruned += result.rowcount or 0
        return pruned

    async def _clear_failures(self, member: BoUniverseMember) -> None:
        if member.fetch_failures:
            await self._session.execute(
                update(BoUniverseMember)
                .where(BoUniverseMember.id == member.id)
                .values(fetch_failures=0, last_error=None)
            )

    async def _count_failure(self, member: BoUniverseMember, error: str) -> None:
        """Consecutive failures only. `MAX_FETCH_FAILURES` retires the token
        with a reason, and qualifying again in a later universe refresh resets
        the counter — a token is retired for being persistently broken, never
        for a bad afternoon."""
        failures = (member.fetch_failures or 0) + 1
        values: dict[str, Any] = {"fetch_failures": failures, "last_error": error[:2000]}
        if failures >= config.MAX_FETCH_FAILURES:
            values |= {"active": False, "inactive_reason": "fetch_failures"}
            logger.warning("breakout_token_retired", mint=member.mint, failures=failures)
        await self._session.execute(
            update(BoUniverseMember).where(BoUniverseMember.id == member.id).values(**values))

    async def prune_runs(self) -> None:
        keep = select(BoRun.id).order_by(BoRun.started_at.desc()).limit(config.RUN_HISTORY)
        await self._session.execute(delete(BoRun).where(BoRun.id.not_in(keep)))

    # --- one-off ------------------------------------------------------------

    async def backfill(self, member: BoUniverseMember, now: datetime, *,
                       max_pages: int = 20) -> dict[str, Any]:
        """Fill both timeframes for ONE token as far as their windows reach,
        ignoring the per-tick page cap. Idempotent: a second run upserts the
        same bars and stops on the same no-progress check."""
        report: dict[str, Any] = {"mint": member.mint, "pool": member.pool_address}
        for timeframe in config.TIMEFRAMES:
            stored = 0
            for _ in range(max_pages):
                newest, oldest, count = await self._coverage(member.mint, timeframe)
                before = None if oldest is None else int(oldest.timestamp())
                if newest is not None and count >= config.candle_window(timeframe):
                    break
                rows = await self._source.gecko_ohlcv(member.pool_address, timeframe,
                                                      before=before)
                stored += await self.upsert(parse_ohlcv(
                    member.mint, member.pool_address, timeframe, rows, now=now))
                _, new_oldest, _ = await self._coverage(member.mint, timeframe)
                if new_oldest is None or (oldest is not None and new_oldest >= oldest):
                    break
            report[timeframe] = stored
        report["requests"] = dict(self._source.requests)
        return report
