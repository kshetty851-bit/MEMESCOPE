"""The `slow_daily` rule set: the Donchian entry and trail, the wide stop,
and the exits it does and does not have."""

from __future__ import annotations

import pytest

from app.labs.crypto_trend import config
from app.labs.crypto_trend.regime import CHOP, RISK_OFF, RISK_ON, Regime
from app.labs.crypto_trend.slow_daily import (
    DECISION_TIMEFRAME,
    DailyState,
    advance,
    compute_states,
    decide,
    direction_of,
    entry_candidates,
    exit_reason,
    verdict_of,
)
from app.labs.crypto_trend.strategy import CLOSE, LONG, OPEN, SHORT, Position, Snapshot
from app.labs.crypto_trend.strategy import StrategyConfig as Cfg
from app.labs.crypto_trend.tests.fakes import (
    NOW,
    sideways_closes,
    synthetic_candles,
    uptrend_closes,
)
from app.labs.crypto_trend.trend import DOWN, FLAT, LONG_BIAS, NEUTRAL, SHORT_BIAS, UP

CFG = Cfg()


def ds(direction: str = UP, *, close: float = 110.0, adx: float = 30.0, atr: float = 2.0,
       breakout_high: float = 105.0, breakout_low: float = 90.0,
       exit_high: float = 108.0, exit_low: float = 95.0,
       symbol: str = "AAAUSDT") -> DailyState:
    return DailyState(symbol, "1d", NOW, NOW, direction, close, 100.0, 100.0, adx, atr,
                      breakout_high, breakout_low, exit_high, exit_low, 3)


def snap(states: dict, *, regime: Regime | None = None, universe=None) -> Snapshot:
    default = Regime(NOW, NOW, 10, 0.5, 0.5, FLAT, FLAT, CHOP)
    return Snapshot(NOW, states, {}, regime or default, {}, frozenset(universe or states))


def pos(side: str = LONG, *, entry: float = 100.0, stop_distance: float = 6.0,
        trail: float | None = None, bars: int = 0, symbol: str = "AAAUSDT") -> Position:
    sign = 1.0 if side == LONG else -1.0
    return Position(symbol, side, 1.0, entry, entry - stop_distance * sign, stop_distance,
                    2.0, NOW, bars, entry, trail, entry, 0.1, 0.05, 0.0, "test", 10.0)


def opens(orders):
    return [o for o in orders if o.action == OPEN]


# --- direction and verdict ------------------------------------------------------------

def test_direction_is_ema_only_no_adx_no_structure() -> None:
    assert direction_of(110, 105, 100) == UP      # close and fast above slow
    assert direction_of(99, 105, 100) == FLAT     # close below slow
    assert direction_of(110, 95, 100) == FLAT     # fast below slow
    assert direction_of(90, 95, 100) == DOWN
    assert direction_of(100, 105, 100) == FLAT    # close ON the slow average


def test_the_verdict_is_the_direction() -> None:
    assert verdict_of({"1d": ds(UP)}, "A").verdict == LONG_BIAS
    assert verdict_of({"1d": ds(DOWN)}, "A").verdict == SHORT_BIAS
    assert verdict_of({"1d": ds(FLAT)}, "A").verdict == NEUTRAL
    assert verdict_of({"1d": None}, "A").reason == "no daily state"


# --- the Donchian entry -----------------------------------------------------------------

def test_a_breakout_must_clear_the_prior_channel() -> None:
    assert opens(decide(snap({"A": {"1d": ds(UP, close=106.0, breakout_high=105.0)}}),
                        [], 1000.0, CFG))
    # exactly at the channel is not beyond it
    assert not opens(decide(snap({"A": {"1d": ds(UP, close=105.0, breakout_high=105.0)}}),
                            [], 1000.0, CFG))
    assert not opens(decide(snap({"A": {"1d": ds(UP, close=104.0, breakout_high=105.0)}}),
                            [], 1000.0, CFG))


def test_a_breakout_against_the_trend_is_not_an_entry() -> None:
    # a new 20-day high while the trend reads DOWN
    assert not opens(decide(snap({"A": {"1d": ds(DOWN, close=106.0, breakout_high=105.0)}}),
                            [], 1000.0, CFG))
    # and the mirror: a new low while the trend reads UP
    assert not opens(decide(snap({"A": {"1d": ds(UP, close=89.0, breakout_low=90.0)}}),
                            [], 1000.0, CFG))


