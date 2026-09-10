"""Every entry gate, every exit rule, the sizing maths and the caps. Pure."""

from __future__ import annotations

import pytest

from app.labs.crypto_trend.regime import CHOP, RISK_OFF, RISK_ON, Regime
from app.labs.crypto_trend.strategy import (
    CLOSE,
    LONG,
    OPEN,
    SHORT,
    Position,
    Snapshot,
    StrategyConfig,
    advance,
    decide,
    exit_reason,
    size,
)
from app.labs.crypto_trend.tests.fakes import NOW
from app.labs.crypto_trend.trend import DOWN, FLAT, UP, TrendState

CFG = StrategyConfig()


def st(direction: str, *, strength: int = 60, close: float = 100.0, atr_pct: float = 2.0,
       tf: str = "4h", symbol: str = "AAAUSDT") -> TrendState:
    return TrendState(symbol, tf, NOW, NOW, direction, strength, 0.0, atr_pct, 3, close, close,
                      None, 30.0, "MIXED", False, close)


def coin(d4: str | None, d1: str | None = None, **kw) -> dict:
    return {"4h": None if d4 is None else st(d4, **kw),
            "1h": None if d1 is None else st(d1, tf="1h", **kw)}


def reg(regime: str = CHOP, up: float = 0.5, down: float = 0.5,
        btc: str | None = FLAT) -> Regime:
    return Regime(NOW, NOW, 10, up, down, btc, FLAT, regime)


NONE = {"4h": None, "1h": None}


def snap(states: dict, *, previous: dict | None = None, regime: Regime | None = None,
         funding: dict | None = None, universe=None, no_regime: bool = False) -> Snapshot:
    previous = dict.fromkeys(states, NONE) if previous is None else previous
    return Snapshot(NOW, states, previous, None if no_regime else (regime or reg()),
                    funding or {}, frozenset(universe or states))


def pos(symbol: str = "AAAUSDT", side: str = LONG, entry: float = 100.0,
        stop_distance: float = 4.0, qty: float = 1.0, bars: int = 0,
        best: float | None = None, trail: float | None = None) -> Position:
    sign = 1.0 if side == LONG else -1.0
    return Position(symbol, side, qty, entry, entry - stop_distance * sign, stop_distance,
                    stop_distance / 2, NOW, bars, entry if best is None else best, trail,
                    entry * qty, entry * qty / 1000.0, 0.05, 0.0, "test")


def opens(orders):
    return [o for o in orders if o.action == OPEN]


# --- entries ------------------------------------------------------------------------

def test_an_entry_needs_a_verdict_flip_not_a_verdict() -> None:
    flipped = decide(snap({"AAAUSDT": coin(UP, UP)}), [], 1000.0, CFG)
    assert [(o.action, o.side, o.symbol) for o in flipped] == [(OPEN, LONG, "AAAUSDT")]
    steady = decide(snap({"AAAUSDT": coin(UP, UP)}, previous={"AAAUSDT": coin(UP, FLAT)}),
                    [], 1000.0, CFG)
    assert steady == []


def test_a_flip_from_the_other_bias_counts() -> None:
    orders = decide(snap({"AAAUSDT": coin(UP, UP)}, previous={"AAAUSDT": coin(DOWN, DOWN)}),
                    [], 1000.0, CFG)
    assert [o.side for o in opens(orders)] == [LONG]


@pytest.mark.parametrize("regime, expect", [
    (reg(RISK_ON, up=0.2), True), (reg(CHOP, up=0.40), True), (reg(CHOP, up=0.39), False),
    (reg(RISK_OFF, up=0.9), False),
])
def test_regime_gate_for_longs(regime, expect) -> None:
    orders = decide(snap({"AAAUSDT": coin(UP, UP)}, regime=regime), [], 1000.0, CFG)
    assert bool(opens(orders)) is expect


@pytest.mark.parametrize("regime, expect", [
    (reg(RISK_OFF, down=0.2), True), (reg(CHOP, down=0.40), True),
    (reg(CHOP, down=0.39), False), (reg(RISK_ON, down=0.9), False),
])
def test_regime_gate_for_shorts(regime, expect) -> None:
    orders = decide(snap({"AAAUSDT": coin(DOWN, DOWN)}, regime=regime), [], 1000.0, CFG)
    assert bool(opens(orders)) is expect


def test_no_regime_means_no_entries() -> None:
    assert decide(snap({"AAAUSDT": coin(UP, UP)}, no_regime=True), [], 1000.0, CFG) == []


