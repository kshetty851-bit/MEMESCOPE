"""Domain objects -> JSON-safe dicts. Pure.

Two rules shape every function here:

* Money (`Decimal`) becomes a string, never a float; prices, ratios and
  percentages stay numbers. A non-finite float becomes null - JSON has no NaN,
  and "not meaningful" must read the same everywhere.
* Prose is NEVER written. Wherever the page shows a sentence, this emits
  `{"code": "..."}` and `prose.render` adds the `text` when a run is read.
  Stored results therefore hold codes only, and rewording is a deploy.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from typing import Any

from app.labs.forex.compare import Scorecard
from app.labs.forex.data import QualityReport
from app.labs.forex.metrics import Metrics, MonthReturn, drawdown_series, utc
from app.labs.forex.research import (
    BootstrapCI,
    Fold,
    GridRow,
    MonteCarloResult,
    RegimeRow,
    SensitivityRow,
    StabilityReport,
    StressRow,
    WalkForwardResult,
    Window,
)
from app.labs.forex.targets import TargetReport
from app.labs.forex.types import BacktestResult, EquityPoint, Trade

#: Charts need the shape, not every point; a decade of days would be 3,650.
MAX_CURVE_POINTS = 1500


def code(value: str | None) -> dict[str, str] | None:
    return None if value is None else {"code": value}


def codes(values: Sequence[str]) -> list[dict[str, str]]:
    return [{"code": v} for v in values]


def num(x: float | None) -> float | None:
    if x is None or not math.isfinite(x):
        return None
    return x


def money(d: Decimal | None) -> str | None:
    return None if d is None else format(d, "f")


def iso(dt: datetime | None) -> str | None:
    return None if dt is None else utc(dt).isoformat()


def window_json(w: Window) -> dict[str, Any]:
    return {"start": iso(w.start), "end": iso(w.end)}


# --------------------------------------------------------------------------
# Metrics
# --------------------------------------------------------------------------


def metrics_json(m: Metrics) -> dict[str, Any]:
    return {
        "starting_balance": money(m.starting_balance),
        "ending_balance": money(m.ending_balance),
        "net_profit": money(m.net_profit),
        "net_return_pct": num(m.net_return_pct),
        "total_trades": m.total_trades,
        "wins": m.wins,
        "losses": m.losses,
        "breakeven": m.breakeven,
        "win_rate_pct": num(m.win_rate_pct),
        "avg_win": money(m.avg_win),
        "avg_loss": money(m.avg_loss),
        "largest_win": money(m.largest_win),
        "largest_loss": money(m.largest_loss),
        "gross_profit": money(m.gross_profit),
        "gross_loss": money(m.gross_loss),
        "profit_factor": num(m.profit_factor),
        "profit_factor_note": code(m.profit_factor_note),
        "expectancy_usd": money(m.expectancy_usd),
        "expectancy_r": num(m.expectancy_r),
        "max_drawdown_pct": num(m.max_drawdown_pct),
        "max_drawdown_usd": money(m.max_drawdown_usd),
        "sharpe": num(m.sharpe),
        "sortino": num(m.sortino),
        "sharpe_note": code(m.sharpe_note),
        "sortino_note": code(m.sortino_note),
        "longest_win_streak": m.longest_win_streak,
        "longest_loss_streak": m.longest_loss_streak,
        "long_trades": m.long_trades,
        "short_trades": m.short_trades,
        "long_net": money(m.long_net),
        "short_net": money(m.short_net),
        "long_win_rate": num(m.long_win_rate),
        "short_win_rate": num(m.short_win_rate),
        "long_expectancy_r": num(m.long_expectancy_r),
        "short_expectancy_r": num(m.short_expectancy_r),
        "total_commission": money(m.total_commission),
        "total_spread_slippage": money(m.total_spread_slippage),
        "total_financing": money(m.total_financing),
        "costs_pct_of_gross_profit": num(m.costs_pct_of_gross_profit),
        "max_margin_utilization_pct": num(m.max_margin_utilization_pct),
        "avg_margin_utilization_pct": num(m.avg_margin_utilization_pct),
        "avg_trade_duration_minutes": num(m.avg_trade_duration_minutes),
        "monthly_trade_frequency": num(m.monthly_trade_frequency),
        "exits_ambiguous": m.exits_ambiguous,
        "margin_closeouts": m.margin_closeouts,
        "expectancy_t_stat": num(m.expectancy_t_stat),
        "significance_note": code(m.significance_note),
    }


def key_metrics_json(m: Metrics | None) -> dict[str, Any]:
    """The handful of figures a scorecard compares; `{}` when there is no run."""
    if m is None:
        return {}
    return {
        "trades": m.total_trades,
        "net_return_pct": num(m.net_return_pct),
        "expectancy_r": num(m.expectancy_r),
        "profit_factor": num(m.profit_factor),
        "max_drawdown_pct": num(m.max_drawdown_pct),
        "win_rate_pct": num(m.win_rate_pct),
        "expectancy_t_stat": num(m.expectancy_t_stat),
    }


def month_json(mr: MonthReturn) -> dict[str, Any]:
    return {
        "month": mr.month,
        "start_equity": money(mr.start_equity),
        "end_equity": money(mr.end_equity),
        "return_pct": num(mr.return_pct),
        "trades": mr.trades,
        "net_pnl": money(mr.net_pnl),
        "pnl": money(mr.net_pnl),
    }


# --------------------------------------------------------------------------
# Curves and trades
# --------------------------------------------------------------------------


def _thin(items: Sequence[Any], limit: int = MAX_CURVE_POINTS) -> list[Any]:
    """Evenly thinned to at most `limit`, always keeping the first and last."""
    n = len(items)
    if n <= limit:
        return list(items)
    step = (n - 1) / (limit - 1)
    picked = sorted({round(i * step) for i in range(limit)} | {n - 1})
    return [items[i] for i in picked]


def equity_json(curve: Sequence[EquityPoint]) -> list[dict[str, Any]]:
    ordered = sorted(curve, key=lambda p: p.time)
    return [
        {
            "t": iso(p.time),
            "balance": money(p.balance),
            "equity": money(p.equity),
            "margin_pct": num(p.margin_utilization_pct),
        }
        for p in _thin(ordered)
    ]


def drawdown_json(result: BacktestResult) -> list[dict[str, Any]]:
    series = drawdown_series(result.equity_curve, result.config.risk.initial_capital)
    return [{"t": iso(t), "dd_pct": num(dd)} for t, dd in _thin(series)]


def trade_json(t: Trade) -> dict[str, Any]:
    return {
        "id": t.id,
        "direction": t.direction.value,
        "signal_time": iso(t.signal_time),
        "entry_time": iso(t.entry_time),
        "exit_time": iso(t.exit_time),
        "entry_price": t.entry_price,
        "exit_price": t.exit_price,
        "stop_price": t.stop_price,
        "take_profit_price": t.take_profit_price,
        "units": t.units,
        "risk_usd": money(t.risk_usd),
        "gross_pnl": money(t.gross_pnl),
        "commission": money(t.commission),
        "spread_slippage_cost": money(t.spread_slippage_cost),
        "financing": money(t.financing),
        "net_pnl": money(t.net_pnl),
        "r_multiple": num(t.r_multiple),
        "exit_reason": t.exit_reason.value,
        "reason": t.reason,
        "ambiguous_exit": t.ambiguous_exit,
        "duration_minutes": (t.exit_time - t.entry_time).total_seconds() / 60.0,
    }


def skipped_json(result: BacktestResult) -> tuple[dict[str, int], list[dict[str, Any]]]:
    counts = Counter(s.reason.value for s in result.skipped)
    ordered = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return dict(ordered), [{"code": c, "count": n} for c, n in ordered]


# --------------------------------------------------------------------------
# Data quality
# --------------------------------------------------------------------------


def quality_json(q: QualityReport, derived_from: str = "stored") -> dict[str, Any]:
    return {
        "symbol": q.symbol,
        "timeframe": q.timeframe.value,
        "bars": q.bars,
        "start": iso(q.start),
        "end": iso(q.end),
        "duplicates": q.duplicates,
        "misaligned": q.misaligned,
        "non_utc": q.non_utc,
        "ohlc_violations": q.ohlc_violations,
        "out_of_order": q.out_of_order,
        "expected_bars": q.expected_bars,
        "missing_bars": q.missing_bars,
        "coverage_pct": num(q.coverage_pct),
        "gap_count": q.gap_count,
        "largest_gap_bars": q.largest_gap_bars,
        "grade": q.grade,
        "gaps": [
            {
                "start": iso(g.start),
                "end": iso(g.end),
                "missing_bars": g.missing_bars,
                "kind": g.kind,
            }
            for g in q.gaps
        ],
        "notes": codes(q.notes),
        "derived_from": derived_from,
    }


# --------------------------------------------------------------------------
# Targets, Monte Carlo, bootstrap
# --------------------------------------------------------------------------


def _month_ref(months: Sequence[MonthReturn], pick_max: bool) -> dict[str, Any] | None:
    if not months:
        return None
    best = (max if pick_max else min)(months, key=lambda m: (m.return_pct, m.month))
    return {"month": best.month, "return_pct": num(best.return_pct)}


def targets_json(report: TargetReport, months: Sequence[MonthReturn]) -> dict[str, Any]:
    ruin = report.risk_of_ruin
    return {
        "label": report.label,
        "months": report.months_total,
        "months_total": report.months_total,
        "profitable_months": report.profitable_months,
        "losing_months": report.losing_months,
        "best_month": _month_ref(months, True),
        "worst_month": _month_ref(months, False),
        "best_month_pct": num(report.best_month_pct),
        "worst_month_pct": num(report.worst_month_pct),
        "max_drawdown_pct": num(report.max_drawdown_pct),
        "rows": [
            {
                "target_pct": r.target_pct,
                "months_hit": r.months_hit,
                "hit_rate_pct": num(r.hit_rate_pct),
                "simulated_hit_rate_pct": num(r.simulated_hit_rate_pct),
            }
            for r in report.rows
        ],
        "risk_of_ruin": {
            # Percent, like every other `_pct` figure on the page.
            "pct": None if ruin.prob_50pct_drawdown is None else ruin.prob_50pct_drawdown * 100.0,
            "prob_50pct_drawdown_pct": (
                None if ruin.prob_50pct_drawdown is None else ruin.prob_50pct_drawdown * 100.0
            ),
            "prob_lose_all_risk_capital_pct": (
                None
                if ruin.prob_lose_all_risk_capital is None
                else ruin.prob_lose_all_risk_capital * 100.0
            ),
            "horizon_months": ruin.horizon_months,
            "iterations": ruin.iterations,
            "assumptions": codes(ruin.assumptions),
            "note": code(ruin.note),
        },
        "disclaimers": codes(report.disclaimer_codes),
        "simulation_note": code(report.simulation_note),
    }


def _pctl(p: Any) -> dict[str, float] | None:
    if p is None:
        return None
    return {"p5": p.p5, "p25": p.p25, "p50": p.p50, "p75": p.p75, "p95": p.p95}


def monte_carlo_json(mc: MonteCarloResult, seed: int) -> dict[str, Any]:
    return {
        "iterations": mc.iterations,
        "seed": seed,
        "final_return_pct": _pctl(mc.final_return_pct),
        "max_drawdown_pct": _pctl(mc.max_drawdown_pct),
        "prob_ruin_pct": None if mc.prob_ruin is None else mc.prob_ruin * 100.0,
        "prob_loss_pct": None if mc.prob_loss is None else mc.prob_loss * 100.0,
        "assumptions": codes(mc.assumptions),
        "note": code(mc.note),
    }


def bootstrap_json(ci: BootstrapCI, seed: int, iterations: int) -> dict[str, Any]:
    return {
        "estimate": num(ci.estimate),
        "low": num(ci.low),
        "high": num(ci.high),
        "n": ci.n,
        "confidence": 0.95,
        "iterations": iterations,
        "seed": seed,
        "note": code(ci.note),
    }


def baseline_json(raw: dict[str, object]) -> dict[str, Any]:
    out: dict[str, Any] = dict(raw)
    out["reference"] = {"code": "baseline_stand_aside"}
    return out


# --------------------------------------------------------------------------
# Research pieces
# --------------------------------------------------------------------------


def _param_value(v: object) -> object:
    if isinstance(v, Decimal):
        return format(v, "f")
    return v


def params_json(params: dict[str, object] | None) -> dict[str, object] | None:
    if params is None:
        return None
    return {k: _param_value(v) for k, v in params.items()}


def grid_row_json(r: GridRow) -> dict[str, Any]:
    return {
        "params": params_json(r.params),
        "trades": r.trades,
        "net_return_pct": num(r.net_return_pct),
        "expectancy_r": num(r.expectancy_r),
        "profit_factor": num(r.profit_factor),
        "max_drawdown_pct": num(r.max_drawdown_pct),
        "score": num(r.score),
    }


def fold_json(f: Fold) -> dict[str, Any]:
    t = f.test_metrics
    return {
        "train": window_json(f.train),
        "test": window_json(f.test),
        "chosen_params": params_json(f.chosen_params),
        "train_score": num(f.train_score),
        "train_expectancy_r": num(f.train_expectancy_r),
        "test_trades": None if t is None else t.trades,
        "test_net_return_pct": None if t is None else num(t.net_return_pct),
        "test_expectancy_r": None if t is None else num(t.expectancy_r),
        "test_profit_factor": None if t is None else num(t.profit_factor),
        "test_max_drawdown_pct": None if t is None else num(t.max_drawdown_pct),
        "note": code(f.note),
    }


def trade_summary_json(summary: dict[str, object]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in summary.items():
        if isinstance(v, Decimal):
            out[k] = money(v)
        elif isinstance(v, float):
            out[k] = num(v)
        else:
            out[k] = v
    return out


def walk_forward_json(wf: WalkForwardResult) -> dict[str, Any]:
    return {
        "folds": [fold_json(f) for f in wf.folds],
        "oos_summary": trade_summary_json(wf.oos_summary),
        "efficiency": num(wf.efficiency),
        "efficiency_note": None if wf.efficiency is not None else {"code": "efficiency_not_meaningful"},
    }


def sensitivity_json(rows: Sequence[SensitivityRow]) -> list[dict[str, Any]]:
    return [
        {
            "value": _param_value(r.value),
            "trades": r.trades,
            "expectancy_r": num(r.expectancy_r),
            "net_return_pct": num(r.net_return_pct),
            "max_drawdown_pct": num(r.max_drawdown_pct),
            "profit_factor": num(r.profit_factor),
        }
        for r in rows
    ]


def stability_json(s: StabilityReport | None) -> dict[str, Any]:
    if s is None:
        return {}
    note = None
    if s.best_params is None:
        note = "no_eligible_parameters"
    elif s.neighbour_count == 0:
        note = "no_neighbouring_cells"
    return {
        "best_params": params_json(s.best_params),
        "neighbour_count": s.neighbour_count,
        "neighbours_positive_pct": num(s.neighbours_positive_pct),
        "best_vs_neighbour_median_ratio": num(s.best_vs_neighbour_median_ratio),
        "isolated_peak": s.isolated_peak,
        "positive_cells_pct": num(s.positive_cells_pct),
        "note": code(note),
    }


def stress_json(rows: Sequence[StressRow]) -> list[dict[str, Any]]:
    return [
        {
            "multiplier": r.multiplier,
            "spread_pips": num(r.spread_pips),
            "slippage_pips": num(r.slippage_pips),
            "trades": r.trades,
            "net_return_pct": num(r.net_return_pct),
            "expectancy_r": num(r.expectancy_r),
            "profit_factor": num(r.profit_factor),
        }
        for r in rows
    ]


def regime_json(rows: Sequence[RegimeRow]) -> list[dict[str, Any]]:
    return [
        {
            "regime": r.regime,
            "trades": r.trades,
            "win_rate_pct": num(r.win_rate_pct),
            "expectancy_r": num(r.expectancy_r),
            "net_pnl": money(r.net_pnl),
        }
        for r in rows
    ]


def scorecard_json(card: Scorecard, *, strategy: str, rank: int) -> dict[str, Any]:
    return {
        "name": card.name,
        "strategy": strategy,
        "rank": rank,
        "robustness_score": num(card.robustness_score),
        "verdict": {"code": card.verdict_code},
        "flags": codes(card.flags),
        "full": key_metrics_json(card.full),
        "development": key_metrics_json(card.development),
        "out_of_sample": key_metrics_json(card.out_of_sample),
        "stressed": key_metrics_json(card.stressed),
        "stability": stability_json(card.stability),
    }


def summary_json(m: Metrics, verdict_code: str | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {
        "net_return_pct": num(m.net_return_pct),
        "total_trades": m.total_trades,
        "expectancy_r": num(m.expectancy_r),
        "max_drawdown_pct": num(m.max_drawdown_pct),
        "profit_factor": num(m.profit_factor),
    }
    if verdict_code is not None:
        out["verdict_code"] = verdict_code
    return out
