"""The harness. Causality, costs, the dead-curve haircut, slots and the gate.

No database: every test builds `Replay` objects directly, which is the whole
reason the harness takes them rather than a session.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.labs.graduation import config
from app.labs.graduation.backtest import (
    BASELINES,
    POST_GRAD,
    PRE_GRAD,
    Backtester,
    Checkpoint,
    Costs,
    CurveTick,
    EntrySignal,
    ExitPolicy,
    ExitState,
    HardStop,
    Replay,
    Strategy,
    TakeProfit,
    Tick,
    TimeBox,
    Trade,
    TrailingStop,
    by_week,
    curve_price,
    evaluate_gate,
    split_halves,
    summarise,
    token_concentration,
    trades_csv,
    view_at,
)

D = Decimal
T0 = datetime(2026, 9, 7, 12, 0, tzinfo=UTC)   # a Monday


def at(minutes: float) -> datetime:
    return T0 + timedelta(minutes=minutes)


def ticks(*pairs: tuple[float, str], source: str = "dexscreener") -> list[Tick]:
    return [Tick(ts=at(m), price=D(p), source=source) for m, p in pairs]


def replay(mint: str = "M1", *, curve=None, checkpoints=None, tick_list=None,
           launch=T0, graduated=None) -> Replay:
    r = Replay(mint=mint, launch_at=launch, graduated_at=graduated,
               quote_currency="SOL")
    r.curve = list(curve or [])
    r.checkpoints = dict(checkpoints or {})
    r.ticks = list(tick_list or [])
    return r


def curve_tick(minute: float, progress: str, price: str, complete: bool = False):
    return CurveTick(ts=at(minute), progress_pct=D(progress), price=D(price),
                     market_cap_quote=None, complete=complete)


class Greedy(Strategy):
    """A strategy that tries to buy the best price it can see.

    The point of it: given the WHOLE series it would find the top, so if the
    harness is causal it must find only what had happened by its decision time.
    """

    name = "greedy"

    def __init__(self, when: datetime) -> None:
        self._when = when
        self.seen: list[Tick] = []

    @property
    def exits(self) -> ExitPolicy:
        return ExitPolicy((TimeBox(5),))

    def decision_times(self, r: Replay) -> list[datetime]:
        return [self._when]

    def entry(self, view) -> EntrySignal | None:
        self.seen = list(view.ticks)
        if not view.ticks:
            return None
        best = max(view.ticks, key=lambda t: t.price)
        return EntrySignal(price=best.price, path=POST_GRAD)


# --- causality ----------------------------------------------------------------

def test_a_view_holds_nothing_past_its_own_clock() -> None:
    r = replay(
        curve=[curve_tick(0, "10", "0.001"), curve_tick(30, "90", "0.009")],
        checkpoints={D(70): Checkpoint(D(70), at(20), D("0.007"), None),
                     D(90): Checkpoint(D(90), at(30), D("0.009"), None)},
        tick_list=ticks((40, "1.0"), (41, "9.9")))
    view = view_at(r, at(25))

    assert [c.ts for c in view.curve] == [at(0)]
    assert [c.level for c in view.checkpoints] == [D(70)]
    assert view.ticks == ()
    assert view.checkpoint(D(90)) is None
    assert max((t.ts for t in view.curve), default=None) <= view.now


def test_a_greedy_strategy_cannot_reach_a_price_it_has_not_reached() -> None:
    """The spike at t+41 is nine times the open. A strategy asked at t+40 must
    fill at 1.0, not at 9.9."""
    r = replay(tick_list=ticks((40, "1.0"), (41, "9.9"), (45, "0.5")),
               graduated=at(39))
    strategy = Greedy(at(40))
    result = Backtester(strategy, costs=Costs(pump_fee_bps=0, slip_bps=0,
                                              priority_fee_quote=D(0))).run([r])

    assert [t.ts for t in strategy.seen] == [at(40)]
    assert result.trades[0].entry_price == D("1.0")


def test_the_view_forward_fills_progress_rather_than_looking_ahead() -> None:
    """Curve samples are change-only, so the progress at a quiet moment is the
    last one OBSERVED — never the next one."""
    r = replay(curve=[curve_tick(0, "10", "0.001"), curve_tick(50, "95", "0.01")])
    assert view_at(r, at(30)).progress() == D("10")
    assert view_at(r, at(50)).progress() == D("95")


# --- cost maths ---------------------------------------------------------------

def test_the_default_cost_model_is_290_bps_a_side() -> None:
    """1% pump fee + 150 bps slippage + a flat 0.002 quote priority fee, which
    on a 0.5 quote position is another 40 bps."""
    costs = Costs()
    assert costs.side_fraction == D("0.029")
    assert costs.buy_price(D(100)) == D("102.9")
    assert costs.sell_price(D(100)) == D("97.1")


def test_costs_turn_a_flat_move_into_a_loss() -> None:
    """The whole reason the model exists: a round trip at the same price loses
    5.64%, not nothing."""
    costs = Costs()
    entry, exit_ = costs.buy_price(D(1)), costs.sell_price(D(1))
    assert round(exit_ / entry - 1, 4) == D("-0.0564")


def test_the_priority_fee_scales_with_position_size() -> None:
    """A flat fee is a bigger fraction of a smaller position, and a backtest
    that ignored that would flatter small sizes."""
    small = Costs(pump_fee_bps=0, slip_bps=0, priority_fee_quote=D("0.002"),
                  notional_quote=D("0.1"))
    large = Costs(pump_fee_bps=0, slip_bps=0, priority_fee_quote=D("0.002"),
                  notional_quote=D("10"))
    assert small.side_fraction == D("0.02")
    assert large.side_fraction == D("0.0002")


def test_a_sell_price_can_never_go_negative() -> None:
    assert Costs(slip_bps=20_000).sell_price(D(1)) == 0


def test_net_and_gross_are_both_reported() -> None:
    """Gross is the move, net is what a book would have kept. Reporting only
    one of them is how a cost model gets quietly dropped later."""
    r = replay(tick_list=ticks((40, "1.0"), (45, "2.0")), graduated=at(39))
    trade = Backtester(BASELINES["B0_open_timebox_5m"]).run([r]).trades[0]
    assert trade.gross_return == D("1")                    # a clean 2x
    assert D("0.88") < trade.net_return < D("0.89")        # after 290 bps a side
    assert trade.pnl_quote == (trade.net_return * config.BACKTEST_NOTIONAL_QUOTE)


# --- exit rules ---------------------------------------------------------------

def state(price: str, *, entry: str = "1.0", peak: str = "1.0",
          minutes: int = 0) -> ExitState:
    return ExitState(clock_at=T0, entry_price=D(entry),
                     tick=Tick(ts=at(minutes), price=D(price),
                               source="dexscreener"),
                     peak=D(peak))


@pytest.mark.parametrize(("rule", "fires", "misses"), [
    (TimeBox(5), state("1.0", minutes=5), state("1.0", minutes=4)),
    (HardStop(D("0.2")), state("0.8"), state("0.81")),
    (TakeProfit(D("0.5")), state("1.5"), state("1.49")),
    (TrailingStop(D("0.3")), state("0.7", peak="1.0"),
     state("0.71", peak="1.0")),
])
def test_each_exit_rule_fires_where_it_should(rule, fires, misses) -> None:
    assert rule.fires(fires) is True
    assert rule.fires(misses) is False


def test_the_first_rule_in_the_policy_wins() -> None:
    """A stop and a take-profit can both be true on one 60-second bar, and
    which filled is not knowable from minute data. Order is the caller's to
    state, and putting the loss first is the conservative reading."""
    both = state("2.0", peak="4.0")  # +100% and -50% from the peak at once
    assert ExitPolicy((TrailingStop(D("0.3")), TakeProfit(D("0.5")))) \
        .fires(both) == "trailing_stop"
    assert ExitPolicy((TakeProfit(D("0.5")), TrailingStop(D("0.3")))) \
        .fires(both) == "take_profit"


def test_the_trailing_peak_is_a_running_peak() -> None:
    """It may only know highs it has already reached. A rule reading the whole
    window's peak would exit on a fall from a price that had not happened."""
    r = replay(tick_list=ticks((40, "1.0"), (41, "2.0"), (42, "1.5"),
                               (43, "4.0")), graduated=at(39))

    class Trailing(Strategy):
        name = "trailing"

        @property
        def exits(self): return ExitPolicy((TrailingStop(D("0.2")),))

        def decision_times(self, rep): return [at(40)]

        def entry(self, view):
            return EntrySignal(price=view.ticks[-1].price, path=POST_GRAD)

    trade = Backtester(Trailing(), costs=Costs(
        pump_fee_bps=0, slip_bps=0, priority_fee_quote=D(0))).run([r]).trades[0]
    # Exits at t+42 on the fall from 2.0, and never sees the 4.0 at t+43.
    assert trade.exit_at == at(42)
    assert trade.exit_reason == "trailing_stop"


