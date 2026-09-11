"""Ingest, the universe filters, resumability and the split flag."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.labs.nse_breakout import config
from app.labs.nse_breakout.ingest import Ingest, median_turnover, trading_days
from app.labs.nse_breakout.models import (
    BtCandle,
    BtIndexClose,
    BtIngestDay,
    BtRun,
    BtUniverseMember,
)
from app.labs.nse_breakout.tests.fakes import FakeArchive, row

NOW = datetime(2026, 9, 11, 13, 0, tzinfo=UTC)
D10 = date(2026, 9, 10)


# --- pure ------------------------------------------------------------------------

def test_trading_days_are_weekdays_newest_first() -> None:
    days = trading_days(date(2026, 9, 7), date(2026, 9, 13))   # Mon..Sun
    assert days == [date(2026, 9, 11), date(2026, 9, 10), date(2026, 9, 9),
                    date(2026, 9, 8), date(2026, 9, 7)]
    assert all(d.weekday() < 5 for d in days)


def test_the_calendar_is_the_archive_not_a_holiday_list() -> None:
    """Diwali is a weekday and the market is shut. Hard-coding Indian holidays
    would be a second source of truth that goes stale every year; a 404 from
    the archive is the exchange answering."""
    assert date(2026, 11, 11) in trading_days(date(2026, 11, 1), date(2026, 11, 30))


def test_turnover_uses_the_median_so_one_block_deal_cannot_qualify_a_name() -> None:
    thin = [Decimal("1000")] * 19 + [Decimal("500000000")]
    assert float(median_turnover(thin)) == pytest.approx(1000.0)
    assert median_turnover([None, None]) is None


# --- one day --------------------------------------------------------------------

@pytest.mark.integration
async def test_a_day_ingests_its_equities_and_records_itself(tracker_session) -> None:
    archive = FakeArchive({D10: [
        row("AAA", D10), row("BBB", D10),
        row("SGBJUN28", D10, series="GB"),      # gold bond
        row("SMEONE", D10, series="SM"),        # SME
        row("NIFTYFUT", D10, instrument="FUT"), # not a share
    ]}, index={D10: 23356.25})
    result = await Ingest(tracker_session, archive).day(D10, now=NOW)

    assert result["status"] == "ok" and result["rows"] == 2
    stored = {c.symbol for c in (await tracker_session.execute(
        select(BtCandle))).scalars()}
    assert stored == {"AAA", "BBB"}, "only EQ/BE equities"
    day = (await tracker_session.execute(select(BtIngestDay))).scalar_one()
    assert day.status == "ok" and day.symbols == 2


@pytest.mark.integration
async def test_a_non_trading_day_is_recorded_missing_not_failed(
    tracker_session,
) -> None:
    """A holiday is a fact about the calendar. Recording it as a failure would
    make the backfill retry it five times, every run, for ever."""
    result = await Ingest(tracker_session, FakeArchive({})).day(D10, now=NOW)
    assert result["status"] == "missing"
    assert (await tracker_session.execute(select(BtIngestDay))).scalar_one().status \
        == "missing"


@pytest.mark.integration
async def test_a_transport_failure_is_recorded_and_counted(tracker_session) -> None:
    job = Ingest(tracker_session, FakeArchive({}, fail={D10}))
    assert (await job.day(D10, now=NOW))["status"] == "failed"
    await job.day(D10, now=NOW)
    day = (await tracker_session.execute(select(BtIngestDay))).scalar_one()
    assert day.status == "failed" and day.failures == 2 and day.last_error


@pytest.mark.integration
async def test_re_ingesting_a_day_rewrites_rather_than_duplicates(
    tracker_session,
) -> None:
    job = Ingest(tracker_session, FakeArchive({D10: [row("AAA", D10, c=104.0)]},
                                              index={D10: 1.0}))
    await job.day(D10, now=NOW)
    corrected = Ingest(tracker_session,
                       FakeArchive({D10: [row("AAA", D10, h=115.0, c=111.0)]}))
    await corrected.day(D10, now=NOW)
    bars = (await tracker_session.execute(select(BtCandle))).scalars().all()
    assert len(bars) == 1 and float(bars[0].close) == pytest.approx(111.0)


@pytest.mark.integration
async def test_the_nifty_close_is_stored_alongside(tracker_session) -> None:
    await Ingest(tracker_session, FakeArchive({D10: [row("AAA", D10)]},
                                              index={D10: 23356.25})).day(D10, now=NOW)
    idx = (await tracker_session.execute(select(BtIndexClose))).scalar_one()
    assert idx.index_name == config.NIFTY_NAME
    assert float(idx.close) == pytest.approx(23356.25)


@pytest.mark.integration
async def test_a_missing_index_file_does_not_take_the_equity_ingest_down(
    tracker_session,
) -> None:
    """Pre-decided: rel_nifty goes null, never zero, and never an outage."""
    result = await Ingest(tracker_session,
                          FakeArchive({D10: [row("AAA", D10)]})).day(D10, now=NOW)
    assert result["status"] == "ok"
    assert (await tracker_session.execute(select(BtIndexClose))).scalars().all() == []


# --- resumability ----------------------------------------------------------------

@pytest.mark.integration
async def test_a_settled_day_is_never_fetched_again(tracker_session) -> None:
    """Resumption is derived, not stored: killing the backfill costs the day
    in flight and nothing else."""
    today = datetime.now(UTC).date()
    recent = trading_days(today - timedelta(days=10), today)
    archive = FakeArchive({d: [row("AAA", d)] for d in recent})
    job = Ingest(tracker_session, archive)

    first = await job.pending_days(3)
    assert len(first) == 3
    for d in first:
        await job.day(d, now=NOW)

    second = await job.pending_days(3)
    assert not set(second) & set(first), "settled days must not come back"


@pytest.mark.integration
async def test_a_day_that_keeps_failing_is_eventually_given_up_on(
    tracker_session,
) -> None:
    today = datetime.now(UTC).date()
    day = trading_days(today - timedelta(days=3), today)[0]
    job = Ingest(tracker_session, FakeArchive({}, fail={day}))
    for _ in range(config.MAX_DAY_FAILURES):
        await job.day(day, now=NOW)
    assert day not in await job.pending_days(50), "should stop being retried"


# --- the universe ----------------------------------------------------------------

async def _seed(session, symbol: str, *, days: int, close: float, turnover: float,
                end: date = D10) -> None:
    job = Ingest(session, FakeArchive())
    bars = []
    for i in range(days):
        when = end - timedelta(days=days - 1 - i)
        bars.append({"symbol": symbol, "date": when,
                     "open": Decimal(str(close)), "high": Decimal(str(close * 1.02)),
                     "low": Decimal(str(close * 0.98)), "close": Decimal(str(close)),
                     "volume": 1000, "turnover": Decimal(str(turnover)),
                     "adjusted": False, "suspect_gap": False})
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    await session.execute(pg_insert(BtCandle).values(bars))
    await session.flush()
    assert job


@pytest.mark.integration
async def test_the_universe_filters_on_price_and_median_turnover(
    tracker_session,
) -> None:
    await _seed(tracker_session, "GOOD", days=25, close=500.0, turnover=5_00_00_000.0)
    await _seed(tracker_session, "PENNY", days=25, close=5.0, turnover=5_00_00_000.0)
    await _seed(tracker_session, "ILLIQUID", days=25, close=500.0, turnover=10_000.0)

    result = await Ingest(tracker_session, FakeArchive()).rebuild_universe(now=NOW)
    rows = {m.symbol: m for m in (await tracker_session.execute(
        select(BtUniverseMember))).scalars()}
    assert rows["GOOD"].active is True
    assert rows["PENNY"].active is False and rows["PENNY"].inactive_reason == "price"
    assert rows["ILLIQUID"].active is False
    assert rows["ILLIQUID"].inactive_reason == "turnover"
    assert result["active"] == 1


@pytest.mark.integration
async def test_a_symbol_that_stops_trading_goes_inactive_not_deleted(
    tracker_session,
) -> None:
    """Pre-decided: a renamed or merged symbol simply stops appearing, and the
    new symbol arrives as its own row. The exchange file carries no linkage."""
    await _seed(tracker_session, "STAYS", days=25, close=500.0, turnover=5_00_00_000.0)
    await _seed(tracker_session, "GONE", days=25, close=500.0, turnover=5_00_00_000.0,
                end=D10 - timedelta(days=3))
    await Ingest(tracker_session, FakeArchive()).rebuild_universe(now=NOW)
    rows = {m.symbol: m for m in (await tracker_session.execute(
        select(BtUniverseMember))).scalars()}
    assert rows["STAYS"].active is True
    assert rows["GONE"].active is False and rows["GONE"].inactive_reason == "absent"


@pytest.mark.integration
async def test_a_short_history_stays_in_the_universe_but_is_counted(
    tracker_session,
) -> None:
    """Pre-decided: < 250 bars is excluded from levels and states, NOT from
    the universe. `bars` is what the health route reports coverage from."""
    await _seed(tracker_session, "NEWLY", days=12, close=500.0, turnover=5_00_00_000.0)
    await Ingest(tracker_session, FakeArchive()).rebuild_universe(now=NOW)
    member = (await tracker_session.execute(select(BtUniverseMember))).scalar_one()
    assert member.active is True
    assert member.bars == 12 < config.MIN_BARS_FOR_LEVELS


# --- corporate actions -----------------------------------------------------------

@pytest.mark.integration
async def test_a_one_for_two_split_is_flagged_never_corrected(
    tracker_session,
) -> None:
    """Bhavcopy is unadjusted and the corroboration source is unreachable.
    Silently halving a price with nothing to check it against invents data;
    a flagged bar stays visible in the health route."""
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    bars = []
    for i in range(6):
        # 1:2 split on the fourth bar: 1000 -> 500.
        close = 1000.0 if i < 3 else 500.0
        when = D10 - timedelta(days=5 - i)
        bars.append({"symbol": "SPLIT", "date": when, "open": Decimal(str(close)),
                     "high": Decimal(str(close)), "low": Decimal(str(close)),
                     "close": Decimal(str(close)), "volume": 1000,
                     "turnover": Decimal("1000000"), "adjusted": False,
                     "suspect_gap": False})
    await tracker_session.execute(pg_insert(BtCandle).values(bars))
    await tracker_session.flush()

    flagged = await Ingest(tracker_session, FakeArchive()).flag_suspect_gaps()
    assert flagged == 1
    rows = {c.date: c for c in (await tracker_session.execute(
        select(BtCandle).where(BtCandle.symbol == "SPLIT"))).scalars()}
    split_day = D10 - timedelta(days=2)
    assert rows[split_day].suspect_gap is True
    assert float(rows[split_day].close) == pytest.approx(500.0), "not corrected"
    assert all(not c.suspect_gap for d, c in rows.items() if d != split_day)


@pytest.mark.integration
async def test_an_ordinary_move_is_not_flagged(tracker_session) -> None:
    await _seed(tracker_session, "CALM", days=10, close=500.0, turnover=1_000_000.0)
    assert await Ingest(tracker_session, FakeArchive()).flag_suspect_gaps() == 0


# --- identity ---------------------------------------------------------------------

@pytest.mark.integration
async def test_the_universe_carries_the_name_isin_and_series_from_the_file(
    tracker_session,
) -> None:
    """`bt_candles` stores prices only, so if the ingest does not lift these
    three across they stay null for ever and `series` silently defaults to EQ
    — which the model promises a later phase can rely on."""
    job = Ingest(tracker_session, FakeArchive({D10: [
        row("AAA", D10, name="Alpha Industries Ltd"),
        row("BBB", D10, name="Beta Trade For Trade Ltd", series="BE"),
    ]}))
    await job.day(D10, now=NOW)
    await job.rebuild_universe(now=NOW)

    rows = {m.symbol: m for m in (await tracker_session.execute(
        select(BtUniverseMember))).scalars()}
    assert rows["AAA"].name == "Alpha Industries Ltd"
    assert rows["AAA"].series == "EQ"
    assert rows["BBB"].series == "BE", "not defaulted"
    assert rows["AAA"].isin and rows["AAA"].isin.startswith("INE")
    assert rows["AAA"].inactive_reason != "pending", "rebuild must judge it"


@pytest.mark.integration
async def test_an_older_day_cannot_overwrite_a_newer_name(tracker_session) -> None:
    """The backfill walks BACKWARDS. Without the newest-day-wins guard every
    slice would rewrite a current name with an older one, and a company that
    renamed itself would end up filed under what it was called three years ago.
    """
    job = Ingest(tracker_session, FakeArchive({
        D10: [row("AAA", D10, name="New Name Ltd")],
        D10 - timedelta(days=400): [
            row("AAA", D10 - timedelta(days=400), name="Old Name Ltd")],
    }))
    await job.day(D10, now=NOW)
    await job.rebuild_universe(now=NOW)
    await job.day(D10 - timedelta(days=400), now=NOW)   # the backfill, going back

    member = (await tracker_session.execute(select(BtUniverseMember))).scalar_one()
    assert member.name == "New Name Ltd"


# --- the deadline -----------------------------------------------------------------

def test_the_backfill_deadline_fits_inside_celery_s_soft_limit() -> None:
    """Asserted against Celery's OWN setting, not against a remembered number.

    A task that manages its own budget and overruns `task_soft_time_limit` is
    killed before it commits — so it loses every day it fetched — and with
    `task_acks_late` it is then redelivered to do the whole thing again. This
    is invisible standalone: the CLI has no time limit, so every local run
    passes while production stores nothing.
    """
    from app.workers.celery_app import celery_app

    soft = celery_app.conf.task_soft_time_limit
    assert soft, "celery must impose a soft limit for this to mean anything"
    assert soft - config.BACKFILL_DEADLINE_SECONDS >= 60, (
        f"{config.BACKFILL_DEADLINE_SECONDS}s leaves no room under {soft}s")


@pytest.mark.integration
async def test_a_slow_archive_stops_the_pass_and_still_records_it(
    tracker_session, monkeypatch,
) -> None:
    """The point of the deadline: what was fetched is kept and committed, and
    the rest stays pending. A truncated pass is a resumable pass."""
    today = datetime.now(UTC).date()
    days = trading_days(today - timedelta(days=30), today)
    archive = FakeArchive({d: [row("AAA", d)] for d in days})
    monkeypatch.setattr(config, "BACKFILL_DEADLINE_SECONDS", 0.0)

    result = await Ingest(tracker_session, archive).backfill(limit=10, now=NOW)

    assert result["stopped_early"] is True
    assert result["days"] == 0
    assert result["remaining_days"] > 0, "nothing was settled, so nothing is lost"
    await tracker_session.flush()   # the run row is added, not executed
    run = (await tracker_session.execute(select(BtRun))).scalars().one()
    assert run.detail["stopped_early"] is True


# --- "not yet" is not "never" -------------------------------------------------------

@pytest.mark.integration
async def test_a_404_before_the_file_is_due_settles_nothing(tracker_session) -> None:
    """`missing` is TERMINAL — `pending_days` never asks about that day again.
    The beat runs after the close, but the CLI can be run at any hour, and a
    lunchtime run recording today as `missing` would drop that whole session
    for ever.
    """
    today = datetime.now(UTC).date()
    # The newest weekday, not literally today: `pending_days` only ever
    # considers weekdays, so a test pinned to `today` fails every Saturday.
    day = trading_days(today - timedelta(days=7), today)[0]
    noon = datetime(day.year, day.month, day.day, 11, tzinfo=UTC)
    job = Ingest(tracker_session, FakeArchive({}))

    result = await job.day(day, now=noon)

    assert result["status"] == "too_early"
    assert (await tracker_session.execute(select(BtIngestDay))).scalars().all() == []
    assert day in await job.pending_days(50), "must still be asked for"


@pytest.mark.integration
async def test_the_same_404_after_the_cutoff_does_settle(tracker_session) -> None:
    """A holiday has to settle eventually or the backfill re-fetches every
    weekend of the last three years on every single run."""
    today = datetime.now(UTC).date()
    day = trading_days(today - timedelta(days=7), today)[0]
    late = (datetime(day.year, day.month, day.day, tzinfo=UTC)
            + timedelta(hours=config.PUBLISH_CUTOFF_HOURS_UTC))
    job = Ingest(tracker_session, FakeArchive({}))

    assert (await job.day(day, now=late))["status"] == "missing"
    assert day not in await job.pending_days(50)


@pytest.mark.integration
async def test_first_seen_is_the_real_first_bar_not_the_turnover_window(
    tracker_session,
) -> None:
    """`first_seen` reads like a listing date and Phase 2 will use it to decide
    whether a name is old enough to score. Derived from the 20-day turnover
    window it would be the window's own start date for every symbol — the same
    date for a company listed in 2019 and one listed last week."""
    await _seed(tracker_session, "OLD", days=300, close=500.0, turnover=5_00_00_000.0)
    await Ingest(tracker_session, FakeArchive()).rebuild_universe(now=NOW)
    member = (await tracker_session.execute(select(BtUniverseMember))).scalar_one()
    assert member.first_seen == D10 - timedelta(days=299)
    assert member.last_seen == D10
    assert member.bars == 300
