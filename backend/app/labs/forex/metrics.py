"""Performance metrics over a finished `BacktestResult`.

Pure: consumes the result, holds no clock. Every figure that cannot be
computed honestly is `None` with a stable note code rather than an estimate,
and losing trades are always in the numbers.

Sign conventions: `gross_loss` is a positive magnitude (the profit-factor
denominator); `avg_loss` and `largest_loss` are signed P&L values (negative).
`Trade.financing` is read as a signed P&L effect, as `CostConfig` defines the
swap (negative = the account pays), so it counts as a cost when negative.
"""

from __future__ import annotations

import math
import statistics
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_EVEN, Decimal

from app.labs.forex.types import CENT, BacktestResult, Direction, EquityPoint, Trade

#: Fewer daily returns than this and an annualised ratio is mostly noise.
MIN_DAYS_FOR_RATIOS = 60
#: Below this a t-statistic on per-trade R is not reported at all.
MIN_TRADES_FOR_SIGNIFICANCE = 30
ANNUALISATION_DAYS = 252
_EPS = 1e-12


@dataclass(frozen=True, slots=True)
class MonthReturn:
    month: str  # "YYYY-MM", UTC
    start_equity: Decimal
    end_equity: Decimal
    return_pct: float
    trades: int
    net_pnl: Decimal


@dataclass(frozen=True, slots=True)
class Metrics:
    starting_balance: Decimal
    ending_balance: Decimal
    net_profit: Decimal
    net_return_pct: float

    total_trades: int
    wins: int
    losses: int
    breakeven: int
    win_rate_pct: float | None
    avg_win: Decimal | None
    avg_loss: Decimal | None
    largest_win: Decimal | None
    largest_loss: Decimal | None
    gross_profit: Decimal
    gross_loss: Decimal
    profit_factor: float | None
    #: "no_losses" when gross_loss is zero but there was profit; "no_trades" otherwise.
    profit_factor_note: str | None
    expectancy_usd: Decimal | None
    expectancy_r: float | None

    max_drawdown_pct: float
    max_drawdown_usd: Decimal
    sharpe: float | None
    sharpe_note: str | None
    sortino: float | None
    sortino_note: str | None

    longest_win_streak: int
    longest_loss_streak: int

    long_trades: int
    short_trades: int
    long_net: Decimal
    short_net: Decimal
    long_win_rate: float | None
    short_win_rate: float | None
    long_expectancy_r: float | None
    short_expectancy_r: float | None

    total_commission: Decimal
    total_spread_slippage: Decimal
    total_financing: Decimal
    costs_pct_of_gross_profit: float | None

    max_margin_utilization_pct: float
    avg_margin_utilization_pct: float | None
    avg_trade_duration_minutes: float | None
    monthly_trade_frequency: float

    exits_ambiguous: int
    margin_closeouts: int

    expectancy_t_stat: float | None
    significance_note: str | None

    months: tuple[MonthReturn, ...]


def utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


def _cents(d: Decimal) -> Decimal:
    return d.quantize(CENT, rounding=ROUND_HALF_EVEN)


def _pct(num: Decimal, den: Decimal) -> float:
    return float(num / den * 100) if den > 0 else 0.0


def t_statistic(values: Sequence[float]) -> float | None:
    """mean / (sd / sqrt(n)); None when it is undefined (n < 2 or zero spread)."""
    n = len(values)
    if n < 2:
        return None
    sd = statistics.stdev(values)
    if sd < _EPS:
        return None
    return statistics.fmean(values) / (sd / math.sqrt(n))


def _sorted_curve(curve: Sequence[EquityPoint]) -> list[EquityPoint]:
    return sorted(curve, key=lambda p: p.time)


def drawdown_series(
    curve: Sequence[EquityPoint], initial: Decimal | None = None
) -> list[tuple[datetime, float]]:
    """Percent below the running equity peak at each point (always <= 0).

    `initial` seeds the peak so a loss on the very first trade is a drawdown;
    without it the first point would define the peak and hide that loss.
    """
    peak = initial
    out: list[tuple[datetime, float]] = []
    for p in _sorted_curve(curve):
        if peak is None or p.equity > peak:
            peak = p.equity
        dd = float((p.equity - peak) / peak * 100) if peak > 0 else 0.0
        out.append((p.time, dd if dd < 0 else 0.0))
    return out


def _max_drawdown(curve: Sequence[EquityPoint], initial: Decimal) -> tuple[float, Decimal]:
    peak = initial
    max_pct = 0.0
    max_usd = Decimal(0)
    for p in _sorted_curve(curve):
        if p.equity > peak:
            peak = p.equity
        usd = peak - p.equity
        if usd > max_usd:
            max_usd = usd
        if peak > 0:
            max_pct = max(max_pct, float(usd / peak * 100))
    return max_pct, _cents(max_usd)


