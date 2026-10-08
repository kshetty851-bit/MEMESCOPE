"""The paper account: fills, exits, sizing, costs and the metrics built on them.

Most tests drive one trade through a scripted tail of candles after a known
signal, so every number can be derived by hand. The constants in the
expectations were computed independently of the code under test (Decimal
arithmetic written out in the docstrings), not copied from its output.

Setup shared by the scripted tests: a 20-candle window on 60,000-61,000, then a
candle closing at `price` (index 20, the signal), then the scripted tail whose
first candle (index 21) is the entry candle. Leverage is raised to 10x so the
risk budget, not the notional cap, sizes the position — the cap has its own tests.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.labs.btc_range.engine import evaluate
from app.labs.btc_range.execution import compute_metrics, run_backtest
from app.labs.btc_range.types import (
    BacktestResult,
    Call,
    Candle,
    ExitReason,
    Reason,
    Trade,
)
from tests.unit.labs.btc_range.builders import (
    LOOKBACK,
    OSC_LOOKBACK,
    STEP,
    T0,
    cfg,
    extend,
    flat,
    osc_cfg,
    oscillation,
    ranging_window,
    trend,
    with_price,
)

pytestmark = pytest.mark.unit

Oscillating = tuple[list[Candle], BacktestResult]
LEV = Decimal(10)
LONG_PRICE = 60100
SHORT_PRICE = 60900


def scripted(price: int, *tail: tuple[object, object, object, object]) -> list[Candle]:
    return extend(with_price(ranging_window(), price), tail)


def run(
    price: int, *tail: tuple[object, object, object, object], **overrides: object
) -> BacktestResult:
    overrides.setdefault("max_leverage", LEV)
    return run_backtest(scripted(price, *tail), cfg(**overrides))


# --- one trade, by hand ------------------------------------------------------


def test_a_long_taking_profit_pays_exactly_the_hand_computed_amount() -> None:
    """
    entry   60,100 * 1.0002                     = 60,112.02
    qty     floor(10.00 / (60,112.02-59,850), 5) = 0.03816   (1% of 1,000 risked)
    entry   notional 0.03816 * 60,112.02         = 2,293.87   fee 10 bps = 2.29
    exit    60,500 * 0.9998                      = 60,487.90
    exit    notional 0.03816 * 60,487.90         = 2,308.22   fee = 2.31
    gross   0.03816 * (60,487.90 - 60,112.02)    = 14.34
    net     14.34 - 2.29 - 2.31                  = 9.74;  R = 9.74 / 10.00
    """
    result = run(
        LONG_PRICE,
        (60100, 60200, 60050, 60150),
        (60150, 60600, 60100, 60550),
    )

    (trade,) = result.trades
    assert trade.side is Call.LONG
    assert trade.entry_price == Decimal("60112.02")
    assert trade.quantity == Decimal("0.03816")
    assert trade.notional == Decimal("2293.87")
    assert trade.exit_price == Decimal("60487.90")
    assert trade.exit_reason is ExitReason.TAKE_PROFIT
    assert trade.fees == Decimal("4.60")
    assert trade.pnl == Decimal("9.74")
    assert trade.r_multiple == Decimal("0.9740")
    assert trade.take_profit == Decimal(60500)
    assert trade.stop_loss == Decimal(59850)
    assert result.metrics.ending_equity == Decimal("1009.74")
    assert result.metrics.return_pct == Decimal("0.9740")


def test_the_entry_fills_at_the_next_candles_open_not_the_signals_close() -> None:
    """The candle that made the decision cannot be the candle that traded on it."""
    candles = scripted(LONG_PRICE, (60130, 60200, 60050, 60150), (60150, 60600, 60100, 60550))
    result = run_backtest(candles, cfg(max_leverage=LEV))

    (trade,) = result.trades
    assert trade.signal_at == candles[LOOKBACK].open_time
    assert trade.entry_at == candles[LOOKBACK + 1].open_time
    assert trade.entry_price == Decimal("60142.03")  # 60,130 * 1.0002, not 60,100


def test_a_stop_inside_the_entry_candle_counts() -> None:
    """
    exit 59,850 * 0.9998 = 59,838.03; gross 0.03816 * (59,838.03-60,112.02) = -10.46
    net -10.46 - 2.29 - 2.28 = -15.03. The loss exceeds 1R because costs come on top.
    """
    result = run(LONG_PRICE, (60100, 60150, 59800, 59900))

    (trade,) = result.trades
    assert trade.exit_reason is ExitReason.STOP_LOSS
    assert trade.exit_at == trade.entry_at
    assert trade.exit_price == Decimal("59838.03")
    assert trade.pnl == Decimal("-15.03")
    assert trade.r_multiple == Decimal("-1.5030")


def test_a_candle_holding_both_stop_and_target_counts_as_the_stop() -> None:
    """OHLC cannot order the two; crediting the target would flatter the result."""
    result = run(LONG_PRICE, (60100, 60600, 59800, 60000))

    (trade,) = result.trades
    assert trade.exit_reason is ExitReason.STOP_LOSS
    assert trade.exit_price == Decimal("59838.03")


def test_the_short_side_resolves_a_double_hit_against_us_too() -> None:
    result = run(SHORT_PRICE, (60900, 61200, 60400, 60800))

    (trade,) = result.trades
    assert trade.side is Call.SHORT
    assert trade.exit_reason is ExitReason.STOP_LOSS


def test_a_gap_through_the_stop_fills_at_the_open_not_the_stop() -> None:
    """
    The stop was 59,850 but the market never traded there: it opened at 59,700.
    exit 59,700 * 0.9998 = 59,688.06; gross -16.18; net -16.18 - 2.29 - 2.28 = -20.75.
    """
    result = run(
        LONG_PRICE,
        (60100, 60200, 60000, 60100),
        (59700, 59800, 59600, 59700),
    )

    (trade,) = result.trades
    assert trade.exit_reason is ExitReason.STOP_LOSS
    assert trade.exit_price == Decimal("59688.06")
    assert trade.pnl == Decimal("-20.75")
    assert trade.r_multiple == Decimal("-2.0750")


def test_a_gap_through_the_target_fills_at_the_open() -> None:
    """Opening at 60,700 against a 60,500 target: the better price is real, take it."""
    result = run(
        LONG_PRICE,
        (60100, 60200, 60000, 60100),
        (60700, 60800, 60650, 60750),
    )

    (trade,) = result.trades
    assert trade.exit_reason is ExitReason.TAKE_PROFIT
    assert trade.exit_price == Decimal("60687.86")  # 60,700 * 0.9998
    assert trade.pnl == Decimal("17.36")


def test_a_short_taking_profit_is_the_mirror_with_adverse_fills() -> None:
    """
    entry 60,900 * 0.9998 = 60,887.82; qty floor(10 / (61,150-60,887.82), 5) = 0.03814
    exit  60,500 * 1.0002 = 60,512.10 (a buy pays up)
    gross 14.33; fees 2.32 + 2.31; net 9.70
    """
    result = run(SHORT_PRICE, (60900, 60950, 60450, 60500))

    (trade,) = result.trades
    assert trade.side is Call.SHORT
    assert trade.entry_price == Decimal("60887.82")
    assert trade.quantity == Decimal("0.03814")
    assert trade.exit_price == Decimal("60512.10")
    assert trade.exit_reason is ExitReason.TAKE_PROFIT
    assert trade.pnl == Decimal("9.70")


def test_a_short_stop_loses_with_adverse_fill() -> None:
    result = run(SHORT_PRICE, (60900, 61200, 60850, 61100))

    (trade,) = result.trades
    assert trade.exit_reason is ExitReason.STOP_LOSS
    assert trade.exit_price == Decimal("61162.23")  # 61,150 * 1.0002
    assert trade.pnl == Decimal("-15.12")


# --- time stop, end of data, open positions -----------------------------------


QUIET = (60100, 60200, 60000, 60150)


def test_the_time_stop_exits_at_the_close_of_the_nth_candle_counting_the_entry() -> None:
    """max_hold 3: held on candles 21, 22 and 23 -> out at candle 23's close, adversely."""
    candles = scripted(LONG_PRICE, QUIET, QUIET, QUIET, QUIET, QUIET)
    result = run_backtest(candles, cfg(max_leverage=LEV, max_hold_candles=3))

    (trade,) = result.trades
    assert trade.exit_reason is ExitReason.TIME_STOP
    assert trade.exit_at == candles[LOOKBACK + 3].open_time
    assert trade.exit_price == Decimal("60137.97")  # 60,150 * 0.9998
    assert trade.pnl == Decimal("-3.59")