@pytest.mark.parametrize("side_states, btc, expect", [
    (coin(UP, UP), DOWN, False), (coin(UP, UP), UP, True), (coin(UP, UP), None, True),
    (coin(DOWN, DOWN), UP, False), (coin(DOWN, DOWN), DOWN, True),
    (coin(DOWN, DOWN), None, True),
])
def test_never_against_btc(side_states, btc, expect) -> None:
    orders = decide(snap({"AAAUSDT": side_states}, regime=reg(btc=btc)), [], 1000.0, CFG)
    assert bool(opens(orders)) is expect


def test_strength_floor_is_inclusive() -> None:
    weak = decide(snap({"AAAUSDT": coin(UP, UP, strength=39)}), [], 1000.0, CFG)
    ok = decide(snap({"AAAUSDT": coin(UP, UP, strength=40)}), [], 1000.0, CFG)
    assert not opens(weak) and opens(ok)


@pytest.mark.parametrize("funding, expect", [
    ({"AAAUSDT": -0.0004}, False), ({"AAAUSDT": -0.0003}, True), ({}, True),
])
def test_shorts_paying_heavily_are_skipped(funding, expect) -> None:
    orders = decide(snap({"AAAUSDT": coin(DOWN, DOWN)}, funding=funding), [], 1000.0, CFG)
    assert bool(opens(orders)) is expect
    # longs never look at funding
    longs = decide(snap({"AAAUSDT": coin(UP, UP)}, funding={"AAAUSDT": -0.01}), [],
                   1000.0, CFG)
    assert opens(longs)


UNIVERSE = {"AAAUSDT", "BBBUSDT", *(f"P{i}USDT" for i in range(5))}


def test_position_caps() -> None:
    """The held symbols are in the universe, or the universe exit would
    close them and free the slots — which is a rule, not a loophole."""
    others = [pos(f"P{i}USDT") for i in range(5)]
    assert not opens(decide(snap({"AAAUSDT": coin(UP, UP)}, universe=UNIVERSE), others,
                            1000.0, CFG))
    # one per symbol: a LONG already held on the coin whose verdict flips long
    # (a SHORT held there would be reversed, which is its own test above)
    held = [pos("AAAUSDT", LONG)]
    assert decide(snap({"AAAUSDT": coin(UP, UP)}, universe=UNIVERSE), held, 1000.0, CFG) == []
    four_longs = [pos(f"P{i}USDT", LONG) for i in range(4)]
    assert not opens(decide(snap({"AAAUSDT": coin(UP, UP)}, universe=UNIVERSE), four_longs,
                            1000.0, CFG))
    short_ok = decide(snap({"AAAUSDT": coin(DOWN, DOWN)}, universe=UNIVERSE), four_longs,
                      1000.0, CFG)
    assert [o.side for o in opens(short_ok)] == [SHORT]


def test_a_position_outside_the_universe_is_closed_and_frees_its_slot() -> None:
    others = [pos(f"P{i}USDT") for i in range(5)]
    orders = decide(snap({"AAAUSDT": coin(UP, UP)}), others, 1000.0, CFG)
    assert [o.reason for o in orders if o.action == CLOSE] == ["universe_exit"] * 5
    assert [o.symbol for o in opens(orders)] == ["AAAUSDT"]


def test_the_strongest_candidate_takes_the_last_slot() -> None:
    states = {"AAAUSDT": coin(UP, UP, strength=50, symbol="AAAUSDT"),
              "BBBUSDT": coin(UP, UP, strength=80, symbol="BBBUSDT")}
    # two longs and two shorts held: one slot left and the long-side cap not binding
    held = [pos(f"P{i}USDT", LONG if i < 2 else SHORT) for i in range(4)]
    orders = decide(snap(states, universe=UNIVERSE), held, 1000.0, CFG)
    assert [o.symbol for o in opens(orders)] == ["BBBUSDT"]


def test_a_close_frees_the_slot_and_the_symbol_on_the_same_bar() -> None:
    """A long being closed by the regime and a fresh SHORT_BIAS flip on the
    same coin: both fill at the next open, so the reversal is allowed."""
    orders = decide(snap({"AAAUSDT": coin(DOWN, DOWN)}, previous={"AAAUSDT": coin(UP, UP)},
                         regime=reg(RISK_OFF)), [pos("AAAUSDT", LONG)], 1000.0, CFG)
    assert [(o.action, o.side) for o in orders] == [(CLOSE, LONG), (OPEN, SHORT)]
    assert orders[0].reason == "regime_exit"


# --- sizing -------------------------------------------------------------------------