def test_shorts_break_the_low_of_the_prior_channel() -> None:
    (order,) = decide(snap({"A": {"1d": ds(DOWN, close=89.0, breakout_low=90.0)}}),
                      [], 1000.0, CFG)
    assert (order.action, order.side) == (OPEN, SHORT)
    assert "20d breakout" in order.reason


def test_the_adx_floor_is_inclusive() -> None:
    assert opens(decide(snap({"A": {"1d": ds(UP, close=106.0, adx=20.0)}}), [], 1000.0, CFG))
    assert not opens(decide(snap({"A": {"1d": ds(UP, close=106.0, adx=19.9)}}), [],
                            1000.0, CFG))


@pytest.mark.parametrize("regime, side_state, expect", [
    (Regime(NOW, NOW, 10, 0.2, 0.2, FLAT, FLAT, RISK_ON), UP, True),
    (Regime(NOW, NOW, 10, 0.40, 0.2, FLAT, FLAT, CHOP), UP, True),
    (Regime(NOW, NOW, 10, 0.39, 0.2, FLAT, FLAT, CHOP), UP, False),
    (Regime(NOW, NOW, 10, 0.2, 0.2, FLAT, FLAT, RISK_OFF), UP, False),
    (Regime(NOW, NOW, 10, 0.2, 0.40, FLAT, FLAT, CHOP), DOWN, True),
    (Regime(NOW, NOW, 10, 0.2, 0.39, FLAT, FLAT, CHOP), DOWN, False),
])
def test_the_regime_gates_entries_on_the_same_thresholds(regime, side_state, expect) -> None:
    state = ds(side_state, close=106.0 if side_state == UP else 89.0)
    orders = decide(snap({"A": {"1d": state}}, regime=regime), [], 1000.0, CFG)
    assert bool(opens(orders)) is expect


def test_there_is_no_btc_alignment_rule() -> None:
    """The 4h strategy refuses longs while BTC is DOWN. This one does not —
    that is the point of the test."""
    hostile = Regime(NOW, NOW, 10, 0.5, 0.5, DOWN, DOWN, CHOP)
    assert opens(decide(snap({"A": {"1d": ds(UP, close=106.0)}}, regime=hostile),
                        [], 1000.0, CFG))


def test_two_entries_per_bar_ranked_by_adx() -> None:
    states = {s: {"1d": ds(UP, close=106.0, adx=a, symbol=s)}
              for s, a in (("A", 25.0), ("B", 40.0), ("C", 33.0))}
    assert [o.symbol for o in opens(decide(snap(states), [], 1000.0, CFG))] == ["B", "C"]


def test_no_same_side_cap_but_the_position_cap_holds() -> None:
    """Four longs held: the 4h strategy's same-side cap would refuse a fifth;
    this rule set takes it, and stops at five positions."""
    states = {s: {"1d": ds(UP, close=106.0, symbol=s)} for s in ("A", "B")}
    held = [pos(LONG, symbol=f"P{i}") for i in range(4)]
    universe = {*states, *(p.symbol for p in held)}
    orders = decide(snap(states, universe=universe), held, 1000.0, CFG)
    assert [o.side for o in opens(orders)] == [LONG]
    held5 = [pos(LONG, symbol=f"P{i}") for i in range(5)]
    universe5 = {*states, *(p.symbol for p in held5)}
    assert not opens(decide(snap(states, universe=universe5), held5, 1000.0, CFG))


def test_sizing_uses_a_three_atr_stop() -> None:
    # ATR 2 -> stop 6 on a 100 close = 6%; 1% of 1,000 / 6% = 166.67 under the 200 cap
    (order,) = decide(snap({"A": {"1d": ds(UP, close=100.0, breakout_high=99.0, atr=2.0)}}),
                      [], 1000.0, CFG)
    assert order.stop_distance == pytest.approx(6.0)
    assert order.notional == pytest.approx(1000 * 0.01 / 0.06)
    assert order.intended_risk_usd == 10.0
    assert order.qty * order.stop_distance == pytest.approx(10.0)


# --- the trail and the exits ---------------------------------------------------------------

