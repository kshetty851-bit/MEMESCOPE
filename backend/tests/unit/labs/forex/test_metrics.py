"""Metrics are computed from hand-built results so each figure can be checked
against arithmetic done on paper. The properties that matter most: losing and
breakeven trades are never dropped, and a figure without enough data is None
with a reason code rather than an estimate."""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.labs.forex.metrics import (
    compute_metrics,
    drawdown_series,
    monthly_returns,
    t_statistic,
)
from app.labs.forex.types import (
    BacktestConfig,
    BacktestResult,
    Direction,
    EquityPoint,
    ExitReason,
    StrategyId,
    Trade,
)

pytestmark = pytest.mark.unit

T0 = datetime(2024, 1, 1, tzinfo=UTC)
D = Decimal


def trade(
    i: int,
    net: str,
    r: float,
    *,
    direction: Direction = Direction.LONG,
    exit_time: datetime | None = None,
    minutes: int = 60,
    commission: str = "0",
    spread: str = "0",
    financing: str = "0",
) -> Trade:
    exit_t = exit_time or T0 + timedelta(hours=i + 1)
    entry = exit_t - timedelta(minutes=minutes)
    return Trade(
        id=i,
        direction=direction,
        signal_time=entry,
        entry_time=entry,
        exit_time=exit_t,
        entry_price=1.1,
        exit_price=1.1,
        stop_price=1.09,
        take_profit_price=None,
        units=1000,
        risk_usd=D("10"),
        gross_pnl=D(net),
        commission=D(commission),
        spread_slippage_cost=D(spread),
        financing=D(financing),
        net_pnl=D(net),
        r_multiple=r,
        exit_reason=ExitReason.STOP_LOSS,
        reason="t",
    )


def result(
    trades: list[Trade],
    curve: list[EquityPoint] | None = None,
    *,
    start: datetime = T0,
    end: datetime = T0 + timedelta(days=30),
    final: str | None = None,
    **kw: int,
) -> BacktestResult:
    cfg = BacktestConfig(strategy=StrategyId.RSI_PULLBACK)
    bal = cfg.risk.initial_capital + sum((t.net_pnl for t in trades), D(0))
    return BacktestResult(
        config=cfg,
        start=start,
        end=end,
        bars=100,
        trades=tuple(trades),
        equity_curve=tuple(curve or []),
        skipped=(),
        final_balance=D(final) if final is not None else bal,
        **kw,
    )


def pt(t: datetime, eq: str, margin: float = 0.0) -> EquityPoint:
    return EquityPoint(time=t, balance=D(eq), equity=D(eq), margin_utilization_pct=margin)


def daily_curve(equities: list[float]) -> list[EquityPoint]:
    return [pt(T0 + timedelta(days=i, hours=23), f"{e:.2f}") for i, e in enumerate(equities)]


def test_counts_and_totals_keep_every_losing_and_breakeven_trade() -> None:
    """Dropping losers or breakevens would flatter the win rate; they are
    counted, with breakeven reported separately from wins and losses."""
    trades = [
        trade(0, "100", 2.0),
        trade(1, "50", 1.0),
        trade(2, "-40", -1.0),
        trade(3, "0", 0.0),
    ]
    m = compute_metrics(result(trades))
    assert (m.total_trades, m.wins, m.losses, m.breakeven) == (4, 2, 1, 1)
    assert m.win_rate_pct == pytest.approx(50.0)
    assert m.gross_profit == D("150")
    assert m.gross_loss == D("40")
    assert m.profit_factor == pytest.approx(3.75)
    assert m.avg_win == D("75.00")
    assert m.avg_loss == D("-40.00")
    assert m.largest_win == D("100")
    assert m.largest_loss == D("-40")
    assert m.expectancy_usd == D("27.50")
    assert m.expectancy_r == pytest.approx(0.5)
    assert m.net_profit == D("110")
    assert m.net_return_pct == pytest.approx(11.0)


def test_profit_factor_is_none_with_reason_when_no_losses() -> None:
    """Dividing by zero would give infinity; the absence of losses is stated."""
    m = compute_metrics(result([trade(0, "10", 1.0), trade(1, "5", 0.5)]))
    assert m.profit_factor is None
    assert m.profit_factor_note == "no_losses"


def test_zero_trades_yield_none_not_zero() -> None:
    """No trades means no win rate or expectancy, not a 0% one."""
    m = compute_metrics(result([]))
    assert m.total_trades == 0
    assert m.win_rate_pct is None
    assert m.expectancy_r is None
    assert m.expectancy_usd is None
    assert m.avg_trade_duration_minutes is None
    assert m.profit_factor_note == "no_trades"
    assert m.costs_pct_of_gross_profit is None
    assert m.net_profit == D(0)


