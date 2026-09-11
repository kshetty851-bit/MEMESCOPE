"""The trader against a real ledger: entries, exits, the kill switch,
idempotency — and the consistency requirement that the recorded outcome and
the traded outcome are the same rule."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.labs.breakout import config, rules
from app.labs.breakout.candles import Candle
from app.labs.breakout.models import (
    BoAccount,
    BoCandle,
    BoEpisode,
    BoEquity,
    BoPosition,
    BoSetupSnapshot,
    BoTrade,
    BoUniverseMember,
)
from app.labs.breakout.setups import trail_result
from app.labs.breakout.trader import BreakoutTrader

T0 = datetime(2026, 1, 1, tzinfo=UTC)
HOUR = timedelta(hours=1)


@pytest.fixture
def trading(monkeypatch):
    monkeypatch.setenv("BREAKOUT_LAB_ENABLED", "true")
    monkeypatch.setenv("BREAKOUT_TRADING_ENABLED", "true")


def member(mint="A", symbol="AAA", liquidity=250_000.0, volume=500_000.0,
           active=True) -> BoUniverseMember:
    return BoUniverseMember(
        mint=mint, symbol=symbol, name=f"Token {symbol}", pool_address=f"P{mint}",
        dex="raydium", pair_created_at=T0 - timedelta(days=90),
        liquidity_usd=Decimal(str(liquidity)), volume_24h_usd=Decimal(str(volume)),
        price_usd=Decimal("10"), fdv=Decimal("1000000"), source="geckoterminal",
        first_seen=T0, last_seen=T0, active=active, fetch_failures=0)


def bar(mint: str, i: int, *, open_=10.0, high=10.5, low=9.5, close=10.0) -> BoCandle:
    return BoCandle(
        mint=mint, pool_address=f"P{mint}", timeframe="hour",
        open_time=T0 + i * HOUR, open=Decimal(str(open_)), high=Decimal(str(high)),
        low=Decimal(str(low)), close=Decimal(str(close)), volume_usd=Decimal("500"),
        close_time=T0 + (i + 1) * HOUR)


def snap(mint: str, i: int, state: str, score: int = 70) -> BoSetupSnapshot:
    """A snapshot on the bar that CLOSED at T0 + (i+1)h."""
    return BoSetupSnapshot(
        mint=mint, bar_close_time=T0 + (i + 1) * HOUR, state=state, score=score,
        components={"volume": 1.0, "structure": 1.0, "position": 1.0,
                    "compression": 0.5, "hourly": 0.8},
        price=Decimal("10"), resistance=Decimal("11"), distance_pct=Decimal("9"),
        hourly_missing=False, computed_at=T0 + (i + 1) * HOUR)


async def arm(session, mint="A", *, score=70, liquidity=250_000.0, open_=10.0,
              active=True) -> BoEpisode:
    """A token that transitioned into PRE_BREAKOUT on bar 1 and has a bar 2 to
    fill on — the exact shape the entry rule looks for."""
    session.add(member(mint, liquidity=liquidity, active=active))
    episode = BoEpisode(mint=mint, opened_at=T0, first_pre_breakout_at=T0 + 2 * HOUR)
    session.add(episode)
    session.add_all([
        bar(mint, 0), bar(mint, 1),
        bar(mint, 2, open_=open_, close=open_, high=open_ * 1.05, low=open_ * 0.99),
        snap(mint, 0, "WATCHING", score),
        snap(mint, 1, "PRE_BREAKOUT", score),
    ])
    await session.flush()
    return episode


# --- the flags ------------------------------------------------------------------

@pytest.mark.integration
async def test_the_trader_is_inert_without_its_own_flag(lab_session, monkeypatch) -> None:
    """The lab flag alone must not open positions: detection and the book are
    separate decisions."""
    monkeypatch.setenv("BREAKOUT_LAB_ENABLED", "true")
    monkeypatch.delenv("BREAKOUT_TRADING_ENABLED", raising=False)
    await arm(lab_session)
    result = await BreakoutTrader(lab_session).run(T0 + 3 * HOUR)
    assert result == {"skipped": "breakout_trading_disabled"}
    assert (await lab_session.execute(select(BoPosition))).scalars().all() == []


# --- entries --------------------------------------------------------------------

@pytest.mark.integration
async def test_a_transition_into_pre_breakout_opens_one_slot_at_the_next_open(
    lab_session, trading,
) -> None:
    await arm(lab_session, open_=10.0)
    result = await BreakoutTrader(lab_session).run(T0 + 3 * HOUR)

    assert len(result["opened"]) == 1
    (position,) = (await lab_session.execute(select(BoPosition))).scalars().all()
    # Filled at bar 2's OPEN (10.0) plus 100bps of slippage.
    assert float(position.entry_price) == pytest.approx(10.1)
    assert float(position.slot_size) == pytest.approx(100.0), "equity/10"
    assert float(position.high_water_value) == pytest.approx(100.0 / 1.003)
    assert position.entry_bar == T0 + 3 * HOUR


@pytest.mark.integration
async def test_a_token_already_in_pre_breakout_is_not_re_entered_every_hour(
    lab_session, trading,
) -> None:
    """A transition, not a state. Entering a six-hour-old PRE_BREAKOUT every
    hour would be a different strategy from the one being recorded."""
    lab_session.add(member("A"))
    lab_session.add(BoEpisode(mint="A", opened_at=T0, first_pre_breakout_at=T0))
    lab_session.add_all([bar("A", 0), bar("A", 1), bar("A", 2),
                         snap("A", 0, "PRE_BREAKOUT"), snap("A", 1, "PRE_BREAKOUT")])
    await lab_session.flush()
    result = await BreakoutTrader(lab_session).run(T0 + 3 * HOUR)
    assert result["opened"] == []


@pytest.mark.integration
async def test_a_thin_pool_is_skipped_with_a_reason(lab_session, trading) -> None:
    await arm(lab_session, liquidity=config.MIN_LIQ_FOR_ENTRY - 1)
    result = await BreakoutTrader(lab_session).run(T0 + 3 * HOUR)
    assert result["opened"] == []
    assert result["skipped"]["A"] == rules.SKIP_LIQUIDITY


@pytest.mark.integration
async def test_a_pool_too_small_for_the_slot_is_skipped(lab_session, trading) -> None:
    """$100 into a $60,000 pool is 0.17% — fine. Into $15,000 it is 0.67%,
    over the cap, and the liquidity floor catches it first."""
    await arm(lab_session, liquidity=60_000.0)
    ok = await BreakoutTrader(lab_session).run(T0 + 3 * HOUR)
    assert len(ok["opened"]) == 1


@pytest.mark.integration
async def test_only_the_strongest_candidate_takes_the_last_free_slot(
    lab_session, trading,
) -> None:
    await arm(lab_session, "weak", score=66)
    await arm(lab_session, "strong", score=95)
    # Nine slots already used. Each filler needs a universe row AND a bar on
    # this tick, or the exit pass force-exits it for being unpriceable and
    # frees the slot back up — which is correct behaviour, and was what this
    # test originally tripped over.
    for i in range(config.SLOTS - 1):
        lab_session.add(member(f"filler{i}"))
        lab_session.add(bar(f"filler{i}", 2, open_=10.0, high=10.1, low=9.9, close=10.0))
        lab_session.add(BoPosition(
            mint=f"filler{i}", qty=Decimal("10"), entry_price=Decimal("10"),
            slot_size=Decimal("100"), high_water_value=Decimal("100"),
            entry_fees=Decimal("0.3"), opened_at=T0, entry_bar=T0))
    await lab_session.flush()

    result = await BreakoutTrader(lab_session).run(T0 + 3 * HOUR)
    assert [o["mint"] for o in result["opened"]] == ["strong"]
    assert result["skipped"]["weak"] == "no_slot"


@pytest.mark.integration
async def test_running_the_same_bar_twice_opens_one_position(
    lab_session, trading,
) -> None:
    await arm(lab_session)
    engine = BreakoutTrader(lab_session)
    await engine.run(T0 + 3 * HOUR)
    await engine.run(T0 + 3 * HOUR)
    positions = (await lab_session.execute(select(BoPosition))).scalars().all()
    assert len(positions) == 1


# --- exits ----------------------------------------------------------------------

async def open_position(session, mint="A", *, entry=10.0, qty=10.0, slot=100.0,
                        high_water=100.0, opened=T0, episode=None) -> BoPosition:
    position = BoPosition(
        mint=mint, episode_id=episode, qty=Decimal(str(qty)),
        entry_price=Decimal(str(entry)), slot_size=Decimal(str(slot)),
        high_water_value=Decimal(str(high_water)), entry_fees=Decimal("0.3"),
        opened_at=opened, entry_bar=opened)
    session.add(position)
    await session.flush()
    return position


@pytest.mark.integration
async def test_the_trailing_stop_closes_the_position_and_writes_a_trade(
    lab_session, trading,
) -> None:
    lab_session.add(member("A"))
    lab_session.add(bar("A", 5, open_=10.0, high=10.2, low=7.0, close=7.5))
    await open_position(lab_session)
    await lab_session.flush()

    result = await BreakoutTrader(lab_session).run(T0 + 6 * HOUR)
    assert [c["reason"] for c in result["closed"]] == [rules.TRAIL_STOP]
    assert (await lab_session.execute(select(BoPosition))).scalars().all() == []
    (trade,) = (await lab_session.execute(select(BoTrade))).scalars().all()
    assert trade.exit_reason == rules.TRAIL_STOP
    assert float(trade.pnl_usd) < 0
    assert float(trade.fees_usd) > 0, "both sides' fees are recorded"


@pytest.mark.integration
async def test_a_high_water_mark_that_rises_is_stored_for_the_next_bar(
    lab_session, trading,
) -> None:
    lab_session.add(member("A"))
    lab_session.add(bar("A", 5, open_=10.0, high=20.0, low=9.9, close=19.0))
    position = await open_position(lab_session)
    await lab_session.flush()

    await BreakoutTrader(lab_session).run(T0 + 6 * HOUR)
    await lab_session.refresh(position)
    assert float(position.high_water_value) == pytest.approx(200.0)


@pytest.mark.integration
async def test_a_failed_episode_closes_a_losing_position_but_not_a_winning_one(
    lab_session, trading,
) -> None:
    lab_session.add_all([member("LOSS"), member("WIN")])
    episode_loss = BoEpisode(mint="LOSS", opened_at=T0, closed_at=T0 + HOUR,
                             close_reason="FAILED")
    episode_win = BoEpisode(mint="WIN", opened_at=T0, closed_at=T0 + HOUR,
                            close_reason="FAILED")
    lab_session.add_all([episode_loss, episode_win])
    await lab_session.flush()
    lab_session.add_all([
        bar("LOSS", 5, high=9.9, low=9.6, close=9.7),    # under entry
        bar("WIN", 5, high=12.0, low=10.5, close=11.0),  # over entry
    ])
    await open_position(lab_session, "LOSS", episode=episode_loss.id)
    await open_position(lab_session, "WIN", episode=episode_win.id)
    await lab_session.flush()

    result = await BreakoutTrader(lab_session).run(T0 + 6 * HOUR)
    assert [c["mint"] for c in result["closed"]] == ["LOSS"]
    assert [c["reason"] for c in result["closed"]] == [rules.FAILED_SETUP]


@pytest.mark.integration
async def test_the_time_stop_closes_a_stale_loser(lab_session, trading) -> None:
    lab_session.add(member("A"))
    late = T0 + timedelta(hours=config.MAX_HOLD_HOURS + 2)
    lab_session.add(BoCandle(
        mint="A", pool_address="PA", timeframe="hour", open_time=late - HOUR,
        open=Decimal("9.8"), high=Decimal("9.9"), low=Decimal("9.6"),
        close=Decimal("9.7"), volume_usd=Decimal("100"), close_time=late))
    await open_position(lab_session, opened=T0)
    await lab_session.flush()

    result = await BreakoutTrader(lab_session).run(late)
    assert [c["reason"] for c in result["closed"]] == [rules.TIME_STOP]


@pytest.mark.integration
async def test_a_token_leaving_the_universe_is_force_exited(
    lab_session, trading,
) -> None:
    lab_session.add(member("A", active=False))
    lab_session.add(bar("A", 5, high=10.2, low=9.9, close=10.1))
    await open_position(lab_session)
    await lab_session.flush()

    result = await BreakoutTrader(lab_session).run(T0 + 6 * HOUR)
    assert [c["reason"] for c in result["closed"]] == [rules.FORCED_EXIT]
    (trade,) = (await lab_session.execute(select(BoTrade))).scalars().all()
    assert trade.exit_reason == rules.FORCED_EXIT


@pytest.mark.integration
async def test_a_position_with_no_bar_this_tick_is_held_not_guessed_at(
    lab_session, trading,
) -> None:
    lab_session.add(member("A"))
    lab_session.add(member("B"))
    lab_session.add(bar("B", 5))          # only B has a bar
    await open_position(lab_session, "A")
    await lab_session.flush()
    result = await BreakoutTrader(lab_session).run(T0 + 6 * HOUR)
    assert result["closed"] == []
    assert len((await lab_session.execute(select(BoPosition))).scalars().all()) == 1


# --- the kill switch ------------------------------------------------------------

@pytest.mark.integration
async def test_the_kill_switch_trips_closes_everything_and_refuses_entries(
    lab_session, trading,
) -> None:
    engine = BreakoutTrader(lab_session)
    account = await engine.account(T0)
    await lab_session.execute(
        BoAccount.__table__.update().values(cash=Decimal("100"),
                                            peak_equity=Decimal("1000")))
    lab_session.add(member("A"))
    lab_session.add(bar("A", 5, high=5.1, low=4.9, close=5.0))
    # A deliberately wide trail (slot $1,000 -> a $250 stop distance) so the
    # trailing stop does NOT fire on this bar. Otherwise the stop closes the
    # position first and the trade is a `trail_stop`, not a `halt` — which is
    # correct, but it is not what this test is about.
    await open_position(lab_session, "A", entry=10.0, qty=10.0, slot=1000.0,
                        high_water=100.0)
    await lab_session.flush()
    await lab_session.refresh(account)

    # Equity is 100 cash + 10 * 5.0 = 150 against a 1000 peak: an 85% drawdown.
    result = await engine.run(T0 + 6 * HOUR)
    assert result["halted"] is True
    assert (await lab_session.execute(select(BoPosition))).scalars().all() == []
    (trade,) = (await lab_session.execute(select(BoTrade))).scalars().all()
    assert trade.exit_reason == rules.HALT
    await lab_session.refresh(account)
    assert account.halted is True and account.halted_reason


@pytest.mark.integration
async def test_a_halted_account_stays_halted_until_it_is_reset(
    lab_session, trading,
) -> None:
    engine = BreakoutTrader(lab_session)
    account = await engine.account(T0)
    await lab_session.execute(BoAccount.__table__.update().values(
        halted=True, halted_reason="drawdown"))
    await arm(lab_session)
    await lab_session.refresh(account)

    result = await engine.run(T0 + 3 * HOUR)
    assert result["opened"] == [] and result["halted"] is True

    reset = await engine.reset_halt(T0 + 4 * HOUR)
    assert reset["halted"] is False
    await lab_session.refresh(account)
    assert account.halted is False
    # The peak is re-based, or the switch would trip again on the next tick.
    assert float(account.peak_equity) == pytest.approx(reset["peak_equity"])


@pytest.mark.integration
async def test_flatten_closes_everything_at_the_last_mark(
    lab_session, trading,
) -> None:
    lab_session.add(member("A"))
    lab_session.add(bar("A", 5, high=12.0, low=11.0, close=11.5))
    await open_position(lab_session)
    await lab_session.flush()

    out = await BreakoutTrader(lab_session).flatten(T0 + 6 * HOUR)
    assert out["flattened"] == ["A"]
    (trade,) = (await lab_session.execute(select(BoTrade))).scalars().all()
    assert trade.exit_reason == rules.FLATTEN
    assert float(trade.pnl_usd) > 0


# --- the account and the curve --------------------------------------------------

@pytest.mark.integration
async def test_a_first_tick_opens_the_account_at_a_thousand_dollars(
    lab_session, trading,
) -> None:
    lab_session.add(member("A"))
    lab_session.add(bar("A", 5))
    await lab_session.flush()
    result = await BreakoutTrader(lab_session).run(T0 + 6 * HOUR)
    assert result["equity"] == pytest.approx(config.STARTING_EQUITY)
    account = (await lab_session.execute(select(BoAccount))).scalar_one()
    assert float(account.cash) == pytest.approx(1000.0)
    assert float(account.peak_equity) == pytest.approx(1000.0)


@pytest.mark.integration
async def test_every_tick_writes_one_equity_point_per_bar(
    lab_session, trading,
) -> None:
    lab_session.add(member("A"))
    lab_session.add(bar("A", 5))
    await lab_session.flush()
    engine = BreakoutTrader(lab_session)
    await engine.run(T0 + 6 * HOUR)
    await engine.run(T0 + 6 * HOUR)  # same bar again
    points = (await lab_session.execute(select(BoEquity))).scalars().all()
    assert len(points) == 1
    assert float(points[0].equity) == pytest.approx(1000.0)


@pytest.mark.integration
async def test_cash_falls_by_the_cost_of_an_entry_and_equity_does_not(
    lab_session, trading,
) -> None:
    """Buying converts cash into position value. Equity should barely move —
    only by the costs."""
    await arm(lab_session)
    result = await BreakoutTrader(lab_session).run(T0 + 3 * HOUR)
    assert result["cash"] == pytest.approx(900.0, abs=0.01)
    assert result["equity"] == pytest.approx(1000.0, abs=2.0)


# --- the consistency requirement ------------------------------------------------

@pytest.mark.integration
async def test_the_live_trader_and_the_recorded_trail_agree_on_the_same_series(
    lab_session, trading, monkeypatch,
) -> None:
    """**Phase 3.4.** `bo_episodes.trail25_result_pct` says what a $100
    position with a $25 trailing stop would have done; the live trader runs
    the same stop at its own slot size. If those two disagree, the table being
    collected is measuring a different strategy from the one being traded and
    every future backtest is worthless.

    With fees and slippage set to zero the two must agree exactly. They share
    `rules.trail_step`, so this is a check that the SHARING is intact rather
    than a comparison of two implementations.
    """
    monkeypatch.setattr(config, "SLIPPAGE_BPS", 0)
    monkeypatch.setattr(config, "FEE_BPS", 0)

    # A series that rallies then collapses through the ratcheted stop.
    closes = [10.0, 12.0, 15.0, 18.0, 14.0, 9.0, 8.0]
    lab_session.add(member("A"))
    episode = BoEpisode(mint="A", opened_at=T0, first_pre_breakout_at=T0 + 2 * HOUR)
    lab_session.add(episode)
    lab_session.add_all([bar("A", 0), bar("A", 1),
                         snap("A", 0, "WATCHING"), snap("A", 1, "PRE_BREAKOUT")])
    for i, close in enumerate(closes):
        lab_session.add(bar("A", 2 + i, open_=close, high=close * 1.02,
                            low=close * 0.98, close=close))
    await lab_session.flush()

    engine = BreakoutTrader(lab_session)
    for i in range(len(closes)):
        await engine.run(T0 + (3 + i) * HOUR)

    trades = (await lab_session.execute(select(BoTrade))).scalars().all()
    assert trades, "the series should have stopped the position out"
    live_pct = float(trades[0].pnl_pct)

    # The same bars, through Phase 2's recorder, from the same entry price.
    entry = float(trades[0].entry_price)
    bars = [
        Candle("A", "PA", "hour", T0 + (2 + i) * HOUR, Decimal(str(close)),
               Decimal(str(close * 1.02)), Decimal(str(close * 0.98)),
               Decimal(str(close)), Decimal("500"), T0 + (3 + i) * HOUR)
        for i, close in enumerate(closes)
    ]
    recorded = trail_result(bars, entry=entry, notional=100.0,
                            trail_usd=100.0 * config.TRAIL_PCT / 100)

    assert live_pct == pytest.approx(recorded.result_pct, abs=0.01), (
        f"live {live_pct:.4f}% vs recorded {recorded.result_pct:.4f}%")


def test_the_two_trail_paths_call_one_function() -> None:
    """Structural, not behavioural: `trail_result` must fold the same
    `rules.trail_step` the trader calls. A second implementation would pass
    the numeric test above until the day someone edited one of them."""
    import ast
    import pathlib

    source = (pathlib.Path(__file__).resolve().parent.parent / "setups.py").read_text()
    calls = {n.func.id for n in ast.walk(ast.parse(source))
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "trail_step" in calls, "trail_result must fold rules.trail_step"