def test_the_trail_sits_on_the_ten_day_channel_and_is_not_ratcheted() -> None:
    p = pos(LONG, entry=100.0)
    (p1,) = advance([p], {"AAAUSDT": {"1d": ds(UP, close=112.0, exit_low=104.0)}}, CFG)
    assert p1.trail_stop == 104.0 and p1.best_close == 112.0
    # the channel falls back: the trail follows it down, unlike the 4h trail
    (p2,) = advance([p1], {"AAAUSDT": {"1d": ds(UP, close=111.0, exit_low=101.0)}}, CFG)
    assert p2.trail_stop == 101.0
    assert p2.best_close == 112.0
    # a short trails the upper channel
    short_state = {"AAAUSDT": {"1d": ds(DOWN, close=90.0, exit_high=96.0)}}
    (s1,) = advance([pos(SHORT)], short_state, CFG)
    assert s1.trail_stop == 96.0


def test_the_four_exits_and_their_order() -> None:
    state = ds(UP, close=110.0)
    assert exit_reason(pos(LONG), snap({"AAAUSDT": {"1d": state}}, universe={"X"}),
                       CFG) == "universe_exit"
    assert exit_reason(pos(LONG), snap({"AAAUSDT": {"1d": ds(DOWN, close=110.0)}}),
                       CFG) == "verdict_exit"
    # hard stop: entry 100, 6 wide -> 94
    assert exit_reason(pos(LONG), snap({"AAAUSDT": {"1d": ds(UP, close=94.0)}}),
                       CFG) == "hard_stop"
    trailing = pos(LONG, trail=105.0)
    assert exit_reason(trailing, snap({"AAAUSDT": {"1d": ds(UP, close=105.0)}}),
                       CFG) == "trail_stop"
    assert exit_reason(trailing, snap({"AAAUSDT": {"1d": ds(UP, close=106.0)}}), CFG) is None


def test_a_flat_direction_does_not_exit() -> None:
    """Only a FLIP to the opposite bias closes a position; drifting to FLAT
    leaves it to the stop or the trail."""
    flat = snap({"AAAUSDT": {"1d": ds(FLAT, close=110.0)}})
    assert exit_reason(pos(LONG), flat, CFG) is None


def test_there_is_no_time_stop_and_no_regime_exit() -> None:
    old = pos(LONG, bars=5000)
    assert exit_reason(old, snap({"AAAUSDT": {"1d": ds(UP, close=110.0)}}), CFG) is None
    hostile = Regime(NOW, NOW, 10, 0.9, 0.9, DOWN, DOWN, RISK_OFF)
    assert exit_reason(pos(LONG), snap({"AAAUSDT": {"1d": ds(UP, close=110.0)}},
                                       regime=hostile), CFG) is None


def test_a_close_and_a_reversal_on_the_same_bar() -> None:
    orders = decide(snap({"AAAUSDT": {"1d": ds(DOWN, close=89.0, breakout_low=90.0)}}),
                    [pos(LONG)], 1000.0, CFG)
    assert [(o.action, o.side) for o in orders] == [(CLOSE, LONG), (OPEN, SHORT)]


# --- the series ------------------------------------------------------------------------------

def daily(closes):
    return synthetic_candles(closes, symbol="AAAUSDT", timeframe="1d")


def test_the_series_is_causal_on_every_prefix() -> None:
    candles = daily(uptrend_closes(300))
    series = compute_states("AAAUSDT", "1d", candles, computed_at=NOW)
    for i in range(config.SLOW_DAILY_MIN_BARS, len(candles), 11):
        fresh = compute_states("AAAUSDT", "1d", candles[:i + 1], computed_at=NOW)
        assert fresh[i] == series[i]


def test_the_channels_never_contain_the_bar_they_gate() -> None:
    candles = daily(uptrend_closes(300))
    series = compute_states("AAAUSDT", "1d", candles, computed_at=NOW)
    for i, state in enumerate(series):
        if state is None:
            continue
        prior = candles[max(0, i - config.SLOW_DAILY_ENTRY_DONCHIAN):i]
        assert state.breakout_high == max(float(c.high) for c in prior)
        assert state.breakout_low == min(float(c.low) for c in prior)
        ten = candles[max(0, i - config.SLOW_DAILY_EXIT_DONCHIAN):i]
        assert state.exit_high == max(float(c.high) for c in ten)
        assert state.exit_low == min(float(c.low) for c in ten)


def test_a_rising_series_reads_up_and_breaks_out() -> None:
    series = compute_states("AAAUSDT", "1d", daily(uptrend_closes(300)), computed_at=NOW)
    last = series[-1]
    assert last is not None and last.direction == UP
    assert last.ema_fast > last.ema_slow and last.close > last.ema_slow
    assert any(s.close > s.breakout_high for s in series if s)