def test_max_drawdown_is_peak_to_trough_on_equity_points() -> None:
    """1000 -> 1100 -> 880 is a 20% fall from the 1100 peak, 220 USD."""
    curve = [pt(T0 + timedelta(hours=h), e) for h, e in [(1, "1000"), (2, "1100"), (3, "880")]]
    m = compute_metrics(result([], curve))
    assert m.max_drawdown_pct == pytest.approx(20.0)
    assert m.max_drawdown_usd == D("220.00")


def test_drawdown_counts_a_loss_on_the_very_first_point() -> None:
    """The initial capital seeds the peak, so an opening loss is a drawdown."""
    m = compute_metrics(result([], [pt(T0 + timedelta(hours=1), "900")]))
    assert m.max_drawdown_pct == pytest.approx(10.0)


def test_drawdown_series_is_non_positive_and_tracks_running_peak() -> None:
    curve = [
        pt(T0 + timedelta(hours=h), e)
        for h, e in [(1, "100"), (2, "120"), (3, "90"), (4, "130")]
    ]
    series = drawdown_series(curve)
    assert [round(v, 4) for _, v in series] == [0.0, 0.0, -25.0, 0.0]
    assert all(v <= 0 for _, v in series)


def test_streaks_reset_on_breakeven() -> None:
    """A breakeven trade is neither a win nor a loss, so it ends both runs."""
    nets = ["1", "1", "1", "0", "1", "-1", "-1", "1", "-1", "-1", "-1", "-1"]
    trades = [trade(i, n, float(n)) for i, n in enumerate(nets)]
    m = compute_metrics(result(trades))
    assert m.longest_win_streak == 3
    assert m.longest_loss_streak == 4


def test_long_short_split() -> None:
    trades = [
        trade(0, "10", 1.0, direction=Direction.LONG),
        trade(1, "-5", -0.5, direction=Direction.LONG),
        trade(2, "20", 2.0, direction=Direction.SHORT),
    ]
    m = compute_metrics(result(trades))
    assert (m.long_trades, m.short_trades) == (2, 1)
    assert m.long_net == D("5")
    assert m.short_net == D("20")
    assert m.long_win_rate == pytest.approx(50.0)
    assert m.short_win_rate == pytest.approx(100.0)
    assert m.long_expectancy_r == pytest.approx(0.25)
    assert m.short_expectancy_r == pytest.approx(2.0)


def test_side_with_no_trades_is_none() -> None:
    m = compute_metrics(result([trade(0, "10", 1.0)]))
    assert m.short_trades == 0
    assert m.short_win_rate is None
    assert m.short_expectancy_r is None


def test_cost_totals_and_share_of_gross_profit() -> None:
    """Financing is a signed P&L effect: a negative swap is a cost."""
    trades = [
        trade(0, "100", 1.0, commission="3", spread="5", financing="-2"),
        trade(1, "-20", -1.0, commission="3", spread="5", financing="1"),
    ]
    m = compute_metrics(result(trades))
    assert m.total_commission == D("6")
    assert m.total_spread_slippage == D("10")
    assert m.total_financing == D("-1")
    assert m.costs_pct_of_gross_profit == pytest.approx(17.0)


def test_costs_share_is_none_without_gross_profit() -> None:
    m = compute_metrics(result([trade(0, "-5", -1.0, commission="1")]))
    assert m.costs_pct_of_gross_profit is None


def test_margin_utilisation_average_only_over_exposed_points() -> None:
    """Flat points would drag the average toward zero and hide how hard the
    account is worked while a position is open."""
    curve = [
        pt(T0 + timedelta(hours=1), "1000", 0.0),
        pt(T0 + timedelta(hours=2), "1000", 10.0),
        pt(T0 + timedelta(hours=3), "1000", 30.0),
    ]
    m = compute_metrics(result([], curve))
    assert m.max_margin_utilization_pct == 30.0
    assert m.avg_margin_utilization_pct == pytest.approx(20.0)
    flat = compute_metrics(result([], [pt(T0 + timedelta(hours=1), "1000")]))
    assert flat.avg_margin_utilization_pct is None


def test_average_duration_and_passthrough_counts() -> None:
    trades = [trade(0, "1", 1.0, minutes=30), trade(1, "1", 1.0, minutes=90)]
    m = compute_metrics(result(trades, exits_ambiguous=2, margin_closeouts=1))
    assert m.avg_trade_duration_minutes == pytest.approx(60.0)
    assert m.exits_ambiguous == 2
    assert m.margin_closeouts == 1


def test_monthly_trade_frequency_uses_calendar_months_spanned() -> None:
    """Jan-Mar with an exclusive end at Apr 1 is three months, not four."""
    trades = [trade(0, "1", 1.0), trade(1, "1", 1.0)]
    m = compute_metrics(result(trades, end=datetime(2024, 4, 1, tzinfo=UTC)))
    assert m.monthly_trade_frequency == pytest.approx(2 / 3)


