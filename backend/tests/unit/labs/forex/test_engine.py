"""Backtest engine: fills, exits, sizing, limits, financing and ledger integrity.

Every scenario is a hand-built candle path with hand-computed expectations, so
a failure points at a rule rather than at a fixture. Costs default to zero so
prices and P&L can be read straight off the path; the costed tests exist to pin
the spread / slippage / commission arithmetic.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.labs.forex.engine import run_backtest
from app.labs.forex.types import (
    INSTRUMENTS,
    BacktestConfig,
    BacktestResult,
    Candle,
    CostConfig,
    Direction,
    DirectionMode,
    ExitReason,
    Instrument,
    RiskConfig,
    Session,
    Signal,
    SkipReason,
    StrategyId,
    StrategyParams,
    Timeframe,
)

pytestmark = pytest.mark.unit

EURUSD = INSTRUMENTS["EURUSD"]
USDJPY = INSTRUMENTS["USDJPY"]
D = Decimal
LONG, SHORT = Direction.LONG, Direction.SHORT

#: Tuesday 2024-01-02 08:00 UTC.
T0 = datetime(2024, 1, 2, 8, 0, tzinfo=UTC)
FLAT = (1.1, 1.1, 1.1, 1.1)

ZERO_COSTS = CostConfig(
    spread_pips=0.0,
    slippage_pips=0.0,
    commission_per_lot_side=D(0),
    financing_enabled=False,
)
REAL_COSTS = CostConfig(
    spread_pips=1.0,
    slippage_pips=0.2,
    commission_per_lot_side=D("3.50"),
    financing_enabled=False,
)
BASE_RISK = RiskConfig(
    initial_capital=D(1000),
    max_leverage=20,
    risk_per_trade_pct=D(1),
    max_daily_loss_pct=D(0),
    max_trades_per_day=10,
    max_open_positions=1,
    margin_closeout_pct=D(50),
)


def make_cfg(
    *,
    costs: CostConfig = ZERO_COSTS,
    risk: RiskConfig = BASE_RISK,
    tf: Timeframe = Timeframe.M5,
    **kw: object,
) -> BacktestConfig:
    return BacktestConfig(
        strategy=kw.pop("strategy", StrategyId.RSI_PULLBACK),  # type: ignore[arg-type]
        timeframe=tf,
        costs=costs,
        risk=risk,
        **kw,  # type: ignore[arg-type]
    )


def bars(
    specs: list[tuple[float, float, float, float]],
    *,
    start: datetime = T0,
    minutes: int = 5,
) -> list[Candle]:
    return [
        Candle(start + timedelta(minutes=minutes * k), o, h, lo, c)
        for k, (o, h, lo, c) in enumerate(specs)
    ]


def sig(
    index: int,
    direction: Direction = LONG,
    sd: float = 0.002,
    tpd: float | None = 0.004,
) -> Signal:
    return Signal(index, direction, sd, tpd, "test")


def run(
    cfg: BacktestConfig,
    candles: list[Candle],
    signals: list[Signal],
    **kw: object,
) -> BacktestResult:
    inst = kw.pop("instrument", EURUSD)
    return run_backtest(cfg, candles, signals, instrument=inst, **kw)  # type: ignore[arg-type]


# --- exact fills with full costs ------------------------------------------
# spread 1 pip -> half 0.00005; slippage 0.2 pip -> 0.00002; 1% of $1000 over a
# 20-pip stop -> 5,000 units; commission 5,000/100,000 * 3.50 = 0.175 -> 0.18
# per side (half-even), 0.36 round trip.


def test_long_take_profit_exact_prices_and_pnl() -> None:
    """A long fills at open + half + slip, the target fills exactly with no slippage,
    and the ledger nets commission: 5,000 x 0.0040 = 20.00 - 0.36 = 19.64."""
    candles = bars([FLAT, (1.1, 1.101, 1.0995, 1.1005), (1.1, 1.105, 1.1, 1.104), FLAT])
    res = run(make_cfg(costs=REAL_COSTS), candles, [sig(0)])
    (t,) = res.trades
    assert t.entry_price == pytest.approx(1.10007)
    assert t.stop_price == pytest.approx(1.09807)
    assert t.take_profit_price == pytest.approx(1.10407)
    assert t.exit_price == pytest.approx(1.10407)
    assert t.exit_reason is ExitReason.TAKE_PROFIT
    assert t.units == 5000
    assert t.risk_usd == D("10.00")
    assert t.gross_pnl == D("20.00")
    assert t.commission == D("0.36")
    assert t.net_pnl == D("19.64")
    assert t.r_multiple == pytest.approx(1.964)
    # 0.35 on entry (half + slip) + 0.25 on exit (half only: a limit fill).
    assert t.spread_slippage_cost == D("0.60")
    assert res.final_balance == D("1019.64")


def test_long_stop_loss_exact_prices_and_pnl() -> None:
    """A stop fills at the stop minus slippage: 5,000 x -0.00202 = -10.10, net -10.46."""
    candles = bars([FLAT, (1.1, 1.101, 1.0995, 1.1005), (1.1, 1.1, 1.097, 1.098), FLAT])
    res = run(make_cfg(costs=REAL_COSTS), candles, [sig(0)])
    (t,) = res.trades
    assert t.exit_reason is ExitReason.STOP_LOSS
    assert t.exit_price == pytest.approx(1.09805)
    assert t.gross_pnl == D("-10.10")
    assert t.net_pnl == D("-10.46")
    assert t.r_multiple == pytest.approx(-1.046)
    assert t.spread_slippage_cost == D("0.70")  # 0.35 in + 0.35 out
    assert not t.ambiguous_exit


def test_short_take_profit_exact_prices_and_pnl() -> None:
    """Shorts mirror longs: entry open - half - slip, target on low + half."""
    candles = bars([FLAT, (1.1, 1.101, 1.099, 1.1), (1.1, 1.1, 1.095, 1.096), FLAT])
    res = run(make_cfg(costs=REAL_COSTS), candles, [sig(0, SHORT)])
    (t,) = res.trades
    assert t.entry_price == pytest.approx(1.09993)
    assert t.stop_price == pytest.approx(1.10193)
    assert t.take_profit_price == pytest.approx(1.09593)
    assert t.exit_price == pytest.approx(1.09593)
    assert t.exit_reason is ExitReason.TAKE_PROFIT
    assert t.gross_pnl == D("20.00")
    assert t.net_pnl == D("19.64")


def test_short_stop_loss_exact_prices_and_pnl() -> None:
    candles = bars([FLAT, (1.1, 1.101, 1.099, 1.1), (1.1, 1.103, 1.1, 1.102), FLAT])
    res = run(make_cfg(costs=REAL_COSTS), candles, [sig(0, SHORT)])
    (t,) = res.trades
    assert t.exit_reason is ExitReason.STOP_LOSS
    assert t.exit_price == pytest.approx(1.10195)
    assert t.gross_pnl == D("-10.10")
    assert t.net_pnl == D("-10.46")


def test_entry_is_next_bar_open_never_signal_close() -> None:
    """The signal bar's close was not tradable when the decision was made."""
    candles = bars([(1.2, 1.2, 1.2, 1.2), (1.1, 1.1, 1.1, 1.1), FLAT, FLAT])
    res = run(make_cfg(), candles, [sig(0)])
    (t,) = res.trades
    assert t.entry_price == 1.1
    assert t.entry_price != candles[0].close
    assert t.entry_time == candles[1].open_time
    assert t.signal_time == candles[0].open_time