def _daily_returns(curve: Sequence[EquityPoint], initial: Decimal) -> list[float]:
    """Simple returns between consecutive UTC days, using each day's LAST point."""
    last_by_day: dict[date, Decimal] = {}
    for p in _sorted_curve(curve):
        last_by_day[utc(p.time).date()] = p.equity
    prev = initial
    out: list[float] = []
    for d in sorted(last_by_day):
        eq = last_by_day[d]
        if prev > 0:
            out.append(float((eq - prev) / prev))
        prev = eq
    return out


def _sharpe(returns: Sequence[float]) -> tuple[float | None, str | None]:
    # Risk-free rate is taken as zero: the lab has no rate series and an
    # invented one would be an estimate.
    if len(returns) < MIN_DAYS_FOR_RATIOS:
        return None, "insufficient_days"
    sd = statistics.stdev(returns)
    if sd < _EPS:
        return None, "zero_variance"
    return statistics.fmean(returns) / sd * math.sqrt(ANNUALISATION_DAYS), None


def _sortino(returns: Sequence[float]) -> tuple[float | None, str | None]:
    if len(returns) < MIN_DAYS_FOR_RATIOS:
        return None, "insufficient_days"
    downside = math.sqrt(sum(min(r, 0.0) ** 2 for r in returns) / len(returns))
    if downside < _EPS:
        return None, "zero_downside"
    return statistics.fmean(returns) / downside * math.sqrt(ANNUALISATION_DAYS), None


def _streaks(trades: Sequence[Trade]) -> tuple[int, int]:
    best_w = best_l = cur_w = cur_l = 0
    for t in sorted(trades, key=lambda x: x.exit_time):
        if t.net_pnl > 0:
            cur_w += 1
            cur_l = 0
        elif t.net_pnl < 0:
            cur_l += 1
            cur_w = 0
        else:  # breakeven breaks both runs
            cur_w = cur_l = 0
        best_w = max(best_w, cur_w)
        best_l = max(best_l, cur_l)
    return best_w, best_l


def _mean_r(trades: Sequence[Trade]) -> float | None:
    return statistics.fmean(t.r_multiple for t in trades) if trades else None


def _win_rate(trades: Sequence[Trade]) -> float | None:
    if not trades:
        return None
    return sum(1 for t in trades if t.net_pnl > 0) / len(trades) * 100


def _month_keys(first: datetime, last: datetime) -> list[tuple[int, int]]:
    f, ls = utc(first), utc(last)
    out: list[tuple[int, int]] = []
    y, m = f.year, f.month
    while (y, m) <= (ls.year, ls.month):
        out.append((y, m))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def _last_instant(result: BacktestResult) -> datetime:
    # `end` is exclusive: a run ending exactly at a month boundary did not trade
    # in the new month, so counting it would understate trade frequency.
    return (
        result.end - timedelta(microseconds=1) if result.end > result.start else result.start
    )


def monthly_returns(result: BacktestResult) -> tuple[MonthReturn, ...]:
    """Per calendar month, including months with no trades (0%).

    Start equity is the last curve point before the month (initial capital for
    the first); end is the last point inside it. `net_pnl` and `trades` count
    trades by EXIT month, so they can differ from the equity change when a
    position is open across a month boundary.
    """
    initial = result.config.risk.initial_capital
    curve = _sorted_curve(result.equity_curve)
    last = _last_instant(result)
    if curve:
        last = max(last, curve[-1].time)
    if result.trades:
        last = max(last, max(t.exit_time for t in result.trades))
    first = min(result.start, curve[0].time) if curve else result.start

    trade_count: Counter[tuple[int, int]] = Counter()
    trade_net: dict[tuple[int, int], Decimal] = {}
    for t in result.trades:
        et = utc(t.exit_time)
        key = (et.year, et.month)
        trade_count[key] += 1
        trade_net[key] = trade_net.get(key, Decimal(0)) + t.net_pnl

    out: list[MonthReturn] = []
    carry = initial
    idx = 0
    for y, m in _month_keys(first, last):
        nxt = (
            datetime(y + 1, 1, 1, tzinfo=UTC) if m == 12 else datetime(y, m + 1, 1, tzinfo=UTC)
        )
        start_eq = carry
        end_eq = carry
        while idx < len(curve) and utc(curve[idx].time) < nxt:
            end_eq = curve[idx].equity
            idx += 1
        carry = end_eq
        out.append(
            MonthReturn(
                month=f"{y:04d}-{m:02d}",
                start_equity=start_eq,
                end_equity=end_eq,
                return_pct=_pct(end_eq - start_eq, start_eq),
                trades=trade_count[(y, m)],
                net_pnl=trade_net.get((y, m), Decimal(0)),
            )
        )
    return tuple(out)


