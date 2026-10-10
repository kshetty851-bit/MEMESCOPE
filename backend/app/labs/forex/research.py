"""Research and validation helpers: splits, grid search, walk-forward,
sensitivity, cost stress, Monte-Carlo, bootstrap and regime breakdown.

Pure. The engine is never imported: every function that needs a backtest takes
an injected `Runner`, which keeps this module testable with a fake and keeps
the engine free to change. Randomness only through `Rng` with an explicit seed.

Nothing here selects on the test window: walk-forward chooses parameters on
the training window alone, and every figure carries the trade count it rests on.
"""

from __future__ import annotations

import dataclasses
import itertools
import math
import statistics
from bisect import bisect_left
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import cast

from app.labs.forex.metrics import Metrics, compute_metrics, t_statistic, utc
from app.labs.forex.rng import Rng
from app.labs.forex.types import BacktestConfig, BacktestResult, Candle, Trade

Runner = Callable[[BacktestConfig, datetime, datetime], BacktestResult]

#: A parameter set with fewer trades than this is never eligible as "best".
MIN_TRADES_FOR_SELECTION = 20
MIN_TRADES_FOR_MONTE_CARLO = 10
MIN_OBSERVATIONS_FOR_BOOTSTRAP = 20
_VOL_LOOKBACK = 500
_MIN_VOL_SAMPLES = 20

MC_ASSUMPTIONS = (
    "iid_trade_order_shuffle",
    "fixed_fractional_compounding",
    "r_multiples_from_history",
)


# --------------------------------------------------------------------------
# Config paths
# --------------------------------------------------------------------------


def _coerce(current: object, value: object, path: str) -> object:
    """Cast `value` to the type of the field's existing value."""
    if current is None:
        return value
    if isinstance(current, bool):
        if not isinstance(value, bool):
            raise ValueError(f"expected_bool:{path}")
        return value
    if isinstance(current, Enum):
        return type(current)(value)
    if isinstance(current, Decimal):
        if not isinstance(value, (int, float, Decimal, str)):
            raise ValueError(f"expected_number:{path}")
        return Decimal(str(value))
    if isinstance(current, int):
        if not isinstance(value, (int, float, Decimal)):
            raise ValueError(f"expected_number:{path}")
        if isinstance(value, float) and not value.is_integer():
            raise ValueError(f"expected_integer:{path}")
        return int(value)
    if isinstance(current, float):
        if not isinstance(value, (int, float, Decimal)):
            raise ValueError(f"expected_number:{path}")
        return float(value)
    return value


def _set_path(obj: object, parts: list[str], value: object, path: str) -> object:
    if not dataclasses.is_dataclass(obj) or isinstance(obj, type):
        raise ValueError(f"unknown_param_path:{path}")
    name = parts[0]
    if name not in {f.name for f in dataclasses.fields(obj)}:
        raise ValueError(f"unknown_param_path:{path}")
    current = getattr(obj, name)
    new = (
        _coerce(current, value, path)
        if len(parts) == 1
        else _set_path(current, parts[1:], value, path)
    )
    return dataclasses.replace(obj, **{name: new})


def with_param(cfg: BacktestConfig, path: str, value: object) -> BacktestConfig:
    """Return a copy of `cfg` with the dotted `path` set, e.g. "costs.spread_pips"."""
    return cast(BacktestConfig, _set_path(cfg, path.split("."), value, path))


# --------------------------------------------------------------------------
# Windows
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Window:
    start: datetime
    end: datetime


@dataclass(frozen=True, slots=True)
class Split:
    development: Window
    validation: Window
    test: Window


def _floor_day(dt: datetime) -> datetime:
    return utc(dt).replace(hour=0, minute=0, second=0, microsecond=0)