def test_gap_through_stop_fills_at_the_open_not_the_stop() -> None:
    """Price jumped over the stop: the stop order fills at the first price
    available, which is worse than the stop."""
    candles = bars([FLAT, FLAT, (1.095, 1.096, 1.094, 1.095), FLAT])
    res = run(make_cfg(), candles, [sig(0)])
    (t,) = res.trades
    assert t.stop_price == pytest.approx(1.098)
    assert t.exit_price == pytest.approx(1.095)
    assert t.exit_reason is ExitReason.STOP_LOSS
    assert t.gross_pnl == D("-25.00")
    assert not t.ambiguous_exit


# --- same-bar stop + target ------------------------------------------------

BOTH_BAR = (1.1, 1.105, 1.097, 1.1)  # touches stop 1.098 and target 1.104


def _minutes(
    specs: list[tuple[float, float, float, float]], start: datetime
) -> list[Candle]:
    return bars(specs, start=start, minutes=1)


def test_same_bar_stop_and_target_without_lower_tf_is_stop_and_flagged() -> None:
    """The bar cannot say which came first; assuming the target would flatter."""
    candles = bars([FLAT, FLAT, BOTH_BAR, FLAT])
    res = run(make_cfg(), candles, [sig(0)])
    (t,) = res.trades
    assert t.exit_reason is ExitReason.STOP_LOSS
    assert t.ambiguous_exit
    assert res.exits_ambiguous == 1
    assert res.exits_resolved_by_lower_tf == 0


