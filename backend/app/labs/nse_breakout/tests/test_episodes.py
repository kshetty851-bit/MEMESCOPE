"""The engine: what the walk writes, and that the two callers agree."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.labs.nse_breakout import config, episodes, states
from app.labs.nse_breakout.models import (
    BtCandle,
    BtEpisode,
    BtEpisodeEvent,
    BtIndexClose,
    BtState,
    BtUniverseMember,
)

NOW = datetime(2026, 9, 11, 13, 0, tzinfo=UTC)
START = date(2024, 1, 1)


def bar(symbol: str, when: date, o: float, h: float, low: float, c: float,
        volume: int = 10_000) -> BtCandle:
    return BtCandle(symbol=symbol, date=when, open=Decimal(str(o)),
                    high=Decimal(str(h)), low=Decimal(str(low)),
                    close=Decimal(str(c)), volume=volume,
                    turnover=Decimal(str(round(c * volume, 2))),
                    adjusted=False, suspect_gap=False)


def sessions(n: int, start: date = START) -> list[date]:
    """`n` weekday dates. Bars are TRADING days — a fixture that puts one on
    every calendar day would make 40 bars look like 40 days to anything that
    reasons in the calendar, which is how the outcome pre-filter reads."""
    out, when = [], start
    while len(out) < n:
        if when.weekday() < 5:
            out.append(when)
        when += timedelta(days=1)
    return out


def coiling(symbol: str = "COIL", n: int = 320, coil: int = 26) -> list[BtCandle]:
    """A series that builds a level, coils under it, then clears it on volume.

    Hand-shaped rather than random, because the point is that the machine finds
    the setup a person would draw on the chart — so the chart has to be
    drawable: a long advance, three rejections at ~101, a tight base just under
    it, volume arriving in the last few days, then a close through on 3x.

    Shaped to the thresholds as they are. Moving a threshold to make a fixture
    work would be tuning the rules to the test.
    """
    bars = []
    rejections = {n - coil - 95, n - coil - 60, n - coil - 24}
    for i, when in enumerate(sessions(n)):
        if i < n - coil - 3:
            base, volume = 62 + 34 * (i / (n - coil - 3)), 10_000
            if i in rejections:
                base, volume = 100.4, 26_000       # sold into, three times
        elif i < n - 3:
            k = i - (n - coil - 3)
            base = 96.0 + k * 0.05                 # the base, drifting up
            volume = 8_000 if k < coil - 4 else 30_000
        else:
            base, volume = 102.5 + (i - (n - 3)) * 1.2, 48_000
        bars.append(bar(symbol, when, round(base - 0.25, 2), round(base + 0.55, 2),
                        round(base - 0.7, 2), round(base, 2), volume))
    return bars


# --- the two callers agree ----------------------------------------------------------

def _carry(row: dict) -> tuple[states.EpisodeState, dict]:
    """The open row as the state and seed the next day's walk is given — the
    same round trip `Detector.daily` makes through the database."""
    def number(value):
        return float(value) if value is not None else None

    return states.EpisodeState(
        opened=row["opened"], state=row["state"],
        first_near_date=row["first_near_date"],
        ref_price=number(row["ref_price"]),
        resistance=number(row["resistance"]),
        breakout_date=row["breakout_date"],
        breakout_price=number(row["breakout_price"]),
        bars_open=row["bars_open"],
        bars_since_breakout=row["bars_since_breakout"],
        weak_bars=row["weak_bars"],
    ), {"id": row["id"], "score_at_open": row["score_at_open"],
        "max_score": row["max_score"],
        "breakout_volume_mult": row["breakout_volume_mult"],
        "days_to_breakout": row["days_to_breakout"]}


def test_the_daily_pass_and_the_replay_produce_the_same_episodes() -> None:
    """**The claim the whole phase rests on.**

    The replayed statistics are only a claim about the LIVE rules if the live
    pass would have produced the same episodes. Here the same bars are walked
    both ways — once in a single sweep, and once one bar at a time carrying the
    episode forward exactly as the daily job does through the database — and
    the episodes must match field for field.
    """
    bars = coiling()
    first = config.MIN_BARS_FOR_LEVELS - 1
    sweep = episodes.walk("COIL", bars, start_index=first)

    carried: states.EpisodeState | None = None
    seed: dict | None = None
    by_open: dict[date, dict] = {}
    for i in range(first, len(bars)):
        step = episodes.walk("COIL", bars[:i + 1], start_index=i,
                             opening=carried, seed=seed)
        row = step.opened[-1] if step.opened else step.current
        if row is None:
            carried, seed = None, None
            continue
        by_open[row["opened"]] = row
        carried, seed = (None, None) if row["closed"] else _carry(row)

    def comparable(rows):
        return [{k: v for k, v in r.items() if k != "id"}
                for r in sorted(rows, key=lambda r: r["opened"])]

    assert sweep.opened, "the fixture must actually produce an episode"
    assert comparable(by_open.values()) == comparable(sweep.opened)


def test_the_fixture_walks_all_the_way_to_a_breakout() -> None:
    """Guards the test above: if the shaped series stopped producing a
    breakout, the agreement test would still pass while proving much less."""
    result = episodes.walk("COIL", coiling(),
                           start_index=config.MIN_BARS_FOR_LEVELS - 1)
    assert any(r["breakout_date"] is not None for r in result.opened)
    assert result.snapshot is not None and result.snapshot["bars"] >= 250


def test_the_walk_never_looks_past_the_bar_it_is_on() -> None:
    """Truncating the future must not change a single decision already made."""
    bars = coiling()
    early = episodes.walk("COIL", bars[:300],
                          start_index=config.MIN_BARS_FOR_LEVELS - 1)
    full = episodes.walk("COIL", bars, start_index=config.MIN_BARS_FOR_LEVELS - 1)
    for a, b in zip(early.events, full.events, strict=False):
        assert (a["date"], a["state"], a["close"]) == (b["date"], b["state"],
                                                       b["close"])


# --- against the database ------------------------------------------------------------

async def _seed(session, bars: list[BtCandle], *, bar_count: int | None = None,
                index: bool = True) -> None:
    session.add_all(bars)
    session.add(BtUniverseMember(
        symbol=bars[0].symbol, name="Coiler Ltd", isin="INECOIL01011",
        series="EQ", last_close=bars[-1].close, turnover_20d=Decimal("500000000"),
        bars=bar_count if bar_count is not None else len(bars),
        first_seen=bars[0].date, last_seen=bars[-1].date, active=True,
        updated_at=NOW))
    if index:
        session.add_all([BtIndexClose(index_name=config.NIFTY_NAME, date=b.date,
                                      close=Decimal("20000"))
                         for b in bars])
    await session.flush()


@pytest.mark.integration
async def test_the_daily_pass_writes_one_state_row_per_symbol(
    tracker_session,
) -> None:
    await _seed(tracker_session, coiling())
    result = await episodes.Detector(tracker_session).daily(now=NOW)
    await tracker_session.flush()
    assert result["symbols"] == 1
    row = (await tracker_session.execute(select(BtState))).scalar_one()
    assert row.symbol == "COIL" and row.bars >= 250
    assert row.clusters, "the ladder is stored, not recomputed by the route"

    await episodes.Detector(tracker_session).daily(now=NOW)
    await tracker_session.flush()
    # The upsert is a Core statement, so the ORM object this test already
    # loaded would still report the OLD value from the identity map.
    tracker_session.expire_all()
    rows = (await tracker_session.execute(select(BtState))).scalars().all()
    assert len(rows) == 1, "upserted, not appended"
    assert rows[0].days_in_state == 2, "same state two passes running"


@pytest.mark.integration
async def test_a_symbol_below_the_bar_minimum_is_never_evaluated(
    tracker_session,
) -> None:
    """Pre-decided: under 250 bars it stays in the universe and out of the
    levels. Scoring it on 60 bars would put a level on the board that a year of
    history might not support."""
    await _seed(tracker_session, coiling(n=100), bar_count=100)
    result = await episodes.Detector(tracker_session).daily(now=NOW)
    assert result["symbols"] == 0
    assert (await tracker_session.execute(select(BtState))).scalars().all() == []


@pytest.mark.integration
async def test_the_replay_marks_a_symbol_even_when_it_found_nothing(
    tracker_session,
) -> None:
    """`replayed_at`, not the presence of episodes, is the marker. A symbol
    that produced none has still been replayed, and counting episodes would
    walk it again on every pass for ever."""
    flat = [bar("FLAT", when, 100, 100.2, 99.8, 100)
            for when in sessions(300)]
    await _seed(tracker_session, flat)
    result = await episodes.Detector(tracker_session).replay(now=NOW)
    assert result["symbols"] == 1
    member = (await tracker_session.execute(
        select(BtUniverseMember))).scalar_one()
    assert member.replayed_at is not None
    assert (await episodes.Detector(tracker_session).replay(now=NOW))["symbols"] == 0


@pytest.mark.integration
async def test_the_replay_writes_episodes_and_their_events(tracker_session) -> None:
    await _seed(tracker_session, coiling())
    await episodes.Detector(tracker_session).replay(now=NOW)
    await tracker_session.flush()
    rows = (await tracker_session.execute(
        select(BtEpisode).where(BtEpisode.source == "replay"))).scalars().all()
    assert rows
    assert all(e.source == "replay" for e in rows)
    assert all(e.outcomes_filled_at is None for e in rows), \
        "detection must never write an outcome"
    events = (await tracker_session.execute(select(BtEpisodeEvent))).scalars().all()
    assert events and {e.episode_id for e in events} <= {e.id for e in rows}


@pytest.mark.integration
async def test_only_one_episode_per_symbol_is_open_at_a_time(
    tracker_session,
) -> None:
    """Enforced by a partial unique index, so a bug that opened a second one
    would fail loudly rather than double-count every statistic."""
    await _seed(tracker_session, coiling())
    await episodes.Detector(tracker_session).daily(now=NOW)
    await tracker_session.flush()
    open_rows = (await tracker_session.execute(
        select(BtEpisode).where(BtEpisode.closed.is_(None)))).scalars().all()
    assert len(open_rows) <= 1


# --- outcomes ---------------------------------------------------------------------

@pytest.mark.integration
async def test_outcomes_wait_for_the_window_and_then_fill_it(
    tracker_session,
) -> None:
    """A half-filled row would be read as a result, so nothing is written until
    every horizon the episode can have is measurable."""
    bars = coiling(n=420)
    await _seed(tracker_session, bars)
    detector = episodes.Detector(tracker_session)
    await detector.replay(now=NOW)
    await tracker_session.flush()
    row = (await tracker_session.execute(
        select(BtEpisode).where(BtEpisode.first_near_date.is_not(None))
        .order_by(BtEpisode.opened))).scalars().first()
    assert row is not None

    # Move the episode's measurement point to the very end of the series: its
    # window cannot have elapsed.
    row.first_near_date = bars[-2].date
    row.breakout_date = None
    row.outcomes_filled_at = None
    await tracker_session.flush()
    await episodes.OutcomeFiller(tracker_session).fill(now=NOW)
    assert row.ret_ref_20 is None, "nothing written while the window is open"
    assert row.outcomes_filled_at is None

    row.first_near_date = bars[-(config.OUTCOME_MAX_HORIZON + 2)].date
    await tracker_session.flush()
    await episodes.OutcomeFiller(tracker_session).fill(now=NOW)
    assert row.outcomes_filled_at is not None
    assert row.ret_ref_20 is not None and row.ret_ref_40 is not None
    assert row.mfe_20 is not None and row.mae_20 is not None


@pytest.mark.integration
async def test_a_missing_nifty_window_leaves_the_relative_return_null(
    tracker_session,
) -> None:
    """Pre-decided: null, never zero. Zero would be averaged in as "matched the
    market" and would drag the aggregate toward a result nobody measured."""
    bars = coiling(n=420)
    await _seed(tracker_session, bars, index=False)
    await episodes.Detector(tracker_session).replay(now=NOW)
    await tracker_session.flush()
    row = (await tracker_session.execute(
        select(BtEpisode).where(BtEpisode.first_near_date.is_not(None))
        .order_by(BtEpisode.opened))).scalars().first()
    assert row is not None
    row.first_near_date = bars[-(config.OUTCOME_MAX_HORIZON + 2)].date
    row.outcomes_filled_at = None
    await tracker_session.flush()
    await episodes.OutcomeFiller(tracker_session).fill(now=NOW)
    assert row.ret_ref_20 is not None
    assert row.rel_nifty_20 is None


