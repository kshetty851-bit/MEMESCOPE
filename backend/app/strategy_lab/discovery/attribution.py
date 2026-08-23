"""Which design choices associate with better out-of-sample results. §30.

**Association, not causation, and the wording matters.** The search is a full
factorial, so every level of every dimension appears against every level of the
others and a marginal mean is a fair comparison *within this dataset*. It is
still one market over one short window: "P2 beat P0 here" is evidence about
these days, not a law about ladders.

Marginal means rather than a fitted model, deliberately. A regression over 1,850
correlated backtests on one regime would produce coefficients with impressive
standard errors and no external validity; a table of means at least cannot be
mistaken for more than it is.
"""

from __future__ import annotations

import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from app.strategy_lab.discovery.engine import Evaluation
from app.strategy_lab.discovery.space import Candidate

_ZERO = Decimal(0)


@dataclass(frozen=True, slots=True)
class Level:
    """One level of one design dimension, and how it did on average."""

    dimension: str
    level: str
    n_strategies: int
    mean_return_pct: Decimal
    median_return_pct: Decimal
    mean_profit_factor: Decimal | None
    mean_capture_pct: Decimal
    survivors: int
    survival_pct: Decimal


def _mean(values: Sequence[Decimal]) -> Decimal:
    return sum(values, _ZERO) / Decimal(len(values)) if values else _ZERO


def _median(values: Sequence[Decimal]) -> Decimal:
    if not values:
        return _ZERO
    return Decimal(str(statistics.median([float(v) for v in values])))


def attribute(
    pairs: Sequence[tuple[Candidate, Evaluation]],
    survivors: set[str],
) -> dict[str, list[Level]]:
    """Marginal performance per level, grouped by dimension.

    `survivors` is the set of strategy ids that passed the survival filters, so
    each level also reports what share of its strategies survived — which is
    often more informative than the mean, because a dimension can raise the
    average while making the tail worse.
    """
    grouped: dict[str, dict[str, list[tuple[Candidate, Evaluation]]]] = {}
    for candidate, evaluation in pairs:
        for dimension, level in candidate.factors().items():
            grouped.setdefault(dimension, {}).setdefault(level, []).append(
                (candidate, evaluation)
            )

    out: dict[str, list[Level]] = {}
    for dimension, levels in grouped.items():
        rows: list[Level] = []
        for level, members in levels.items():
            returns = [e.return_pct for _, e in members]
            factors = [e.profit_factor for _, e in members if e.profit_factor is not None]
            captures = [e.capture_pct for _, e in members]
            survived = sum(1 for c, _ in members if c.strategy_id in survivors)
            rows.append(
                Level(
                    dimension=dimension,
                    level=level,
                    n_strategies=len(members),
                    mean_return_pct=_mean(returns),
                    median_return_pct=_median(returns),
                    mean_profit_factor=_mean(factors) if factors else None,
                    mean_capture_pct=_mean(captures),
                    survivors=survived,
                    survival_pct=(
                        Decimal(survived) / Decimal(len(members)) * 100 if members else _ZERO
                    ),
                )
            )
        rows.sort(key=lambda r: r.mean_return_pct, reverse=True)
        out[dimension] = rows
    return out


@dataclass(frozen=True, slots=True)
class Comparison:
    """§21. Two strategies, measured two ways.

    The distinction the brief asks for: a strategy can look better because it
    *avoided* trades or because it *managed the same trades* better. Only the
    second is a management edge, and only the shared-entry view can see it.
    """

    left: str
    right: str
    all_eligible_left_pnl: Decimal
    all_eligible_right_pnl: Decimal
    shared_mints: int
    shared_left_pnl: Decimal
    shared_right_pnl: Decimal

    @property
    def management_edge(self) -> Decimal:
        """Difference on the tokens **both** entered. Selection cancels out."""
        return self.shared_left_pnl - self.shared_right_pnl

    @property
    def selection_edge(self) -> Decimal:
        """Whatever is left once management is removed: the entry decision."""
        total = self.all_eligible_left_pnl - self.all_eligible_right_pnl
        return total - self.management_edge


def compare(left: Evaluation, right: Evaluation) -> Comparison:
    shared = left.entered_mints() & right.entered_mints()
    return Comparison(
        left=left.strategy_id,
        right=right.strategy_id,
        all_eligible_left_pnl=sum((t.net_pnl for t in left.trades), _ZERO),
        all_eligible_right_pnl=sum((t.net_pnl for t in right.trades), _ZERO),
        shared_mints=len(shared),
        shared_left_pnl=sum(
            (t.net_pnl for t in left.trades if t.mint_address in shared), _ZERO
        ),
        shared_right_pnl=sum(
            (t.net_pnl for t in right.trades if t.mint_address in shared), _ZERO
        ),
    )
