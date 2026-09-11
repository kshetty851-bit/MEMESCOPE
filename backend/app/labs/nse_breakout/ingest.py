"""One trading day in, bars and a universe out. And the resumable backfill.

The whole design turns on one property of the source: **a single bhavcopy ZIP
carries every symbol for that day.** So a three-year history is ~620 requests
rather than one per symbol for 2,800 symbols, the daily feed and the backfill
are the same code path, and there is no second source whose adjustments have
to be reconciled with the first.
"""

from __future__ import annotations

import statistics
import time
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.labs.nse_breakout import bhavcopy, config
from app.labs.nse_breakout.bhavcopy import Bar
from app.labs.nse_breakout.models import (
    BtCandle,
    BtIndexClose,
    BtIngestDay,
    BtRun,
    BtUniverseMember,
)
from app.labs.nse_breakout.sources import NotPublished, NseArchive

logger = get_logger(__name__)

OK, MISSING, FAILED = "ok", "missing", "failed"
#: Not a stored status. A 404 for a day the archive has not had time to
#: publish is reported as this and recorded as NOTHING, so the day stays
#: pending and is asked for again.
TOO_EARLY = "too_early"
#: A universe row created by the identity pass, before
#: `rebuild_universe` has judged it. Never committed in this state.
PENDING = "pending"


def trading_days(start: date, end: date) -> list[date]:
    """Weekdays between two dates, newest first.

    Deliberately NOT a holiday calendar. The exchange's own archive is the
    calendar: a 404 means it did not trade, which is recorded as `missing` and
    never asked about again. Hard-coding Indian market holidays would be a
    second source of truth that goes stale every year.
    """
    days, cursor = [], end
    while cursor >= start:
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor -= timedelta(days=1)
    return days


def median_turnover(values: Sequence[Decimal | None]) -> Decimal | None:
    """Median, not mean: one block deal must not qualify a name that is
    otherwise untradeable."""
    real = [float(v) for v in values if v is not None]
    return Decimal(str(statistics.median(real))) if real else None


def settleable(when: date, now: datetime) -> bool:
    """Has the archive had time to publish this day?

    The beat runs after the close so it normally never sees a "no", but the
    CLI can be run at any hour and `missing` is a terminal state.
    """
    midnight = datetime(when.year, when.month, when.day, tzinfo=UTC)
    return now - midnight >= timedelta(hours=config.PUBLISH_CUTOFF_HOURS_UTC)