def chronological_split(
    start: datetime, end: datetime, dev_pct: float = 60.0, val_pct: float = 20.0
) -> Split:
    """Contiguous development / validation / test windows, in time order.

    Cut points are floored to whole UTC days so no day is shared between two
    windows. The test window is whatever remains after development and
    validation, and is meant to be looked at once.
    """
    if not (dev_pct > 0 and val_pct > 0 and dev_pct + val_pct < 100):
        raise ValueError("invalid_split_fractions")
    if end <= start:
        raise ValueError("end_not_after_start")
    span = end - start
    cut1 = _floor_day(start + span * (dev_pct / 100.0))
    cut2 = _floor_day(start + span * ((dev_pct + val_pct) / 100.0))
    if not (start < cut1 < cut2 < end):
        raise ValueError("window_too_short_for_split")
    return Split(Window(start, cut1), Window(cut1, cut2), Window(cut2, end))


# --------------------------------------------------------------------------
# Grid search
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class GridRow:
    params: dict[str, object]
    trades: int
    net_return_pct: float
    expectancy_r: float | None
    profit_factor: float | None
    max_drawdown_pct: float
    score: float | None


@dataclass(frozen=True, slots=True)
class OptimiseResult:
    rows: list[GridRow]
    best: GridRow | None


def grid(
    base_cfg: BacktestConfig, space: dict[str, Sequence[object]]
) -> list[tuple[dict[str, object], BacktestConfig]]:
    """Cartesian product of `space`, in the dict's key order."""
    keys = list(space)
    out: list[tuple[dict[str, object], BacktestConfig]] = []
    for combo in itertools.product(*(space[k] for k in keys)):
        cfg = base_cfg
        for k, v in zip(keys, combo, strict=True):
            cfg = with_param(cfg, k, v)
        out.append((dict(zip(keys, combo, strict=True)), cfg))
    return out


def objective(metrics: Metrics) -> float | None:
    """Robustness-oriented score; None when there are too few trades to rank.

    base = expectancy_r * sqrt(min(trades, 100)): more evidence raises the
    score only up to 100 trades, so a long noisy run cannot beat a clean one.
    Drawdown scales it toward zero (x(1 - dd/100)) when base is positive and
    away from zero when negative, so a deeper drawdown never improves a loser.
    """
    if metrics.total_trades < MIN_TRADES_FOR_SELECTION or metrics.expectancy_r is None:
        return None
    base = metrics.expectancy_r * math.sqrt(min(metrics.total_trades, 100))
    dd = min(max(metrics.max_drawdown_pct, 0.0), 100.0) / 100.0
    return base * (1.0 - dd) if base >= 0 else base * (1.0 + dd)


def _row(params: dict[str, object], m: Metrics) -> GridRow:
    return GridRow(
        params=params,
        trades=m.total_trades,
        net_return_pct=m.net_return_pct,
        expectancy_r=m.expectancy_r,
        profit_factor=m.profit_factor,
        max_drawdown_pct=m.max_drawdown_pct,
        score=objective(m),
    )


def _best(rows: Sequence[GridRow]) -> GridRow | None:
    best: GridRow | None = None
    for r in rows:  # strict ">" keeps the first of equal scores: deterministic
        if r.score is not None and (best is None or r.score > (best.score or 0.0)):
            best = r
    return best


def optimise(
    base_cfg: BacktestConfig,
    space: dict[str, Sequence[object]],
    runner: Runner,
    window: Window,
) -> OptimiseResult:
    rows = [
        _row(params, compute_metrics(runner(cfg, window.start, window.end)))
        for params, cfg in grid(base_cfg, space)
    ]
    return OptimiseResult(rows=rows, best=_best(rows))


# --------------------------------------------------------------------------
# Walk-forward
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MetricsSummary:
    trades: int
    net_return_pct: float
    expectancy_r: float | None
    profit_factor: float | None
    max_drawdown_pct: float


def summarise(m: Metrics) -> MetricsSummary:
    return MetricsSummary(
        trades=m.total_trades,
        net_return_pct=m.net_return_pct,
        expectancy_r=m.expectancy_r,
        profit_factor=m.profit_factor,
        max_drawdown_pct=m.max_drawdown_pct,
    )


@dataclass(frozen=True, slots=True)
class Fold:
    train: Window
    test: Window
    chosen_params: dict[str, object] | None
    train_score: float | None
    train_expectancy_r: float | None
    test_metrics: MetricsSummary | None
    #: "no_eligible_parameters" when no train cell reached the trade minimum.
    note: str | None = None