def test_a_window_where_nothing_fires_says_so() -> None:
    """Closing at the last tick is a decision, not a neutral default."""
    r = replay(tick_list=ticks((40, "1.0"), (41, "1.1")), graduated=at(39))

    class Never(Strategy):
        name = "never"

        @property
        def exits(self): return ExitPolicy((TakeProfit(D(100)),))

        def decision_times(self, rep): return [at(40)]

        def entry(self, view):
            return EntrySignal(price=view.ticks[-1].price, path=POST_GRAD)

    trade = Backtester(Never()).run([r]).trades[0]
    assert trade.exit_reason == "end_of_data"
    assert trade.exit_at == at(41)


# --- the dead curve -----------------------------------------------------------

def test_a_pre_grad_entry_that_never_migrates_takes_the_haircut() -> None:
    """No pool, no route out, no bid. The default writes off half."""
    r = replay(
        curve=[curve_tick(0, "50", "0.001"), curve_tick(30, "90", "0.002"),
               curve_tick(40, "88", "0.0018")],
        checkpoints={D(90): Checkpoint(D(90), at(30), D("0.002"), None)},
        tick_list=[])   # never migrated
    result = Backtester(BASELINES["B1_f90_then_open_5m"],
                        costs=Costs(pump_fee_bps=0, slip_bps=0,
                                    priority_fee_quote=D(0))).run([r])

    trade = result.trades[0]
    assert result.dead_curve_exits == 1
    assert trade.exit_reason == "dead_curve"
    assert trade.graduated is False
    # Last observed curve price 0.0018, halved.
    assert trade.exit_price == D("0.0009")
    assert trade.exit_at == at(30) + timedelta(hours=config.PRE_GRAD_DEAD_HOURS)