def test_a_time_stop_of_one_exits_on_the_entry_candle() -> None:
    result = run(LONG_PRICE, QUIET, QUIET, max_hold_candles=1)
    (trade,) = result.trades
    assert trade.exit_at == trade.entry_at


def test_a_stop_beats_the_time_stop_on_the_same_candle() -> None:
    result = run(LONG_PRICE, (60100, 60150, 59800, 59900), max_hold_candles=1)
    assert result.trades[0].exit_reason is ExitReason.STOP_LOSS


def test_a_zero_hold_limit_disables_the_time_stop() -> None:
    result = run(LONG_PRICE, QUIET, QUIET, QUIET, max_hold_candles=0)
    (trade,) = result.trades
    assert trade.exit_reason is ExitReason.END_OF_DATA


def test_a_position_open_at_the_end_is_closed_at_the_last_close_with_costs() -> None:
    result = run(LONG_PRICE, QUIET, QUIET, max_hold_candles=0)

    (trade,) = result.trades
    assert trade.exit_reason is ExitReason.END_OF_DATA
    assert trade.exit_price == Decimal("60137.97")
    assert result.open_position is None
    # Ending equity agrees with the trades that produced it, not with a mark
    # taken before the exit fee.
    assert result.metrics.ending_equity == Decimal(1000) + trade.pnl
    assert result.equity_curve[-1].equity == result.metrics.ending_equity