@dataclass(frozen=True, slots=True)
class WalkForwardResult:
    folds: list[Fold]
    oos_trades: tuple[Trade, ...]
    oos_summary: dict[str, object]
    efficiency: float | None


def trade_summary(trades: Sequence[Trade]) -> dict[str, object]:
    """Plain figures over a pooled list of trades (used for out-of-sample)."""
    n = len(trades)
    rs = [t.r_multiple for t in trades]
    gp = sum((t.net_pnl for t in trades if t.net_pnl > 0), Decimal(0))
    gl = -sum((t.net_pnl for t in trades if t.net_pnl < 0), Decimal(0))
    return {
        "trades": n,
        "net_pnl": sum((t.net_pnl for t in trades), Decimal(0)),
        "win_rate_pct": (sum(1 for t in trades if t.net_pnl > 0) / n * 100) if n else None,
        "expectancy_r": statistics.fmean(rs) if n else None,
        "profit_factor": float(gp / gl) if gl > 0 else None,
        "expectancy_t_stat": t_statistic(rs) if n >= 30 else None,
    }


def walk_forward(
    base_cfg: BacktestConfig,
    space: dict[str, Sequence[object]],
    runner: Runner,
    start: datetime,
    end: datetime,
    train_days: int,
    test_days: int,
    step_days: int | None = None,
) -> WalkForwardResult:
    """Choose parameters on each train window ONLY, then trade the next window.

    `step_days` defaults to `test_days`; a smaller step would let test windows
    overlap and double-count trades in the pooled out-of-sample list, so it is
    refused.
    """
    step = test_days if step_days is None else step_days
    if train_days <= 0 or test_days <= 0 or step <= 0:
        raise ValueError("windows_must_be_positive")
    if step < test_days:
        raise ValueError("step_smaller_than_test_window")

    folds: list[Fold] = []
    oos: list[Trade] = []
    cursor = start
    while True:
        train = Window(cursor, cursor + timedelta(days=train_days))
        test = Window(train.end, train.end + timedelta(days=test_days))
        if test.end > end:
            break
        best = optimise(base_cfg, space, runner, train).best
        if best is None:
            folds.append(Fold(train, test, None, None, None, None, "no_eligible_parameters"))
        else:
            cfg = base_cfg
            for path, value in best.params.items():
                cfg = with_param(cfg, path, value)
            res = runner(cfg, test.start, test.end)
            oos.extend(res.trades)
            folds.append(
                Fold(
                    train,
                    test,
                    dict(best.params),
                    best.score,
                    best.expectancy_r,
                    summarise(compute_metrics(res)),
                )
            )
        cursor += timedelta(days=step)
    if not folds:
        raise ValueError("no_fold_fits_range")

    pairs = [
        (f.train_expectancy_r, f.test_metrics.expectancy_r)
        for f in folds
        if f.test_metrics is not None
        and f.train_expectancy_r is not None
        and f.test_metrics.expectancy_r is not None
    ]
    efficiency: float | None = None
    if pairs:
        train_mean = statistics.fmean(p[0] for p in pairs)
        test_mean = statistics.fmean(p[1] for p in pairs if p[1] is not None)
        # A non-positive in-sample mean makes the ratio meaningless.
        efficiency = test_mean / train_mean if train_mean > 0 else None
    return WalkForwardResult(folds, tuple(oos), trade_summary(oos), efficiency)


# --------------------------------------------------------------------------
# Sensitivity, stability, cost stress
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SensitivityRow:
    value: object
    trades: int
    expectancy_r: float | None
    net_return_pct: float
    max_drawdown_pct: float
    profit_factor: float | None


def sensitivity(
    base_cfg: BacktestConfig,
    path: str,
    values: Sequence[object],
    runner: Runner,
    window: Window,
) -> list[SensitivityRow]:
    out: list[SensitivityRow] = []
    for v in values:
        m = compute_metrics(runner(with_param(base_cfg, path, v), window.start, window.end))
        out.append(
            SensitivityRow(
                v,
                m.total_trades,
                m.expectancy_r,
                m.net_return_pct,
                m.max_drawdown_pct,
                m.profit_factor,
            )
        )
    return out