class Ingest:
    def __init__(self, session: AsyncSession, archive: NseArchive) -> None:
        self._session = session
        self._archive = archive

    # --- one day -------------------------------------------------------------

    async def day(self, when: date, *, now: datetime) -> dict[str, Any]:
        """Fetch, parse and upsert one trading day. Idempotent on
        `(symbol, date)`, so re-running a day rewrites rather than duplicates."""
        try:
            payload = await self._archive.bhavcopy(when)
        except NotPublished:
            if not settleable(when, now):
                # "Not published yet" is not "never published", and `missing`
                # is terminal — `pending_days` never asks again. Recording it
                # from a pre-publication run would silently drop that session.
                logger.info("nse_bhavcopy_not_yet", date=when.isoformat())
                return {"date": when.isoformat(), "status": TOO_EARLY, "rows": 0}
            await self._record_day(when, MISSING, 0, 0, None, now)
            return {"date": when.isoformat(), "status": MISSING, "rows": 0}
        except Exception as exc:
            logger.warning("nse_bhavcopy_failed", date=when.isoformat(), error=repr(exc))
            await self._record_day(when, FAILED, 0, 0, repr(exc)[:2000], now)
            return {"date": when.isoformat(), "status": FAILED, "error": repr(exc)}

        try:
            bars = list(bhavcopy.parse(bhavcopy.unzip(payload)))
        except bhavcopy.BhavcopyError as exc:
            logger.warning("nse_bhavcopy_unparsable", date=when.isoformat(),
                           error=repr(exc))
            await self._record_day(when, FAILED, 0, 0, repr(exc)[:2000], now)
            return {"date": when.isoformat(), "status": FAILED, "error": repr(exc)}

        stored = await self.upsert_bars(bars)
        await self.upsert_identity(bars, when)
        await self.upsert_index(when)
        await self._record_day(when, OK, stored, len({b.symbol for b in bars}), None, now)
        return {"date": when.isoformat(), "status": OK, "rows": stored,
                "symbols": len({b.symbol for b in bars})}

    async def upsert_bars(self, bars: Sequence[Bar]) -> int:
        if not bars:
            return 0
        rows = [{
            "symbol": b.symbol, "date": b.date, "open": b.open, "high": b.high,
            "low": b.low, "close": b.close, "volume": b.volume,
            "turnover": b.turnover, "adjusted": False, "suspect_gap": False,
        } for b in bars]
        # Chunked: a single statement with 2,900 VALUES rows is close to
        # Postgres's parameter ceiling and gains nothing over four.
        total = 0
        for start in range(0, len(rows), 1000):
            chunk = rows[start:start + 1000]
            stmt = pg_insert(BtCandle).values(chunk)
            await self._session.execute(stmt.on_conflict_do_update(
                constraint="uq_bt_candles_symbol_date",
                set_={k: getattr(stmt.excluded, k) for k in
                      ("open", "high", "low", "close", "volume", "turnover")},
            ))
            total += len(chunk)
        return total

    async def upsert_identity(self, bars: Sequence[Bar], when: date) -> int:
        """Carry each symbol's NAME, ISIN and series from the file into
        `bt_universe`.

        `bt_candles` stores prices only, and `rebuild_universe` runs off the
        candle table — so it can preserve these three columns but can never
        fill them. This is the one place they come from.

        **Newest day wins.** The backfill walks the archive BACKWARDS, so
        without the guard every slice would overwrite a current name with an
        older one and a company that changed its name would end up filed under
        whatever it was called three years ago. `last_seen` is maintained by
        `rebuild_universe` from the candles, so comparing against it is the
        same question as "is this day newer than what we already have?".
        """
        if not bars:
            return 0
        newest = {b.symbol: b for b in bars}
        rows = [{"symbol": b.symbol, "name": b.name, "isin": b.isin,
                 "series": b.series, "first_seen": when, "last_seen": when,
                 # Not yet judged. `rebuild_universe` decides in this same
                 # transaction, so this never reaches a reader.
                 "active": False, "inactive_reason": PENDING,
                 "updated_at": datetime.now(UTC)}
                for b in newest.values()]
        total = 0
        for start in range(0, len(rows), 1000):
            chunk = rows[start:start + 1000]
            stmt = pg_insert(BtUniverseMember).values(chunk)
            await self._session.execute(stmt.on_conflict_do_update(
                constraint="uq_bt_universe_symbol",
                set_={"name": stmt.excluded.name, "isin": stmt.excluded.isin,
                      "series": stmt.excluded.series},
                where=BtUniverseMember.last_seen <= stmt.excluded.last_seen))
            total += len(chunk)
        return total

    async def upsert_index(self, when: date) -> bool:
        """Nifty 50's close for the day. A missing index file makes one
        window's relative return null — the pre-decided rule — and must never
        take the equity ingest down with it."""
        try:
            parsed = bhavcopy.parse_index_closes(await self._archive.index_closes(when))
        except Exception as exc:   # NotPublished included: a missing index
                                   # file is a fact, not an outage
            logger.info("nse_index_unavailable", date=when.isoformat(), error=repr(exc))
            return False
        if parsed is None:
            return False
        index_date, close = parsed
        stmt = pg_insert(BtIndexClose).values(
            index_name=config.NIFTY_NAME, date=index_date, close=close)
        await self._session.execute(stmt.on_conflict_do_update(
            constraint="uq_bt_index_closes_name_date",
            set_={"close": stmt.excluded.close}))
        return True

    async def _record_day(self, when: date, status: str, rows: int, symbols: int,
                          error: str | None, now: datetime) -> None:
        stmt = pg_insert(BtIngestDay).values(
            date=when, status=status, rows=rows, symbols=symbols,
            failures=1 if status == FAILED else 0, last_error=error, ingested_at=now)
        await self._session.execute(stmt.on_conflict_do_update(
            constraint="uq_bt_ingest_days_date",
            set_={"status": stmt.excluded.status, "rows": stmt.excluded.rows,
                  "symbols": stmt.excluded.symbols, "last_error": stmt.excluded.last_error,
                  "failures": BtIngestDay.failures + (1 if status == FAILED else 0),
                  "ingested_at": now}))

    # --- the resumable backfill ---------------------------------------------

    async def pending_days(self, limit: int) -> list[date]:
        """Trading days not yet settled, newest first.

        Resumption is derived, not stored: a day is pending when
        `bt_ingest_days` has no `ok`/`missing` row for it and it has not failed
        `MAX_DAY_FAILURES` times. Killing the job mid-backfill costs the
        current day and nothing else.
        """
        today = datetime.now(UTC).date()
        candidates = trading_days(today - timedelta(days=config.BACKFILL_DAYS), today)
        settled = {d for (d,) in (await self._session.execute(
            select(BtIngestDay.date).where(
                BtIngestDay.status.in_((OK, MISSING))))).all()}
        exhausted = {d for (d,) in (await self._session.execute(
            select(BtIngestDay.date).where(
                BtIngestDay.failures >= config.MAX_DAY_FAILURES))).all()}
        return [d for d in candidates
                if d not in settled and d not in exhausted][:limit]

    async def backfill(self, *, limit: int = config.BACKFILL_DAYS_PER_RUN,
                       now: datetime | None = None) -> dict[str, Any]:
        now = now or datetime.now(UTC)
        started = now
        days = await self.pending_days(limit)
        done: list[dict[str, Any]] = []
        # A wall-clock stop, not just a day count. See BACKFILL_DEADLINE_SECONDS:
        # overrunning Celery's soft limit does not merely truncate the pass, it
        # loses everything the pass had already fetched.
        deadline = time.monotonic() + config.BACKFILL_DEADLINE_SECONDS
        stopped_early = False
        for when in days:
            if time.monotonic() >= deadline:
                stopped_early = True
                logger.info("nse_backfill_deadline", done=len(done),
                            planned=len(days))
                break
            done.append(await self.day(when, now=now))
        ok = [d for d in done if d["status"] == OK]
        self._session.add(BtRun(
            phase="backfill", started_at=started, finished_at=datetime.now(UTC),
            days=len(done), rows=sum(d.get("rows", 0) for d in ok),
            symbols=max((d.get("symbols", 0) for d in ok), default=0),
            detail={"ok": len(ok),
                    "missing": sum(1 for d in done if d["status"] == MISSING),
                    "failed": sum(1 for d in done if d["status"] == FAILED),
                    "requests": self._archive.requests,
                    "stopped_early": stopped_early},
            errors=[d["error"] for d in done if d.get("error")] or None))
        remaining = len(await self.pending_days(10_000))
        return {"phase": "backfill", "days": len(done), "ok": len(ok),
                "rows": sum(d.get("rows", 0) for d in ok),
                "remaining_days": remaining, "requests": self._archive.requests,
                "stopped_early": stopped_early}

    # --- the universe --------------------------------------------------------

    async def rebuild_universe(self, *, now: datetime | None = None) -> dict[str, Any]:
        """Re-derive membership from what is actually stored.

        Runs off `bt_candles`, not off a fresh download: the filters are about
        20 days of turnover, so the answer lives in the database the ingest has
        already built. A name that stops qualifying is marked inactive with a
        reason, never deleted.
        """
        now = now or datetime.now(UTC)
        started = now
        latest = await self._session.scalar(select(func.max(BtCandle.date)))
        if latest is None:
            return {"phase": "universe", "skipped": "no candles yet"}

        window_start = latest - timedelta(days=config.TURNOVER_WINDOW_DAYS * 2)
        rows = (await self._session.execute(
            select(BtCandle.symbol, BtCandle.date, BtCandle.close, BtCandle.turnover)
            .where(BtCandle.date >= window_start)
            .order_by(BtCandle.symbol, BtCandle.date))).all()

        by_symbol: dict[str, list[tuple[date, Decimal, Decimal | None]]] = {}
        for symbol, when, close, turnover in rows:
            by_symbol.setdefault(symbol, []).append((when, close, turnover))

        # Count AND span, over the whole table — not over the turnover window.
        # `first_seen` derived from the window would be the window's own start
        # date for every symbol, which reads like a listing date and is not one.
        spans = {s: (n, lo, hi) for s, n, lo, hi in (await self._session.execute(
            select(BtCandle.symbol, func.count(), func.min(BtCandle.date),
                   func.max(BtCandle.date)).group_by(BtCandle.symbol))).all()}
        meta = {s: (n, i, ser) for s, n, i, ser in (await self._session.execute(
            select(BtUniverseMember.symbol, BtUniverseMember.name,
                   BtUniverseMember.isin, BtUniverseMember.series))).all()}

        active = inactive = 0
        for symbol, series_rows in by_symbol.items():
            recent = series_rows[-config.TURNOVER_WINDOW_DAYS:]
            last_close = recent[-1][1]
            turnover = median_turnover([t for _, _, t in recent])
            name, isin, stored_series = meta.get(symbol, (None, None, "EQ"))
            reason = None
            if recent[-1][0] < latest:
                reason = "absent"          # did not trade on the latest day
            elif isin and not isin.startswith(config.ALLOWED_ISIN_PREFIX):
                # An ETF. Its "resistance" is the index's, its volume is the
                # market maker's, and a breakout in it is not a fact about a
                # company — so it is not what this tracker is for.
                reason = "etf"
            elif float(last_close) < config.MIN_PRICE_INR:
                reason = "price"
            elif turnover is None or float(turnover) < config.MIN_TURNOVER_INR:
                reason = "turnover"
            is_active = reason is None
            active += int(is_active)
            inactive += int(not is_active)

            count, first_bar, last_bar = spans.get(
                symbol, (0, series_rows[0][0], recent[-1][0]))
            stmt = pg_insert(BtUniverseMember).values(
                symbol=symbol, name=name, isin=isin, series=stored_series,
                last_close=last_close, turnover_20d=turnover, bars=int(count),
                first_seen=first_bar, last_seen=last_bar,
                active=is_active, inactive_reason=reason, updated_at=now)
            await self._session.execute(stmt.on_conflict_do_update(
                constraint="uq_bt_universe_symbol",
                set_={"last_close": stmt.excluded.last_close,
                      "turnover_20d": stmt.excluded.turnover_20d,
                      "bars": stmt.excluded.bars,
                      # Re-derived, not preserved: a backfill that reaches
                      # further back moves the real first bar earlier.
                      "first_seen": stmt.excluded.first_seen,
                      "last_seen": stmt.excluded.last_seen,
                      "active": stmt.excluded.active,
                      "inactive_reason": stmt.excluded.inactive_reason,
                      "updated_at": now}))

        self._session.add(BtRun(
            phase="universe", started_at=started, finished_at=datetime.now(UTC),
            symbols=active, detail={"active": active, "inactive": inactive,
                                    "as_of": latest.isoformat()}))
        logger.info("nse_universe_rebuilt", active=active, inactive=inactive,
                    as_of=latest.isoformat())
        return {"phase": "universe", "active": active, "inactive": inactive,
                "as_of": latest.isoformat()}

    # --- corporate actions ---------------------------------------------------

    async def flag_suspect_gaps(self) -> int:
        """Mark overnight gaps wider than `SPLIT_GAP_PCT`.

        Bhavcopy is unadjusted and the brief's corroboration source (yfinance)
        is unreachable from here, so this FLAGS rather than corrects. Silently
        rewriting a price with nothing to check it against invents data; a
        flagged bar stays visible in the health route and can be excluded by
        anything that cares.
        """
        previous = func.lag(BtCandle.close).over(
            partition_by=BtCandle.symbol, order_by=BtCandle.date)
        ranked = select(
            BtCandle.id.label("id"), BtCandle.close.label("close"),
            previous.label("prev")).subquery()
        gapped = select(ranked.c.id).where(
            ranked.c.prev.is_not(None), ranked.c.prev > 0,
            func.abs(ranked.c.close - ranked.c.prev) / ranked.c.prev
            > config.SPLIT_GAP_PCT / 100)
        result = await self._session.execute(
            update(BtCandle).where(BtCandle.id.in_(gapped),
                                   BtCandle.suspect_gap.is_(False))
            .values(suspect_gap=True))
        return result.rowcount or 0

    async def prune_runs(self, keep: int = 500) -> None:
        newest = select(BtRun.id).order_by(BtRun.started_at.desc()).limit(keep)
        await self._session.execute(delete(BtRun).where(BtRun.id.not_in(newest)))