def test_same_bar_target_first_resolved_by_lower_tf() -> None:
    candles = bars([FLAT, FLAT, BOTH_BAR, FLAT])
    ltf = _minutes(
        [
            (1.1, 1.105, 1.1, 1.104),
            (1.104, 1.104, 1.097, 1.098),
            (1.098, 1.1, 1.098, 1.1),
            (1.1, 1.1, 1.1, 1.1),
            (1.1, 1.1, 1.1, 1.1),
        ],
        candles[2].open_time,
    )
    res = run(make_cfg(), candles, [sig(0)], lower_tf=ltf)
    (t,) = res.trades
    assert t.exit_reason is ExitReason.TAKE_PROFIT
    assert t.exit_price == pytest.approx(1.104)
    assert not t.ambiguous_exit
    assert res.exits_resolved_by_lower_tf == 1
    assert res.exits_ambiguous == 0


def test_same_bar_stop_first_resolved_by_lower_tf() -> None:
    candles = bars([FLAT, FLAT, BOTH_BAR, FLAT])
    ltf = _minutes(
        [
            (1.1, 1.1, 1.097, 1.098),
            (1.098, 1.105, 1.098, 1.104),
            (1.104, 1.104, 1.1, 1.1),
            (1.1, 1.1, 1.1, 1.1),
            (1.1, 1.1, 1.1, 1.1),
        ],
        candles[2].open_time,
    )
    res = run(make_cfg(), candles, [sig(0)], lower_tf=ltf)
    (t,) = res.trades
    assert t.exit_reason is ExitReason.STOP_LOSS
    assert t.exit_price == pytest.approx(1.098)
    assert not t.ambiguous_exit
    assert res.exits_resolved_by_lower_tf == 1


def test_both_levels_inside_one_minute_stays_ambiguous_stop_first() -> None:
    candles = bars([FLAT, FLAT, BOTH_BAR, FLAT])
    ltf = _minutes(
        [
            (1.1, 1.105, 1.097, 1.1),
            (1.1, 1.1, 1.1, 1.1),
            (1.1, 1.1, 1.1, 1.1),
            (1.1, 1.1, 1.1, 1.1),
            (1.1, 1.1, 1.1, 1.1),
        ],
        candles[2].open_time,
    )
    res = run(make_cfg(), candles, [sig(0)], lower_tf=ltf)
    (t,) = res.trades
    assert t.exit_reason is ExitReason.STOP_LOSS
    assert t.ambiguous_exit
    assert res.exits_ambiguous == 1


