"""The three computations a run performs, in memory. Pure.

Each takes already-loaded `Market`s and returns `(result, summary)` as
JSON-safe dicts holding CODES, never prose (see `serialize`). Progress is
reported through a plain callback so the caller decides where it goes; nothing
here knows about a database, a thread or a clock.

## Why the test window is only looked at once

`run_research` searches parameters on the DEVELOPMENT window and nowhere else.
The winner is then applied, unchanged, to validation and test. Nothing computed
from validation or test feeds back into the choice, and the result says so with
the `selection_on_development_only` note. Walk-forward is a separate protocol
that chooses on each of its own training windows; it is reported next to the
split, never used to pick the headline parameters.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from app.labs.forex import codec, meta, pipeline, serialize
from app.labs.forex.compare import Scorecard, evaluate, rank
from app.labs.forex.data import slice_window, validate
from app.labs.forex.metrics import Metrics, compute_metrics
from app.labs.forex.pipeline import Market
from app.labs.forex.research import (
    Split,
    Window,
    baseline_comparison,
    bootstrap_ci,
    chronological_split,
    cost_stress,
    monte_carlo,
    optimise,
    parameter_stability,
    regime_breakdown,
    sensitivity,
    walk_forward,
)
from app.labs.forex.targets import target_analysis
from app.labs.forex.types import BacktestConfig, BacktestResult, Timeframe

Progress = Callable[[int, str], None]

MC_SEED = 7
BOOTSTRAP_SEED = 11
TARGET_SEED = 3
STRESS_MULTIPLE = 2.0

MIN_MC_ITERATIONS = 100
MAX_MC_ITERATIONS = 10_000
DEFAULT_STRESS = (1.0, 1.5, 2.0, 3.0)
MAX_STRESS_ROWS = 6

SELECTION_ON_DEVELOPMENT_ONLY = "selection_on_development_only"
NO_ELIGIBLE_PARAMETERS = "no_eligible_parameters_base_config_used"


def _noop(pct: int, message: str) -> None:
    return None


# --------------------------------------------------------------------------
# Options
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Options:
    dev_pct: float = 60.0
    val_pct: float = 20.0
    grid: dict[str, list[object]] | None = None
    train_days: int = 90
    test_days: int = 30
    mc_iterations: int = 1000
    stress_multipliers: tuple[float, ...] = DEFAULT_STRESS


def _number(raw: object, name: str, lo: float, hi: float) -> float:
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise codec.ConfigError(f"options.{name}: expected a number")
    if not lo <= float(raw) <= hi:
        raise codec.ConfigError(f"options.{name}: must be between {lo:g} and {hi:g}")
    return float(raw)


def parse_options(raw: Mapping[str, object] | None) -> Options:
    """Validate the request's `options`. Unknown keys are refused, not ignored."""
    if raw is None:
        return Options()
    if not isinstance(raw, Mapping):
        raise codec.ConfigError("options: expected an object")
    unknown = set(raw) - {
        "dev_pct", "val_pct", "grid", "walk_forward", "mc_iterations", "stress_multipliers",
    }  # fmt: skip
    if unknown:
        raise codec.ConfigError(f"options: unknown keys {sorted(unknown)}")
    base = Options()
    dev = _number(raw.get("dev_pct", base.dev_pct), "dev_pct", 10, 90)
    val = _number(raw.get("val_pct", base.val_pct), "val_pct", 5, 50)
    if dev + val > 95:
        raise codec.ConfigError("options: dev_pct + val_pct must leave at least 5% for test")
    train, test = base.train_days, base.test_days
    wf = raw.get("walk_forward")
    if wf is not None:
        if not isinstance(wf, Mapping) or set(wf) - {"train_days", "test_days"}:
            raise codec.ConfigError("options.walk_forward: expected {train_days, test_days}")
        train = int(_number(wf.get("train_days", train), "walk_forward.train_days", 7, 730))
        test = int(_number(wf.get("test_days", test), "walk_forward.test_days", 1, 365))
    mc = int(
        _number(
            raw.get("mc_iterations", base.mc_iterations),
            "mc_iterations",
            MIN_MC_ITERATIONS,
            MAX_MC_ITERATIONS,
        )
    )
    stress = base.stress_multipliers
    if "stress_multipliers" in raw:
        sm = raw["stress_multipliers"]
        if not isinstance(sm, (list, tuple)) or not 1 <= len(sm) <= MAX_STRESS_ROWS:
            raise codec.ConfigError(
                f"options.stress_multipliers: expected 1 to {MAX_STRESS_ROWS} numbers"
            )
        stress = tuple(_number(x, "stress_multipliers", 0.5, 10) for x in sm)
    grid = raw.get("grid")
    if grid is not None and (not isinstance(grid, Mapping) or not grid):
        raise codec.ConfigError("options.grid: expected an object of path -> values")
    return Options(
        dev_pct=dev,
        val_pct=val,
        grid=None if grid is None else {str(k): v for k, v in grid.items()},
        train_days=train,
        test_days=test,
        mc_iterations=mc,
        stress_multipliers=stress,
    )


