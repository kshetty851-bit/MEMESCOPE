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
    completes_curve,
    curve_fill_buy,
    curve_fill_sell,
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


#: The real seeded constants, so every fixture curve is a curve that could
#: exist. `K` is the constant product the account is seeded with.
V0, R0 = D("1073000000"), D("793100000")
K = D(30) * V0


def reserves_at(progress: str) -> tuple[Decimal, Decimal]:
    """(v_sol, v_tok) at a given progress, from the constant product."""
    v_tok = V0 - D(progress) / 100 * R0
    return (K / v_tok).quantize(D("0.000000001")), v_tok


def replay(mint: str = "M1", *, curve=None, checkpoints=None, tick_list=None,
           launch=T0, graduated=None) -> Replay:
    r = Replay(mint=mint, launch_at=launch, graduated_at=graduated,
               quote_currency="SOL")
    r.curve = list(curve or [])
    r.checkpoints = dict(checkpoints or {})
    r.ticks = list(tick_list or [])
    return r


def curve_tick(minute: float, progress: str, complete: bool = False):
    v_sol, v_tok = reserves_at(progress)
    return CurveTick(ts=at(minute), progress_pct=D(progress),
                     price=(v_sol / v_tok), v_quote=v_sol, v_token=v_tok,
                     market_cap_quote=None, complete=complete)


def checkpoint(level: int, minute: float, progress: str | None = None):
    v_sol, v_tok = reserves_at(progress or str(level))
    return Checkpoint(level=D(level), ts=at(minute), price=(v_sol / v_tok),
                      v_quote=v_sol, v_token=v_tok, market_cap_quote=None)


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
        curve=[curve_tick(0, "10"), curve_tick(30, "90")],
        checkpoints={D(70): checkpoint(70, 20), D(90): checkpoint(90, 30)},
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
    r = replay(curve=[curve_tick(0, "10"), curve_tick(50, "95")])
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


# --- the exact fill maths -----------------------------------------------------

def test_buy_fill_at_70_percent_matches_the_hand_computation() -> None:
    """Worked by hand from the seeded constants.

        v_tok    = 1,073,000,000 - 0.70 x 793,100,000 = 517,830,000
        v_sol    = (30 x 1,073,000,000) / 517,830,000 = 62.163258212
        to_curve = 0.498 x 10000 / 10100                (the 1% fee, as a markup)
        tokens   = to_curve x v_tok / (v_sol + to_curve)
    """
    v_sol, v_tok = reserves_at("70")
    assert v_tok == D("517830000")
    assert v_sol == D("62.163258212")

    # At the shipped 125 bps (pump.fun's live schedule).
    out = curve_fill_buy(v_sol, v_tok, D("0.498"))
    assert out == D("4065041.848699714908")
    # All-in cost per token against the curve's spot, for the default 0.5 SOL
    # position: 2.46%, of which 1.25% is the fee and the rest is real impact.
    premium = (D("0.5") / out) / (v_sol / v_tok) - 1
    assert round(premium, 4) == D("0.0246")
    # And the buy itself moves the curve half a point.
    assert round(out / R0 * 100, 4) == D("0.5126")
    # The program README's older 100 bps, for comparison.
    assert curve_fill_buy(v_sol, v_tok, D("0.498"),
                          fee_bps=100) == D("4075024.651433293009")


def test_buy_fill_at_95_percent_is_cheaper_because_the_curve_is_deeper() -> None:
    """Later on the curve there is MORE sol backing it, so the same size moves
    it less — the opposite of the intuition that a nearly-full curve is thin.

        v_tok = 319,555,000   v_sol = 100.733832986
    """
    v_sol, v_tok = reserves_at("95")
    assert v_tok == D("319555000")
    assert v_sol == D("100.733832986")

    out = curve_fill_buy(v_sol, v_tok, D("0.498"))
    assert out == D("1552705.904339268295")
    premium = (D("0.5") / out) / (v_sol / v_tok) - 1
    assert round(premium, 4) == D("0.0215")      # against 0.0246 at 70%
    assert round(out / R0 * 100, 4) == D("0.1958")


def test_a_100_dollar_buy_does_not_move_95_percent_by_a_point() -> None:
    """Worth pinning because it is easy to assume otherwise. At the default
    0.5 SOL (~$100) the move at 95% is a fifth of a point; it takes about 2.6
    SOL (~$520) to shift the curve a full point from there."""
    v_sol, v_tok = reserves_at("95")
    assert curve_fill_buy(v_sol, v_tok, D("0.498")) / R0 * 100 < 1
    assert curve_fill_buy(v_sol, v_tok, D("2.6")) / R0 * 100 >= 1