def test_lower_tf_with_missing_minutes_falls_back_to_ambiguous() -> None:
    """A partial walk could miss an earlier touch, so incomplete coverage is
    treated as no coverage."""
    candles = bars([FLAT, FLAT, BOTH_BAR, FLAT])
    ltf = _minutes([(1.1, 1.105, 1.1, 1.104), (1.104, 1.104, 1.097, 1.098)], candles[2].open_time)
    res = run(make_cfg(), candles, [sig(0)], lower_tf=ltf)
    assert res.trades[0].ambiguous_exit
    assert res.exits_ambiguous == 1


# --- sizing -----------------------------------------------------------------


def test_position_size_comes_from_stop_distance() -> None:
    """$1000 x 1% = $10 risk over a 20-pip stop on EURUSD = 5,000 units."""
    res = run(make_cfg(), bars([FLAT] * 4), [sig(0)])
    (t,) = res.trades
    assert t.units == 5000
    assert t.risk_usd == D("10.00")
    assert t.margin_used == D("275.00")  # 5,000 x 1.10 / 20


def test_usdjpy_pip_value_conversion() -> None:
    """On USDJPY the P&L is in JPY and converts at the exit price: risk $10 over
    a 15-pip (0.15 yen) stop at 150.00 is 10,000 units; +0.30 yen on 10,000 units
    is 3,000 JPY = 3000 / 150.30 = $19.96."""
    flat = (150.0, 150.0, 150.0, 150.0)
    win = (150.0, 150.4, 150.0, 150.3)
    candles = bars([flat, flat, win, flat])
    res = run(make_cfg(), candles, [sig(0, sd=0.15, tpd=0.30)], instrument=USDJPY)
    (t,) = res.trades
    assert t.units == 10_000
    assert t.risk_usd == D("10.00")
    assert t.margin_used == D("500.00")  # USD is the base: 10,000 / 20
    assert t.exit_reason is ExitReason.TAKE_PROFIT
    assert t.gross_pnl == D("19.96")


def test_unsupported_cross_is_refused() -> None:
    gbpjpy = Instrument("GBPJPY", "GBP", "JPY", 0.01, 3)
    with pytest.raises(ValueError, match="unsupported cross"):
        run(make_cfg(), bars([FLAT] * 3), [sig(0)], instrument=gbpjpy)


def test_leverage_cap_binds_and_margin_stays_within_equity() -> None:
    """A 1-pip stop would size to 100,000 units; 20x leverage on $1000 allows
    18,000. The cap shrinks size — it does not change how P&L is computed."""
    res = run(make_cfg(), bars([FLAT] * 4), [sig(0, sd=0.0001, tpd=None)])
    (t,) = res.trades
    assert t.units == 18_000
    assert t.margin_used == D("990.00")
    assert t.margin_used <= D(1000)
    assert t.risk_usd == D("1.80")  # the risk actually carried, not the $10 target


def test_margin_insufficient_when_other_positions_use_the_margin() -> None:
    risk = replace(BASE_RISK, max_open_positions=2)
    candles = bars([FLAT] * 6)
    res = run(
        make_cfg(risk=risk),
        candles,
        [sig(0, sd=0.0001, tpd=None), sig(2)],
    )
    assert len(res.trades) == 1
    assert [s.reason for s in res.skipped] == [SkipReason.MARGIN_INSUFFICIENT]


def test_size_below_minimum_is_skipped() -> None:
    """0.05% of $1000 over 20 pips is 250 units, below one micro lot."""
    risk = replace(BASE_RISK, risk_per_trade_pct=D("0.05"))
    res = run(make_cfg(risk=risk), bars([FLAT] * 4), [sig(0)])
    assert res.trades == ()
    assert [s.reason for s in res.skipped] == [SkipReason.SIZE_BELOW_MINIMUM]
    assert res.signals == 1