def resolve_grid(cfg: BacktestConfig, opts: Options) -> dict[str, Sequence[object]]:
    space = opts.grid if opts.grid is not None else meta.default_grid(cfg.strategy)
    return codec.validate_grid(cfg, space)


def resolve_default_grid(cfg: BacktestConfig) -> dict[str, Sequence[object]]:
    return codec.validate_grid(cfg, meta.default_grid(cfg.strategy))


# --------------------------------------------------------------------------
# Plumbing
# --------------------------------------------------------------------------


class _Runner:
    """A research `Runner` over one market that reports its own progress."""

    def __init__(self, market: Market, progress: Progress, total: int, base: int = 0) -> None:
        self.market = market
        self.progress = progress
        self.total = max(total, 1)
        self.done = base

    def __call__(self, cfg: BacktestConfig, start: datetime, end: datetime) -> BacktestResult:
        result = pipeline.run(cfg, self.market, start, end)
        self.done += 1
        self.progress(min(95, int(95 * self.done / self.total)), f"replay {self.done}")
        return result


def stress_config(cfg: BacktestConfig, multiplier: float) -> BacktestConfig:
    """Spread, slippage and commission scaled together (as `cost_stress` does)."""
    c = cfg.costs
    costs = dataclasses.replace(
        c,
        spread_pips=c.spread_pips * multiplier,
        slippage_pips=c.slippage_pips * multiplier,
        commission_per_lot_side=c.commission_per_lot_side * Decimal(str(multiplier)),
    )
    return dataclasses.replace(cfg, costs=costs)


def _span(w: Window) -> dict[str, Any]:
    return serialize.window_json(w)


def _data_block(
    cfg: BacktestConfig, market: Market, start: datetime, end: datetime, result: BacktestResult
) -> dict[str, Any]:
    quality = validate(slice_window(market.candles, start, end), cfg.symbol, cfg.timeframe)
    return {
        "symbol": cfg.symbol,
        "timeframe": cfg.timeframe.value,
        "start": serialize.iso(start),
        "end": serialize.iso(end),
        "bars": result.bars,
        "sources": list(market.sources),
        "quality_grade": quality.grade,
        "coverage_pct": serialize.num(quality.coverage_pct),
        "lower_tf_available": bool(market.lower) and cfg.timeframe is not Timeframe.M1,
        "htf_derived": market.htf_derived,
        "exec_derived": market.exec_derived,
    }


def _period(result: BacktestResult, window: Window) -> tuple[Metrics, dict[str, Any]]:
    m = compute_metrics(result)
    return m, {
        "window": _span(window),
        "metrics": serialize.metrics_json(m),
        "months": [serialize.month_json(x) for x in m.months],
        "equity_curve": serialize.equity_json(result.equity_curve),
        "trade_count": m.total_trades,
    }


def _monte_carlo(result: BacktestResult, opts: Options) -> dict[str, Any]:
    cfg = result.config
    mc = monte_carlo(
        result.trades,
        cfg.risk.initial_capital,
        cfg.risk.risk_per_trade_pct,
        iterations=opts.mc_iterations,
        seed=MC_SEED,
    )
    return serialize.monte_carlo_json(mc, MC_SEED)


def _bootstrap(result: BacktestResult, months: Sequence[Any], opts: Options) -> dict[str, Any]:
    r_ci = bootstrap_ci(
        [t.r_multiple for t in result.trades],
        iterations=opts.mc_iterations,
        seed=BOOTSTRAP_SEED,
    )
    m_ci = bootstrap_ci(
        [m.return_pct for m in months], iterations=opts.mc_iterations, seed=BOOTSTRAP_SEED
    )
    return {
        "expectancy_r": serialize.bootstrap_json(r_ci, BOOTSTRAP_SEED, opts.mc_iterations),
        "monthly_return": serialize.bootstrap_json(m_ci, BOOTSTRAP_SEED, opts.mc_iterations),
    }


def _targets(result: BacktestResult, m: Metrics, label: str, opts: Options) -> dict[str, Any]:
    cfg = result.config
    report = target_analysis(
        m.months,
        result.trades,
        targets=meta.TARGET_PCTS,
        initial_capital=cfg.risk.initial_capital,
        risk_pct=cfg.risk.risk_per_trade_pct,
        max_drawdown_pct=m.max_drawdown_pct,
        seed=TARGET_SEED,
        iterations=opts.mc_iterations,
        label=label,
    )
    return serialize.targets_json(report, m.months)