def test_the_haircut_is_configurable() -> None:
    r = replay(curve=[curve_tick(30, "90", "0.002")],
               checkpoints={D(90): Checkpoint(D(90), at(30), D("0.002"), None)})
    trade = Backtester(BASELINES["B1_f90_then_open_5m"], dead_haircut=D("0.9"),
                       costs=Costs(pump_fee_bps=0, slip_bps=0,
                                   priority_fee_quote=D(0))).run([r]).trades[0]
    assert trade.exit_price == D("0.0002")


def test_a_pruned_dead_token_loses_exactly_the_haircut() -> None:
    """The pruner deletes a non-graduate's curve series after 24h and keeps its
    checkpoints, so the last observed price IS the entry. That is the intended
    reading, not an accident."""
    r = replay(curve=[],   # pruned away
               checkpoints={D(90): Checkpoint(D(90), at(30), D("0.002"), None)})
    trade = Backtester(BASELINES["B1_f90_then_open_5m"],
                       costs=Costs(pump_fee_bps=0, slip_bps=0,
                                   priority_fee_quote=D(0))).run([r]).trades[0]
    assert trade.net_return == D("-0.5")


def test_a_migration_after_the_deadline_is_still_dead() -> None:
    r = replay(
        curve=[curve_tick(30, "90", "0.002")],
        checkpoints={D(90): Checkpoint(D(90), at(30), D("0.002"), None)},
        tick_list=ticks((60 * 48, "0.01")))   # opens two days later
    result = Backtester(BASELINES["B1_f90_then_open_5m"]).run([r])
    assert result.trades[0].exit_reason == "dead_curve"


def test_a_graduate_with_no_native_prices_is_skipped_not_counted_as_a_loss() -> None:
    """Every post-graduation sample was a backfilled candle, which carries no
    native price. That is a data gap, not a result."""
    r = replay(tick_list=[], graduated=at(39))
    result = Backtester(BASELINES["B0_open_timebox_5m"]).run([r])
    assert result.trades == []
    # It must not vanish: a funnel that starts at `considered` would show
    # nothing at all here, and a graduate skipped for want of price data would
    # be indistinguishable from one that was never loaded.
    assert result.eligible == 1
    assert result.no_decision_time == 1
    assert result.considered == 0