def test_margin_closeout_on_adverse_gap_with_high_leverage() -> None:
    """Risk 80% at 100x gives 80,000 units. Price gaps 80 pips down: the stop
    (100 pips) is untouched, but equity 320 is under 50% of the 880 margin used,
    so the broker liquidates at the bar's adverse extreme."""
    risk = replace(BASE_RISK, max_leverage=100, risk_per_trade_pct=D(80))
    candles = bars([FLAT, FLAT, (1.092, 1.092, 1.0915, 1.092), FLAT])
    res = run(make_cfg(risk=risk), candles, [sig(0, sd=0.01, tpd=None)])
    (t,) = res.trades
    assert t.units == 80_000
    assert t.exit_reason is ExitReason.MARGIN_CLOSEOUT
    assert t.exit_price == pytest.approx(1.0915)
    assert t.net_pnl == D("-680.00")
    assert res.margin_closeouts == 1
    assert res.final_balance == D("320.00")


# --- entry limits ------------------------------------------------------------


def _hourly(n: int, start: datetime = T0) -> list[Candle]:
    return bars([FLAT] * n, start=start, minutes=60)


def _stop_bar_at(candles: list[Candle], k: int) -> None:
    candles[k] = Candle(candles[k].open_time, 1.1, 1.1, 1.097, 1.098)


def test_daily_loss_limit_blocks_later_entries_that_day_but_not_next_day() -> None:
    """4% risk -> the first stop-out loses $40, past the 3% ($30) day limit. The
    next signal that day is blocked; one on the next UTC day trades again."""
    risk = replace(BASE_RISK, risk_per_trade_pct=D(4), max_daily_loss_pct=D(3))
    candles = _hourly(20)
    _stop_bar_at(candles, 1)
    res = run(
        make_cfg(risk=risk, tf=Timeframe.H1),
        candles,
        [sig(0), sig(2), sig(15)],  # bar 16 is 2024-01-03 00:00
    )
    assert [t.entry_time for t in res.trades] == [candles[1].open_time, candles[16].open_time]
    assert [(s.time, s.reason) for s in res.skipped] == [
        (candles[2].open_time, SkipReason.DAILY_LOSS_LIMIT)
    ]


def test_daily_loss_limit_zero_disables_it() -> None:
    risk = replace(BASE_RISK, risk_per_trade_pct=D(4), max_daily_loss_pct=D(0))
    candles = _hourly(6)
    _stop_bar_at(candles, 1)
    res = run(make_cfg(risk=risk, tf=Timeframe.H1), candles, [sig(0), sig(2)])
    assert len(res.trades) == 2
    assert res.skipped == ()


def test_max_trades_per_day() -> None:
    risk = replace(BASE_RISK, max_trades_per_day=2, max_open_positions=5)
    res = run(make_cfg(risk=risk), bars([FLAT] * 8), [sig(0), sig(2), sig(4)])
    assert len(res.trades) == 2
    assert [s.reason for s in res.skipped] == [SkipReason.MAX_TRADES_PER_DAY]


def test_max_trades_per_day_resets_on_the_next_utc_day() -> None:
    risk = replace(BASE_RISK, max_trades_per_day=1, max_open_positions=5)
    res = run(make_cfg(risk=risk, tf=Timeframe.H1), _hourly(20), [sig(0), sig(2), sig(15)])
    assert len(res.trades) == 2
    assert [s.reason for s in res.skipped] == [SkipReason.MAX_TRADES_PER_DAY]


def test_max_open_positions() -> None:
    res = run(make_cfg(), bars([FLAT] * 6), [sig(0), sig(2)])
    assert len(res.trades) == 1
    assert [s.reason for s in res.skipped] == [SkipReason.MAX_OPEN_POSITIONS]


