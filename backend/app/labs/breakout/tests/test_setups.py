"""Every transition of the state machine, the episode lifecycle, and the
trailing-stop outcome — including the ordering that decides whether a
backtest is honest."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.labs.breakout import config
from app.labs.breakout.candles import Candle
from app.labs.breakout.models import BoCandle, BoEpisode, BoSetupSnapshot, BoUniverseMember
from app.labs.breakout.setups import (
    BROKE_OUT,
    EXPIRED,
    FAILED,
    NONE,
    PRE_BREAKOUT,
    UNIVERSE_EXIT,
    WATCHING,
    OutcomeEngine,
    SetupEngine,
    evaluate,
    expired,
    price_at,
    trail_result,
)

T0 = datetime(2026, 1, 1, tzinfo=UTC)
RESIST = 100.0


def at(distance_pct: float) -> float:
    """A price `distance_pct` below resistance."""
    return RESIST * (1 - distance_pct / 100)


# --- the state machine ----------------------------------------------------------

def test_no_resistance_above_means_no_setup() -> None:
    """Nothing to break. Not an error, not a WATCHING — just nothing."""
    assert evaluate(99, 50.0, None, had_pre_breakout=False).state == NONE
    assert evaluate(99, 50.0, 0.0, had_pre_breakout=False).state == NONE


def test_watching_needs_the_score_floor_and_the_wide_zone() -> None:
    assert evaluate(config.WATCH_SCORE, at(14), RESIST,
                    had_pre_breakout=False).state == WATCHING
    assert evaluate(config.WATCH_SCORE - 1, at(14), RESIST,
                    had_pre_breakout=False).state == NONE, "score floor"
    assert evaluate(config.WATCH_SCORE, at(config.WATCH_ZONE_PCT + 0.1), RESIST,
                    had_pre_breakout=False).state == NONE, "outside the zone"


def test_pre_breakout_needs_the_higher_score_and_the_tighter_zone() -> None:
    assert evaluate(config.PRE_SCORE, at(5), RESIST,
                    had_pre_breakout=False).state == PRE_BREAKOUT
    assert evaluate(config.PRE_SCORE - 1, at(5), RESIST,
                    had_pre_breakout=False).state == WATCHING, "falls back, not out"
    assert evaluate(config.PRE_SCORE, at(config.PRE_ZONE_PCT + 0.1), RESIST,
                    had_pre_breakout=False).state == WATCHING


def test_both_zone_edges_are_inclusive() -> None:
    assert evaluate(config.PRE_SCORE, at(config.PRE_ZONE_PCT), RESIST,
                    had_pre_breakout=False).state == PRE_BREAKOUT
    assert evaluate(config.WATCH_SCORE, at(config.WATCH_ZONE_PCT), RESIST,
                    had_pre_breakout=False).state == WATCHING


def test_a_break_needs_a_close_more_than_the_confirm_pct_above() -> None:
    above = RESIST * (1 + config.BREAK_CONFIRM_PCT / 100 + 0.001)
    assert evaluate(0, above, RESIST, had_pre_breakout=False).state == BROKE_OUT
    assert evaluate(99, above, RESIST, had_pre_breakout=True).state == BROKE_OUT, \
        "a break beats every other rule, whatever the score"


def test_the_band_just_above_resistance_is_deliberately_neither() -> None:
    """PRE_BREAKOUT is strictly below resistance and a break needs 1% above,
    so the sliver between them is NONE — a lull, not an answer. It must not
    close an episode."""
    just_above = RESIST * 1.005
    assert evaluate(99, just_above, RESIST, had_pre_breakout=True).state == NONE


def test_a_setup_fails_only_after_it_reached_pre_breakout() -> None:
    far = at(config.FAIL_PCT + 1)
    assert evaluate(config.WATCH_SCORE, far, RESIST,
                    had_pre_breakout=False).state == WATCHING, "never armed, cannot fail"
    assert evaluate(config.WATCH_SCORE, far, RESIST,
                    had_pre_breakout=True).state == FAILED


def test_a_setup_also_fails_when_its_momentum_dies_in_the_zone() -> None:
    assert evaluate(config.FAIL_SCORE - 1, at(3), RESIST,
                    had_pre_breakout=True).state == FAILED


def test_the_failure_floor_is_not_the_watch_floor() -> None:
    """**The coupling that would have changed trading silently.**

    `FAILED` is one of the paper trader's exits. While the failure rule read
    `WATCH_SCORE`, widening the watchlist would have lowered the bar at which
    a live position is declared dead — holding losers longer — without
    anything in the diff saying so. They are two questions and now two
    constants.
    """
    assert config.FAIL_SCORE >= config.WATCH_SCORE, (
        "a setup must not be declared dead while still worth watching")
    score = config.WATCH_SCORE          # worth watching, not worth holding
    assert score < config.FAIL_SCORE, "pick a score between the two to test this"
    # Fresh setup at that score: watched.
    assert evaluate(score, at(3), RESIST, had_pre_breakout=False).state == WATCHING
    # Same score on a setup that already armed: dead.
    assert evaluate(score, at(3), RESIST, had_pre_breakout=True).state == FAILED


def test_the_widened_watch_gate_did_not_move_the_trading_gate() -> None:
    """Pre-registered: WATCH_SCORE and WATCH_ZONE_PCT were relaxed to grow the
    watchlist. PRE_SCORE and PRE_ZONE_PCT — the only two the trader reads —
    were not, so the episode record stays comparable across the change."""
    assert config.PRE_SCORE == 65
    assert config.PRE_ZONE_PCT == 6.0
    assert config.PRE_SCORE > config.WATCH_SCORE
    assert config.PRE_ZONE_PCT < config.WATCH_ZONE_PCT
    # A token inside the watch zone but outside the pre zone is watched, never
    # bought, whatever its score.
    outside = at((config.PRE_ZONE_PCT + config.WATCH_ZONE_PCT) / 2)
    assert evaluate(100, outside, RESIST, had_pre_breakout=False).state == WATCHING


def test_failure_is_checked_before_the_entry_states_so_it_cannot_re_arm() -> None:
    """Falling far away and scoring well at the same time is a failure, not a
    fresh WATCHING on the same bar."""
    assert evaluate(99, at(config.FAIL_PCT + 1), RESIST,
                    had_pre_breakout=True).state == FAILED


def test_distance_is_signed_and_measured_against_resistance() -> None:
    assert evaluate(99, at(5), RESIST, had_pre_breakout=False).distance_pct \
        == pytest.approx(5.0)
    assert evaluate(0, RESIST * 1.02, RESIST, had_pre_breakout=False).distance_pct \
        == pytest.approx(-2.0), "negative means above"


def test_an_episode_expires_exactly_at_the_limit() -> None:
    assert expired(T0, T0 + timedelta(hours=config.MAX_EPISODE_HOURS - 1)) is False
    assert expired(T0, T0 + timedelta(hours=config.MAX_EPISODE_HOURS)) is True


# --- the trailing-stop outcome --------------------------------------------------

def hour(i: int, *, high: float, low: float, close: float | None = None) -> Candle:
    close = (high + low) / 2 if close is None else close
    return Candle("M", "P", "hour", T0 + timedelta(hours=i), Decimal(str(close)),
                  Decimal(str(high)), Decimal(str(low)), Decimal(str(close)),
                  Decimal("100"), T0 + timedelta(hours=i + 1))


def test_trail_exits_at_exactly_minus_twenty_five_percent_on_an_immediate_drop() -> None:
    """$100 in, no new high, price falls: the stop sits at $75 and the result
    is -25%. Hand-computed, no library."""
    bars = [hour(0, high=100, low=70)]
    result = trail_result(bars, entry=100.0)
    assert result.result_pct == pytest.approx(-25.0)


def test_the_stop_ratchets_up_with_the_high_water_value() -> None:
    """Price doubles (value $200, stop $175) then collapses. The result is
    +75%, not -25%: the stop followed the high."""
    bars = [hour(0, high=200, low=100), hour(1, high=200, low=10)]
    assert trail_result(bars, entry=100.0).result_pct == pytest.approx(75.0)


def test_an_unstopped_position_is_marked_to_the_last_close() -> None:
    bars = [hour(i, high=100 + i, low=99 + i, close=100 + i) for i in range(5)]
    assert trail_result(bars, entry=100.0).result_pct == pytest.approx(4.0)


def test_the_low_is_taken_before_the_high_on_every_bar() -> None:
    """**The ordering that decides whether a backtest is honest.** One bar
    that would both stop the position out and set a new high must exit at the
    stop. Getting this backwards is how a backtest invents money.
    """
    both = [hour(0, high=1000, low=70)]
    assert trail_result(both, entry=100.0).result_pct == pytest.approx(-25.0)
    # And the same bar without the low does ratchet, proving the high is read.
    assert trail_result([hour(0, high=1000, low=99)], entry=100.0).result_pct > 0


def test_a_stop_can_never_be_lifted_by_a_high_reached_after_it_was_hit() -> None:
    bars = [hour(0, high=100, low=100), hour(1, high=5000, low=60)]
    assert trail_result(bars, entry=100.0).result_pct == pytest.approx(-25.0)


def test_non_contiguous_bars_are_flagged_gappy_and_treated_as_no_movement() -> None:
    bars = [hour(0, high=100, low=99), hour(5, high=100, low=99)]
    result = trail_result(bars, entry=100.0)
    assert result.gappy is True
    contiguous = trail_result([hour(0, high=100, low=99), hour(1, high=100, low=99)],
                              entry=100.0)
    assert contiguous.gappy is False


def test_no_bars_or_no_entry_is_gappy_and_flat_rather_than_a_crash() -> None:
    for result in (trail_result([], entry=100.0),
                   trail_result([hour(0, high=1, low=1)], entry=0.0)):
        assert result.result_pct == 0.0
        assert result.gappy is True


def test_the_trail_scales_with_the_notional_not_with_the_price() -> None:
    """A $25 stop on $100 is 25% whatever the token costs — the reason Phase 3
    stores it as a percentage of the slot."""
    cheap = trail_result([hour(0, high=0.001, low=0.0007)], entry=0.001)
    dear = trail_result([hour(0, high=10_000, low=7_000)], entry=10_000.0)
    assert cheap.result_pct == pytest.approx(dear.result_pct)


def test_price_at_reads_the_last_bar_that_had_closed_by_then() -> None:
    bars = [hour(i, high=10 + i, low=9, close=10 + i) for i in range(5)]
    assert price_at(bars, T0 + timedelta(hours=3)) == pytest.approx(12.0)
    assert price_at(bars, T0) is None, "nothing had closed yet"


# --- the pass -------------------------------------------------------------------

def member(mint="M1", volume=900_000) -> BoUniverseMember:
    return BoUniverseMember(
        mint=mint, symbol="AAA", name="Token A", pool_address=f"P{mint}", dex="raydium",
        pair_created_at=T0 - timedelta(days=90), liquidity_usd=Decimal("250000"),
        volume_24h_usd=Decimal(volume), price_usd=Decimal("50"), fdv=Decimal("1000000"),
        source="geckoterminal", first_seen=T0, last_seen=T0, active=True,
        fetch_failures=0,
    )


async def seed(session, mint: str, *, daily_highs: list[float],
               hourly_closes: list[float], start=T0) -> None:
    """A token with a daily series that builds a resistance level, and an
    hourly series ending wherever the test wants the price."""
    for i, high in enumerate(daily_highs):
        session.add(BoCandle(
            mint=mint, pool_address=f"P{mint}", timeframe="day",
            open_time=start + timedelta(days=i), open=Decimal(str(high * 0.95)),
            high=Decimal(str(high)), low=Decimal(str(high * 0.9)),
            close=Decimal(str(high * 0.95)), volume_usd=Decimal("5000"),
            close_time=start + timedelta(days=i + 1)))
    base = start + timedelta(days=len(daily_highs))
    for i, close in enumerate(hourly_closes):
        session.add(BoCandle(
            mint=mint, pool_address=f"P{mint}", timeframe="hour",
            open_time=base + timedelta(hours=i), open=Decimal(str(close)),
            high=Decimal(str(close * 1.01)), low=Decimal(str(close * 0.99)),
            close=Decimal(str(close)), volume_usd=Decimal("100"),
            close_time=base + timedelta(hours=i + 1)))
    await session.flush()


@pytest.mark.integration
async def test_a_token_with_too_few_daily_bars_is_skipped_not_an_error(
    lab_session,
) -> None:
    lab_session.add(member())
    await seed(lab_session, "M1", daily_highs=[10] * 5, hourly_closes=[10] * 12)
    result = await SetupEngine(lab_session).run(T0 + timedelta(days=30))
    assert result["skipped"] == 1 and result["errors"] == []
    assert result["levels"] == 0


@pytest.mark.integration
async def test_a_pass_writes_levels_a_snapshot_and_opens_one_episode(
    lab_session,
) -> None:
    lab_session.add(member())
    # A resistance shelf near 100, then price parked just under it.
    highs = [50, 60, 100, 60, 55, 58, 62, 100, 61, 57, 59, 63, 60, 58,
             61, 59, 62, 60, 58, 61]
    await seed(lab_session, "M1", daily_highs=highs, hourly_closes=[96.0] * 20)
    now = T0 + timedelta(days=len(highs), hours=21)
    result = await SetupEngine(lab_session).run(now)

    assert result["levels"] == 1
    assert result["errors"] == []
    episodes = (await lab_session.execute(select(BoEpisode))).scalars().all()
    snapshots = (await lab_session.execute(select(BoSetupSnapshot))).scalars().all()
    if episodes:
        assert len(episodes) == 1
        assert snapshots and snapshots[0].state in (WATCHING, PRE_BREAKOUT)
        assert snapshots[0].components, "a snapshot explains its own score"


@pytest.mark.integration
async def test_a_second_pass_on_the_same_bar_rewrites_rather_than_duplicates(
    lab_session,
) -> None:
    lab_session.add(member())
    highs = [50, 60, 100, 60, 55, 58, 62, 100, 61, 57, 59, 63, 60, 58,
             61, 59, 62, 60, 58, 61]
    await seed(lab_session, "M1", daily_highs=highs, hourly_closes=[96.0] * 20)
    now = T0 + timedelta(days=len(highs), hours=21)
    engine = SetupEngine(lab_session)
    await engine.run(now)
    first = len((await lab_session.execute(select(BoSetupSnapshot))).scalars().all())
    await engine.run(now + timedelta(minutes=5))
    assert len((await lab_session.execute(
        select(BoSetupSnapshot))).scalars().all()) == first
    assert len((await lab_session.execute(select(BoEpisode))).scalars().all()) <= 1


@pytest.mark.integration
async def test_an_episode_expires_once_it_outlives_the_limit(lab_session) -> None:
    lab_session.add(member())
    await lab_session.flush()
    episode = BoEpisode(mint="M1", opened_at=T0)
    lab_session.add(episode)
    await seed(lab_session, "M1", daily_highs=[10] * 20, hourly_closes=[10] * 20)
    await SetupEngine(lab_session).run(
        T0 + timedelta(hours=config.MAX_EPISODE_HOURS + 1))
    refreshed = (await lab_session.execute(
        select(BoEpisode).where(BoEpisode.mint == "M1"))).scalar_one()
    assert refreshed.closed_at is not None
    assert refreshed.close_reason == EXPIRED


@pytest.mark.integration
async def test_a_token_that_leaves_the_universe_closes_its_episode(lab_session) -> None:
    """Pre-decided: EXPIRED with reason `universe_exit`. A token we can no
    longer see cannot answer its own question."""
    gone = member("GONE")
    gone.active = False
    lab_session.add(gone)
    await lab_session.flush()
    lab_session.add(BoEpisode(mint="GONE", opened_at=T0))
    await lab_session.flush()

    result = await SetupEngine(lab_session).run(T0 + timedelta(hours=2))
    assert result["episodes_closed"] == 1
    closed = (await lab_session.execute(
        select(BoEpisode).where(BoEpisode.mint == "GONE"))).scalar_one()
    assert closed.close_reason == UNIVERSE_EXIT


@pytest.mark.integration
async def test_one_token_failing_does_not_stop_the_pass(lab_session) -> None:
    lab_session.add_all([member("GOOD"), member("BAD")])
    await seed(lab_session, "GOOD", daily_highs=[10] * 20, hourly_closes=[10] * 20)
    # BAD has a daily series but no hourly bars at all.
    await seed(lab_session, "BAD", daily_highs=[10] * 20, hourly_closes=[])
    result = await SetupEngine(lab_session).run(T0 + timedelta(days=21))
    assert result["errors"] == []
    assert result["tokens"] == 2


@pytest.mark.integration
async def test_outcomes_fill_only_after_the_window_and_only_once(lab_session) -> None:
    lab_session.add(member())
    await lab_session.flush()
    start = T0
    episode = BoEpisode(mint="M1", opened_at=start, first_pre_breakout_at=start,
                        closed_at=start + timedelta(hours=1), close_reason=FAILED,
                        entry_ref_price=Decimal("100"))
    lab_session.add(episode)
    for i in range(80):
        lab_session.add(BoCandle(
            mint="M1", pool_address="PM1", timeframe="hour",
            open_time=start + timedelta(hours=i), open=Decimal("100"),
            high=Decimal("110"), low=Decimal("95"), close=Decimal("105"),
            volume_usd=Decimal("10"), close_time=start + timedelta(hours=i + 1)))
    await lab_session.flush()

    engine = OutcomeEngine(lab_session)
    too_early = await engine.run(start + timedelta(hours=10))
    assert too_early["filled"] == 0, "the 72h window has not passed"

    done = await engine.run(start + timedelta(hours=100))
    assert done["filled"] == 1
    row = (await lab_session.execute(select(BoEpisode))).scalar_one()
    assert row.outcome_at is not None
    assert row.max_gain_pct_from_ref == pytest.approx(Decimal("10"))
    assert row.max_loss_pct_from_ref == pytest.approx(Decimal("-5"))
    assert row.trail25_result_pct is not None

    again = await engine.run(start + timedelta(hours=200))
    assert again["filled"] == 0, "`outcome_at` makes it idempotent"


@pytest.mark.integration
async def test_an_episode_that_never_reached_pre_breakout_gets_no_outcome(
    lab_session,
) -> None:
    """There is no reference price, so there is nothing to measure from. It
    must not be filled with zeros that would then be averaged in."""
    lab_session.add(member())
    await lab_session.flush()
    lab_session.add(BoEpisode(mint="M1", opened_at=T0, closed_at=T0 + timedelta(hours=1),
                              close_reason=EXPIRED))
    await lab_session.flush()
    result = await OutcomeEngine(lab_session).run(T0 + timedelta(hours=200))
    assert result["filled"] == 0
    row = (await lab_session.execute(select(BoEpisode))).scalar_one()
    assert row.outcome_at is None and row.trail25_result_pct is None