@pytest.mark.integration
async def test_an_episode_that_cannot_fill_yet_does_not_starve_the_others(
    tracker_session,
) -> None:
    """An episode measured ten bars before the end of the data will not fill
    until more bars arrive. Left in the pending set it would sit at the front
    of the ordering re-failing on every pass, and every symbol after the batch
    limit would never be reached at all.
    """
    bars = coiling(n=420)
    await _seed(tracker_session, bars)
    await episodes.Detector(tracker_session).replay(now=NOW)
    await tracker_session.flush()
    rows = (await tracker_session.execute(
        select(BtEpisode).where(BtEpisode.first_near_date.is_not(None))
        .order_by(BtEpisode.opened))).scalars().all()
    assert rows
    for row in rows:
        row.first_near_date = bars[-2].date
        row.breakout_date = None
        row.outcomes_filled_at = None
    await tracker_session.flush()

    result = await episodes.OutcomeFiller(tracker_session).fill(now=NOW)
    assert result["symbols"] == 0, "not even loaded — nothing there can fill"
    assert result["filled"] == 0


@pytest.mark.integration
async def test_a_name_that_leaves_the_universe_loses_its_state_row(
    tracker_session,
) -> None:
    """Its episodes stay — that is the record — but a stale score against a
    current-looking `bar_date` would be read as today's answer."""
    await _seed(tracker_session, coiling())
    await episodes.Detector(tracker_session).daily(now=NOW)
    await tracker_session.flush()
    assert (await tracker_session.execute(select(BtState))).scalars().all()

    member = (await tracker_session.execute(
        select(BtUniverseMember))).scalar_one()
    member.active = False
    await tracker_session.flush()
    await episodes.Detector(tracker_session).daily(now=NOW)
    await tracker_session.flush()
    assert (await tracker_session.execute(select(BtState))).scalars().all() == []