def test_sizing_math_capped_and_uncapped() -> None:
    # stop 2 x 2 = 4 (4%); 1% of 1,000 / 4% = 250 -> capped at 20% = 200
    capped = size(1000.0, 100.0, 2.0, CFG)
    assert (capped.stop_distance, capped.notional, capped.qty, capped.implied_leverage) == (
        4.0, 200.0, 2.0, 0.2)
    # stop 2 x 5 = 10 (10%); 10 / 10% = 100 -> under the cap
    free = size(1000.0, 100.0, 5.0, CFG)
    assert (free.stop_distance, free.notional, free.qty, free.implied_leverage) == (
        10.0, 100.0, 1.0, 0.1)
    assert size(1000.0, 100.0, 0.0, CFG) is None
    assert size(0.0, 100.0, 2.0, CFG) is None


def test_the_order_carries_its_size_and_a_reason() -> None:
    (order,) = decide(snap({"AAAUSDT": coin(UP, UP, close=100.0, atr_pct=5.0)}),
                      [], 1000.0, CFG)
    assert (order.qty, order.stop_distance, order.notional, order.implied_leverage) == (
        1.0, 10.0, 100.0, 0.1)
    assert order.atr == 5.0 and order.reference_price == 100.0
    assert order.reason.startswith("verdict flip to LONG_BIAS, strength 60, regime CHOP")


# --- exits ----------------------------------------------------------------------------

def test_universe_exit() -> None:
    s = snap({"AAAUSDT": coin(UP, UP)}, universe={"BBBUSDT"})
    assert exit_reason(pos(), s, CFG) == "universe_exit"


def test_regime_exit_is_side_specific() -> None:
    assert exit_reason(pos(side=LONG), snap({"AAAUSDT": coin(UP, UP)}, regime=reg(RISK_OFF)),
                       CFG) == "regime_exit"
    short_in_risk_on = snap({"AAAUSDT": coin(DOWN, DOWN)}, regime=reg(RISK_ON))
    assert exit_reason(pos(side=SHORT), short_in_risk_on, CFG) == "regime_exit"
    assert exit_reason(pos(side=LONG), snap({"AAAUSDT": coin(UP, UP)}, regime=reg(RISK_ON)),
                       CFG) is None


def test_verdict_exit_needs_the_opposite_bias_not_neutral() -> None:
    assert exit_reason(pos(side=LONG), snap({"AAAUSDT": coin(DOWN, DOWN)}),
                       CFG) == "verdict_exit"
    assert exit_reason(pos(side=LONG), snap({"AAAUSDT": coin(FLAT, DOWN)}), CFG) is None
    assert exit_reason(pos(side=SHORT), snap({"AAAUSDT": coin(UP, FLAT)}),
                       CFG) == "verdict_exit"


def test_hard_stop_on_the_close() -> None:
    p = pos(side=LONG, entry=100.0, stop_distance=4.0)  # stop 96
    assert exit_reason(p, snap({"AAAUSDT": coin(UP, UP, close=96.0)}), CFG) == "hard_stop"
    assert exit_reason(p, snap({"AAAUSDT": coin(UP, UP, close=96.5)}), CFG) is None
    s = pos(side=SHORT, entry=100.0, stop_distance=4.0)  # stop 104
    assert exit_reason(s, snap({"AAAUSDT": coin(DOWN, DOWN, close=104.0)}), CFG) == "hard_stop"


def test_trail_stop_on_the_close() -> None:
    p = pos(side=LONG, entry=100.0, best=115.0, trail=110.0)
    assert exit_reason(p, snap({"AAAUSDT": coin(UP, UP, close=110.0)}), CFG) == "trail_stop"
    assert exit_reason(p, snap({"AAAUSDT": coin(UP, UP, close=110.5)}), CFG) is None


def test_time_stop_only_when_under_water() -> None:
    assert exit_reason(pos(bars=60), snap({"AAAUSDT": coin(UP, UP, close=99.0)}),
                       CFG) == "time_stop"
    assert exit_reason(pos(bars=60), snap({"AAAUSDT": coin(UP, UP, close=101.0)}), CFG) is None
    assert exit_reason(pos(bars=59), snap({"AAAUSDT": coin(UP, UP, close=99.0)}), CFG) is None