@dataclass(frozen=True, slots=True)
class StabilityReport:
    best_params: dict[str, object] | None
    neighbour_count: int
    neighbours_positive_pct: float | None
    best_vs_neighbour_median_ratio: float | None
    isolated_peak: bool
    positive_cells_pct: float | None


def _positive(r: GridRow) -> bool:
    return r.expectancy_r is not None and r.expectancy_r > 0


def _index_of(values: Sequence[object], v: object) -> int | None:
    for i, x in enumerate(values):
        if x == v:
            return i
    return None


def _is_neighbour(
    a: dict[str, object], b: dict[str, object], space: dict[str, Sequence[object]]
) -> bool:
    differing = 0
    for key, values in space.items():
        ia, ib = _index_of(values, a.get(key)), _index_of(values, b.get(key))
        if ia is None or ib is None:
            return False
        if ia != ib:
            if abs(ia - ib) != 1:
                return False
            differing += 1
    return differing == 1


def parameter_stability(
    rows: Sequence[GridRow], space: dict[str, Sequence[object]]
) -> StabilityReport:
    """Does the best cell sit on a plateau or on an isolated spike?

    Neighbours are cells one step away in exactly one parameter. A positive
    best whose neighbours are mostly not positive is flagged `isolated_peak`,
    the usual signature of a fit to noise.
    """
    positive_cells = sum(1 for r in rows if _positive(r)) / len(rows) * 100 if rows else None
    best = _best(rows)
    if best is None:
        return StabilityReport(None, 0, None, None, False, positive_cells)
    neigh = [r for r in rows if r is not best and _is_neighbour(best.params, r.params, space)]
    if not neigh:
        return StabilityReport(dict(best.params), 0, None, None, False, positive_cells)
    pos_pct = sum(1 for r in neigh if _positive(r)) / len(neigh) * 100
    median = statistics.median(r.expectancy_r or 0.0 for r in neigh)
    ratio = (
        best.expectancy_r / median if best.expectancy_r is not None and median > 0 else None
    )
    isolated = _positive(best) and pos_pct < 50.0
    return StabilityReport(
        dict(best.params), len(neigh), pos_pct, ratio, isolated, positive_cells
    )


@dataclass(frozen=True, slots=True)
class StressRow:
    multiplier: float
    spread_pips: float
    slippage_pips: float
    trades: int
    net_return_pct: float
    expectancy_r: float | None
    profit_factor: float | None


def cost_stress(
    base_cfg: BacktestConfig,
    runner: Runner,
    window: Window,
    multipliers: Sequence[float] = (1.0, 1.5, 2.0, 3.0),
) -> list[StressRow]:
    """Re-run with spread, slippage and commission scaled together."""
    out: list[StressRow] = []
    for mult in multipliers:
        c = base_cfg.costs
        costs = dataclasses.replace(
            c,
            spread_pips=c.spread_pips * mult,
            slippage_pips=c.slippage_pips * mult,
            commission_per_lot_side=c.commission_per_lot_side * Decimal(str(mult)),
        )
        cfg = dataclasses.replace(base_cfg, costs=costs)
        m = compute_metrics(runner(cfg, window.start, window.end))
        out.append(
            StressRow(
                mult,
                costs.spread_pips,
                costs.slippage_pips,
                m.total_trades,
                m.net_return_pct,
                m.expectancy_r,
                m.profit_factor,
            )
        )
    return out


# --------------------------------------------------------------------------
# Monte-Carlo and bootstrap
# --------------------------------------------------------------------------


def percentile(sorted_values: Sequence[float], q: float) -> float:
    """Linear-interpolated percentile (q in 0..100) of an ascending sequence."""
    if not sorted_values:
        raise ValueError("empty_sequence")
    pos = (len(sorted_values) - 1) * q / 100.0
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return sorted_values[lo]
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (pos - lo)