def test_the_fee_is_a_markup_on_a_buy_and_a_deduction_on_a_sell() -> None:
    """Same side of the trade — always the SOL — but not the same arithmetic.

    A buy divides by (1 + fee); `sol_in x (1 - fee)` is the naive form and is
    wrong by about a basis point at 100 bps, always in the trader's favour.
    """
    v_sol, v_tok = reserves_at("70")
    naive = curve_fill_buy(v_sol, v_tok, D("0.498") * D("0.9875"), fee_bps=0)
    exact = curve_fill_buy(v_sol, v_tok, D("0.498"))
    assert exact > naive                      # dividing keeps slightly more
    # About 1.6 bp at 125, and always the same direction.
    assert round(exact / naive - 1, 5) == D("0.00016")

    # A sell simply loses the fee off the proceeds.
    gross = curve_fill_sell(v_sol, v_tok, D("1000000"), fee_bps=0)
    net = curve_fill_sell(v_sol, v_tok, D("1000000"))
    assert round(net / gross, 6) == D("0.9875")


def test_a_zero_or_negative_fill_returns_zero_rather_than_raising() -> None:
    v_sol, v_tok = reserves_at("70")
    assert curve_fill_buy(v_sol, v_tok, D(0)) == 0
    assert curve_fill_buy(D(0), v_tok, D(1)) == 0
    assert curve_fill_sell(v_sol, v_tok, D(0)) == 0
    assert curve_fill_sell(v_sol, D(0), D(1)) == 0


def test_an_immediate_round_trip_loses_the_fee_twice_and_the_impact_twice() -> None:
    """The exact model's answer to "what does a flat trade cost". At 70% and
    the live 125 bps it is 4.37%, against the 5.64% the flat AMM model charges
    — so the flat model still OVERstates a curve entry, even at the higher
    fee."""
    v_sol, v_tok = reserves_at("70")
    out = curve_fill_buy(v_sol, v_tok, D("0.498"))
    back = curve_fill_sell(v_sol, v_tok, out)
    assert round(back / D("0.5") - 1, 4) == D("-0.0437")


# --- self-graduation ----------------------------------------------------------

def test_completes_curve_knows_the_sellable_remainder() -> None:
    """The remainder is `v_tok - 279,900,000`: at 95% that is 39,655,000
    tokens, which takes about 14.5 SOL to clear."""
    _, v_tok = reserves_at("95")
    assert completes_curve(v_tok, D("39655000")) is True
    assert completes_curve(v_tok, D("39654999")) is False


def test_a_buy_that_fills_the_curve_is_flagged_and_exits_post_grad() -> None:
    """Pricing the rest of that position on a curve the buy just ended would
    be inventing a fill."""
    r = replay(curve=[curve_tick(30, "95")],
               checkpoints={D(95): checkpoint(95, 30)},
               tick_list=ticks((60, "0.0000004"), (65, "0.0000006")),
               graduated=at(59))

    class Big(Strategy):
        name = "big"
        level = D(95)

        @property
        def exits(self): return ExitPolicy((TimeBox(5),))

        def decision_times(self, rep): return [at(30)]

        def entry(self, view):
            mark = view.checkpoint(D(95))
            return EntrySignal(path=PRE_GRAD,
                               reserves=(mark.v_quote, mark.v_token))

    # 20 SOL clears the 39.6M remaining at 95%.
    big = Backtester(Big(), costs=Costs(notional_quote=D(20),
                                        priority_fee_quote=D(0)))
    trade_ = big.run([r]).trades[0]
    assert trade_.self_graduated is True
    assert trade_.exit_reason == "time_box"          # priced on the pool
    # The box runs from the ENTRY, so it is already long expired by the time
    # the pool opens: the first pool quote is the exit.
    assert trade_.exit_at == at(60)

    # The default size does not, and is not flagged.
    small = Backtester(Big()).run([r]).trades[0]
    assert small.self_graduated is False