def test_exit_priority_and_a_missing_state() -> None:
    s = snap({"AAAUSDT": coin(DOWN, DOWN, close=50.0)}, regime=reg(RISK_OFF), universe={"X"})
    assert exit_reason(pos(), s, CFG) == "universe_exit"
    s = snap({"AAAUSDT": coin(DOWN, DOWN, close=50.0)}, regime=reg(RISK_OFF))
    assert exit_reason(pos(), s, CFG) == "regime_exit"
    s = snap({"AAAUSDT": coin(DOWN, DOWN, close=50.0)})
    assert exit_reason(pos(), s, CFG) == "verdict_exit"
    # no 4h state: nothing price-based can fire
    assert exit_reason(pos(bars=99), snap({"AAAUSDT": {"4h": None, "1h": None}}), CFG) is None


# --- between bars -------------------------------------------------------------------------

def test_advance_counts_bars_and_arms_the_trail() -> None:
    p = pos(side=LONG, entry=100.0, stop_distance=4.0)  # atr_at_entry 2 -> trigger at +3
    (p1,) = advance([p], {"AAAUSDT": coin(UP, close=102.0)}, CFG)
    assert (p1.bars_held, p1.best_close, p1.trail_stop) == (1, 102.0, None)
    (p2,) = advance([p1], {"AAAUSDT": coin(UP, close=103.0, atr_pct=2.0)}, CFG)
    # armed: best 103, current ATR 2.06 -> 103 - 2.5 x 2.06
    assert p2.trail_stop == pytest.approx(103.0 - 2.5 * 2.06)
    (p3,) = advance([p2], {"AAAUSDT": coin(UP, close=101.0, atr_pct=2.0)}, CFG)
    assert p3.best_close == 103.0 and p3.trail_stop >= p2.trail_stop  # never loosens
    (p4,) = advance([p3], {"AAAUSDT": coin(UP, close=110.0, atr_pct=2.0)}, CFG)
    assert p4.trail_stop == pytest.approx(110.0 - 2.5 * 2.2)


def test_advance_for_a_short_mirrors() -> None:
    p = pos(side=SHORT, entry=100.0, stop_distance=4.0)
    (p1,) = advance([p], {"AAAUSDT": coin(DOWN, close=97.0, atr_pct=2.0)}, CFG)
    assert p1.best_close == 97.0
    assert p1.trail_stop == pytest.approx(97.0 + 2.5 * 1.94)
    (p2,) = advance([p1], {"AAAUSDT": coin(DOWN, close=99.0, atr_pct=2.0)}, CFG)
    assert p2.trail_stop <= p1.trail_stop


def test_advance_without_a_state_only_counts() -> None:
    (p1,) = advance([pos(best=105.0, trail=101.0)], {"AAAUSDT": {"4h": None, "1h": None}}, CFG)
    assert (p1.bars_held, p1.best_close, p1.trail_stop) == (1, 105.0, 101.0)


# --- the correlation guard (Phase 3.1) --------------------------------------------

def three_flips() -> dict:
    return {s: coin(UP, UP, strength=st_, symbol=s)
            for s, st_ in (("AAAUSDT", 70), ("BBBUSDT", 90), ("CCCUSDT", 80))}


def test_at_most_two_new_entries_per_bar_strongest_first() -> None:
    orders = decide(snap(three_flips()), [], 1000.0, CFG)
    assert [o.symbol for o in opens(orders)] == ["BBBUSDT", "CCCUSDT"]


def test_the_entry_cap_is_configurable_and_never_exceeds_the_room() -> None:
    one = StrategyConfig(max_new_entries_per_bar=1)
    only_one = decide(snap(three_flips()), [], 1000.0, one)
    assert [o.symbol for o in opens(only_one)] == ["BBBUSDT"]
    five = StrategyConfig(max_new_entries_per_bar=5)
    assert len(opens(decide(snap(three_flips()), [], 1000.0, five))) == 3
    # four held of five: the room, not the cap, is the limit
    held = [pos(f"P{i}USDT", LONG if i < 2 else SHORT) for i in range(4)]
    universe = set(three_flips()) | {p.symbol for p in held}
    assert len(opens(decide(snap(three_flips(), universe=universe), held, 1000.0, five))) == 1


def test_size_reports_intended_and_actual_risk() -> None:
    capped = size(1000.0, 100.0, 2.0, CFG)   # notional capped at 200
    assert (capped.intended_risk_usd, capped.risk_usd) == (10.0, 8.0)
    free = size(1000.0, 100.0, 5.0, CFG)     # under the cap
    assert (free.intended_risk_usd, free.risk_usd) == (10.0, 10.0)
    (order,) = decide(snap({"AAAUSDT": coin(UP, UP, close=100.0, atr_pct=2.0)}), [],
                      1000.0, CFG)
    assert order.intended_risk_usd == 10.0 and order.qty * order.stop_distance == 8.0
