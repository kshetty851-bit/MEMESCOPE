"""Meme Lifecycle Lab — trade statistics from closed paper trades.

Only ``status='closed'`` trades count. A position still open when the data ran
out (``END_OF_DATA``) has no exit, and inventing one to make the table complete
would report a result the market never delivered; it is counted separately as
``open_at_end``.

Conventions, chosen once and stated here:

* A **win** is ``pnl > 0``; a **loss** is ``pnl <= 0`` — after costs, a trade
  that returned nothing was a loss of time and fees. Same split as
  ``app.lab.leaderboard`` (restated, not imported: that module does SQL).
* ``profit_factor`` is ``None`` when nothing lost. Undefined, not infinite:
  three wins and no losses have not proven a ratio.
* Percentiles use linear interpolation between closest ranks (numpy's
  default), in ``Decimal``.
* ``top_n_contribution`` is the share of net profit produced by the N best
  trades; ``None`` when net profit is not positive (a share of a loss is not a
  meaningful number). ``net_pnl_ex_top_n`` is the same fact as a remainder —
  a strategy that is only profitable because of one trade says so here.
* ``max_drawdown`` is the largest snapshot drawdown (fraction of the running
  peak of known equity), ``None`` with no measured snapshot.

All figures are ``Decimal``; ``to_dict()`` serialises them as strings.

Pure: no I/O, no clock, no randomness.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from app.lifecycle_lab.experiments import sample_label
from app.lifecycle_lab.portfolio import STATUS_CLOSED, PaperTrade, PortfolioSnapshot

_ZERO = Decimal(0)
TOP_N: tuple[int, ...] = (1, 5, 10)
PERCENTILES: tuple[int, ...] = (25, 50, 75, 90, 95)


def percentile(sorted_values: Sequence[Decimal], pct: int) -> Decimal | None:
    """Linear-interpolated percentile of an ascending sequence."""
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = Decimal(pct) / Decimal(100) * Decimal(len(sorted_values) - 1)
    lo = int(rank)
    hi = min(lo + 1, len(sorted_values) - 1)
    frac = rank - Decimal(lo)
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * frac


def _median(values: Sequence[Decimal]) -> Decimal | None:
    return percentile(sorted(values), 50)


@dataclass(frozen=True, slots=True)
class LabMetrics:
    trades: int
    wins: int
    losses: int
    win_rate: Decimal | None
    avg_win: Decimal | None
    avg_loss: Decimal | None
    expectancy: Decimal | None
    profit_factor: Decimal | None
    net_pnl: Decimal
    roi: Decimal | None
    max_drawdown: Decimal | None
    longest_losing_streak: int
    avg_holding_seconds: Decimal | None
    median_holding_seconds: Decimal | None
    #: Keys: p25 p50 p75 p90 p95 min max mean — over ``return_pct``.
    return_percentiles: dict[str, Decimal | None]
    #: Keys "1", "5", "10".
    top_n_contribution: dict[str, Decimal | None]
    net_pnl_ex_top_n: dict[str, Decimal]
    sample_label: str
    open_at_end: int
    contains_backfill: bool
    hindsight: bool
    exits_by_reason: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        def s(v: Decimal | None) -> str | None:
            return None if v is None else str(v)

        return {
            "trades": self.trades,
            "wins": self.wins,
            "losses": self.losses,
            "win_rate": s(self.win_rate),
            "avg_win": s(self.avg_win),
            "avg_loss": s(self.avg_loss),
            "expectancy": s(self.expectancy),
            "profit_factor": s(self.profit_factor),
            "net_pnl": str(self.net_pnl),
            "roi": s(self.roi),
            "max_drawdown": s(self.max_drawdown),
            "longest_losing_streak": self.longest_losing_streak,
            "avg_holding_seconds": s(self.avg_holding_seconds),
            "median_holding_seconds": s(self.median_holding_seconds),
            "return_percentiles": {k: s(v) for k, v in self.return_percentiles.items()},
            "top_n_contribution": {k: s(v) for k, v in self.top_n_contribution.items()},
            "net_pnl_ex_top_n": {k: str(v) for k, v in self.net_pnl_ex_top_n.items()},
            "sample_label": self.sample_label,
            "open_at_end": self.open_at_end,
            "contains_backfill": self.contains_backfill,
            "hindsight": self.hindsight,
            "exits_by_reason": dict(self.exits_by_reason),
        }


def compute_metrics(
    trades: Sequence[PaperTrade],
    snapshots: Sequence[PortfolioSnapshot] = (),
    *,
    starting_capital: Decimal,
) -> LabMetrics:
    closed = sorted(
        (t for t in trades if t.status == STATUS_CLOSED and t.pnl_usd is not None),
        key=lambda t: (t.exit_at or t.entry_at, t.trade_key),
    )
    pnls = [t.pnl_usd for t in closed if t.pnl_usd is not None]
    n = len(pnls)
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    gross_win = sum(wins, _ZERO)
    gross_loss = -sum(losses, _ZERO)
    net = sum(pnls, _ZERO)

    streak = best = 0
    for p in pnls:
        if p <= 0:
            streak += 1
            best = max(best, streak)
        else:
            streak = 0

    holds = [
        Decimal(int((t.exit_at - t.entry_at).total_seconds()))
        for t in closed
        if t.exit_at is not None
    ]
    returns = sorted(t.return_pct for t in closed if t.return_pct is not None)
    rp: dict[str, Decimal | None] = {f"p{q}": percentile(returns, q) for q in PERCENTILES}
    rp["min"] = returns[0] if returns else None
    rp["max"] = returns[-1] if returns else None
    rp["mean"] = sum(returns, _ZERO) / len(returns) if returns else None

    ranked = sorted(pnls, reverse=True)
    top: dict[str, Decimal | None] = {}
    ex_top: dict[str, Decimal] = {}
    for k in TOP_N:
        head = sum(ranked[:k], _ZERO)
        top[str(k)] = head / net if net > 0 else None
        ex_top[str(k)] = net - head

    drawdowns = [s.drawdown for s in snapshots if s.drawdown is not None]
    reasons: dict[str, int] = {}
    for t in closed:
        if t.exit_reason is not None:
            reasons[t.exit_reason.value] = reasons.get(t.exit_reason.value, 0) + 1

    return LabMetrics(
        trades=n,
        wins=len(wins),
        losses=len(losses),
        win_rate=Decimal(len(wins)) / Decimal(n) if n else None,
        avg_win=gross_win / len(wins) if wins else None,
        avg_loss=sum(losses, _ZERO) / len(losses) if losses else None,
        expectancy=net / n if n else None,
        profit_factor=gross_win / gross_loss if gross_loss > 0 else None,
        net_pnl=net,
        roi=net / starting_capital if starting_capital > 0 else None,
        max_drawdown=max(drawdowns) if drawdowns else None,
        longest_losing_streak=best,
        avg_holding_seconds=sum(holds, _ZERO) / len(holds) if holds else None,
        median_holding_seconds=_median(holds),
        return_percentiles=rp,
        top_n_contribution=top,
        net_pnl_ex_top_n=ex_top,
        sample_label=sample_label(n),
        open_at_end=sum(1 for t in trades if t.status != STATUS_CLOSED),
        contains_backfill=any(t.contains_backfill for t in trades),
        hindsight=any(t.hindsight for t in trades),
        exits_by_reason=dict(sorted(reasons.items())),
    )