def test_the_funnel_accounts_for_every_token_loaded() -> None:
    """Each token ends in exactly one terminal bucket, so the counts add up
    and a reader can check that they do."""
    tradeable = [replay(f"OK{i}", tick_list=ticks((40, "1.0"), (45, "1.2")),
                        graduated=at(39)) for i in range(3)]
    no_prices = [replay("GAP", tick_list=[], graduated=at(39))]
    result = Backtester(BASELINES["B0_open_timebox_5m"], max_slots=1) \
        .run(tradeable + no_prices)
    counts = result.counts

    assert counts["eligible"] == 4
    terminal = (counts["no_decision_time"] + counts["no_signal"]
                + counts["skipped_no_slot"] + counts["skipped_no_exit_data"]
                + counts["trades"])
    assert terminal == counts["eligible"]


# --- slots --------------------------------------------------------------------

def test_a_signal_with_every_slot_full_is_skipped_not_queued() -> None:
    """A backtest that queues signals is quietly assuming capital it did not
    have."""
    replays = [replay(f"M{i}", tick_list=ticks((40, "1.0"), (50, "1.2")),
                      graduated=at(39)) for i in range(5)]
    result = Backtester(BASELINES["B0_open_timebox_5m"], max_slots=2).run(replays)
    assert len(result.trades) == 2
    assert result.skipped_no_slot == 3


def test_a_slot_is_freed_in_simulated_time() -> None:
    """The first trade exits at t+45, so a signal at t+50 fits even though the
    slot was busy when the loop started."""
    early = replay("EARLY", tick_list=ticks((40, "1.0"), (45, "1.2")),
                   graduated=at(39))
    late = replay("LATE", tick_list=ticks((50, "1.0"), (55, "1.2")),
                  graduated=at(49))
    result = Backtester(BASELINES["B0_open_timebox_5m"], max_slots=1) \
        .run([early, late])
    assert len(result.trades) == 2
    assert result.skipped_no_slot == 0


def test_slots_are_shared_across_tokens_not_per_token() -> None:
    """Ordering globally is the point: walking tokens one at a time would let
    every signal fill, which is the same as having no limit."""
    overlapping = [replay(f"M{i}", tick_list=ticks((40, "1.0"), (90, "1.2")),
                          graduated=at(39)) for i in range(4)]
    result = Backtester(BASELINES["B0_open_timebox_5m"], max_slots=1) \
        .run(overlapping)
    assert len(result.trades) == 1


# --- weeks and the gate -------------------------------------------------------

def trade(week_offset: int, pnl: str, mint: str = "M1") -> Trade:
    when = T0 + timedelta(weeks=week_offset)
    return Trade(mint=mint, strategy="s", path=POST_GRAD, entry_at=when,
                 entry_price=D(1), exit_at=when, exit_price=D(1),
                 exit_reason="time_box", gross_return=D(pnl),
                 net_return=D(pnl), pnl_quote=D(pnl),
                 entry_progress_pct=None, graduated=True)


def test_trades_group_by_the_iso_week_of_entry() -> None:
    weeks = by_week([trade(0, "1"), trade(0, "-2"), trade(1, "3")])
    assert [w.week for w in weeks] == ["2026-W37", "2026-W38"]
    assert weeks[0].gross_profit == 1 and weeks[0].gross_loss == 2
    assert weeks[0].profit_factor == D("0.5")
    assert weeks[1].net_pnl == 3


def test_profit_factor_is_none_rather_than_infinite_when_undefined() -> None:
    """A profit factor printed as a number when its denominator is zero is the
    kind of thing that gets quoted in a summary and believed."""
    assert summarise([trade(0, "1")]).profit_factor is None
    assert summarise([]).profit_factor is None


def test_the_split_is_on_weeks_not_on_trades() -> None:
    weeks = by_week([trade(w, "1") for w in range(4)])
    in_sample, oos = split_halves(weeks)
    assert [w.week for w in in_sample] == ["2026-W37", "2026-W38"]
    assert [w.week for w in oos] == ["2026-W39", "2026-W40"]