def test_the_live_book_gets_the_open_position_back_instead_of_a_trade() -> None:
    """
    unrealised = 0.03816 * (60,150 - 60,112.02) - entry fee 2.29 = 1.45 - 2.29 = -0.84
    """
    candles = scripted(LONG_PRICE, QUIET, QUIET)
    result = run_backtest(
        candles, cfg(max_leverage=LEV, max_hold_candles=0), close_open_at_end=False
    )

    assert result.trades == ()
    position = result.open_position
    assert position is not None
    assert position.side is Call.LONG
    assert position.entry_price == Decimal("60112.02")
    assert position.entry_fee == Decimal("2.29")
    assert position.mark_price == Decimal("60150.00")
    assert position.unrealised_pnl == Decimal("-0.84")
    assert result.equity_curve[-1].equity == Decimal("999.16")
    assert result.metrics.ending_equity == Decimal("999.16")
    assert result.metrics.max_drawdown_pct is None  # no closed trade, nothing measured


def test_the_equity_curve_is_marked_to_market_at_each_close() -> None:
    result = run(LONG_PRICE, QUIET, (60150, 60600, 60100, 60550))

    # idx 20 signal candle, flat; idx 21 open at a mark of 60,150; idx 22 closed.
    assert [p.equity for p in result.equity_curve] == [
        Decimal("1000"),
        Decimal("999.16"),
        Decimal("1009.74"),
    ]
    assert [p.at for p in result.equity_curve] == [T0 + STEP * k for k in (20, 21, 22)]


# --- sizing ------------------------------------------------------------------


def test_risk_per_trade_sets_the_quantity_when_the_cap_does_not_bind() -> None:
    """A stop-out before costs loses at most the 1% risk budget, never more."""
    result = run(LONG_PRICE, (60100, 60150, 59800, 59900))
    (trade,) = result.trades

    stop_loss_before_costs = trade.quantity * (trade.entry_price - trade.stop_loss)
    assert Decimal("9.99") < stop_loss_before_costs <= Decimal("10.00")