def test_sharpe_withheld_below_sixty_daily_returns() -> None:
    """A ratio from a few weeks of returns is noise; it is withheld, not shown."""
    m = compute_metrics(result([], daily_curve([1000 + i for i in range(30)])))
    assert m.sharpe is None and m.sharpe_note == "insufficient_days"
    assert m.sortino is None and m.sortino_note == "insufficient_days"


def test_sharpe_zero_variance_is_reported() -> None:
    """Flat equity has no variance; the ratio is undefined, not infinite."""
    m = compute_metrics(result([], daily_curve([1000.0] * 70)))
    assert m.sharpe is None and m.sharpe_note == "zero_variance"
    assert m.sortino is None and m.sortino_note == "zero_downside"


def test_sharpe_and_sortino_values_from_daily_returns() -> None:
    eq = [1000.0]
    for i in range(80):
        eq.append(eq[-1] * (1.01 if i % 2 == 0 else 0.995))
    m = compute_metrics(result([], daily_curve(eq[1:])))
    rets = [eq[1] / 1000 - 1] + [eq[i + 1] / eq[i] - 1 for i in range(1, 80)]
    mean = sum(rets) / len(rets)
    sd = math.sqrt(sum((r - mean) ** 2 for r in rets) / (len(rets) - 1))
    assert m.sharpe == pytest.approx(mean / sd * math.sqrt(252), rel=1e-3)
    assert m.sortino is not None and m.sortino > 0


def test_daily_returns_use_the_last_point_of_each_utc_day() -> None:
    """An intraday spike that is gone by the day's close must not move Sharpe."""
    closes = [1000 + 3 * i + (i % 5) for i in range(70)]
    clean = daily_curve(closes)
    noisy = list(clean)
    for i in range(len(closes)):
        noisy.append(pt(T0 + timedelta(days=i, hours=2), "5000" if i % 2 else "10"))
    a = compute_metrics(result([], clean))
    b = compute_metrics(result([], noisy))
    assert a.sharpe is not None and a.sharpe == pytest.approx(b.sharpe or 0.0)


def test_t_stat_withheld_below_thirty_trades() -> None:
    """Significance is not claimed from fewer than 30 trades."""
    m = compute_metrics(result([trade(i, "1", 1.0 + (i % 2)) for i in range(29)]))
    assert m.expectancy_t_stat is None
    assert m.significance_note == "insufficient_trades"


def test_t_stat_value_at_thirty_trades() -> None:
    rs = [2.0, -0.5] * 15
    m = compute_metrics(
        result([trade(i, "1" if r > 0 else "-1", r) for i, r in enumerate(rs)])
    )
    mean = sum(rs) / 30
    sd = math.sqrt(sum((r - mean) ** 2 for r in rs) / 29)
    assert m.expectancy_t_stat == pytest.approx(mean / (sd / math.sqrt(30)))
    assert m.significance_note is None


def test_t_stat_zero_variance_is_noted() -> None:
    m = compute_metrics(result([trade(i, "1", 1.0) for i in range(30)]))
    assert m.expectancy_t_stat is None
    assert m.significance_note == "zero_variance"
    assert t_statistic([1.0]) is None


def test_monthly_returns_include_empty_months_and_chain_start_equity() -> None:
    """Start equity is the last point before the month, so a month with no
    activity shows 0% rather than disappearing."""
    jan = pt(datetime(2024, 1, 15, tzinfo=UTC), "1100")
    mar = pt(datetime(2024, 3, 10, tzinfo=UTC), "1210")
    trades = [
        trade(0, "100", 1.0, exit_time=jan.time),
        trade(1, "110", 1.0, exit_time=mar.time),
    ]
    res = result(trades, [jan, mar], end=datetime(2024, 4, 1, tzinfo=UTC))
    months = monthly_returns(res)
    assert [m.month for m in months] == ["2024-01", "2024-02", "2024-03"]
    assert [m.return_pct for m in months] == pytest.approx([10.0, 0.0, 10.0])
    assert months[1].start_equity == months[1].end_equity == D("1100")
    assert [m.trades for m in months] == [1, 0, 1]
    assert months[2].net_pnl == D("110")
    assert compute_metrics(res).months == months


def test_monthly_returns_span_a_year_boundary() -> None:
    res = result(
        [],
        [pt(datetime(2024, 1, 5, tzinfo=UTC), "1000")],
        start=datetime(2023, 12, 1, tzinfo=UTC),
        end=datetime(2024, 2, 1, tzinfo=UTC),
    )
    assert [m.month for m in monthly_returns(res)] == ["2023-12", "2024-01"]