def test_token_concentration_finds_the_one_token_carrying_the_result() -> None:
    mint, share = token_concentration(
        [trade(0, "9", "HERO"), trade(0, "1", "M2"), trade(0, "-5", "M3")])
    assert mint == "HERO"
    assert share == D("0.9")


def test_the_gate_fails_a_strategy_one_token_is_carrying() -> None:
    """Profit factor and trade count can both pass while the result is one
    token. Read as a whole, that is not an edge."""
    trades = [trade(w, "0.01", f"M{i}") for w in range(4) for i in range(30)]
    trades.append(trade(3, "500", "HERO"))
    criteria = {c.name: c for c in evaluate_gate(trades, by_week(trades))}

    assert criteria["trades"].passed is True
    assert criteria["max token share of gross profit"].passed is False


def test_the_gate_fails_a_losing_out_of_sample_week() -> None:
    trades = ([trade(w, "1", f"M{w}") for w in range(3)]
              + [trade(3, "-1", "M9")] + [trade(3, "0.1", "M8")])
    criteria = {c.name: c for c in evaluate_gate(trades, by_week(trades))}
    assert criteria["every OOS week profitable"].passed is False


def test_the_gate_passes_only_when_every_criterion_does() -> None:
    trades = []
    for week in range(8):
        for i in range(20):
            # Comfortably profitable, spread across tokens, every week.
            trades.append(trade(week, "1" if i % 4 else "-0.2", f"M{week}_{i}"))
    criteria = evaluate_gate(trades, by_week(trades))
    assert all(c.passed for c in criteria), [
        (c.name, c.actual) for c in criteria if not c.passed]


def test_the_gate_thresholds_come_from_config() -> None:
    """Pre-stated, and in one place — so raising the bar after seeing a result
    is a visible edit rather than a quiet one."""
    criteria = {c.name: c for c in evaluate_gate([trade(0, "1")], by_week(
        [trade(0, "1")]))}
    assert str(config.GATE_MIN_PF) in criteria["OOS profit factor"].target
    assert str(config.GATE_MIN_TRADES) in criteria["trades"].target


# --- baselines and output -----------------------------------------------------

def test_both_baselines_ship_and_neither_is_tuned() -> None:
    """They exist to be beaten. If one ever passes the gate on real data, the
    first suspicion should be the harness, not the edge."""
    assert set(BASELINES) == {"B0_open_timebox_5m", "B1_f90_then_open_5m"}
    assert BASELINES["B0_open_timebox_5m"].exits.rules == (TimeBox(5),)


def test_b0_enters_at_the_pool_open() -> None:
    r = replay(tick_list=ticks((40, "1.0"), (45, "1.5")), graduated=at(39))
    trade_ = Backtester(BASELINES["B0_open_timebox_5m"]).run([r]).trades[0]
    assert trade_.path == POST_GRAD
    assert trade_.entry_at == at(40)
    assert trade_.exit_at == at(45)


def test_b1_enters_on_the_curve_and_times_out_after_the_open() -> None:
    """Its clock starts at the pool open: a pre-graduation entry sits on a
    curve with no ticks to evaluate a time box against."""
    r = replay(
        curve=[curve_tick(30, "90", "0.002", complete=False)],
        checkpoints={D(90): Checkpoint(D(90), at(30), D("0.002"), None)},
        tick_list=ticks((60, "0.004"), (65, "0.006")), graduated=at(59))
    trade_ = Backtester(BASELINES["B1_f90_then_open_5m"]).run([r]).trades[0]
    assert trade_.path == PRE_GRAD
    assert trade_.entry_at == at(30)
    assert trade_.exit_at == at(65)        # open at t+60, plus five
    assert trade_.entry_progress_pct == D("90")


def test_curve_price_is_the_constant_products_own_price() -> None:
    assert curve_price(D("30.000000006"), D("1073000000")) == D("0.000000027959")
    assert curve_price(D(1), D(0)) is None
    assert curve_price(None, D(1)) is None


def test_the_csv_carries_every_trade_and_its_week() -> None:
    rows = trades_csv([trade(0, "1", "M1"), trade(1, "-1", "M2")])
    assert rows.splitlines()[0].startswith("mint,strategy,path,iso_week")
    assert "2026-W37" in rows and "2026-W38" in rows
    assert len(rows.strip().splitlines()) == 3