def compound_path(
    r_multiples: Sequence[float], risk_pct: float, start: float = 1.0
) -> tuple[float, float, float]:
    """Fixed-fractional compounding. Returns (final, max drawdown %, lowest equity).

    Equity is floored at zero: a path cannot go negative, it is wiped out.
    """
    eq = peak = lowest = start
    max_dd = 0.0
    for r in r_multiples:
        eq *= max(0.0, 1.0 + r * risk_pct / 100.0)
        peak = max(peak, eq)
        lowest = min(lowest, eq)
        if peak > 0:
            max_dd = max(max_dd, (peak - eq) / peak * 100.0)
    return eq, max_dd, lowest


@dataclass(frozen=True, slots=True)
class Percentiles:
    p5: float
    p25: float
    p50: float
    p75: float
    p95: float


def _percentiles(values: Sequence[float]) -> Percentiles:
    s = sorted(values)
    return Percentiles(*(percentile(s, q) for q in (5.0, 25.0, 50.0, 75.0, 95.0)))


@dataclass(frozen=True, slots=True)
class MonteCarloResult:
    iterations: int
    final_return_pct: Percentiles | None
    max_drawdown_pct: Percentiles | None
    prob_ruin: float | None
    prob_loss: float | None
    assumptions: tuple[str, ...]
    note: str | None = None


def monte_carlo(
    trades: Sequence[Trade],
    initial_capital: Decimal,
    risk_pct: Decimal,
    iterations: int = 1000,
    seed: int = 7,
    ruin_drawdown_pct: float = 50.0,
) -> MonteCarloResult:
    """Reorder the historical R-multiples and compound them fixed-fractionally.

    Reordering keeps the product of the (1 + r*risk) factors, so the FINAL
    return is identical on every path; what the shuffle exposes is the spread
    of drawdowns. Final-return percentiles are therefore degenerate by
    construction, and `iid_trade_order_shuffle` says so in the assumptions.
    """
    if initial_capital <= 0 or risk_pct <= 0 or iterations < 1:
        raise ValueError("invalid_monte_carlo_inputs")
    rs = [t.r_multiple for t in trades]
    if len(rs) < MIN_TRADES_FOR_MONTE_CARLO:
        return MonteCarloResult(
            iterations, None, None, None, None, MC_ASSUMPTIONS, "insufficient_trades"
        )
    rng = Rng(seed)
    risk = float(risk_pct)
    start = float(initial_capital)
    finals: list[float] = []
    dds: list[float] = []
    ruined = lost = 0
    for _ in range(iterations):
        rng.shuffle(rs)
        final, dd, _low = compound_path(rs, risk, start)
        finals.append((final / start - 1.0) * 100.0)
        dds.append(dd)
        ruined += dd >= ruin_drawdown_pct
        lost += final < start * (1.0 - 1e-12)
    return MonteCarloResult(
        iterations,
        _percentiles(finals),
        _percentiles(dds),
        ruined / iterations,
        lost / iterations,
        MC_ASSUMPTIONS,
    )


@dataclass(frozen=True, slots=True)
class BootstrapCI:
    estimate: float | None
    low: float | None
    high: float | None
    n: int
    note: str | None


def _mean(values: Sequence[float]) -> float:
    return statistics.fmean(values)


def bootstrap_ci(
    values: Sequence[float],
    *,
    iterations: int = 2000,
    seed: int = 11,
    confidence: float = 0.95,
    statistic: Callable[[Sequence[float]], float] = _mean,
) -> BootstrapCI:
    """Percentile bootstrap interval. No bounds are given below 20 observations."""
    if not 0.0 < confidence < 1.0 or iterations < 1:
        raise ValueError("invalid_bootstrap_inputs")
    n = len(values)
    estimate = statistic(values) if n else None
    if n < MIN_OBSERVATIONS_FOR_BOOTSTRAP:
        return BootstrapCI(estimate, None, None, n, "insufficient_observations")
    rng = Rng(seed)
    stats = sorted(
        statistic([values[rng.randrange(n)] for _ in range(n)]) for _ in range(iterations)
    )
    tail = (1.0 - confidence) / 2.0 * 100.0
    return BootstrapCI(
        estimate, percentile(stats, tail), percentile(stats, 100.0 - tail), n, None
    )