def test_a_self_graduating_buy_with_no_pool_data_is_skipped() -> None:
    """The buy filled the curve, so the curve cannot price the exit, and no
    pool was recorded either. Nothing can fill this."""
    r = replay(curve=[curve_tick(30, "95")],
               checkpoints={D(95): checkpoint(95, 30)}, tick_list=[])

    class Big(Strategy):
        name = "big"

        @property
        def exits(self): return ExitPolicy((TimeBox(5),))

        def decision_times(self, rep): return [at(30)]

        def entry(self, view):
            mark = view.checkpoint(D(95))
            return EntrySignal(path=PRE_GRAD,
                               reserves=(mark.v_quote, mark.v_token))

    result = Backtester(Big(), costs=Costs(notional_quote=D(20),
                                           priority_fee_quote=D(0))).run([r])
    assert result.trades == []
    assert result.skipped_no_exit_data == 1


# --- the dead curve -----------------------------------------------------------

def test_a_dead_curve_is_sold_back_into_its_own_reserves() -> None:
    """No haircut guess: the position is closed by selling the tokens it holds
    against the last reserves observed. A curve that never moved gives back the
    fee twice and the impact twice, and nothing more."""
    r = replay(curve=[curve_tick(30, "90")],
               checkpoints={D(90): checkpoint(90, 30)},
               tick_list=[])   # never migrated
    result = Backtester(BASELINES["B1_f90_timebox_5m"],
                        costs=Costs(priority_fee_quote=D(0))).run([r])

    trade_ = result.trades[0]
    assert result.dead_curve_exits == 1
    assert trade_.exit_reason == "dead_curve"
    assert trade_.graduated is False
    v_sol, v_tok = reserves_at("90")
    expected = curve_fill_sell(v_sol, v_tok,
                               curve_fill_buy(v_sol, v_tok, D("0.5")))
    assert round(trade_.net_return, 6) == round(expected / D("0.5") - 1, 6)
    assert trade_.exit_at == at(30) + timedelta(hours=config.PRE_GRAD_DEAD_HOURS)


def test_a_dead_curve_that_fell_sells_into_the_worse_reserves() -> None:
    """The exit reads the LAST observed state, so a curve that gave ground
    between the entry and the write-off is sold into that."""
    high = replay("HIGH", curve=[curve_tick(30, "90")],
                  checkpoints={D(90): checkpoint(90, 30)})
    fell = replay("FELL", curve=[curve_tick(30, "90"), curve_tick(90, "74")],
                  checkpoints={D(90): checkpoint(90, 30)})
    run = Backtester(BASELINES["B1_f90_timebox_5m"])
    flat = run.run([high]).trades[0]
    down = run.run([fell]).trades[0]
    assert down.net_return < flat.net_return


def test_the_optional_extra_haircut_defaults_to_nothing() -> None:
    """It used to be the whole model and a guess. It is now a knob for the part
    arithmetic cannot see — that a stalled curve may have no bid at all."""
    assert config.PRE_GRAD_DEAD_HAIRCUT == 0
    r = replay(curve=[curve_tick(30, "90")],
               checkpoints={D(90): checkpoint(90, 30)})
    run = Backtester(BASELINES["B1_f90_timebox_5m"],
                     costs=Costs(priority_fee_quote=D(0)))
    plain = run.run([r]).trades[0]
    charged = Backtester(BASELINES["B1_f90_timebox_5m"], dead_haircut=D("0.5"),
                         costs=Costs(priority_fee_quote=D(0))).run([r]).trades[0]
    assert round(charged.net_return, 6) == round(
        (plain.net_return + 1) / 2 - 1, 6)


def test_a_pruned_dead_token_round_trips_against_its_entry_state() -> None:
    """The pruner deletes a non-graduate's curve series and keeps its
    checkpoints, so the last observed state IS the entry."""
    r = replay(curve=[],   # pruned away
               checkpoints={D(90): checkpoint(90, 30)})
    trade_ = Backtester(BASELINES["B1_f90_timebox_5m"],
                        costs=Costs(priority_fee_quote=D(0))).run([r]).trades[0]
    v_sol, v_tok = reserves_at("90")
    expected = curve_fill_sell(v_sol, v_tok,
                               curve_fill_buy(v_sol, v_tok, D("0.5")))
    assert round(trade_.net_return, 6) == round(expected / D("0.5") - 1, 6)


