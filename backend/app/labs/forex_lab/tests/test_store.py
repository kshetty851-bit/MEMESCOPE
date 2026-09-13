"""The loader's idempotence and the integrity check, against a real Postgres.

The engine tests prove the strategy; these prove the dataset it will be fed —
which is the other half of a backtest anyone should believe.
"""

from __future__ import annotations

import lzma
import struct
from datetime import UTC, datetime, timedelta

import pytest

from app.labs.forex_lab import store
from app.labs.forex_lab.ingest import _store, iter_hours
from app.labs.forex_lab.models import FxCandle, FxIngestHour

# `asyncio_mode = "auto"` in pyproject.toml already runs the coroutines here; a
# module-level mark would also be applied to the two synchronous tests below
# and warn on each.


def bi5(hour: datetime, n_minutes: int, first_ms: int = 500) -> bytes:
    """A synthetic hour-file: one tick a second for `n_minutes` minutes."""
    recs = []
    for m in range(n_minutes):
        for s in range(0, 60, 10):
            ms = first_ms + (m * 60 + s) * 1000
            px = 105600 + m * 10 + s
            recs.append(struct.pack(">3I2f", ms, px + 5, px, 1.0, 1.0))
    return lzma.compress(b"".join(recs), format=lzma.FORMAT_ALONE)


HOUR = datetime(2023, 1, 3, 14, 0, tzinfo=UTC)


# --- the loader ---------------------------------------------------------------


async def test_storing_the_same_hour_twice_changes_nothing(session):
    raw = bi5(HOUR, 60)
    first = await _store(session, "EURUSD", HOUR, raw)
    assert first == {"ticks": 6 * 60, "candles": 60, "empty": False}

    before = (await session.execute(
        store.select(store.func.count()).select_from(FxCandle))).scalar_one()
    second = await _store(session, "EURUSD", HOUR, raw)
    after = (await session.execute(
        store.select(store.func.count()).select_from(FxCandle))).scalar_one()

    assert second == first
    assert before == after == 60
    rows = (await session.execute(store.select(FxIngestHour))).scalars().all()
    assert len(rows) == 1 and rows[0].ok and rows[0].candle_count == 60


async def test_an_hour_the_feed_does_not_have_is_recorded_not_retried(session):
    r = await _store(session, "EURUSD", HOUR, None)
    assert r["empty"] is True
    (row,) = (await session.execute(store.select(FxIngestHour))).scalars().all()
    assert row.ok and row.empty and row.candle_count == 0


async def test_the_resume_query_asks_only_for_what_is_missing(session):
    from app.labs.forex_lab.ingest import _missing_hours

    hours = [HOUR + timedelta(hours=i) for i in range(4)]
    await _store(session, "EURUSD", hours[0], bi5(hours[0], 5))
    await _store(session, "EURUSD", hours[2], None)
    session.add(FxIngestHour(symbol="EURUSD", hour_start=hours[3], ok=False,
                             empty=False, tick_count=0, candle_count=0,
                             error="HTTP 503", fetched_at=datetime.now(UTC)))
    await session.commit()

    missing = await _missing_hours(session, "EURUSD", hours)
    # Loaded and genuinely-empty hours are done; the failed one comes back.
    assert missing == [hours[1], hours[3]]


def test_the_planner_skips_the_hours_the_market_is_shut():
    """Saturday, Friday after 22:00 UTC and Sunday before 22:00 UTC. Asking for
    them would add ~15,000 requests to a CDN-bound job, each a 404."""
    start = datetime(2023, 1, 6, 20, 0, tzinfo=UTC)  # Friday
    hours = list(iter_hours(start, start + timedelta(days=3)))
    assert datetime(2023, 1, 6, 21, 0, tzinfo=UTC) in hours     # Friday 21:00
    assert datetime(2023, 1, 6, 22, 0, tzinfo=UTC) not in hours  # after close
    assert not any(h.weekday() == 5 for h in hours)              # no Saturday
    assert datetime(2023, 1, 8, 21, 0, tzinfo=UTC) not in hours  # before open
    assert datetime(2023, 1, 8, 22, 0, tzinfo=UTC) in hours      # Sunday open


