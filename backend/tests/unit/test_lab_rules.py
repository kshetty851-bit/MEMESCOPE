"""Entry and exit evaluation — the ENGINE, independent of any registry.

Fixtures are built here rather than pulled from `spec.BY_ID`. They used to name
V6 strategies, which meant the V7 cutover broke a dozen tests that had nothing
to do with V7: the engine had not changed, only the registry it happened to
borrow examples from. Several of them tested exit families (partial, runner,
two-sided route) that V7's grid does not contain at all, so there was no
V7 strategy to repoint them at.

A synthetic strategy states exactly the condition under test and keeps working
whatever the live tournament happens to be.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.lab import spec
from app.lab.rules import MarkState, evaluate_entry, evaluate_exit
from app.lab.spec import Condition, Exits, Strategy

D = Decimal


def strat(*conditions: Condition, exits: Exits | None = None,
          trades: bool = True) -> Strategy:
    """A minimal strategy carrying exactly the rules under test."""
    return Strategy(
        id="TEST-01", name="synthetic", hypothesis="fixture",
        checkpoint_minutes=30 if trades else None,
        entry=conditions,
        size_usd=D("5") if trades else D("0"),
        max_concurrent=10 if trades else 0,
        max_exposure_usd=D("50") if trades else D("0"),
        exits=exits or Exits(take_profit=D("1.25"), time_exit_hours=6),
        evidence="NONE", overfit_risk="NONE",
    )


def cond(feature: str, op: str, value, reason: str) -> Condition:
    return Condition(feature, op, value, reason)


def mark(**kw) -> MarkState:
    base = dict(
        exec_multiple=D(1), peak_exec_multiple=D(1), held_hours=0.0,
        liquidity_usd=D("100000"), entry_liquidity_usd=D("100000"),
        is_dead=False, sell_route_ok=None, break_even_armed=False,
        partial_done=False, flat_hours=0.0,
    )
    base.update(kw)
    return MarkState(**base)


# ---------------------------------------------------------------- entry

def test_unknown_feature_is_false_and_names_itself():
    v = evaluate_entry(strat(cond("liq", "gte", D("300000"), "liq_below_300k")), {})
    assert v.eligible is False
    assert v.skip_reason == "unknown_liq"


def test_unknown_is_never_treated_as_zero_or_as_pass():
    # A rule requiring a real two-sided route. No quote must not become a PASS.
    s = strat(cond("liq", "gte", D("100000"), "liq_below_100k"),
              cond("buy_route_ok", "is_true", True, "buy_route_failed"))
    v = evaluate_entry(s, {"liq": D("500000")})
    assert v.eligible is False
    assert v.skip_reason == "unknown_buy_route_ok"


def test_first_failing_condition_wins_in_specification_order():
    s = strat(cond("liq", "gte", D("100000"), "liq_below_100k"),
              cond("liqchg_15m", "gte", D("0.0"), "liquidity_not_growing"),
              cond("sell_share_15m", "lte", D("0.45"), "sell_share_above_0_45"),
              cond("dd_from_peak_det", "gte", D("-0.5"), "drawdown_below_50pct"))
    v = evaluate_entry(s, {"liq": D("100000"), "liqchg_15m": D("-0.5"),
                           "sell_share_15m": D("0.9"), "dd_from_peak_det": D("-0.9")})
    assert v.skip_reason == "liquidity_not_growing"


def test_cash_control_has_no_conditions_but_never_reaches_evaluation():
    assert strat(trades=False).trades is False
    # and the live registry still has exactly one
    assert sum(1 for x in spec.STRATEGIES if not x.trades) == 1


def test_random_control_accepts_everything_eligible():
    assert evaluate_entry(strat(), {"liq": D("1")}).eligible is True


@pytest.mark.parametrize("liq,expected", [("399999", False), ("400000", True),
                                          ("400001", True)])
def test_a_gte_boundary_is_inclusive(liq, expected):
    s = strat(cond("liq", "gte", D("400000"), "liq_below_400k"))
    assert evaluate_entry(s, {"liq": D(liq)}).eligible is expected


def test_flow_quality_and_buyers_above_sellers():
    s = strat(cond("liq", "gte", D("50000"), "liq_below_50k"),
              cond("flow_quality", "eq", "exact", "flow_window_capped"),
              cond("w1h_unique_wallets", "gte", 20, "wallets_below_20"),
              cond("w1h_unique_buyers", "gt_field", "w1h_unique_sellers",
                   "buyers_not_above_sellers"))
    good = {"liq": D("60000"), "flow_quality": "exact", "w1h_unique_wallets": 40,
            "w1h_unique_buyers": 25, "w1h_unique_sellers": 15,
            "w1h_top10_tx_share": D("0.4")}
    assert evaluate_entry(s, good).eligible is True
    assert evaluate_entry(s, {**good, "flow_quality": "capped"}).skip_reason == \
        "flow_window_capped"
    assert evaluate_entry(s, {**good, "w1h_unique_buyers": 10}).skip_reason == \
        "buyers_not_above_sellers"
    assert evaluate_entry(s, {**good, "w1h_unique_wallets": 19}).skip_reason == \
        "wallets_below_20"


def test_both_route_sides_and_an_impact_ceiling():
    s = strat(cond("buy_route_ok", "is_true", True, "buy_route_failed"),
              cond("sell_route_ok", "is_true", True, "sell_route_failed"),
              cond("buy_impact_pct", "lte", D("3.0"), "impact_above_3pct"))
    good = {"buy_route_ok": True, "sell_route_ok": True,
            "buy_impact_pct": D("1.5"), "liq": D("200000")}
    assert evaluate_entry(s, good).eligible is True
    assert evaluate_entry(s, {**good, "sell_route_ok": False}).skip_reason == \
        "sell_route_failed"
    assert evaluate_entry(s, {**good, "buy_impact_pct": D("3.01")}).skip_reason == \
        "impact_above_3pct"


# ---------------------------------------------------------------- exits

def test_dead_pool_settles_before_any_target_is_honoured():
    e = Exits(take_profit=D("1.25"))
    v = evaluate_exit(e, mark(exec_multiple=D("5"), is_dead=True))
    assert (v.action, v.reason) == ("CLOSE", "dead_zero")


def test_take_profit_fires_at_the_executable_multiple():
    e = Exits(take_profit=D("1.25"))
    assert evaluate_exit(e, mark(exec_multiple=D("1.24"))).action is None
    v = evaluate_exit(e, mark(exec_multiple=D("1.25")))
    assert v.action == "CLOSE" and v.trigger_multiple == D("1.25")


def test_time_exit_fires_only_at_its_own_horizon():
    e = Exits(take_profit=D("1.25"), time_exit_hours=2)
    assert evaluate_exit(e, mark(held_hours=1.9)).action is None
    assert evaluate_exit(e, mark(held_hours=2.0)).reason == "time_2h"


def test_trailing_arms_at_1_5x_and_never_on_a_loser():
    e = Exits(trailing_drawdown=D("0.35"), trailing_arm_at=D("1.50"))
    # never armed: a position that only ever fell must not "trail" out
    assert evaluate_exit(e, mark(exec_multiple=D("0.4"),
                                 peak_exec_multiple=D("1.1"))).action is None
    # armed at 1.6x, then gives back 35%
    assert evaluate_exit(e, mark(exec_multiple=D("1.2"),
                                 peak_exec_multiple=D("1.6"))).action is None
    v = evaluate_exit(e, mark(exec_multiple=D("1.03"), peak_exec_multiple=D("1.6")))
    assert v.reason == "trailing_stop"


def test_partial_then_runner_then_break_even():
    # Thresholds chosen to match what the assertions below exercise: a partial
    # at 1.25x, a runner target at 2x once banked, break-even at 1.0.
    e = Exits(take_profit=D("2.0"), partial_at=D("1.25"),
              partial_fraction=D("0.5"), runner_target=D("2.0"),
              break_even_arm=D("1.5"), break_even_exit=D("1.0"),
              time_exit_hours=6)
    v = evaluate_exit(e, mark(exec_multiple=D("1.25")))
    assert (v.action, v.trigger_multiple) == ("PARTIAL", D("1.25"))
    # once banked, the runner target replaces the take profit
    assert evaluate_exit(e, mark(exec_multiple=D("1.9"), partial_done=True)).action is None
    v = evaluate_exit(e, mark(exec_multiple=D("2.0"), partial_done=True))
    assert v.reason == "target_runner_2x"
    # armed break-even exits the runner if it round-trips
    v = evaluate_exit(e, mark(exec_multiple=D("1.0"), partial_done=True,
                              break_even_armed=True))
    assert v.reason == "break_even"


def test_liquidity_floor_and_decay_are_separate_triggers():
    e = Exits(take_profit=D("1.25"), liquidity_exit_absolute_usd=D("1000"),
              liquidity_exit_frac_of_entry=D("0.50"))
    assert evaluate_exit(e, mark(liquidity_usd=D("999"))).reason == "liquidity_floor"
    assert evaluate_exit(e, mark(liquidity_usd=D("40000"),
                                 entry_liquidity_usd=D("100000"))).reason == "liquidity_decay"
    assert evaluate_exit(e, mark(liquidity_usd=D("60000"),
                                 entry_liquidity_usd=D("100000"))).action is None


def test_sell_route_loss_only_exits_strategies_that_declared_it():
    holder = Exits(take_profit=D("1.25"))            # sell_route_loss defaults to hold
    assert evaluate_exit(holder, mark(sell_route_ok=False)).action is None
    exiter = Exits(take_profit=D("1.25"), sell_route_loss="exit_at_best_quote")
    assert evaluate_exit(exiter, mark(sell_route_ok=False)).reason == "sell_route_lost"


def test_losses_are_checked_before_gains_on_the_same_mark():
    """A dead pool that also prints a 2x is dead, not a winner."""
    e = Exits(take_profit=D("2.0"), liquidity_exit_absolute_usd=D("1000"))
    v = evaluate_exit(e, mark(exec_multiple=D("2.5"), liquidity_usd=D("500")))
    assert v.reason == "liquidity_floor"


def test_stagnation_needs_both_the_band_and_the_hours():
    e = Exits(take_profit=D("1.25"), stagnation_hours=2)
    assert evaluate_exit(e, mark(exec_multiple=D("1.0"), flat_hours=1.0)).action is None
    assert evaluate_exit(e, mark(exec_multiple=D("1.2"), flat_hours=9.0)).action is None
    assert evaluate_exit(e, mark(exec_multiple=D("1.0"), flat_hours=2.0)).reason == \
        "stagnation"


def test_holding_is_the_default():
    assert evaluate_exit(Exits(take_profit=D("1.25")), mark()).action is None
