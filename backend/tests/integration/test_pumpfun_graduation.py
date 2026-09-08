"""The graduation collector: our stamp is the measurement.

pump.fun exposes `complete` but no graduation timestamp. Everything that
matters here follows from that: the first sighting IS the event time, so the
tests defend what would corrupt it — stamping a coin that graduated before we
looked, re-stamping one we already have, and storing an implausible market cap
as though it were a reading.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

import pytest
from sqlalchemy import select

from app.models.graduation import PumpfunGraduation, PumpfunGraduationMark
from app.pumpfun import graduation

pytestmark = pytest.mark.integration

NOW = datetime(2026, 9, 8, 12, 0, tzinfo=UTC)


def _coin(mint: str, *, age_min: float, mcap=50000.0, ath=60000.0):
    created = NOW - timedelta(minutes=age_min)
    return {"mint": mint, "complete": True,
            "created_timestamp": int(created.timestamp() * 1000),
            "usd_market_cap": mcap, "ath_market_cap": ath, "reply_count": 3}


async def _run_discover(db_session, monkeypatch, coins):
    async def fake_get(client, url, **params):
        return coins
    monkeypatch.setattr(graduation, "_get", fake_get)
    return await graduation.discover(db_session, now=NOW)


# --------------------------------------------------------------------------
# the stamp
# --------------------------------------------------------------------------


async def test_a_fresh_graduate_is_stamped_at_first_sighting(db_session, monkeypatch):
    out = await _run_discover(db_session, monkeypatch,
                              [_coin("Mint" + "a" * 40, age_min=20)])
    assert out["stamped"] == 1
    g = (await db_session.execute(select(PumpfunGraduation))).scalars().first()
    assert g.first_seen_complete_at == NOW
    assert g.mcap_usd_at_graduation == D("50000")


async def test_a_coin_that_graduated_before_we_looked_is_refused(db_session, monkeypatch):
    """THE test. A coin that graduated last week still reads `complete`, and
    stamping it today would record a fact about US — when we noticed — as
    though it were a fact about the coin. That single error is what made the
    snapshot analysis unanswerable, because every bucket then mixes coins that
    graduated minutes ago with coins that graduated days ago."""
    out = await _run_discover(
        db_session, monkeypatch,
        [_coin("Old" + "b" * 41,
               age_min=graduation.MAX_AGE_AT_DISCOVERY_MINUTES + 60)])
    assert out["stamped"] == 0 and out["too_old"] == 1
    assert (await db_session.execute(select(PumpfunGraduation))).first() is None


async def test_a_coin_is_never_stamped_twice(db_session, monkeypatch):
    """The stamp is the FIRST sighting. A second one would overwrite the only
    thing this table exists to record."""
    coins = [_coin("Mint" + "c" * 40, age_min=10)]
    first = await _run_discover(db_session, monkeypatch, coins)
    second = await _run_discover(db_session, monkeypatch, coins)
    assert first["stamped"] == 1
    assert second["stamped"] == 0 and second["already_known"] == 1
    rows = (await db_session.execute(select(PumpfunGraduation))).scalars().all()
    assert len(rows) == 1 and rows[0].first_seen_complete_at == NOW


async def test_an_implausible_market_cap_is_unknown_not_stored(db_session, monkeypatch):
    """pump.fun has returned caps above 10^20. Storing one — or clamping it —
    puts a number in the table that somebody later trusts. None says we do not
    know, which is true."""
    out = await _run_discover(db_session, monkeypatch,
                              [_coin("Mint" + "d" * 40, age_min=5, mcap=1e25)])
    assert out["stamped"] == 1
    g = (await db_session.execute(select(PumpfunGraduation))).scalars().first()
    assert g.mcap_usd_at_graduation is None


# --------------------------------------------------------------------------
# the follow-up marks
# --------------------------------------------------------------------------


async def _stamp(db_session, mint: str, ago_min: float):
    g = PumpfunGraduation(mint_address=mint,
                          first_seen_complete_at=NOW - timedelta(minutes=ago_min),
                          created_at_source=NOW - timedelta(minutes=ago_min + 5),
                          mcap_usd_at_graduation=D("50000"))
    db_session.add(g)
    await db_session.flush()
    return g


async def test_a_mark_is_taken_at_the_target_age(db_session, monkeypatch):
    await _stamp(db_session, "Mint" + "e" * 40, ago_min=5)

    async def fake_get(client, url, **params):
        return {"usd_market_cap": 25000.0, "ath_market_cap": 70000.0}
    monkeypatch.setattr(graduation, "_get", fake_get)

    out = await graduation.mark(db_session, now=NOW)
    assert out["written"] == 1
    m = (await db_session.execute(select(PumpfunGraduationMark))).scalars().first()
    assert m.minutes_since == 5 and m.mcap_usd == D("25000")


async def test_a_mark_is_never_written_twice_for_the_same_age(db_session, monkeypatch):
    """`mark` runs every minute and the tolerance window is wider than the poll
    interval, so the same coin is due repeatedly. Without the guard the cohort
    would be counted several times at one age."""
    await _stamp(db_session, "Mint" + "f" * 40, ago_min=5)

    async def fake_get(client, url, **params):
        return {"usd_market_cap": 25000.0, "ath_market_cap": 70000.0}
    monkeypatch.setattr(graduation, "_get", fake_get)

    await graduation.mark(db_session, now=NOW)
    await graduation.mark(db_session, now=NOW + timedelta(minutes=1))
    rows = (await db_session.execute(
        select(PumpfunGraduationMark).where(
            PumpfunGraduationMark.minutes_since == 5))).scalars().all()
    assert len(rows) == 1


async def test_a_coin_too_young_for_a_target_is_not_marked(db_session, monkeypatch):
    await _stamp(db_session, "Mint" + "g" * 40, ago_min=1)

    async def fake_get(client, url, **params):
        return {"usd_market_cap": 1.0}
    monkeypatch.setattr(graduation, "_get", fake_get)

    out = await graduation.mark(db_session, now=NOW)
    assert out["written"] == 0


async def test_an_unreadable_response_writes_no_row(db_session, monkeypatch):
    """A missing reading must be an ABSENT row, not a row of nulls — the two
    read identically in an average and only one of them is honest."""
    await _stamp(db_session, "Mint" + "h" * 40, ago_min=5)

    async def fake_get(client, url, **params):
        return None
    monkeypatch.setattr(graduation, "_get", fake_get)

    out = await graduation.mark(db_session, now=NOW)
    assert out["written"] == 0 and out["unreadable"] == 1
    assert (await db_session.execute(select(PumpfunGraduationMark))).first() is None




# --------------------------------------------------------------------------
# the cohort endpoint
# --------------------------------------------------------------------------


async def _grad(db_session, mint, *, seen_at, mcap):
    from decimal import Decimal
    g = PumpfunGraduation(mint_address=mint, first_seen_complete_at=seen_at,
                          created_at_source=seen_at - timedelta(minutes=30),
                          mcap_usd_at_graduation=Decimal(str(mcap)))
    db_session.add(g)
    await db_session.flush()
    return g


async def _mark(db_session, g, *, minutes, mcap):
    from decimal import Decimal
    db_session.add(PumpfunGraduationMark(
        graduation_id=g.id, mint_address=g.mint_address,
        observed_at=g.first_seen_complete_at + timedelta(minutes=minutes),
        minutes_since=minutes, mcap_usd=Decimal(str(mcap))))
    await db_session.flush()


async def test_the_cold_start_batch_is_excluded(db_session):
    """The collector's first pass stamped every coin ALREADY complete. Their
    stamp is when we started watching, not when they graduated — including them
    would reintroduce the exact error the collector was built to remove."""
    from app.pumpfun.graduation_api import graduations

    cold = NOW
    for i in range(3):  # the cold-start batch: same instant
        g = await _grad(db_session, f"Cold{i}" + "z" * 38, seen_at=cold, mcap=50000)
        await _mark(db_session, g, minutes=5, mcap=50000)
    real = await _grad(db_session, "Real" + "y" * 40,
                       seen_at=cold + timedelta(minutes=2), mcap=50000)
    await _mark(db_session, real, minutes=5, mcap=25000)

    out = await graduations(db_session)
    assert out["total_stamped"] == 4
    assert out["cohort"] == 1, "only the coin we watched flip"
    assert out["excluded_cold_start"] == 3
    five = next(r for r in out["ages"] if r["minutes"] == 5)
    assert five["n"] == 1 and five["median_pct"] == -50.0


async def test_a_coin_without_a_graduation_price_is_excluded(db_session):
    """Nothing can be measured against an unknown reference, and substituting a
    curve-derived estimate would be an assumption dressed as an observation."""
    from decimal import Decimal
    from app.pumpfun.graduation_api import graduations

    cold = NOW
    await _grad(db_session, "Cold" + "a" * 40, seen_at=cold, mcap=50000)
    g = PumpfunGraduation(mint_address="NoPx" + "b" * 40,
                          first_seen_complete_at=cold + timedelta(minutes=3),
                          mcap_usd_at_graduation=None)
    db_session.add(g)
    await db_session.flush()
    await _mark(db_session, g, minutes=5, mcap=Decimal("10"))

    out = await graduations(db_session)
    assert out["cohort"] == 0
    assert next(r for r in out["ages"] if r["minutes"] == 5)["n"] == 0


async def test_returns_are_measured_against_the_stamped_graduation_price(db_session):
    from app.pumpfun.graduation_api import graduations

    cold = NOW
    await _grad(db_session, "Cold" + "c" * 40, seen_at=cold, mcap=50000)
    for i, (grad_mc, mc5) in enumerate([(40000, 20000), (50000, 75000)]):
        g = await _grad(db_session, f"Coin{i}" + "d" * 38,
                        seen_at=cold + timedelta(minutes=2 + i), mcap=grad_mc)
        await _mark(db_session, g, minutes=5, mcap=mc5)

    out = await graduations(db_session)
    five = next(r for r in out["ages"] if r["minutes"] == 5)
    assert five["n"] == 2
    assert five["worst_pct"] == -50.0   # 20000/40000
    assert five["best_pct"] == 50.0     # 75000/50000
    assert five["pct_up"] == 50.0


async def test_an_age_with_no_readings_reports_zero_rather_than_nothing(db_session):
    """A missing age must be visibly empty, not silently absent — otherwise the
    page implies the measurement was taken and came back flat."""
    from app.pumpfun.graduation_api import graduations

    out = await graduations(db_session)
    assert [r["minutes"] for r in out["ages"]] == list(TARGET_MINUTES_FOR_TEST)
    assert all(r["n"] == 0 for r in out["ages"])


TARGET_MINUTES_FOR_TEST = graduation.TARGET_MINUTES


# --------------------------------------------------------------------------
# the simulated $100 book — every guard against a flattering number
# --------------------------------------------------------------------------


async def test_a_glitch_multiple_is_excluded_not_banked(db_session):
    """THE test. The raw feed produced an 11,670x on one coin. Left in, that
    single row turns a $100 book into six figures and the page reports a
    fortune that never existed."""
    from app.pumpfun.graduation_api import graduation_paper

    cold = NOW
    await _grad(db_session, "Cold" + "g" * 40, seen_at=cold, mcap=50000)
    g = await _grad(db_session, "Glitch" + "h" * 38,
                    seen_at=cold + timedelta(minutes=1), mcap=50000)
    await _mark(db_session, g, minutes=5, mcap=50000 * 11670)

    out = await graduation_paper(db_session)
    five = next(h for h in out["horizons"] if h["minutes"] == 5)
    assert five["excluded_glitch"] == 1
    assert five["trades"] == 0
    assert float(five["final_equity_gross"]) == 100.0, "the book must not move"


async def test_a_coin_with_no_mark_yet_is_not_counted_as_flat(db_session):
    """An unpriced position is not a break-even one. Counting it as flat would
    report the survivors as the population."""
    from app.pumpfun.graduation_api import graduation_paper

    cold = NOW
    await _grad(db_session, "Cold" + "i" * 40, seen_at=cold, mcap=50000)
    await _grad(db_session, "NoMark" + "j" * 38,
                seen_at=cold + timedelta(minutes=1), mcap=50000)

    out = await graduation_paper(db_session)
    five = next(h for h in out["horizons"] if h["minutes"] == 5)
    assert five["skipped_no_mark_yet"] == 1
    assert five["trades"] == 0


async def test_a_total_loss_is_banked_as_a_total_loss(db_session):
    """The whole point. A coin that went to nothing must cost the book its
    stake, not quietly leave the simulation."""
    from app.pumpfun.graduation_api import graduation_paper

    cold = NOW
    await _grad(db_session, "Cold" + "k" * 40, seen_at=cold, mcap=50000)
    g = await _grad(db_session, "Dead" + "l" * 40,
                    seen_at=cold + timedelta(minutes=1), mcap=50000)
    await _mark(db_session, g, minutes=5, mcap=1)  # ~ -100%

    out = await graduation_paper(db_session)
    five = next(h for h in out["horizons"] if h["minutes"] == 5)
    assert five["trades"] == 1
    assert float(five["pnl_gross"]) < -9.9, "a rug must cost the full stake"


async def test_the_book_cannot_hold_more_than_its_slots(db_session):
    """$10 x 10 is the whole $100. An eleventh concurrent position would be
    money the book does not have, and a simulation that spends it reports
    returns on capital that was never at risk."""
    from app.pumpfun.graduation_api import graduation_paper

    cold = NOW
    await _grad(db_session, "Cold" + "m" * 40, seen_at=cold, mcap=50000)
    for i in range(14):  # all inside the 5-minute window, so slots overlap
        g = await _grad(db_session, f"Many{i:02d}" + "n" * 36,
                        seen_at=cold + timedelta(seconds=30 + i), mcap=50000)
        await _mark(db_session, g, minutes=5, mcap=55000)

    out = await graduation_paper(db_session)
    five = next(h for h in out["horizons"] if h["minutes"] == 5)
    assert five["trades"] == 10, f"took {five['trades']}, book has 10 slots"
    assert five["skipped_capacity"] == 4


async def test_execution_is_charged_on_every_trade_taken(db_session):
    from app.pumpfun.graduation_api import (PAPER_EXECUTION_PCT,
                                            PAPER_POSITION_USD,
                                            graduation_paper)

    cold = NOW
    await _grad(db_session, "Cold" + "o" * 40, seen_at=cold, mcap=50000)
    g = await _grad(db_session, "Flat" + "p" * 40,
                    seen_at=cold + timedelta(minutes=1), mcap=50000)
    await _mark(db_session, g, minutes=5, mcap=50000)  # exactly flat

    out = await graduation_paper(db_session)
    five = next(h for h in out["horizons"] if h["minutes"] == 5)
    # The payload rounds to cents for display, so compare at that resolution.
    expected = float(PAPER_POSITION_USD * PAPER_EXECUTION_PCT)
    assert abs(float(five["execution_charged"]) - expected) < 0.01
    assert float(five["pnl_gross"]) == 0.0
    assert float(five["pnl_net"]) < 0.0, "a flat trade still costs the spread"


async def test_the_cold_start_batch_is_excluded_from_the_book(db_session):
    from app.pumpfun.graduation_api import graduation_paper

    cold = NOW
    for i in range(3):
        g = await _grad(db_session, f"Cold{i}" + "q" * 38, seen_at=cold, mcap=50000)
        await _mark(db_session, g, minutes=5, mcap=100000)  # would double
    out = await graduation_paper(db_session)
    five = next(h for h in out["horizons"] if h["minutes"] == 5)
    assert five["trades"] == 0
    assert float(five["final_equity_gross"]) == 100.0


async def test_the_book_reports_itself_without_its_best_trade(db_session):
    """The column that stops the page lying by omission.

    On the real cohort these two numbers disagree completely: at 15 minutes the
    book read +$82 and ONE coin doing 14.4x was that entire result — removed,
    the same book read -$51. A strategy whose whole outcome is one trade has
    not been shown to work.
    """
    from app.pumpfun.graduation_api import graduation_paper

    cold = NOW
    await _grad(db_session, "Cold" + "r" * 40, seen_at=cold, mcap=50000)
    # Nine small losers and one enormous winner — the shape every false edge
    # on this platform has had.
    for i in range(9):
        g = await _grad(db_session, f"Lose{i}" + "s" * 38,
                        seen_at=cold + timedelta(minutes=1 + i), mcap=50000)
        await _mark(db_session, g, minutes=5, mcap=45000)          # -10%
    winner = await _grad(db_session, "Win" + "t" * 41,
                         seen_at=cold + timedelta(minutes=20), mcap=50000)
    await _mark(db_session, winner, minutes=5, mcap=50000 * 14)     # 14x

    out = await graduation_paper(db_session)
    five = next(h for h in out["horizons"] if h["minutes"] == 5)
    assert five["trades"] == 10
    assert float(five["best_trade_multiple"]) == 14.0
    # With the winner: strongly up. Without it: down.
    assert float(five["pnl_net"]) > 0
    assert float(five["pnl_without_best"]) < 0
    assert float(five["final_equity_without_best"]) < float(five["final_equity_net"])


async def test_without_best_is_reported_even_for_a_single_trade(db_session):
    """One trade minus its best trade is NO trades — the book, untouched. A
    null here would render as "unknown" and read like missing data rather than
    like the honest answer, which is that one trade proves nothing."""
    from app.pumpfun.graduation_api import graduation_paper

    cold = NOW
    await _grad(db_session, "Cold" + "u" * 40, seen_at=cold, mcap=50000)
    g = await _grad(db_session, "Solo" + "v" * 40,
                    seen_at=cold + timedelta(minutes=1), mcap=50000)
    await _mark(db_session, g, minutes=5, mcap=500000)  # 10x

    out = await graduation_paper(db_session)
    five = next(h for h in out["horizons"] if h["minutes"] == 5)
    assert float(five["pnl_without_best"]) == 0.0


# --------------------------------------------------------------------------
# the 48-hour horizon
# --------------------------------------------------------------------------


def test_the_targets_run_hourly_to_two_days():
    assert graduation.TARGET_MINUTES[:3] == (5, 15, 30)
    hourly = graduation.TARGET_MINUTES[3:]
    assert hourly[0] == 60 and hourly[-1] == 2880
    assert all(b - a == 60 for a, b in zip(hourly, hourly[1:])), "hourly, no gaps"
    assert len(graduation.TARGET_MINUTES) == 51


def test_a_long_horizon_gets_a_wider_window():
    """Four minutes either side of a 48-hour mark demands the collector be
    alive at that exact minute two days later, and a missed window is not
    recoverable — the age passes and that coin has no reading, ever."""
    assert graduation._tolerance(5) == graduation.MARK_TOLERANCE_MINUTES
    assert graduation._tolerance(60) == graduation.MARK_TOLERANCE_MINUTES
    assert graduation._tolerance(2880) == graduation.LONG_MARK_TOLERANCE_MINUTES
    assert graduation._tolerance(2880) > graduation._tolerance(60)


def test_the_budget_covers_steady_state_with_room():
    """52 targets at ~30 graduations an hour is 26 marks a minute. The budget
    is spent in target order, so a tight one starves the LONGEST horizons —
    the readings that took two days to earn and cannot be re-taken."""
    marks_per_minute = (30 * (len(graduation.TARGET_MINUTES) - 3) + 30 * 3) / 60
    assert graduation.MARK_BUDGET >= marks_per_minute * 4, (
        f"budget {graduation.MARK_BUDGET} is thin against "
        f"{marks_per_minute:.0f} marks/minute"
    )


async def test_a_two_day_old_coin_is_marked_at_its_48h_age(db_session, monkeypatch):
    from datetime import timedelta as _td

    g = await _stamp(db_session, "Old48" + "w" * 39, ago_min=2880)

    async def fake_get(client, url, **params):
        return {"usd_market_cap": 5000.0, "ath_market_cap": 90000.0}
    monkeypatch.setattr(graduation, "_get", fake_get)

    out = await graduation.mark(db_session, now=NOW)
    assert out["written"] >= 1
    rows = (await db_session.execute(
        select(PumpfunGraduationMark).where(
            PumpfunGraduationMark.minutes_since == 2880))).scalars().all()
    assert len(rows) == 1 and rows[0].mcap_usd == D("5000")