def test_a_sideways_series_offers_no_entry_at_all() -> None:
    """Direction still flips on a flat market — the rule has no ADX term in
    it — but nothing clears both the ADX floor and the prior channel, so
    there is never a candidate."""
    series = [s for s in compute_states("AAAUSDT", "1d", daily(sideways_closes(300)),
                                        computed_at=NOW) if s]
    assert series
    for state in series:
        assert not entry_candidates(snap({"AAAUSDT": {"1d": state}}), CFG)


def test_too_little_history_is_no_state() -> None:
    closes = uptrend_closes(config.SLOW_DAILY_MIN_BARS - 1)
    short = compute_states("AAAUSDT", "1d", daily(closes), computed_at=NOW)
    assert all(s is None for s in short)


def test_the_module_exposes_the_replay_interface() -> None:
    from app.labs.crypto_trend import slow_daily, strategy

    for name in ("TIMEFRAMES", "DECISION_TIMEFRAME", "compute_states", "breadth_direction",
                 "verdict_of", "advance", "exit_reason", "decide"):
        assert hasattr(slow_daily, name), name
        assert hasattr(strategy, name), name
    assert slow_daily.TIMEFRAMES == ("1d",) and DECISION_TIMEFRAME == "1d"
    assert strategy.TIMEFRAMES == ("4h", "1h")


# --- end to end through the shared harness ---------------------------------------

def test_the_replay_drives_it_on_daily_bars() -> None:
    """The harness, the account and the costs are the same objects the 4h
    strategy uses; only the rule module and the bars change."""
    from datetime import timedelta

    from app.labs.crypto_trend.candles import to_ms
    from app.labs.crypto_trend.replay import Dataset, run_replay

    end = NOW.replace(hour=0, minute=0, second=0, microsecond=0)
    rising = uptrend_closes(360, up=9, down=3)
    # a rally that rolls over: the positions it opens are closed inside the
    # window, so there are trades to reconcile rather than open positions.
    turning = rising + [rising[-1] - 4.0 * i for i in range(1, 41)]
    candles = {(s, "1d"): synthetic_candles(path, symbol=s, timeframe="1d",
                                            end_ms=to_ms(end))
               for s, path in (("AAAUSDT", turning), ("BBBUSDT", turning),
                               ("CCCUSDT", sideways_closes(400)))}
    dataset = Dataset(candles=candles, funding={}, universe=sorted(s for s, _ in candles),
                      universe_name="synthetic")

    result = run_replay(dataset, start=end - timedelta(days=200), end=end,
                        params={"STRATEGY": "slow_daily", "CHOP_BREADTH_MIN": 0.3})

    assert result.summary["window"]["strategy"] == "slow_daily"
    assert result.trades, "expected the rally to open and the reversal to close"
    assert {t.side for t in result.trades} == {LONG}
    assert not any(t.symbol == "CCCUSDT" for t in result.trades)
    assert {t.reason for t in result.trades} <= {"trail_stop", "hard_stop", "verdict_exit"}
    # every fill is a daily open, and the shared cost model applied
    opens_ = {c.open_time for c in candles[("AAAUSDT", "1d")]}
    assert all(t.opened_at in opens_ for t in result.trades if t.symbol == "AAAUSDT")
    assert all(t.fees > 0 for t in result.trades)
    # three funding settlements a day, not one: a five-day hold pays fifteen
    long_hold = max(result.trades, key=lambda t: t.bars_held)
    assert long_hold.bars_held >= 3
    # a long pays the fallback rate at three settlements a day, so the carry
    # is roughly 3 x 0.0001 x notional x days (the exact figure is pinned in
    # test_replay's first-principles reconciliation).
    rough = 3 * 0.0001 * long_hold.qty * long_hold.entry_price * long_hold.bars_held
    assert long_hold.funding == pytest.approx(rough, rel=0.5)
    assert result.summary["window"]["bars"] > 100


def test_an_unknown_strategy_name_is_refused() -> None:
    from app.labs.crypto_trend.replay import load_strategy

    assert load_strategy("slow_daily").DECISION_TIMEFRAME == "1d"
    assert load_strategy("default").DECISION_TIMEFRAME == "4h"
    with pytest.raises(ValueError, match="unknown strategy"):
        load_strategy("nope")