def compute_metrics(result: BacktestResult) -> Metrics:
    trades = result.trades
    initial = result.config.risk.initial_capital
    ending = result.final_balance
    net_profit = ending - initial

    win_t = [t for t in trades if t.net_pnl > 0]
    loss_t = [t for t in trades if t.net_pnl < 0]
    gross_profit = sum((t.net_pnl for t in win_t), Decimal(0))
    gross_loss = -sum((t.net_pnl for t in loss_t), Decimal(0))
    n = len(trades)

    if gross_loss > 0:
        pf: float | None = float(gross_profit / gross_loss)
        pf_note = None
    else:
        pf = None
        pf_note = "no_losses" if gross_profit > 0 else "no_trades"

    rs = [t.r_multiple for t in trades]
    streak_w, streak_l = _streaks(trades)
    longs = [t for t in trades if t.direction == Direction.LONG]
    shorts = [t for t in trades if t.direction == Direction.SHORT]

    commission = sum((t.commission for t in trades), Decimal(0))
    spread_slip = sum((t.spread_slippage_cost for t in trades), Decimal(0))
    financing = sum((t.financing for t in trades), Decimal(0))
    costs = commission + spread_slip - financing
    costs_pct = float(costs / gross_profit * 100) if gross_profit > 0 else None

    dd_pct, dd_usd = _max_drawdown(result.equity_curve, initial)
    returns = _daily_returns(result.equity_curve, initial)
    sharpe, sharpe_note = _sharpe(returns)
    sortino, sortino_note = _sortino(returns)

    exposed = [
        p.margin_utilization_pct for p in result.equity_curve if p.margin_utilization_pct > 0
    ]
    max_margin = max((p.margin_utilization_pct for p in result.equity_curve), default=0.0)

    if n:
        durations = [(t.exit_time - t.entry_time).total_seconds() / 60 for t in trades]
        avg_duration: float | None = statistics.fmean(durations)
    else:
        avg_duration = None

    span = len(_month_keys(result.start, _last_instant(result)))

    t_stat: float | None = None
    sig_note: str | None = None
    if n < MIN_TRADES_FOR_SIGNIFICANCE:
        sig_note = "insufficient_trades"
    else:
        t_stat = t_statistic(rs)
        if t_stat is None:
            sig_note = "zero_variance"

    return Metrics(
        starting_balance=initial,
        ending_balance=ending,
        net_profit=net_profit,
        net_return_pct=_pct(net_profit, initial),
        total_trades=n,
        wins=len(win_t),
        losses=len(loss_t),
        breakeven=n - len(win_t) - len(loss_t),
        win_rate_pct=_win_rate(trades),
        avg_win=_cents(gross_profit / len(win_t)) if win_t else None,
        avg_loss=_cents(-gross_loss / len(loss_t)) if loss_t else None,
        largest_win=max((t.net_pnl for t in win_t), default=None),
        largest_loss=min((t.net_pnl for t in loss_t), default=None),
        gross_profit=gross_profit,
        gross_loss=gross_loss,
        profit_factor=pf,
        profit_factor_note=pf_note,
        expectancy_usd=_cents(sum((t.net_pnl for t in trades), Decimal(0)) / n) if n else None,
        expectancy_r=_mean_r(trades),
        max_drawdown_pct=dd_pct,
        max_drawdown_usd=dd_usd,
        sharpe=sharpe,
        sharpe_note=sharpe_note,
        sortino=sortino,
        sortino_note=sortino_note,
        longest_win_streak=streak_w,
        longest_loss_streak=streak_l,
        long_trades=len(longs),
        short_trades=len(shorts),
        long_net=sum((t.net_pnl for t in longs), Decimal(0)),
        short_net=sum((t.net_pnl for t in shorts), Decimal(0)),
        long_win_rate=_win_rate(longs),
        short_win_rate=_win_rate(shorts),
        long_expectancy_r=_mean_r(longs),
        short_expectancy_r=_mean_r(shorts),
        total_commission=commission,
        total_spread_slippage=spread_slip,
        total_financing=financing,
        costs_pct_of_gross_profit=costs_pct,
        max_margin_utilization_pct=max_margin,
        avg_margin_utilization_pct=statistics.fmean(exposed) if exposed else None,
        avg_trade_duration_minutes=avg_duration,
        monthly_trade_frequency=n / span,
        exits_ambiguous=result.exits_ambiguous,
        margin_closeouts=result.margin_closeouts,
        expectancy_t_stat=t_stat,
        significance_note=sig_note,
        months=monthly_returns(result),
    )