def test_the_leverage_cap_limits_notional_to_equity_times_leverage() -> None:
    """At 1x, 1,000 buys 0.01663 BTC at 60,112.02 (999.66), not the 0.03816 risk asks for."""
    result = run(LONG_PRICE, QUIET, QUIET, max_leverage=Decimal(1))

    (trade,) = result.trades
    assert trade.quantity == Decimal("0.01663")
    assert trade.notional == Decimal("999.66")
    assert trade.notional <= Decimal(1000)


def test_a_leverage_below_one_sizes_below_the_account() -> None:
    result = run(LONG_PRICE, QUIET, QUIET, max_leverage=Decimal("0.5"))
    assert result.trades[0].notional <= Decimal(500)


def test_the_quantity_rounds_down_never_up() -> None:
    """Rounding up could breach the cap or the risk budget by a fraction of a satoshi-lot."""
    result = run(LONG_PRICE, QUIET, QUIET)
    (trade,) = result.trades
    assert trade.quantity == Decimal("0.03816")  # 0.0381650... floors, not rounds


def test_a_zero_balance_never_trades() -> None:
    result = run(LONG_PRICE, QUIET, QUIET, starting_balance=Decimal(0))
    assert result.trades == ()
    assert result.open_position is None


def test_a_signal_that_cannot_be_sized_is_skipped_not_forced() -> None:
    """With a risk budget of zero the quantity is zero; the strategy stands aside."""
    result = run(LONG_PRICE, QUIET, QUIET, risk_per_trade_pct=Decimal(0))
    assert result.trades == ()
    assert result.signal_counts[Call.LONG] >= 1


def test_each_trade_risks_a_percent_of_the_cash_at_its_own_entry() -> None:
    """Equity is cash while flat, so the risk budget compounds with realised P&L.

    The budget is recovered as pnl / r_multiple and compared with 1% of the
    running balance; trades with a tiny r are skipped because r is rounded to
    four places and the quotient would be noise.
    """
    result = run_backtest(
        oscillation(3000),
        osc_cfg(max_leverage=Decimal(100), cooldown_candles=0, risk_per_trade_pct=Decimal(2)),
    )
    assert len(result.trades) > 10
    balance = Decimal(1000)
    checked = 0
    for trade in result.trades:
        if trade.r_multiple is not None and abs(trade.r_multiple) > Decimal("0.2"):
            budget = trade.pnl / trade.r_multiple
            assert abs(budget - balance * Decimal("0.02")) <= balance * Decimal("0.0005")
            checked += 1
        balance += trade.pnl
    assert checked > 5


# --- flow --------------------------------------------------------------------


def test_one_position_at_a_time() -> None:
    result = run_backtest(oscillation(1500), osc_cfg())
    assert len(result.trades) > 5
    for earlier, later in zip(result.trades, result.trades[1:], strict=False):
        assert later.entry_at > earlier.exit_at


def test_cooldown_keeps_the_account_flat_after_an_exit() -> None:
    """Between an exit and the next entry sit at least `cooldown_candles` flat candles."""
    for cooldown in (0, 4, 12):
        result = run_backtest(oscillation(1500), osc_cfg(cooldown_candles=cooldown))
        assert result.trades
        for earlier, later in zip(result.trades, result.trades[1:], strict=False):
            flat_candles = (later.entry_at - earlier.exit_at) // STEP - 1
            assert flat_candles >= cooldown


def test_a_longer_cooldown_never_adds_trades_it_only_removes_opportunity() -> None:
    quick = run_backtest(oscillation(1500), osc_cfg(cooldown_candles=0))
    slow = run_backtest(oscillation(1500), osc_cfg(cooldown_candles=30))
    assert len(slow.trades) <= len(quick.trades)
    assert slow.signal_counts[Call.WAIT] + slow.signal_counts[Call.LONG] + slow.signal_counts[
        Call.SHORT
    ] < sum(quick.signal_counts.values())


