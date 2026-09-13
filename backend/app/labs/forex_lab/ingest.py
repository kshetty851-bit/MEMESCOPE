"""Phase 1: download Dukascopy EUR/USD ticks, aggregate, store.

Idempotent and resumable, in that order:

* **idempotent** because `fx_candles` is keyed on (symbol, minute) and every
  write is an upsert — running the same hour twice produces the same table;
* **resumable** because `fx_ingest_hours` gets a row per hour-file the moment
  its candles commit, and the planner asks the database which hours are
  missing rather than assuming a contiguous cursor. A pass that loses a sixth
  of its requests to the CDN costs a second pass, not a restart.

The CDN is the reason this is not a simple loop. `datafeed.dukascopy.com`
answers a meaningful share of requests with a 503 from whichever edge node
takes them, and — measured over 512 real hour-files — also with a *transient*
404 whose body is 3,464 bytes of styled HTML, as against the 162-byte body of
a genuine one. Neither is a reason to record a hole, so both are retried, and
only the 162-byte kind is ever believed.

The dominant failure, though, is neither: it is **429**. Dukascopy meters this
feed, and over a job this size the meter is reached constantly. A 429 is not a
fact about one request — it is the server asking the whole client to slow down
— so it is handled with a shared cooldown rather than a per-request backoff.
The first coroutine to see one closes a gate that every other coroutine waits
at, and re-opens it after `Retry-After` (or a default) has passed. Backing off
one request at a time would leave the other 95 hammering through the penalty
window, which is exactly how a rate limit becomes a permanent failure instead
of a pause.

The throttle is CUMULATIVE, which is the part that catches you out. The first
several thousand files come down at 1.5–2.5/s and then the feed starts
answering everything with 503 — measured: 64 consecutive 503s after ~7,900
files, and full recovery after two minutes of silence.

The instinct is to slow down and wait it out. Measured, that is the wrong
trade: at concurrency 24 with a gate that fired on every wall, 120 of 162
elapsed seconds were spent waiting and the rate fell to 0.62 files/s — against
1.55 for a fast pass that simply let 5% of its requests fail. **A failed hour
is one row, and the next pass asks for exactly those rows.** Three passes at
5% leave 1 hour in 8,000, and cost a quarter of the wall clock that patience
does. So the gate now fires only on a genuine wall — forty consecutive 503s,
which cannot be noise with 64 requests in flight — and `passes` runs the whole
thing again until nothing is outstanding.
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.labs.forex_lab import config
from app.labs.forex_lab.market import open_hours
from app.labs.forex_lab.models import FxCandle, FxIngestHour
from app.labs.forex_lab.ticks import TickDecodeError, decode_hour, hour_url, to_minute_candles

#: A genuine "this hour does not exist" page. The transient one is ~3.4 kB.
_GENUINE_404_MAX_BYTES = 512
#: How long everybody waits when the feed says 429 and offers no `Retry-After`.
_COOLDOWN_SECONDS = 30.0
_COOLDOWN_MAX = 180.0
#: A 503 is an overloaded edge node, which one retry usually gets past — but a
#: WALL of them is the cumulative throttle, and then everyone has to stop.
#: Two minutes is what the feed was measured to need to come back.
_COOLDOWN_503_SECONDS = 120.0
#: Consecutive 503s, across all coroutines, before the gate treats it as the
#: throttle rather than as bad luck. With 64 requests in flight, forty in a row
#: cannot be noise — and anything lower makes the gate fire on ordinary
#: turbulence, which measured SLOWER than not having a gate at all.
_503_WALL = 40


class _Gate:
    """Open by default; a 429 shuts it for everyone.

    Deliberately not a token bucket. The rate this feed will tolerate is not
    published and moves about, so a fixed budget would be either wasteful or
    wrong. Reacting to the server's own answer needs no guess.
    """

    def __init__(self) -> None:
        self._open = asyncio.Event()
        self._open.set()
        self._closing = False
        self.cooldowns = 0
        self.seconds_waiting = 0.0
        self.consecutive_503 = 0

    async def wait(self) -> None:
        await self._open.wait()

    async def shut(self, seconds: float) -> None:
        if self._closing:  # somebody else is already serving the penalty
            await self._open.wait()
            return
        self._closing = True
        self._open.clear()
        seconds = min(max(seconds, 1.0), _COOLDOWN_MAX)
        self.cooldowns += 1
        self.seconds_waiting += seconds
        try:
            await asyncio.sleep(seconds)
        finally:
            self._open.set()
            self._closing = False


def _retry_after(r: httpx.Response) -> float:
    raw = r.headers.get("Retry-After", "")
    try:
        return float(raw)
    except ValueError:
        return _COOLDOWN_SECONDS


def iter_hours(start: datetime, end: datetime) -> Iterator[datetime]:
    """Every OPEN hour in [start, end).

    Asking for the ~50 dead hours of every weekend would add 15,000 requests to
    a job that is already feed-bound, and each would come back as a genuine 404.
    The definition of "dead" lives in `market.py` and is expressed in New York
    time, because the boundary is 17:00 there — 21:00 UTC in summer, not 22:00.
    """
    yield from open_hours(start, end)


async def _fetch(client: httpx.AsyncClient, url: str, gate: _Gate) -> bytes | None:
    """The hour's bytes, or None for an hour the feed genuinely does not have.

    Raises on exhausted retries, so the caller records a failure rather than a
    hole.
    """
    last = "no attempt"
    for attempt in range(config.INGEST_RETRIES):
        await gate.wait()
        try:
            r = await client.get(url, timeout=config.INGEST_TIMEOUT_SECONDS)
        except httpx.HTTPError as exc:
            last = f"{type(exc).__name__}: {exc}"
        else:
            if r.status_code == 200:
                gate.consecutive_503 = 0
                return r.content
            if r.status_code == 404 and len(r.content) <= _GENUINE_404_MAX_BYTES:
                return None
            last = f"HTTP {r.status_code} ({len(r.content)}B)"
            if r.status_code == 429:
                # Everybody stops, not just this coroutine. A 429 retried
                # individually is a 429 again, 95 times over.
                gate.consecutive_503 = 0
                await gate.shut(_retry_after(r))
                continue
            if r.status_code == 503:
                gate.consecutive_503 += 1
                if gate.consecutive_503 >= _503_WALL:
                    gate.consecutive_503 = 0
                    await gate.shut(_COOLDOWN_503_SECONDS)
                    continue
        # Jittered backoff: a fleet of coroutines that all retry on the same
        # schedule just rebuilds the burst that drew the 503.
        await asyncio.sleep(min(20.0, 1.5 * (attempt + 1)) * (0.5 + random.random()))
    raise RuntimeError(last)


async def _missing_hours(session: AsyncSession, symbol: str, hours: list[datetime]) -> list[datetime]:
    done = set(
        (await session.execute(
            select(FxIngestHour.hour_start).where(
                FxIngestHour.symbol == symbol, FxIngestHour.ok.is_(True)
            )
        )).scalars()
    )
    # Postgres hands back tz-aware datetimes; normalise both sides.
    done = {d.astimezone(UTC) for d in done}
    return [h for h in hours if h not in done]


async def _store(session: AsyncSession, symbol: str, hour: datetime, raw: bytes | None) -> dict:
    """Decode, aggregate and upsert one hour. Commits."""
    if raw is None:
        session.add(FxIngestHour(
            symbol=symbol, hour_start=hour, ok=True, empty=True,
            tick_count=0, candle_count=0, error=None, fetched_at=datetime.now(UTC),
        ))
        await session.commit()
        return {"ticks": 0, "candles": 0, "empty": True}

    ticks = decode_hour(raw, hour)
    candles = to_minute_candles(ticks)
    if candles:
        await session.execute(
            pg_insert(FxCandle)
            .values([{
                "symbol": symbol, "minute": c.minute,
                "bid_open": c.bid_open, "bid_high": c.bid_high,
                "bid_low": c.bid_low, "bid_close": c.bid_close,
                "ask_open": c.ask_open, "ask_high": c.ask_high,
                "ask_low": c.ask_low, "ask_close": c.ask_close,
                "ticks": c.ticks,
            } for c in candles])
            .on_conflict_do_nothing(index_elements=["symbol", "minute"])
        )
    await session.execute(
        pg_insert(FxIngestHour)
        .values(symbol=symbol, hour_start=hour, ok=True, empty=not candles,
                tick_count=len(ticks), candle_count=len(candles), error=None,
                fetched_at=datetime.now(UTC))
        .on_conflict_do_update(
            index_elements=["symbol", "hour_start"],
            set_={"ok": True, "empty": not candles, "tick_count": len(ticks),
                  "candle_count": len(candles), "error": None,
                  "fetched_at": datetime.now(UTC)},
        )
    )
    await session.commit()
    return {"ticks": len(ticks), "candles": len(candles), "empty": not candles}


async def _record_failure(session_factory, symbol: str, hour: datetime, error: str) -> None:
    async with session_factory() as session:
        await session.execute(
            pg_insert(FxIngestHour)
            .values(symbol=symbol, hour_start=hour, ok=False, empty=False,
                    tick_count=0, candle_count=0, error=error[:256],
                    fetched_at=datetime.now(UTC))
            .on_conflict_do_update(
                index_elements=["symbol", "hour_start"],
                set_={"ok": False, "error": error[:256],
                      "fetched_at": datetime.now(UTC)},
            )
        )
        await session.commit()


async def ingest_until_clean(
    session_factory,
    symbol: str = config.SYMBOL,
    start: datetime | None = None,
    end: datetime | None = None,
    concurrency: int | None = None,
    passes: int = 8,
    pause_between: float = 60.0,
    progress_every: int = 250,
    on_progress=None,
    on_pass=None,
) -> dict:
    """Pass after pass until nothing is outstanding, or `passes` is reached.

    Stops early on a pass that loads nothing new — that is the feed refusing
    rather than the job finishing, and another identical pass will not help.
    The pause between passes is not politeness; it is the two minutes the feed
    was measured to need before it starts answering again.
    """
    history = []
    for i in range(passes):
        stats = await ingest(session_factory, symbol, start, end, concurrency,
                             progress_every, on_progress)
        history.append(stats)
        if on_pass:
            on_pass(i + 1, stats)
        if stats["todo"] == 0 or stats["failed"] == 0:
            break
        if stats["ok"] == 0:
            break
        if i + 1 < passes:
            await asyncio.sleep(pause_between)
    return {"passes": len(history), "history": history,
            "outstanding": history[-1]["failed"] if history else 0}


async def ingest(
    session_factory,
    symbol: str = config.SYMBOL,
    start: datetime | None = None,
    end: datetime | None = None,
    concurrency: int | None = None,
    progress_every: int = 250,
    on_progress=None,
) -> dict:
    """One pass over every hour not already recorded `ok`. Returns a summary."""
    start = start or datetime(config.START.year, config.START.month, config.START.day, tzinfo=UTC)
    end = end or datetime(config.END.year, config.END.month, config.END.day, tzinfo=UTC) + timedelta(days=1)
    conc = concurrency or config.INGEST_CONCURRENCY

    all_hours = list(iter_hours(start, end))
    async with session_factory() as session:
        todo = await _missing_hours(session, symbol, all_hours)

    stats = {"planned": len(all_hours), "todo": len(todo), "ok": 0, "empty": 0,
             "failed": 0, "ticks": 0, "candles": 0, "cooldowns": 0,
             "cooldown_seconds": 0.0}
    if not todo:
        return stats

    sem = asyncio.Semaphore(conc)
    gate = _Gate()
    limits = httpx.Limits(max_connections=conc, max_keepalive_connections=conc)
    lock = asyncio.Lock()

    async with httpx.AsyncClient(limits=limits, headers={"User-Agent": "Mozilla/5.0"}) as client:
        async def one(hour: datetime) -> None:
            async with sem:
                try:
                    raw = await _fetch(client, hour_url(symbol, hour), gate)
                except Exception as exc:  # exhausted retries
                    await _record_failure(session_factory, symbol, hour, f"{type(exc).__name__}: {exc}")
                    async with lock:
                        stats["failed"] += 1
                    return
                try:
                    async with session_factory() as session:
                        r = await _store(session, symbol, hour, raw)
                except (TickDecodeError, Exception) as exc:
                    await _record_failure(session_factory, symbol, hour, f"{type(exc).__name__}: {exc}")
                    async with lock:
                        stats["failed"] += 1
                    return
            async with lock:
                stats["ok"] += 1
                stats["empty"] += int(r["empty"])
                stats["ticks"] += r["ticks"]
                stats["candles"] += r["candles"]
                stats["cooldowns"] = gate.cooldowns
                stats["cooldown_seconds"] = round(gate.seconds_waiting, 1)
                n = stats["ok"] + stats["failed"]
                if on_progress and n % progress_every == 0:
                    on_progress(dict(stats))

        await asyncio.gather(*(one(h) for h in todo))
    stats["cooldowns"] = gate.cooldowns
    stats["cooldown_seconds"] = round(gate.seconds_waiting, 1)
    return stats


# --- verification against the feed's own candles ------------------------------


async def verify_against_published(
    session_factory,
    symbol: str = config.SYMBOL,
    days: int = 20,
    tolerance: float = 1e-5,
    seed: int = 20260913,
) -> dict:
    """Compare stored candles against Dukascopy's OWN 1-minute candles.

    The dataset is built by aggregating ticks in `ticks.py`. That aggregator is
    unit-tested against hand-written tick lists, which proves it agrees with my
    arithmetic — this proves it agrees with the vendor's, over the same ticks,
    on real days chosen at random from what is actually loaded.

    Sampled rather than exhaustive: it costs two requests a day against a feed
    that is already the job's bottleneck, and a systematic aggregation error
    would show up on the first day, not the two-hundredth. The seed is fixed so
    a rerun checks the same days and a difference is a real change.
    """
    from app.labs.forex_lab.models import FxCandle
    from app.labs.forex_lab.ticks import decode_day_candles, day_candles_url

    rng = random.Random(seed)
    async with session_factory() as session:
        loaded = sorted({
            r[0].date() for r in (await session.execute(
                select(FxIngestHour.hour_start).where(
                    FxIngestHour.symbol == symbol,
                    FxIngestHour.ok.is_(True),
                    FxIngestHour.empty.is_(False),
                )
            )).all()
        })
    if not loaded:
        return {"checked_days": 0, "compared": 0, "differences": 0,
                "passed": False, "reason": "nothing loaded"}

    # Only days whose every trading hour is loaded; a half-loaded day would
    # report every missing minute as a difference.
    sample = rng.sample(loaded, min(days, len(loaded)))
    compared = differences = 0
    worst: list[dict] = []
    checked: list[str] = []

    async with httpx.AsyncClient(headers={"User-Agent": "Mozilla/5.0"}) as client:
        gate = _Gate()
        for d in sample:
            day = datetime(d.year, d.month, d.day, tzinfo=UTC)
            try:
                bid_raw = await _fetch(client, day_candles_url(symbol, day, "BID"), gate)
                ask_raw = await _fetch(client, day_candles_url(symbol, day, "ASK"), gate)
            except Exception as exc:
                worst.append({"day": d.isoformat(), "error": f"{type(exc).__name__}: {exc}"})
                continue
            if bid_raw is None or ask_raw is None:
                continue
            theirs_bid = decode_day_candles(bid_raw, day)
            theirs_ask = decode_day_candles(ask_raw, day)

            async with session_factory() as session:
                rows = (await session.execute(
                    select(FxCandle).where(
                        FxCandle.symbol == symbol,
                        FxCandle.minute >= day,
                        FxCandle.minute < day + timedelta(days=1),
                    )
                )).scalars().all()
            if not rows:
                continue
            checked.append(d.isoformat())
            for row in rows:
                m = row.minute.astimezone(UTC).replace(tzinfo=UTC)
                for side, theirs in (("bid", theirs_bid), ("ask", theirs_ask)):
                    t = theirs.get(m)
                    if t is None:
                        continue
                    ours = (float(getattr(row, f"{side}_open")),
                            float(getattr(row, f"{side}_high")),
                            float(getattr(row, f"{side}_low")),
                            float(getattr(row, f"{side}_close")))
                    compared += 1
                    if max(abs(a - b) for a, b in zip(ours, t)) > tolerance:
                        differences += 1
                        if len(worst) < 10:
                            worst.append({"minute": m.isoformat(), "side": side,
                                          "ours": ours, "theirs": t})
    return {
        "checked_days": len(checked), "days": checked,
        "compared": compared, "differences": differences,
        "passed": compared > 0 and differences == 0,
        "sample": worst,
    }