# --------------------------------------------------------------------------
# Regimes
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RegimeRow:
    regime: str
    trades: int
    win_rate_pct: float | None
    expectancy_r: float | None
    net_pnl: Decimal


def _ema(closes: Sequence[float], period: int) -> list[float | None]:
    out: list[float | None] = [None] * len(closes)
    if period < 1 or len(closes) < period:
        return out
    value = sum(closes[:period]) / period
    out[period - 1] = value
    alpha = 2.0 / (period + 1)
    for i in range(period, len(closes)):
        value += alpha * (closes[i] - value)
        out[i] = value
    return out


def _wilder_atr(candles: Sequence[Candle], period: int) -> list[float | None]:
    out: list[float | None] = [None] * len(candles)
    if period < 1 or len(candles) <= period:
        return out
    tr = [candles[0].high - candles[0].low]
    for i in range(1, len(candles)):
        c, pc = candles[i], candles[i - 1].close
        tr.append(max(c.high - c.low, abs(c.high - pc), abs(c.low - pc)))
    value = sum(tr[1 : period + 1]) / period
    out[period] = value
    for i in range(period + 1, len(candles)):
        value = (value * (period - 1) + tr[i]) / period
        out[i] = value
    return out


def regime_breakdown(
    result: BacktestResult,
    candles: Sequence[Candle],
    *,
    ema_period: int = 200,
    atr_period: int = 14,
) -> list[RegimeRow]:
    """Group trades by the market state known at entry, never after it.

    Only candles opened strictly before the entry time are read, so a trade is
    classified by information that existed when it was taken. Each trade lands
    in one row per dimension (trend, volatility, year); trades that cannot be
    classified for lack of history go to an explicit "*_unclassified" row
    rather than being dropped.
    """
    cs = sorted(candles, key=lambda c: c.open_time)
    times = [c.open_time for c in cs]
    ema = _ema([c.close for c in cs], ema_period)
    atr = _wilder_atr(cs, atr_period)

    groups: dict[str, list[Trade]] = {}

    def add(key: str, trade: Trade) -> None:
        groups.setdefault(key, []).append(trade)

    for t in result.trades:
        idx = bisect_left(times, t.entry_time) - 1
        trend = "trend_unclassified"
        vol = "vol_unclassified"
        if idx >= 0:
            e = ema[idx]
            if e is not None:
                trend = "uptrend" if cs[idx].close > e else "downtrend"
            a = atr[idx]
            window = [
                x for x in atr[max(0, idx - _VOL_LOOKBACK + 1) : idx + 1] if x is not None
            ]
            if a is not None and len(window) >= _MIN_VOL_SAMPLES:
                vol = "high_vol" if a > statistics.median(window) else "low_vol"
        add(trend, t)
        add(vol, t)
        add(f"year_{utc(t.entry_time).year:04d}", t)

    order = [
        "uptrend", "downtrend", "trend_unclassified",
        "high_vol", "low_vol", "vol_unclassified",
    ]  # fmt: skip
    keys = [k for k in order if k in groups] + sorted(
        k for k in groups if k.startswith("year_")
    )
    rows: list[RegimeRow] = []
    for k in keys:
        ts = groups[k]
        rows.append(
            RegimeRow(
                regime=k,
                trades=len(ts),
                win_rate_pct=sum(1 for t in ts if t.net_pnl > 0) / len(ts) * 100,
                expectancy_r=statistics.fmean(t.r_multiple for t in ts),
                net_pnl=sum((t.net_pnl for t in ts), Decimal(0)),
            )
        )
    return rows


def baseline_comparison(metrics: Metrics) -> dict[str, object]:
    """Compare against standing aside: zero return and zero drawdown.

    `expectancy_ci_excludes_zero` uses |t| >= 2 on per-trade R as the
    criterion and is None whenever the t-statistic was not reported.
    """
    t = metrics.expectancy_t_stat
    return {
        "excess_return_pct": metrics.net_return_pct,
        "beats_no_trade": metrics.net_return_pct > 0,
        "expectancy_ci_excludes_zero": None if t is None else abs(t) >= 2.0,
        "max_drawdown_pct_vs_baseline": metrics.max_drawdown_pct,
    }