def test_the_last_candle_is_never_traded_on() -> None:
    """A signal on the final candle has no next open to fill at."""
    candles = with_price(ranging_window(), LONG_PRICE)  # signal on the very last candle
    result = run_backtest(candles, cfg())

    assert result.trades == ()
    assert result.open_position is None
    assert result.last_signal is not None
    assert result.last_signal.call is Call.LONG
    assert result.signal_counts == {Call.LONG: 0, Call.SHORT: 0, Call.WAIT: 0}


# --- the oscillating range: the strategy does what it claims ------------------


@pytest.fixture(scope="module")
def oscillating() -> Oscillating:
    candles = oscillation(2000)
    return candles, run_backtest(candles, osc_cfg())


def test_longs_are_taken_only_near_support_and_shorts_only_near_resistance(
    oscillating: Oscillating,
) -> None:
    """Re-derive each trade's signal from the candles: the zone is a property of the trade."""
    candles, result = oscillating
    by_time = {c.open_time: i for i, c in enumerate(candles)}
    assert {t.side for t in result.trades} == {Call.LONG, Call.SHORT}

    for trade in result.trades:
        i = by_time[trade.signal_at]
        signal = evaluate(candles[i - OSC_LOOKBACK : i + 1], osc_cfg())
        assert signal.call is trade.side
        assert signal.range is not None
        if trade.side is Call.LONG:
            assert signal.range.position <= Decimal("0.20")
            assert signal.reasons == (Reason.NEAR_SUPPORT,)
        else:
            assert signal.range.position >= Decimal("0.80")
            assert signal.reasons == (Reason.NEAR_RESISTANCE,)


def test_trade_prices_are_adverse_to_the_candle_they_filled_in(
    oscillating: Oscillating,
) -> None:
    candles, result = oscillating
    by_time = {c.open_time: c for c in candles}
    for trade in result.trades:
        entry_candle = by_time[trade.entry_at]
        if trade.side is Call.LONG:
            assert trade.entry_price >= entry_candle.open
        else:
            assert trade.entry_price <= entry_candle.open


def test_every_trade_time_is_a_real_candle_time(oscillating: Oscillating) -> None:
    candles, result = oscillating
    times = {c.open_time for c in candles}
    for trade in result.trades:
        assert {trade.signal_at, trade.entry_at, trade.exit_at} <= times
        assert trade.signal_at < trade.entry_at <= trade.exit_at


def test_disabling_a_side_removes_exactly_that_side() -> None:
    candles = oscillation(2000)
    longs_only = run_backtest(candles, osc_cfg(allow_short=False))
    shorts_only = run_backtest(candles, osc_cfg(allow_long=False))

    assert longs_only.trades and {t.side for t in longs_only.trades} == {Call.LONG}
    assert shorts_only.trades and {t.side for t in shorts_only.trades} == {Call.SHORT}
    assert longs_only.wait_reasons.get(Reason.SIDE_DISABLED, 0) > 0


def test_long_and_short_metrics_sum_to_the_totals(oscillating: Oscillating) -> None:
    _, result = oscillating
    total, long, short = result.metrics, result.long_metrics, result.short_metrics

    assert total.trades == long.trades + short.trades > 0
    assert total.wins == long.wins + short.wins
    assert total.losses == long.losses + short.losses
    assert total.net_pnl == long.net_pnl + short.net_pnl
    assert total.gross_profit == long.gross_profit + short.gross_profit
    assert total.gross_loss == long.gross_loss + short.gross_loss


def test_ending_equity_is_start_plus_net_pnl_when_nothing_is_left_open(
    oscillating: Oscillating,
) -> None:
    _, result = oscillating
    assert result.open_position is None
    assert result.metrics.ending_equity == Decimal(1000) + result.metrics.net_pnl
    assert result.equity_curve[-1].equity == result.metrics.ending_equity


def test_signal_counts_cover_every_evaluated_candle(oscillating: Oscillating) -> None:
    candles, result = oscillating
    assert sum(result.signal_counts.values()) <= len(candles) - OSC_LOOKBACK - 1
    assert sum(result.wait_reasons.values()) == result.signal_counts[Call.WAIT]
    assert len(result.equity_curve) == len(candles) - OSC_LOOKBACK


