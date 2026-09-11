"""Parsing, the forming-bar cut, backward paging, upsert idempotency,
failure counting, and the budget's carry."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.labs.breakout import config
from app.labs.breakout.candles import (
    BreakoutCandles,
    due_timeframes,
    find_gaps,
    interval,
    last_closed_open,
    parse_ohlcv,
)
from app.labs.breakout.models import BoCandle, BoUniverseMember
from app.labs.breakout.tests.fakes import NOW, FakeSource, ohlcv


def member(mint="M1", pool="P1", volume=900_000) -> BoUniverseMember:
    return BoUniverseMember(
        mint=mint, symbol="AAA", name="Token A", pool_address=pool, dex="raydium",
        pair_created_at=NOW - timedelta(days=90), liquidity_usd=Decimal("250000"),
        volume_24h_usd=Decimal(volume), price_usd=Decimal("0.04"),
        fdv=Decimal("1000000"), source="geckoterminal", first_seen=NOW, last_seen=NOW,
        active=True, fetch_failures=0,
    )


# --- pure ---------------------------------------------------------------------

def test_last_closed_open_is_one_interval_before_the_forming_bar() -> None:
    now = datetime(2026, 9, 11, 2, 20, tzinfo=UTC)
    assert last_closed_open("hour", now) == datetime(2026, 9, 11, 1, 0, tzinfo=UTC)
    assert last_closed_open("day", now) == datetime(2026, 9, 10, 0, 0, tzinfo=UTC)


def test_a_bar_exactly_on_its_close_counts_as_closed() -> None:
    on_the_hour = datetime(2026, 9, 11, 2, 0, 0, tzinfo=UTC)
    assert last_closed_open("hour", on_the_hour) == datetime(2026, 9, 11, 1, 0, tzinfo=UTC)


def test_the_forming_bar_is_dropped() -> None:
    """GeckoTerminal serves the bar currently forming as its FIRST row.
    Storing it would write a close that is still moving."""
    now = datetime(2026, 9, 11, 2, 20, tzinfo=UTC)
    rows = ohlcv("hour", bars=5, newest_open=datetime(2026, 9, 11, 2, 0, tzinfo=UTC))
    parsed = parse_ohlcv("M1", "P1", "hour", rows, now=now)
    assert len(parsed) == 4
    assert parsed[-1].open_time == datetime(2026, 9, 11, 1, 0, tzinfo=UTC)


def test_parsed_bars_come_back_oldest_first_with_a_close_one_interval_on() -> None:
    rows = ohlcv("hour", bars=4, newest_open=datetime(2026, 9, 11, 1, 0, tzinfo=UTC))
    parsed = parse_ohlcv("M1", "P1", "hour", rows, now=NOW)
    assert [c.open_time for c in parsed] == sorted(c.open_time for c in parsed)
    for candle in parsed:
        assert candle.close_time - candle.open_time == interval("hour")
        assert candle.low <= candle.open <= candle.high
        assert candle.low <= candle.close <= candle.high


def test_a_bar_with_a_junk_price_is_dropped_not_stored_as_zero() -> None:
    """A zero low would sit under every future support level for ever."""
    rows = ohlcv("hour", bars=3, newest_open=datetime(2026, 9, 11, 1, 0, tzinfo=UTC))
    rows[1][3] = None
    rows[2][1] = "NaN"
    parsed = parse_ohlcv("M1", "P1", "hour", rows, now=NOW)
    assert len(parsed) == 1


def test_a_short_or_unparseable_row_is_skipped() -> None:
    rows = [[1789084800], ["not a timestamp", 1, 2, 3, 4, 5]]
    assert parse_ohlcv("M1", "P1", "day", rows, now=NOW) == []


def test_find_gaps_reports_the_missing_range_not_the_stored_neighbours() -> None:
    step = interval("hour")
    base = datetime(2026, 9, 11, 0, 0, tzinfo=UTC)
    stored = [base, base + step, base + 4 * step]
    assert find_gaps(stored, step) == [(base + 2 * step, base + 3 * step)]
    assert find_gaps([base, base + step], step) == []
    assert find_gaps([], step) == []


def test_the_daily_bar_is_not_asked_for_in_the_first_minutes_after_midnight() -> None:
    """It closes at 00:00 UTC and GeckoTerminal needs a moment to publish it."""
    assert due_timeframes(datetime(2026, 9, 11, 0, 2, tzinfo=UTC)) == ("hour",)
    assert due_timeframes(datetime(2026, 9, 11, 0, 6, tzinfo=UTC)) == config.TIMEFRAMES
    assert due_timeframes(datetime(2026, 9, 11, 13, 0, tzinfo=UTC)) == config.TIMEFRAMES


# --- the sync -----------------------------------------------------------------

@pytest.mark.integration
async def test_a_first_sync_backfills_forward_then_pages_backward(lab_session) -> None:
    pool, newest = "P1", datetime(2026, 9, 11, 2, 0, tzinfo=UTC)
    source = FakeSource(ohlcv_by={(pool, "hour"): ohlcv("hour", bars=400,
                                                        newest_open=newest)})
    row = member(pool=pool)
    lab_session.add(row)
    await lab_session.flush()

    stored = await BreakoutCandles(lab_session, source).sync(row, "hour", NOW)
    # One forward page of 100 (minus the forming bar) plus
    # BACKFILL_PAGES_PER_TICK backward pages.
    assert len([c for c in source.calls if c[0] == "ohlcv"]) == (
        1 + config.BACKFILL_PAGES_PER_TICK)
    # 99 + 100 + 100 bars written, of which two are the bar each backward page
    # repeats because `before_timestamp` is inclusive. The upsert absorbs them,
    # so the ROW count is two below the write count — which is the whole point
    # of keying on (mint, timeframe, open_time).
    assert stored == 299
    count = await lab_session.scalar(select(func.count()).select_from(BoCandle))
    assert count == 297


@pytest.mark.integration
async def test_backward_paging_uses_before_timestamp_and_resumes_next_tick(
    lab_session,
) -> None:
    pool, newest = "P1", datetime(2026, 9, 11, 2, 0, tzinfo=UTC)
    source = FakeSource(ohlcv_by={(pool, "hour"): ohlcv("hour", bars=400,
                                                        newest_open=newest)})
    row = member(pool=pool)
    lab_session.add(row)
    await lab_session.flush()
    engine = BreakoutCandles(lab_session, source)

    await engine.sync(row, "hour", NOW)
    befores = [c[4] for c in source.calls if c[0] == "ohlcv"]
    assert befores[0] is None, "the forward page asks for the newest bars"
    assert all(b is not None for b in befores[1:])
    assert befores[1] > befores[2], "each page asks for bars older than the last"
    first_pass = await lab_session.scalar(select(func.count()).select_from(BoCandle))

    # A second tick continues where the page cap stopped it.
    source.calls.clear()
    await engine.sync(row, "hour", NOW)
    assert await lab_session.scalar(select(func.count()).select_from(BoCandle)) > first_pass


@pytest.mark.integration
async def test_backward_paging_stops_at_the_pools_first_bar_rather_than_spinning(
    lab_session,
) -> None:
    """`before_timestamp` is INCLUSIVE, so the last page comes back holding
    only bars already stored. No progress means no more history."""
    pool, newest = "P1", datetime(2026, 9, 11, 2, 0, tzinfo=UTC)
    source = FakeSource(ohlcv_by={(pool, "hour"): ohlcv("hour", bars=120,
                                                        newest_open=newest)})
    row = member(pool=pool)
    lab_session.add(row)
    await lab_session.flush()
    engine = BreakoutCandles(lab_session, source)

    await engine.sync(row, "hour", NOW)
    await engine.sync(row, "hour", NOW)
    stored = await lab_session.scalar(select(func.count()).select_from(BoCandle))
    assert stored == 119, "120 bars less the forming one"
    calls_before = len(source.calls)
    await engine.sync(row, "hour", NOW)
    # Nothing new has closed and the history is exhausted: at most the one
    # no-progress probe, never a loop.
    assert len(source.calls) - calls_before <= 1


@pytest.mark.integration
async def test_nothing_is_requested_when_no_bar_has_closed_since_the_last_stored_one(
    lab_session,
) -> None:
    pool, newest = "P1", datetime(2026, 9, 11, 1, 0, tzinfo=UTC)
    rows = ohlcv("hour", bars=config.CANDLE_WINDOW_1H + 5, newest_open=newest)
    source = FakeSource(ohlcv_by={(pool, "hour"): rows})
    row = member(pool=pool)
    lab_session.add(row)
    await lab_session.flush()
    engine = BreakoutCandles(lab_session, source)

    for _ in range(6):  # fill the window, then keep ticking
        await engine.sync(row, "hour", NOW)
    source.calls.clear()
    assert await engine.sync(row, "hour", NOW) == 0
    assert source.calls == [], "a quiet tick sends no request at all"


@pytest.mark.integration
async def test_a_forward_fetch_asks_only_for_the_bars_that_have_closed(
    lab_session,
) -> None:
    pool = "P1"
    source = FakeSource(ohlcv_by={(pool, "hour"): ohlcv(
        "hour", bars=120, newest_open=datetime(2026, 9, 11, 1, 0, tzinfo=UTC))})
    row = member(pool=pool)
    lab_session.add(row)
    await lab_session.flush()
    engine = BreakoutCandles(lab_session, source)
    await engine.sync(row, "hour", NOW)

    source.calls.clear()
    three_hours_on = NOW + timedelta(hours=3)
    source.ohlcv_by[(pool, "hour")] = ohlcv(
        "hour", bars=130, newest_open=datetime(2026, 9, 11, 5, 0, tzinfo=UTC))
    await engine.sync(row, "hour", three_hours_on)
    forward = next(c for c in source.calls if c[0] == "ohlcv" and c[4] is None)
    assert forward[3] == 4, "three closed bars plus the forming one"


@pytest.mark.integration
async def test_upserting_the_same_bars_twice_is_one_set_of_rows(lab_session) -> None:
    pool = "P1"
    rows = ohlcv("hour", bars=50, newest_open=datetime(2026, 9, 11, 1, 0, tzinfo=UTC))
    source = FakeSource(ohlcv_by={(pool, "hour"): rows})
    row = member(pool=pool)
    lab_session.add(row)
    await lab_session.flush()
    engine = BreakoutCandles(lab_session, source)

    parsed = parse_ohlcv("M1", pool, "hour", rows, now=NOW)
    assert await engine.upsert(parsed) == len(parsed)
    assert await engine.upsert(parsed) == len(parsed)
    assert await lab_session.scalar(
        select(func.count()).select_from(BoCandle)) == len(parsed)


@pytest.mark.integration
async def test_an_upsert_corrects_a_bar_rather_than_duplicating_it(lab_session) -> None:
    rows = ohlcv("hour", bars=3, newest_open=datetime(2026, 9, 11, 1, 0, tzinfo=UTC))
    engine = BreakoutCandles(lab_session, FakeSource())
    await engine.upsert(parse_ohlcv("M1", "P1", "hour", rows, now=NOW))
    rows[2][4] = 999.0
    await engine.upsert(parse_ohlcv("M1", "P1", "hour", rows, now=NOW))
    closes = (await lab_session.execute(
        select(BoCandle.close).order_by(BoCandle.open_time))).scalars().all()
    assert Decimal("999") in closes and len(closes) == 3


# --- failures and the budget --------------------------------------------------

@pytest.mark.integration
async def test_consecutive_failures_retire_a_token_and_a_success_clears_them(
    lab_session,
) -> None:
    row = member(pool="BadPool")
    lab_session.add(row)
    await lab_session.flush()
    broken = FakeSource(fail_pools={"BadPool"})

    for expected in range(1, config.MAX_FETCH_FAILURES + 1):
        await BreakoutCandles(lab_session, broken).refresh(NOW)
        refreshed = (await lab_session.execute(
            select(BoUniverseMember).where(BoUniverseMember.mint == "M1"))).scalar_one()
        assert refreshed.fetch_failures == expected
        if expected < config.MAX_FETCH_FAILURES:
            assert refreshed.active is True
    assert refreshed.active is False
    assert refreshed.inactive_reason == "fetch_failures"
    assert refreshed.last_error

    await lab_session.execute(BoUniverseMember.__table__.update().values(
        active=True, inactive_reason=None))
    working = FakeSource(ohlcv_by={("BadPool", "hour"): ohlcv(
        "hour", bars=10, newest_open=datetime(2026, 9, 11, 1, 0, tzinfo=UTC))})
    await BreakoutCandles(lab_session, working).refresh(NOW)
    healed = (await lab_session.execute(
        select(BoUniverseMember).where(BoUniverseMember.mint == "M1"))).scalar_one()
    assert healed.fetch_failures == 0 and healed.last_error is None


@pytest.mark.integration
async def test_one_token_failing_costs_that_token_and_nothing_else(lab_session) -> None:
    good, bad = member("M1", "Good", volume=900_000), member("M2", "Bad", volume=800_000)
    lab_session.add_all([good, bad])
    await lab_session.flush()
    source = FakeSource(
        fail_pools={"Bad"},
        ohlcv_by={("Good", "hour"): ohlcv("hour", bars=10,
                                          newest_open=datetime(2026, 9, 11, 1, 0,
                                                               tzinfo=UTC))})
    result = await BreakoutCandles(lab_session, source).refresh(NOW)
    assert result["candles_upserted"] > 0 and result["tokens_refreshed"] == 1
    assert len(result["errors"]) == 1 and "M2" in result["errors"][0]
    mints = (await lab_session.execute(select(BoCandle.mint).distinct())).scalars().all()
    assert mints == ["M1"], "the failing token's savepoint took nothing with it"


@pytest.mark.integration
async def test_the_queue_is_ordered_by_volume_and_the_remainder_carries(
    lab_session,
) -> None:
    """A 429 storm spends the tick's allowance. The tick must stop, report
    what it did not reach, and leave it for the next one — never crash."""
    newest = datetime(2026, 9, 11, 1, 0, tzinfo=UTC)
    members = [member(f"M{i}", f"P{i}", volume=1_000 * (10 - i)) for i in range(5)]
    lab_session.add_all(members)
    await lab_session.flush()
    bars = {(f"P{i}", tf): ohlcv(tf, bars=10, newest_open=newest)
            for i in range(5) for tf in config.TIMEFRAMES}

    # Two calls of allowance: enough to start the most liquid token and no more.
    starved = FakeSource(ohlcv_by=bars, max_calls=2)
    result = await BreakoutCandles(lab_session, starved).refresh(NOW)
    assert result["tokens_carried"] == 5, "the half-served token is still due"
    assert (await lab_session.execute(
        select(BoCandle.mint).distinct())).scalars().all() == ["M0"], "most liquid first"
    assert result["candles_upserted"] > 0, "what the spent calls bought is kept"

    # The next tick, with room, picks up exactly what was carried.
    roomy = FakeSource(ohlcv_by=bars)
    second = await BreakoutCandles(lab_session, roomy).refresh(NOW)
    assert second["tokens_carried"] == 0
    covered = (await lab_session.execute(
        select(BoCandle.mint).distinct().order_by(BoCandle.mint))).scalars().all()
    assert covered == ["M0", "M1", "M2", "M3", "M4"]


@pytest.mark.integration
async def test_the_deadline_stops_a_tick_and_carries_the_rest(lab_session) -> None:
    members = [member(f"M{i}", f"P{i}", volume=1_000 * (10 - i)) for i in range(4)]
    lab_session.add_all(members)
    await lab_session.flush()
    result = await BreakoutCandles(lab_session, FakeSource()).refresh(
        NOW, deadline_seconds=-1)
    assert result["tokens_carried"] == 4 and result["candles_upserted"] == 0


@pytest.mark.integration
async def test_the_rolling_window_bounds_each_timeframe_separately(lab_session) -> None:
    pool = "P1"
    row = member(pool=pool)
    lab_session.add(row)
    await lab_session.flush()
    engine = BreakoutCandles(lab_session, FakeSource())
    over = config.CANDLE_WINDOW_1H + 40
    await engine.upsert(parse_ohlcv("M1", pool, "hour", ohlcv(
        "hour", bars=over, newest_open=datetime(2026, 9, 11, 1, 0, tzinfo=UTC)), now=NOW))
    await engine.upsert(parse_ohlcv("M1", pool, "day", ohlcv(
        "day", bars=20, newest_open=datetime(2026, 9, 10, 0, 0, tzinfo=UTC)), now=NOW))

    await engine.prune()
    counts = dict((await lab_session.execute(
        select(BoCandle.timeframe, func.count()).group_by(BoCandle.timeframe))).all())
    assert counts["hour"] == config.CANDLE_WINDOW_1H
    assert counts["day"] == 20, "a short daily history is not pruned by the hourly cap"


@pytest.mark.integration
async def test_a_backward_page_asks_only_for_what_the_window_still_wants(
    lab_session,
) -> None:
    """Fetching a full page past the window wrote rows the same tick's prune
    then deleted."""
    pool = "P1"
    source = FakeSource(ohlcv_by={(pool, "day"): ohlcv(
        "day", bars=400, newest_open=datetime(2026, 9, 10, 0, 0, tzinfo=UTC))})
    row = member(pool=pool)
    lab_session.add(row)
    await lab_session.flush()

    await BreakoutCandles(lab_session, source).sync(row, "day", NOW)
    stored = await lab_session.scalar(select(func.count()).select_from(BoCandle))
    assert stored <= config.CANDLE_WINDOW_1D, f"{stored} bars for a 180-bar window"
    backward = [c for c in source.calls if c[0] == "ohlcv" and c[4] is not None]
    assert backward[-1][3] < config.OHLCV_LIMIT, "the last page asked for less than a page"


@pytest.mark.integration
async def test_a_tick_under_a_429_storm_carries_the_queue_instead_of_crashing(
    lab_session,
) -> None:
    """The brief's budget test, driven through the REAL HTTP layer: an
    httpx transport that answers 429 to everything, the real `CallBudget`,
    the real backoff and the real retry loop. Nothing raises out of the tick.
    """
    import httpx

    from app.labs.breakout.sources import BreakoutSource
    from app.labs.breakout.tests.test_sources import Clock, _budget

    lab_session.add_all(
        [member(f"M{i}", f"P{i}", volume=1_000 * (10 - i)) for i in range(4)])
    await lab_session.flush()

    clock = Clock()
    storm = httpx.AsyncClient(transport=httpx.MockTransport(
        lambda r: httpx.Response(429, headers={"retry-after": "0"}, json={"errors": []})))
    source = BreakoutSource(
        client=storm, sleep=clock.sleep, max_calls=12,
        gecko_budget=_budget(clock, config.GECKOTERMINAL_CALLS_PER_MINUTE),
        dex_budget=_budget(clock, config.DEXSCREENER_CALLS_PER_MINUTE))

    result = await BreakoutCandles(lab_session, source).refresh(NOW)

    assert result["candles_upserted"] == 0
    assert result["tokens_carried"] > 0, "the budget stopped the tick"
    assert result["errors"], "the tokens it did try are reported, not swallowed"
    assert source.requests["geckoterminal"] >= 12, "retries counted against the cap"
    assert clock.t > 0.0, "Retry-After: 0 did not defeat the backoff"

    # Every token it actually attempted carries a failure count, and none is
    # retired yet — one bad tick is not five.
    rows = (await lab_session.execute(select(BoUniverseMember))).scalars().all()
    tried = [r for r in rows if r.fetch_failures]
    assert tried and all(r.active and r.fetch_failures == 1 for r in tried)