# --------------------------------------------------------------------------
# Backtest
# --------------------------------------------------------------------------


def run_backtest_job(
    cfg: BacktestConfig,
    market: Market,
    start: datetime,
    end: datetime,
    opts: Options,
    progress: Progress = _noop,
) -> tuple[dict[str, Any], dict[str, Any]]:
    progress(5, "replaying")
    result = pipeline.run(cfg, market, start, end)
    m = compute_metrics(result)
    progress(60, "measuring")
    skipped, skipped_text = serialize.skipped_json(result)
    out: dict[str, Any] = {
        "type": "backtest",
        "data": _data_block(cfg, market, start, end, result),
        "metrics": serialize.metrics_json(m),
        "months": [serialize.month_json(x) for x in m.months],
        "equity_curve": serialize.equity_json(result.equity_curve),
        "drawdown": serialize.drawdown_json(result),
        "trades": [serialize.trade_json(t) for t in result.trades],
        "signals": result.signals,
        "skipped": skipped,
        "skipped_text": skipped_text,
        "assumptions": serialize.codes(result.assumptions),
        "baseline": serialize.baseline_json(baseline_comparison(m)),
    }
    progress(75, "simulating")
    out["monte_carlo"] = _monte_carlo(result, opts)
    out["bootstrap"] = _bootstrap(result, m.months, opts)
    out["targets"] = _targets(result, m, "full", opts)
    progress(99, "done")
    return out, serialize.summary_json(m)


# --------------------------------------------------------------------------
# Research
# --------------------------------------------------------------------------