def test_a_backtest_is_deterministic() -> None:
    candles = oscillation(1500)
    assert run_backtest(candles, osc_cfg()) == run_backtest(candles, osc_cfg())


def test_gaps_in_the_data_are_used_as_given_not_filled() -> None:
    """Dropping candles leaves a shorter series; no candle is invented to replace them."""
    candles = [c for i, c in enumerate(oscillation(1500)) if i % 97 != 0]
    result = run_backtest(candles, osc_cfg())

    assert result.candles == len(candles)
    assert len(result.equity_curve) == len(candles) - OSC_LOOKBACK
    times = {c.open_time for c in candles}
    assert all(p.at in times for p in result.equity_curve)
    assert all(t.entry_at in times and t.exit_at in times for t in result.trades)


def test_the_result_describes_the_data_it_ran_on(oscillating: Oscillating) -> None:
    candles, result = oscillating
    assert result.candles == len(candles)
    assert result.start == candles[0].open_time
    assert result.end == candles[-1].open_time
    assert result.last_signal is not None
    assert result.last_signal.at == candles[-1].open_time


# --- never force a trade -----------------------------------------------------


@pytest.mark.parametrize(
    "candles",
    [flat(500), trend(500), trend(500, step=-40)],
    ids=["flat", "uptrend", "downtrend"],
)
def test_data_without_a_qualified_signal_produces_no_trades(candles: list[Candle]) -> None:
    result = run_backtest(candles, cfg())

    assert result.trades == ()
    assert result.open_position is None
    assert result.signal_counts[Call.LONG] == 0
    assert result.signal_counts[Call.SHORT] == 0
    assert result.signal_counts[Call.WAIT] > 0
    assert all(p.equity == Decimal(1000) for p in result.equity_curve)
    metrics = result.metrics
    assert metrics.trades == 0
    assert metrics.win_rate is None
    assert metrics.profit_factor is None
    assert metrics.expectancy is None
    assert metrics.max_drawdown_pct is None
    assert metrics.net_pnl == 0
    assert metrics.return_pct == 0
    assert metrics.ending_equity == Decimal(1000)


def test_a_persistent_trend_waits_as_a_breakout_or_trending() -> None:
    """Every candle of a trend closes beyond its window, so the reason is a breakout."""
    up = run_backtest(trend(500), cfg())
    down = run_backtest(trend(500, step=-40), cfg())
    assert set(up.wait_reasons) <= {Reason.BREAKOUT_UP, Reason.TRENDING}
    assert set(down.wait_reasons) <= {Reason.BREAKOUT_DOWN, Reason.TRENDING}
    assert up.wait_reasons[Reason.BREAKOUT_UP] > 0


def test_fewer_candles_than_the_window_needs_yields_an_empty_honest_result() -> None:
    result = run_backtest(oscillation(OSC_LOOKBACK), osc_cfg())

    assert result.trades == ()
    assert result.equity_curve == ()
    assert result.last_signal is None
    assert result.metrics.ending_equity == Decimal(1000)
    assert result.metrics.max_drawdown_pct is None


def test_no_candles_at_all() -> None:
    result = run_backtest([], cfg())
    assert result.candles == 0
    assert result.start is None and result.end is None
    assert result.trades == ()


def test_a_nonsensical_lookback_is_refused() -> None:
    with pytest.raises(ValueError):
        run_backtest(flat(10), cfg(lookback=0))


# --- metrics -----------------------------------------------------------------


def _trade(pnl: str, side: Call = Call.LONG) -> Trade:
    return Trade(
        side=side,
        signal_at=T0,
        entry_at=T0 + STEP,
        entry_price=Decimal(100),
        take_profit=Decimal(110),
        stop_loss=Decimal(90),
        quantity=Decimal(1),
        notional=Decimal(100),
        exit_at=T0 + STEP * 2,
        exit_price=Decimal(100),
        exit_reason=ExitReason.TAKE_PROFIT,
        fees=Decimal(0),
        pnl=Decimal(pnl),
        r_multiple=None,
    )