# --- the integrity check ------------------------------------------------------


async def _fill_minutes(session, start: datetime, n: int, spread: float = 0.00005,
                        skip: set[int] | None = None):
    skip = skip or set()
    for i in range(n):
        if i in skip:
            continue
        m = start + timedelta(minutes=i)
        bid = 1.0500 + i * 1e-5
        session.add(FxCandle(
            symbol="EURUSD", minute=m,
            bid_open=bid, bid_high=bid, bid_low=bid, bid_close=bid,
            ask_open=bid + spread, ask_high=bid + spread,
            ask_low=bid + spread, ask_close=bid + spread, ticks=6))
    await session.commit()


async def test_a_gap_over_an_hour_outside_a_weekend_is_reported(session):
    start = datetime(2023, 1, 3, 0, 0, tzinfo=UTC)  # Tuesday
    await _fill_minutes(session, start, 30)
    await _fill_minutes(session, start + timedelta(minutes=150), 30)

    r = await store.integrity_check(session)
    assert r["gaps_total"] == 1
    assert r["gaps_unexplained"] == 1
    assert r["gaps_worst"][0]["minutes"] == 121
    assert r["passed"] is False


async def test_the_weekend_is_not_a_gap(session):
    """Friday 21:59 UTC to Sunday 22:00 UTC is the market being shut, not the
    loader dropping something."""
    await _fill_minutes(session, datetime(2023, 1, 6, 21, 30, tzinfo=UTC), 30)
    await _fill_minutes(session, datetime(2023, 1, 8, 22, 0, tzinfo=UTC), 30)
    r = await store.integrity_check(session)
    assert r["gaps_total"] == 0


async def test_a_christmas_gap_is_reported_but_explained(session):
    await _fill_minutes(session, datetime(2023, 12, 25, 0, 0, tzinfo=UTC), 10)
    await _fill_minutes(session, datetime(2023, 12, 25, 20, 0, tzinfo=UTC), 10)
    r = await store.integrity_check(session)
    assert r["gaps_total"] == 1
    assert r["gaps_unexplained"] == 0
    assert r["gaps_holiday_sample"][0]["holiday"] == "Christmas Day"


async def test_a_crossed_quote_fails_the_check(session):
    start = datetime(2023, 1, 3, 0, 0, tzinfo=UTC)
    await _fill_minutes(session, start, 10)
    session.add(FxCandle(
        symbol="EURUSD", minute=start + timedelta(minutes=10),
        bid_open=1.06, bid_high=1.06, bid_low=1.06, bid_close=1.06,
        ask_open=1.05, ask_high=1.05, ask_low=1.05, ask_close=1.05, ticks=1))
    await session.commit()

    r = await store.integrity_check(session)
    assert r["crossed_quotes"] == 1
    assert r["passed"] is False


async def test_a_failed_hour_still_outstanding_fails_the_check(session):
    """A pass that lost requests to the CDN must not be able to produce a green
    integrity check just because the minutes it did get look tidy."""
    await _fill_minutes(session, datetime(2023, 1, 3, 0, 0, tzinfo=UTC), 10)
    session.add(FxIngestHour(symbol="EURUSD", hour_start=HOUR, ok=False,
                             empty=False, tick_count=0, candle_count=0,
                             error="HTTP 503", fetched_at=datetime.now(UTC)))
    await session.commit()
    r = await store.integrity_check(session)
    assert r["hours_failed"] == 1
    assert r["passed"] is False


def test_expected_minutes_counts_the_window_not_an_average_week():
    """2026 stops on 30 June, and 2020 and 2024 have a 29 February in them."""
    from app.labs.forex_lab.store import _expected_minutes

    assert _expected_minutes(2021) > _expected_minutes(2026)
    assert _expected_minutes(2020) > _expected_minutes(2021)  # leap year
    # A full year is ~5 days x 24 h x 52 weeks of open market, less holidays.
    assert 340_000 < _expected_minutes(2021) < 380_000