def _expected_runs(
    space: dict[str, Sequence[object]], opts: Options, start: datetime, end: datetime
) -> int:
    cells = 1
    for values in space.values():
        cells *= len(values)
    sens = sum(len(v) for v in space.values())
    days = max((end - start).days, 1)
    folds = max((days - opts.train_days) // max(opts.test_days, 1), 0)
    return cells + 5 + sens + len(opts.stress_multipliers) + folds * (cells + 1)


def run_research_job(
    cfg: BacktestConfig,
    market: Market,
    start: datetime,
    end: datetime,
    opts: Options,
    *,
    name: str | None = None,
    progress: Progress = _noop,
) -> tuple[dict[str, Any], dict[str, Any]]:
    split = chronological_split(start, end, opts.dev_pct, opts.val_pct)
    space = resolve_grid(cfg, opts)
    runner = _Runner(market, progress, _expected_runs(space, opts, start, end))
    dev, val, test = split.development, split.validation, split.test

    progress(2, "searching development window")
    opt = optimise(cfg, space, runner, dev)
    if opt.best is None:
        chosen_cfg, chosen = cfg, {}
        selection = NO_ELIGIBLE_PARAMETERS
    else:
        chosen_cfg, chosen = codec.apply_params(cfg, opt.best.params), dict(opt.best.params)
        selection = SELECTION_ON_DEVELOPMENT_ONLY

    dev_res = runner(chosen_cfg, dev.start, dev.end)
    val_res = runner(chosen_cfg, val.start, val.end)
    test_res = runner(chosen_cfg, test.start, test.end)
    full_res = runner(chosen_cfg, start, end)
    oos_res = runner(chosen_cfg, val.start, test.end)
    stressed_res = runner(stress_config(chosen_cfg, STRESS_MULTIPLE), start, end)

    dev_m, dev_json = _period(dev_res, dev)
    _val_m, val_json = _period(val_res, val)
    test_m, test_json = _period(test_res, test)
    full_m = compute_metrics(full_res)
    oos_m = compute_metrics(oos_res)
    stressed_m = compute_metrics(stressed_res)

    progress(60, "walk-forward")
    try:
        wf = walk_forward(cfg, space, runner, start, end, opts.train_days, opts.test_days)
        wf_json: dict[str, Any] = serialize.walk_forward_json(wf)
    except ValueError as exc:
        # A window too short for a single fold is a fact about the request, not
        # a failure of the run: the rest of the report still stands.
        wf_json = {
            "folds": [],
            "oos_summary": {},
            "efficiency": None,
            "efficiency_note": {"code": str(exc)},
        }

    sens = {
        path: serialize.sensitivity_json(sensitivity(chosen_cfg, path, values, runner, dev))
        for path, values in space.items()
    }
    stability = parameter_stability(opt.rows, space)
    stress = cost_stress(chosen_cfg, runner, Window(start, end), opts.stress_multipliers)

    progress(90, "measuring")
    card = evaluate(
        name or meta.STRATEGIES[cfg.strategy].name,
        full=full_m,
        development=dev_m,
        out_of_sample=test_m,
        stressed=stressed_m,
        stability=stability,
    )
    result: dict[str, Any] = {
        "type": "research",
        "split": {"development": _span(dev), "validation": _span(val), "test": _span(test)},
        "optimisation": {
            "space": {k: list(v) for k, v in space.items()},
            "rows": [serialize.grid_row_json(r) for r in opt.rows],
            "best": None if opt.best is None else serialize.grid_row_json(opt.best),
        },
        "chosen_params": serialize.params_json(chosen),
        "chosen_config": codec.config_to_json(chosen_cfg),
        "selection_note": {"code": selection},
        "development": dev_json,
        "validation": val_json,
        "test": test_json,
        "walk_forward": wf_json,
        "sensitivity": sens,
        "stability": serialize.stability_json(stability),
        "cost_stress": serialize.stress_json(stress),
        "monte_carlo": _monte_carlo(oos_res, opts),
        "bootstrap": _bootstrap(oos_res, oos_m.months, opts),
        "regimes": serialize.regime_json(regime_breakdown(full_res, market.candles)),
        "baseline": serialize.baseline_json(baseline_comparison(full_m)),
        "targets": {
            "full": _targets(full_res, full_m, "full", opts),
            "out_of_sample": _targets(oos_res, oos_m, "out_of_sample", opts),
        },
        "scorecard": serialize.scorecard_json(card, strategy=cfg.strategy.value, rank=1),
        "data": _data_block(cfg, market, start, end, full_res),
        "trades": [serialize.trade_json(t) for t in full_res.trades],
    }
    progress(99, "done")
    return result, serialize.summary_json(full_m, card.verdict_code)


# --------------------------------------------------------------------------
# Compare
# --------------------------------------------------------------------------


def _unique_names(configs: Sequence[BacktestConfig]) -> list[str]:
    seen: dict[str, int] = {}
    out: list[str] = []
    for c in configs:
        base = meta.STRATEGIES[c.strategy].name
        seen[base] = seen.get(base, 0) + 1
        out.append(base if seen[base] == 1 else f"{base} ({seen[base]})")
    return out


def run_compare_job(
    configs: Sequence[BacktestConfig],
    markets: Sequence[Market],
    start: datetime,
    end: datetime,
    opts: Options,
    progress: Progress = _noop,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if not configs or len(configs) != len(markets):
        raise ValueError("compare_needs_a_market_per_config")
    split: Split = chronological_split(start, end, opts.dev_pct, opts.val_pct)
    names = _unique_names(configs)

    spaces = [resolve_default_grid(c) for c in configs]
    total = 0
    for sp in spaces:
        cells = 1
        for values in sp.values():
            cells *= len(values)
        total += cells + 4
    cards: list[tuple[Scorecard, str, str, dict[str, Any]]] = []
    done_base = 0
    for cfg, market, space, name in zip(configs, markets, spaces, names, strict=True):
        runner = _Runner(market, progress, total, done_base)
        opt = optimise(cfg, space, runner, split.development)
        stability = parameter_stability(opt.rows, space)
        full_m = compute_metrics(runner(cfg, start, end))
        dev_m = compute_metrics(runner(cfg, split.development.start, split.development.end))
        test_m = compute_metrics(runner(cfg, split.test.start, split.test.end))
        stressed_m = compute_metrics(runner(stress_config(cfg, STRESS_MULTIPLE), start, end))
        done_base = runner.done
        card = evaluate(
            name,
            full=full_m,
            development=dev_m,
            out_of_sample=test_m,
            stressed=stressed_m,
            stability=stability,
        )
        detail = {
            "name": name,
            "full": serialize.key_metrics_json(full_m),
            "development": serialize.key_metrics_json(dev_m),
            "out_of_sample": serialize.key_metrics_json(test_m),
            "stressed": serialize.key_metrics_json(stressed_m),
            "stability": serialize.stability_json(stability),
        }
        cards.append((card, cfg.strategy.value, name, detail))

    by_card = {id(c[0]): c for c in cards}
    ranked = rank([c[0] for c in cards])
    scorecards = []
    for i, card in enumerate(ranked, start=1):
        _card, strategy, _name, _detail = by_card[id(card)]
        scorecards.append(serialize.scorecard_json(card, strategy=strategy, rank=i))

    per_strategy: dict[str, Any] = {}
    for _card, strategy, name, detail in cards:
        key = strategy if strategy not in per_strategy else f"{strategy}:{name}"
        per_strategy[key] = detail

    top = ranked[0]
    result = {
        "type": "compare",
        "window": {"start": serialize.iso(start), "end": serialize.iso(end)},
        "split": {
            "development": _span(split.development),
            "validation": _span(split.validation),
            "test": _span(split.test),
        },
        "scorecards": scorecards,
        "per_strategy": per_strategy,
    }
    progress(99, "done")
    return result, serialize.summary_json(top.full, top.verdict_code)
