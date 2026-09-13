"""Metrics, controls, walk-forward, statistics and the acceptance gate.

`RESEARCH_ONLY`. Pure: no I/O, no clock beyond what the dataset carries.

## The gate is judged on WEEKLY folds and nothing else

`walk_forward` also computes a daily split, because an archive too short for
weeks still has something worth showing. That split is EXPLORATORY: `gate()`
reads the weekly folds, and a daily result can never turn a fail into a pass.
Both are returned, labelled, and the report prints the label.

## Censored trades never become zeros

A censored trade has no return. It is counted in `censored`, excluded from PF
and expectancy, and reported as a share — never coerced to 0%, which would be a
claim the data does not make and would drag every average toward the middle.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal

from app.labs.v6_fast_accum import config
from app.labs.v6_fast_accum.dataset import Dataset
from app.labs.v6_fast_accum.simulator import Trade, run_strategy, apply_position_limits


@dataclass
class Metrics:
    trades: int = 0
    censored: int = 0
    wins: int = 0
    losses: int = 0
    win_rate: float = 0.0
    gross_profit: float = 0.0
    gross_loss: float = 0.0
    profit_factor: float | None = None
    expectancy: float = 0.0
    avg_winner: float = 0.0
    avg_loser: float = 0.0
    median_return: float = 0.0
    cumulative_pnl: float = 0.0
    max_drawdown: float = 0.0
    sharpe: float | None = None
    sortino: float | None = None
    rate_2x: float = 0.0
    rate_2x_before_stop: float = 0.0
    graduation_rate: float = 0.0
    median_time_to_2x_s: float | None = None
    median_mae: float | None = None
    median_mfe: float | None = None
    exit_mix: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}


def _pct(xs: list[float], q: float) -> float | None:
    if not xs:
        return None
    s = sorted(xs)
    return s[min(len(s) - 1, int(q * len(s)))]


def compute(trades: list[Trade]) -> Metrics:
    m = Metrics(trades=len(trades))
    resolved = [t for t in trades if not t.censored and t.net_pnl_usd is not None]
    m.censored = len(trades) - len(resolved)
    if not resolved:
        return m

    pnl = [float(t.net_pnl_usd) for t in resolved]
    rets = [float(t.net_return) for t in resolved if t.net_return is not None]
    wins = [p for p in pnl if p > 0]
    losses = [p for p in pnl if p <= 0]

    m.wins, m.losses = len(wins), len(losses)
    m.win_rate = 100.0 * len(wins) / len(pnl)
    m.gross_profit = sum(wins)
    m.gross_loss = abs(sum(losses))
    m.profit_factor = (m.gross_profit / m.gross_loss) if m.gross_loss > 0 else None
    m.expectancy = sum(pnl) / len(pnl)
    m.avg_winner = (sum(wins) / len(wins)) if wins else 0.0
    m.avg_loser = (sum(losses) / len(losses)) if losses else 0.0
    m.median_return = _pct(rets, 0.5) or 0.0
    m.cumulative_pnl = sum(pnl)

    # Drawdown on the equity curve in ENTRY order, which is the order the book
    # would actually have experienced them.
    eq = 0.0
    peak = 0.0
    for t in sorted(resolved, key=lambda x: x.entry_ts):
        eq += float(t.net_pnl_usd)
        peak = max(peak, eq)
        m.max_drawdown = min(m.max_drawdown, eq - peak)

    if len(rets) > 1:
        mu = sum(rets) / len(rets)
        sd = math.sqrt(sum((r - mu) ** 2 for r in rets) / (len(rets) - 1))
        m.sharpe = (mu / sd) if sd > 0 else None
        downs = [r for r in rets if r < 0]
        if len(downs) > 1:
            dsd = math.sqrt(sum(r ** 2 for r in downs) / len(downs))
            m.sortino = (mu / dsd) if dsd > 0 else None

    # Edge metrics span ALL trades including censored ones: whether a token
    # touched 2x is observable even when the exit was not.
    n = len(trades) or 1
    m.rate_2x = 100.0 * sum(1 for t in trades if t.reached_100) / n
    m.rate_2x_before_stop = 100.0 * sum(
        1 for t in trades if t.exit_reason == "take_profit") / n
    m.graduation_rate = 100.0 * sum(1 for t in trades if t.graduated) / n
    m.median_time_to_2x_s = _pct(
        [float(t.time_to_100_s) for t in trades if t.time_to_100_s is not None], 0.5)
    m.median_mae = _pct([float(t.mae) for t in trades if t.mae is not None], 0.5)
    m.median_mfe = _pct([float(t.mfe) for t in trades if t.mfe is not None], 0.5)

    mix: dict[str, int] = {}
    for t in trades:
        mix[t.exit_reason] = mix.get(t.exit_reason, 0) + 1
    m.exit_mix = mix
    return m


def concentration(trades: list[Trade]) -> dict:
    """How much of the profit came from how few tokens (§13)."""
    profits = sorted(
        (float(t.net_pnl_usd) for t in trades
         if not t.censored and t.net_pnl_usd is not None and t.net_pnl_usd > 0),
        reverse=True)
    total = sum(profits)
    if total <= 0:
        return {"total_profit": total, "best_token_pct": 0.0, "top5_pct": 0.0,
                "median_token_contribution": 0.0, "profitable_tokens": len(profits)}
    return {
        "total_profit": total,
        "best_token_pct": 100.0 * profits[0] / total,
        "top5_pct": 100.0 * sum(profits[:5]) / total,
        "median_token_contribution": 100.0 * (_pct(profits, 0.5) or 0.0) / total,
        "profitable_tokens": len(profits),
    }


def bootstrap_ci(trades: list[Trade], *, iterations: int = config.BOOTSTRAP_ITERATIONS,
                 seed: int = config.RANDOM_SEED) -> dict:
    """Percentile bootstrap on mean net PnL and on profit factor.

    Answers the §14(7) question: is the result carried by a handful of extreme
    winners? A lower bound at or below zero on a positive point estimate says
    the mean is not distinguishable from no edge once resampling is allowed to
    leave the big winners out.
    """
    pnl = [float(t.net_pnl_usd) for t in trades
           if not t.censored and t.net_pnl_usd is not None]
    if len(pnl) < 2:
        return {"n": len(pnl), "insufficient": True}
    rng = random.Random(seed)
    means, pfs = [], []
    n = len(pnl)
    for _ in range(iterations):
        s = [pnl[rng.randrange(n)] for _ in range(n)]
        means.append(sum(s) / n)
        gp = sum(x for x in s if x > 0)
        gl = abs(sum(x for x in s if x <= 0))
        pfs.append(gp / gl if gl > 0 else float("inf"))
    means.sort()
    finite = sorted(p for p in pfs if math.isfinite(p))
    lo, hi = int(0.025 * iterations), int(0.975 * iterations) - 1
    return {
        "n": n, "insufficient": False,
        "mean_pnl": sum(pnl) / n,
        "mean_ci_low": means[lo], "mean_ci_high": means[hi],
        "pf_ci_low": finite[int(0.025 * len(finite))] if finite else None,
        "pf_ci_high": finite[int(0.975 * len(finite)) - 1] if finite else None,
        "mean_ci_excludes_zero": means[lo] > 0,
    }


def one_sample_p(trades: list[Trade]) -> tuple[float, float]:
    """`(p_value, effect_size)` for "mean net PnL > 0", a one-sided t-test.

    Normal approximation to the t distribution: at these sample sizes the
    difference is far smaller than the bias the censoring already introduces,
    and pretending otherwise would be false precision.
    """
    pnl = [float(t.net_pnl_usd) for t in trades
           if not t.censored and t.net_pnl_usd is not None]
    if len(pnl) < 3:
        return 1.0, 0.0
    n = len(pnl)
    mu = sum(pnl) / n
    sd = math.sqrt(sum((x - mu) ** 2 for x in pnl) / (n - 1))
    if sd == 0:
        return (0.0 if mu > 0 else 1.0), 0.0
    t = mu / (sd / math.sqrt(n))
    p = 0.5 * math.erfc(t / math.sqrt(2))
    return p, mu / sd  # Cohen's d


def benjamini_hochberg(pvalues: dict[str, float], alpha: float) -> dict[str, dict]:
    """BH step-up. Returns raw p, adjusted p and the reject flag per hypothesis."""
    items = sorted(pvalues.items(), key=lambda kv: kv[1])
    m = len(items)
    out: dict[str, dict] = {}
    prev = 1.0
    for i in range(m - 1, -1, -1):
        name, p = items[i]
        adj = min(prev, p * m / (i + 1))
        prev = adj
        out[name] = {"raw_p": p, "adjusted_p": adj, "reject_null": adj <= alpha}
    return out


# --- walk-forward -------------------------------------------------------------


@dataclass
class Fold:
    index: int
    train_start: datetime
    train_end: datetime
    test_start: datetime
    test_end: datetime
    selected_config: str | None = None
    train_trades: int = 0
    test_metrics: Metrics = field(default_factory=Metrics)

    def as_dict(self) -> dict:
        return {
            "index": self.index,
            "train_start": self.train_start.isoformat(),
            "train_end": self.train_end.isoformat(),
            "test_start": self.test_start.isoformat(),
            "test_end": self.test_end.isoformat(),
            "selected_config": self.selected_config,
            "train_trades": self.train_trades,
            "test": self.test_metrics.as_dict(),
        }


def _slice(trades: list[Trade], a: datetime, b: datetime) -> list[Trade]:
    return [t for t in trades if a <= t.entry_ts < b]


def select_config(by_cfg: dict[str, list[Trade]], a: datetime, b: datetime) -> str | None:
    """Pick the candidate with the best TRAIN profit factor. Train only.

    This is the only place a configuration is chosen, and it never sees a test
    fold. Ties and empty folds return None rather than a default, so "nothing
    qualified" cannot masquerade as a choice.
    """
    best, best_pf = None, None
    for name, trades in by_cfg.items():
        m = compute(_slice(trades, a, b))
        if m.trades == 0 or m.profit_factor is None:
            continue
        if best_pf is None or m.profit_factor > best_pf:
            best, best_pf = name, m.profit_factor
    return best


def walk_forward(ds: Dataset, by_cfg: dict[str, list[Trade]], *,
                 fold: str = config.FOLD) -> tuple[list[Fold], str]:
    """Purged, embargoed, expanding-window walk-forward.

    Returns `(folds, status)`. A status of `INSUFFICIENT_HISTORY` means the
    archive is too short to form even one train/test pair at this width — which
    is a result about the data, not about the strategy, and is reported as such.
    """
    width = timedelta(days=7 if fold == "weekly" else 1)
    embargo = timedelta(minutes=config.EMBARGO_MIN)
    start, end = ds.window_start, ds.window_end
    if end - start < width * 2:
        return [], "INSUFFICIENT_HISTORY"

    folds: list[Fold] = []
    idx = 0
    test_start = start + width
    while test_start + width <= end:
        test_end = test_start + width
        # The embargo shortens TRAIN, never test: a trade opened just before the
        # boundary can still be running when the test fold opens, and its
        # outcome would otherwise be in both.
        train_end = test_start - embargo
        f = Fold(idx, start, train_end, test_start, test_end)
        f.selected_config = select_config(by_cfg, start, train_end)
        if f.selected_config:
            f.train_trades = len(_slice(by_cfg[f.selected_config], start, train_end))
            f.test_metrics = compute(
                _slice(by_cfg[f.selected_config], test_start, test_end))
        folds.append(f)
        idx += 1
        test_start = test_end
    return folds, ("OK" if folds else "INSUFFICIENT_HISTORY")


# --- the gate -----------------------------------------------------------------


def gate(folds: list[Fold], status: str, oos: list[Trade],
         conc: dict, boot: dict, bh: dict[str, dict]) -> dict:
    """§14, evaluated literally. A condition that cannot be evaluated FAILS.

    "Not evaluable" is not "satisfied". An experiment that cannot check a
    condition has not met it, and recording it as a pass because no evidence
    contradicted it is the precise mistake the gate exists to prevent.
    """
    m = compute(oos)
    checks: list[dict] = []

    def add(name: str, ok: bool | None, detail: str) -> None:
        checks.append({"condition": name,
                       "status": "PASS" if ok else ("FAIL" if ok is False else "NOT_EVALUABLE"),
                       "detail": detail})

    if status == "INSUFFICIENT_HISTORY":
        for name in ("oos_profit_factor_ge_1.5", "oos_trades_ge_100",
                     "no_token_over_20pct_profit", "every_test_week_profitable",
                     "positive_after_fees_and_slippage",
                     "survives_multiple_comparison", "bootstrap_ci_not_outlier_driven"):
            add(name, None, "no out-of-sample period exists at the pre-registered "
                            "weekly fold width")
        return {"passed": False, "checks": checks,
                "verdict": "NO RELIABLE EDGE IDENTIFIED",
                "reason": "INSUFFICIENT_HISTORY"}

    pf = m.profit_factor
    add("oos_profit_factor_ge_1.5",
        pf is not None and Decimal(str(pf)) >= config.GATE_MIN_PROFIT_FACTOR,
        f"PF={pf}")
    add("oos_trades_ge_100", m.trades - m.censored >= config.GATE_MIN_OOS_TRADES,
        f"resolved OOS trades={m.trades - m.censored}")
    add("no_token_over_20pct_profit",
        conc.get("best_token_pct", 100.0) <= float(config.GATE_MAX_SINGLE_TOKEN_PROFIT_SHARE) * 100,
        f"best token={conc.get('best_token_pct', 0):.1f}%")
    profitable = [f for f in folds if f.test_metrics.cumulative_pnl > 0]
    add("every_test_week_profitable", len(profitable) == len(folds) and bool(folds),
        f"{len(profitable)}/{len(folds)} test folds profitable")
    add("positive_after_fees_and_slippage", m.cumulative_pnl > 0,
        f"net cumulative PnL=${m.cumulative_pnl:.2f}")
    rejected = any(v["reject_null"] for v in bh.values())
    add("survives_multiple_comparison", rejected,
        f"{sum(1 for v in bh.values() if v['reject_null'])}/{len(bh)} hypotheses "
        f"reject the null after BH")
    add("bootstrap_ci_not_outlier_driven",
        bool(boot.get("mean_ci_excludes_zero")),
        f"mean 95% CI=[{boot.get('mean_ci_low')}, {boot.get('mean_ci_high')}]")

    passed = all(c["status"] == "PASS" for c in checks)
    return {"passed": passed, "checks": checks,
            "verdict": "EDGE SUPPORTED" if passed else "NO RELIABLE EDGE IDENTIFIED",
            "reason": "gate" if not passed else "pass"}


def build_controls(ds: Dataset, cfg: config.EntryConfig) -> dict[str, list[Trade]]:
    """The four §9 controls, each the same simulator over a different rule.

    Attribution is only possible because each control differs from the base in
    exactly ONE respect — the overlay it drops, or the timing it randomises.
    """
    return {
        config.CONTROL_A: apply_position_limits(
            run_strategy(ds, cfg, strategy=config.CONTROL_A, randomise_in_region=True)),
        config.CONTROL_B: apply_position_limits(
            run_strategy(ds, cfg, strategy=config.CONTROL_B, require_mcap=True)),
        config.CONTROL_C: apply_position_limits(
            run_strategy(ds, cfg, strategy=config.CONTROL_C, require_mcap=False)),
        config.CONTROL_D: apply_position_limits(
            run_strategy(ds, cfg, strategy=config.CONTROL_D, require_mcap=False)),
    }