def test_direction_mode_filters_the_other_side() -> None:
    candles = bars([FLAT] * 8)
    longs = run(
        make_cfg(direction=DirectionMode.LONG_ONLY), candles, [sig(0, SHORT), sig(3, LONG)]
    )
    assert [t.direction for t in longs.trades] == [LONG]
    assert [s.reason for s in longs.skipped] == [SkipReason.DIRECTION_DISABLED]
    shorts = run(
        make_cfg(direction=DirectionMode.SHORT_ONLY), candles, [sig(0, SHORT), sig(3, LONG)]
    )
    assert [t.direction for t in shorts.trades] == [SHORT]
    assert [s.reason for s in shorts.skipped] == [SkipReason.DIRECTION_DISABLED]


def test_session_filter_judges_the_entry_bar() -> None:
    """Entry at 07:00 is inside 07:00-10:00; entry at 12:00 is not."""
    candles = _hourly(8, start=datetime(2024, 1, 2, 6, 0, tzinfo=UTC))
    cfg = make_cfg(tf=Timeframe.H1, session_filter=Session(7, 10))
    res = run(cfg, candles, [sig(0), sig(5)])
    assert [t.entry_time.hour for t in res.trades] == [7]
    assert [s.reason for s in res.skipped] == [SkipReason.OUTSIDE_SESSION]


def test_gap_before_entry_skips_the_signal() -> None:
    """A weekend or data hole between signal and entry bar is not a fill."""
    candles = bars([FLAT] * 6)
    del candles[2]  # bar 1 -> next bar is 10 minutes later
    res = run(make_cfg(), candles, [sig(1)])
    assert res.trades == ()
    assert [s.reason for s in res.skipped] == [SkipReason.GAP_BEFORE_ENTRY]


def test_signal_on_last_candle_has_no_next_bar() -> None:
    candles = bars([FLAT] * 4)
    res = run(make_cfg(), candles, [sig(3)])
    assert res.trades == ()
    assert [s.reason for s in res.skipped] == [SkipReason.NO_NEXT_BAR]
    assert res.signals == 1


# --- exits -------------------------------------------------------------------


def _session_end_candles() -> list[Candle]:
    specs = [
        FLAT,  # 07:00 signal
        FLAT,  # 08:00 entry
        (1.1, 1.102, 1.1, 1.102),  # 09:00
        (1.103, 1.103, 1.103, 1.103),  # 10:00 outside the window
        (1.104, 1.104, 1.104, 1.104),
    ]
    return bars(specs, start=datetime(2024, 1, 2, 7, 0, tzinfo=UTC), minutes=60)


def test_session_end_exit_for_non_london_strategy_uses_session_filter() -> None:
    candles = _session_end_candles()
    cfg = make_cfg(
        tf=Timeframe.H1,
        session_filter=Session(8, 10),
        params=StrategyParams(close_at_session_end=True),
    )
    res = run(cfg, candles, [sig(0, sd=0.01, tpd=None)])
    (t,) = res.trades
    assert t.exit_reason is ExitReason.SESSION_END
    assert t.exit_time == candles[3].open_time
    assert t.exit_price == pytest.approx(1.103)
    assert t.gross_pnl == D("3.00")  # 1,000 units x 0.003


def test_session_end_exit_for_london_breakout_uses_trading_session() -> None:
    candles = _session_end_candles()
    cfg = make_cfg(
        tf=Timeframe.H1,
        strategy=StrategyId.LONDON_BREAKOUT,
        params=StrategyParams(close_at_session_end=True, trading_session=Session(8, 10)),
    )
    res = run(cfg, candles, [sig(0, sd=0.01, tpd=None)])
    (t,) = res.trades
    assert t.exit_reason is ExitReason.SESSION_END
    assert t.exit_time == candles[3].open_time


def test_session_end_is_inert_without_a_window() -> None:
    cfg = make_cfg(tf=Timeframe.H1, params=StrategyParams(close_at_session_end=True))
    res = run(cfg, _session_end_candles(), [sig(0, sd=0.01, tpd=None)])
    assert res.trades[0].exit_reason is ExitReason.END_OF_DATA