def test_a_migration_after_the_deadline_is_still_dead() -> None:
    r = replay(
        curve=[curve_tick(30, "90")],
        checkpoints={D(90): checkpoint(90, 30)},
        tick_list=ticks((60 * 48, "0.00001")))   # opens two days later
    result = Backtester(BASELINES["B1_f90_timebox_5m"]).run([r])
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
    assert set(BASELINES) == {"B0_open_timebox_5m", "B1_f90_timebox_5m"}
    assert BASELINES["B0_open_timebox_5m"].exits.rules == (TimeBox(5),)
    assert BASELINES["B1_f90_timebox_5m"].exits.rules == (TimeBox(5),)


def test_b0_enters_at_the_pool_open() -> None:
    r = replay(tick_list=ticks((40, "1.0"), (45, "1.5")), graduated=at(39))
    trade_ = Backtester(BASELINES["B0_open_timebox_5m"]).run([r]).trades[0]
    assert trade_.path == POST_GRAD
    assert trade_.entry_at == at(40)
    assert trade_.exit_at == at(45)


def test_b1_enters_on_the_curve_and_its_box_runs_from_the_entry() -> None:
    """The box is evaluated on the CURVE too, so it fires at the first curve
    sample five minutes past the entry — it no longer waits for a pool."""
    r = replay(
        curve=[curve_tick(30, "90"), curve_tick(36, "91"),
               curve_tick(50, "93")],
        checkpoints={D(90): checkpoint(90, 30)},
        tick_list=ticks((60, "0.0000004"), (65, "0.0000006")), graduated=at(59))
    trade_ = Backtester(BASELINES["B1_f90_timebox_5m"]).run([r]).trades[0]
    assert trade_.path == PRE_GRAD
    assert trade_.entry_at == at(30)
    assert trade_.exit_at == at(36)        # the first curve sample past +5m
    assert trade_.exit_reason == "time_box"
    assert trade_.entry_progress_pct == D("90")


def test_a_stop_can_now_fire_while_the_token_is_still_on_the_curve() -> None:
    """The gap this closes. A hard stop used to be unable to fire until a pool
    existed, which on a token that never graduates is never — the position sat
    for 24 hours however far the curve fell."""
    r = replay(
        curve=[curve_tick(30, "90"), curve_tick(40, "78"), curve_tick(50, "60")],
        checkpoints={D(90): checkpoint(90, 30)},
        tick_list=[])

    class Stopped(Strategy):
        name = "stopped"

        @property
        def exits(self): return ExitPolicy((HardStop(D("0.25")),))

        def decision_times(self, rep): return [at(30)]

        def entry(self, view):
            mark = view.checkpoint(D(90))
            return EntrySignal(path=PRE_GRAD,
                               reserves=(mark.v_quote, mark.v_token))

    result = Backtester(Stopped(), costs=Costs(priority_fee_quote=D(0))).run([r])
    trade_ = result.trades[0]
    assert trade_.exit_reason == "hard_stop"
    assert trade_.exit_at in (at(40), at(50))
    assert result.dead_curve_exits == 0      # it exited, it did not rot
    assert trade_.net_return > D("-0.5")


def test_the_trailing_peak_carries_across_the_curve_into_the_pool() -> None:
    """One running peak over both venues. Resetting it at migration would be a
    stop reading a high it had already seen."""
    r = replay(
        curve=[curve_tick(30, "90"), curve_tick(35, "97")],
        checkpoints={D(90): checkpoint(90, 30)},
        tick_list=ticks((40, "0.0000009"), (41, "0.0000002")),
        graduated=at(39))

    class Trail(Strategy):
        name = "trail"

        @property
        def exits(self): return ExitPolicy((TrailingStop(D("0.5")),))

        def decision_times(self, rep): return [at(30)]

        def entry(self, view):
            mark = view.checkpoint(D(90))
            return EntrySignal(path=PRE_GRAD,
                               reserves=(mark.v_quote, mark.v_token))

    trade_ = Backtester(Trail(), costs=Costs(priority_fee_quote=D(0))) \
        .run([r]).trades[0]
    assert trade_.exit_reason == "trailing_stop"


def test_curve_price_is_the_constant_products_own_price() -> None:
    assert curve_price(D("30.000000006"), D("1073000000")) == D("0.000000027959")
    assert curve_price(D(1), D(0)) is None
    assert curve_price(None, D(1)) is None


def test_the_csv_carries_every_trade_and_its_week() -> None:
    rows = trades_csv([trade(0, "1", "M1"), trade(1, "-1", "M2")])
    assert rows.splitlines()[0].startswith("mint,strategy,path,iso_week")
    assert "2026-W37" in rows and "2026-W38" in rows
    assert len(rows.strip().splitlines()) == 3