async def test_iter_candles_pages_without_dropping_or_repeating_a_row(session):
    """The chunked cursor is inclusive on the first page and exclusive after —
    an off-by-one either way silently loses or duplicates a minute."""
    start = datetime(2023, 1, 3, 0, 0, tzinfo=UTC)
    await _fill_minutes(session, start, 25)
    got = [r[0] async for r in store.iter_candles(session, chunk=7)]
    assert len(got) == 25
    assert len(set(got)) == 25
    assert got == sorted(got)


# --- the rate limiter ---------------------------------------------------------


async def test_a_429_stops_every_coroutine_not_just_the_one_that_saw_it():
    """A 429 is the server asking the CLIENT to slow down. Backed off one
    request at a time it is a 429 again, ninety-five times over — which is how
    a rate limit turns into a permanent failure instead of a pause.
    """
    import asyncio

    from app.labs.forex_lab.ingest import _Gate

    gate = _Gate()
    order: list[str] = []

    async def worker(name: str) -> None:
        await gate.wait()
        order.append(name)

    shut = asyncio.create_task(gate.shut(0.15))
    await asyncio.sleep(0)  # let the gate actually close
    waiters = [asyncio.create_task(worker(f"w{i}")) for i in range(5)]
    await asyncio.sleep(0.05)
    assert order == [], "nobody passes while the gate is shut"
    await shut
    await asyncio.gather(*waiters)
    assert len(order) == 5
    assert gate.cooldowns == 1


async def test_a_second_429_during_a_cooldown_does_not_extend_it():
    """Ninety-six coroutines will all see the 429. Serving the penalty once per
    coroutine would turn a 30-second pause into a 48-minute one."""
    import asyncio

    from app.labs.forex_lab.ingest import _Gate

    gate = _Gate()
    await asyncio.gather(*(gate.shut(0.05) for _ in range(10)))
    assert gate.cooldowns == 1
    assert gate.seconds_waiting == pytest.approx(1.0)  # clamped to the floor


def test_retry_after_is_honoured_when_the_feed_sends_one():
    import httpx

    from app.labs.forex_lab.ingest import _COOLDOWN_SECONDS, _retry_after

    assert _retry_after(httpx.Response(429, headers={"Retry-After": "12"})) == 12.0
    # GeckoTerminal-style nonsense and a missing header both fall back.
    assert _retry_after(httpx.Response(429, headers={"Retry-After": "soon"})) == _COOLDOWN_SECONDS
    assert _retry_after(httpx.Response(429)) == _COOLDOWN_SECONDS


async def test_passes_repeat_until_nothing_is_outstanding(session_factory, session):
    """A pass that loses 5% to the throttle is not a failed pass — it is a pass
    whose leftovers the next one asks for. What must NOT happen is an eighth
    identical pass against a feed that has stopped answering."""
    from app.labs.forex_lab import ingest as ing

    calls: list[int] = []
    outcomes = [
        {"planned": 10, "todo": 10, "ok": 8, "empty": 0, "failed": 2,
         "ticks": 0, "candles": 0},
        {"planned": 10, "todo": 2, "ok": 2, "empty": 0, "failed": 0,
         "ticks": 0, "candles": 0},
    ]

    async def fake_ingest(*a, **kw):
        calls.append(1)
        return outcomes[len(calls) - 1]

    monkey = ing.ingest
    ing.ingest = fake_ingest
    try:
        r = await ing.ingest_until_clean(session_factory, passes=8, pause_between=0)
    finally:
        ing.ingest = monkey
    assert r["passes"] == 2, "stops as soon as a pass has no failures"
    assert r["outstanding"] == 0


async def test_a_pass_that_loads_nothing_stops_the_loop(session_factory):
    """Zero loaded is the feed refusing, not the job finishing. Another
    identical pass will not help and would burn the remaining seven."""
    from app.labs.forex_lab import ingest as ing

    calls: list[int] = []

    async def fake_ingest(*a, **kw):
        calls.append(1)
        return {"planned": 10, "todo": 10, "ok": 0, "empty": 0, "failed": 10,
                "ticks": 0, "candles": 0}

    monkey = ing.ingest
    ing.ingest = fake_ingest
    try:
        r = await ing.ingest_until_clean(session_factory, passes=8, pause_between=0)
    finally:
        ing.ingest = monkey
    assert len(calls) == 1
    assert r["outstanding"] == 10