def test_session_end_exit_precedes_entries_on_that_bar() -> None:
    """The window-closing exit realises its loss before the same bar's entry is
    judged, so a daily-loss block it causes applies to that entry."""
    risk = replace(BASE_RISK, risk_per_trade_pct=D(5), max_daily_loss_pct=D(3), max_open_positions=1)
    specs = [FLAT, FLAT, FLAT, (1.09, 1.09, 1.09, 1.09), FLAT, FLAT]
    candles = bars(specs, start=datetime(2024, 1, 2, 7, 0, tzinfo=UTC), minutes=60)
    cfg = make_cfg(
        tf=Timeframe.H1,
        risk=risk,
        params=StrategyParams(close_at_session_end=True),
        session_filter=Session(8, 10),
    )
    # Signal at idx 2 enters at 10:00 (outside the filter too) - use a wider
    # filter-free probe: the second signal's entry bar is the exit bar.
    res = run(cfg, candles, [sig(0, sd=0.05, tpd=None), sig(2, sd=0.05, tpd=None)])
    assert res.trades[0].exit_reason is ExitReason.SESSION_END
    assert res.trades[0].net_pnl < 0
    assert [s.reason for s in res.skipped] == [SkipReason.OUTSIDE_SESSION]


def _financing_run(
    start: datetime, hours: int, direction: Direction, enabled: bool
) -> BacktestResult:
    costs = replace(ZERO_COSTS, financing_enabled=enabled)
    candles = bars([FLAT] * hours, start=start, minutes=60)
    return run(
        make_cfg(costs=costs, tf=Timeframe.H1),
        candles,
        [sig(0, direction, tpd=None)],
    )


def test_financing_charges_rollovers_with_wednesday_triple() -> None:
    """Held Tue 20:00 -> Fri 03:00 crosses Tue (x1), Wed (x3) and Thu (x1) =
    5 nights; 5,000 units is 0.05 lot, so long pays 7.00 x 0.05 x 5 = 1.75 and
    short earns 2.00 x 0.05 x 5 = 0.50."""
    start = datetime(2024, 1, 2, 19, 0, tzinfo=UTC)
    long_res = _financing_run(start, 33, LONG, True)
    assert long_res.trades[0].financing == D("-1.75")
    assert long_res.trades[0].net_pnl == D("-1.75")
    assert long_res.final_balance == D("998.25")
    short_res = _financing_run(start, 33, SHORT, True)
    assert short_res.trades[0].financing == D("0.50")


def test_financing_single_wednesday_night_is_triple() -> None:
    res = _financing_run(datetime(2024, 1, 3, 19, 0, tzinfo=UTC), 8, LONG, True)
    assert res.trades[0].financing == D("-1.05")  # 7.00 x 0.05 x 3


def test_financing_disabled_charges_nothing() -> None:
    res = _financing_run(datetime(2024, 1, 2, 19, 0, tzinfo=UTC), 33, LONG, False)
    assert res.trades[0].financing == D("0.00")
    assert res.final_balance == D(1000)


def test_end_of_data_closes_and_counts_the_loser() -> None:
    """A position left open at the end is closed at the last close, not hidden."""
    candles = bars([FLAT, FLAT, FLAT, (1.095, 1.097, 1.095, 1.095)])
    res = run(make_cfg(), candles, [sig(0, sd=0.01, tpd=None)])
    (t,) = res.trades
    assert t.exit_reason is ExitReason.END_OF_DATA
    assert t.exit_price == pytest.approx(1.095)
    assert t.exit_time == candles[3].open_time + timedelta(minutes=5)
    assert t.net_pnl == D("-5.00")
    assert res.final_balance == D("995.00")


# --- ledger integrity -------------------------------------------------------