def test_profit_factor_is_undefined_not_infinite_with_no_losing_trade() -> None:
    metrics = compute_metrics([_trade("5"), _trade("3")], Decimal(1000))

    assert metrics.profit_factor is None
    assert metrics.wins == 2
    assert metrics.losses == 0
    assert metrics.win_rate == Decimal("100.0000")


def test_summary_figures_from_known_trades() -> None:
    """Wins 10 and 5, losses 6 and 4: PF 15/10, win rate 50%, expectancy 5/4."""
    trades = [_trade("10"), _trade("-6"), _trade("5"), _trade("-4")]
    metrics = compute_metrics(trades, Decimal(1000))

    assert metrics.trades == 4
    assert (metrics.wins, metrics.losses) == (2, 2)
    assert metrics.win_rate == Decimal("50.0000")
    assert metrics.gross_profit == Decimal(15)
    assert metrics.gross_loss == Decimal(-10)
    assert metrics.net_pnl == Decimal(5)
    assert metrics.profit_factor == Decimal("1.5000")
    assert metrics.expectancy == Decimal("1.25")
    assert metrics.ending_equity == Decimal(1005)
    assert metrics.return_pct == Decimal("0.5000")


def test_a_flat_trade_is_neither_a_win_nor_a_loss() -> None:
    metrics = compute_metrics([_trade("0"), _trade("2")], Decimal(1000))
    assert (metrics.wins, metrics.losses) == (1, 0)
    assert metrics.win_rate == Decimal("50.0000")


def test_drawdown_is_peak_to_trough_on_the_equity_curve() -> None:
    """Peak 1,100 to trough 990 is 110/1,100 = 10%; the later recovery does not erase it."""
    curve = [Decimal(v) for v in (1000, 1100, 990, 1050, 1060)]
    metrics = compute_metrics([_trade("60")], Decimal(1000), curve)

    assert metrics.max_drawdown_pct == Decimal("10.0000")
    assert metrics.ending_equity == Decimal(1060)


def test_drawdown_counts_a_dip_below_the_starting_balance() -> None:
    curve = [Decimal(v) for v in (950, 900, 1000)]
    metrics = compute_metrics([_trade("0")], Decimal(1000), curve)
    assert metrics.max_drawdown_pct == Decimal("10.0000")


def test_a_side_without_its_own_curve_is_measured_on_its_realised_trades() -> None:
    """Start 1,000 -> 1,100 -> 1,045 -> 1,100: 55/1,100 = 5%."""
    trades = [_trade("100"), _trade("-55"), _trade("55")]
    metrics = compute_metrics(trades, Decimal(1000))

    assert metrics.max_drawdown_pct == Decimal("5.0000")
    assert metrics.ending_equity == Decimal(1100)


def test_a_curve_that_only_rises_has_a_zero_drawdown_once_traded() -> None:
    metrics = compute_metrics([_trade("10")], Decimal(1000))
    assert metrics.max_drawdown_pct == Decimal("0.0000")


def test_no_trades_means_none_for_every_figure_that_needs_one() -> None:
    metrics = compute_metrics([], Decimal(1000))

    assert metrics.trades == 0
    assert metrics.win_rate is None
    assert metrics.profit_factor is None
    assert metrics.expectancy is None
    assert metrics.max_drawdown_pct is None
    assert metrics.ending_equity == Decimal(1000)
    assert metrics.return_pct == Decimal("0.0000")


def test_the_drawdown_of_a_backtest_includes_the_unrealised_dip() -> None:
    """A trade that is down 20 mid-hold and finishes up still drew down."""
    result = run(
        LONG_PRICE,
        (60100, 60200, 59860, 59900),  # marks well below entry
        (59900, 60600, 59880, 60550),  # then recovers through the target
    )
    (trade,) = result.trades
    assert trade.pnl > 0
    assert result.metrics.max_drawdown_pct is not None
    assert result.metrics.max_drawdown_pct > 0
    assert result.long_metrics.max_drawdown_pct == Decimal("0.0000")