def _mixed_path() -> tuple[list[Candle], list[Signal]]:
    win = (1.1, 1.105, 1.1, 1.104)
    loss = (1.1, 1.103, 1.1, 1.102)
    specs = [FLAT, FLAT, win, FLAT, FLAT, loss, FLAT, FLAT, FLAT, FLAT]
    return bars(specs), [sig(0), sig(3, SHORT), sig(6)]


def test_equity_curve_ends_at_initial_plus_sum_of_net() -> None:
    candles, signals = _mixed_path()
    res = run(make_cfg(costs=REAL_COSTS), candles, signals)
    assert len(res.trades) == 3
    net = sum((t.net_pnl for t in res.trades), D(0))
    assert res.final_balance == D(1000) + net
    assert res.equity_curve[0].equity == D(1000)
    assert res.equity_curve[-1].equity == res.final_balance
    assert res.equity_curve[-1].balance == res.final_balance
    assert res.equity_curve[-1].margin_utilization_pct == 0.0


def test_no_losing_trade_is_dropped() -> None:
    """Every signal is either a trade or a recorded skip, and the losers stay."""
    candles, signals = _mixed_path()
    res = run(make_cfg(costs=REAL_COSTS), candles, signals)
    assert len(res.trades) + len(res.skipped) == res.signals == 3
    reasons = [t.exit_reason for t in res.trades]
    assert reasons == [ExitReason.TAKE_PROFIT, ExitReason.STOP_LOSS, ExitReason.END_OF_DATA]
    assert sum(1 for t in res.trades if t.net_pnl < 0) == 2
    assert [t.id for t in res.trades] == [1, 2, 3]


def test_equity_curve_marks_open_positions_and_margin_utilisation() -> None:
    """While a position is open the day-end point is marked at the close, exit
    side, and utilisation is margin / equity."""
    candles = _hourly(30)
    candles[10] = Candle(candles[10].open_time, 1.1, 1.101, 1.1, 1.101)
    res = run(make_cfg(tf=Timeframe.H1), candles, [sig(0, sd=0.01, tpd=None)])
    # 1,000 units; Jan 2 ends at bar 15 (23:00) with the price at 1.1 -> flat P&L.
    day_end = [p for p in res.equity_curve if p.time == candles[15].open_time]
    assert day_end and day_end[0].equity == D("1000.00")
    assert day_end[0].margin_utilization_pct == pytest.approx(5.5)  # 55 / 1000


def test_trade_from_ignores_earlier_signals_entirely() -> None:
    """Warm-up signals are not counted, not traded and not listed as skipped."""
    candles = bars([FLAT] * 10)
    res = run(
        make_cfg(), candles, [sig(0), sig(1), sig(5)], trade_from=candles[4].open_time
    )
    assert res.signals == 1
    assert [t.signal_time for t in res.trades] == [candles[5].open_time]
    assert res.skipped == ()
    assert res.start == candles[4].open_time
    assert res.end == candles[-1].open_time
    assert res.bars == 6
    assert res.equity_curve[0].time == candles[4].open_time


def test_deterministic_two_runs_are_equal() -> None:
    candles, signals = _mixed_path()
    cfg = make_cfg(costs=REAL_COSTS)
    assert run(cfg, candles, signals) == run(cfg, candles, signals)


def test_no_lookahead_future_candles_do_not_change_a_closed_trade() -> None:
    """A trade that exited at bar k depends only on bars <= k: cutting the data
    there, or rewriting everything after it, leaves the trade identical."""
    candles, signals = _mixed_path()
    cfg = make_cfg(costs=REAL_COSTS)
    full = run(cfg, candles, signals)
    first = full.trades[0]
    k = next(i for i, c in enumerate(candles) if c.open_time == first.exit_time)

    cut = run(cfg, candles[: k + 1], [s for s in signals if s.index <= k])
    assert cut.trades[0] == first

    wild = candles[: k + 1] + [Candle(c.open_time, 9.0, 9.0, 0.5, 5.0) for c in candles[k + 1 :]]
    assert run(cfg, wild, signals).trades[0] == first
