"""Strategy scorecards: flags, a verdict code and a robustness score.

The verdict never says "profitable". A strategy whose balance rose is still
`no_edge_detected` when its per-trade expectancy in R is not positive, because
a rising balance can come from a few oversized winners or from compounding.
Missing evidence (no out-of-sample run, too few trades) lands in
`inconclusive`, never in `candidate_edge`.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from app.labs.forex.metrics import Metrics
from app.labs.forex.research import StabilityReport

MIN_FULL_TRADES = 30
MIN_OOS_TRADES = 15
MAX_ACCEPTABLE_DRAWDOWN_PCT = 30.0
MIN_T_STAT = 2.0
#: Development expectancy (R) above which an out-of-sample collapse reads as overfitting.
STRONG_DEV_EXPECTANCY_R = 0.1
#: R per trade that earns full marks in the robustness score.
FULL_MARKS_R = 0.5

NEGATIVE_EXPECTANCY = "negative_expectancy"
INSUFFICIENT_TRADES = "insufficient_trades"
EXCESSIVE_DRAWDOWN = "excessive_drawdown"
COST_SENSITIVE = "cost_sensitive"
POOR_OUT_OF_SAMPLE = "poor_out_of_sample"
POSSIBLE_OVERFITTING = "possible_overfitting"
NOT_SIGNIFICANT = "not_significant"
NO_OUT_OF_SAMPLE = "no_out_of_sample"


@dataclass(frozen=True, slots=True)
class Scorecard:
    name: str
    full: Metrics
    development: Metrics | None
    out_of_sample: Metrics | None
    stressed: Metrics | None
    stability: StabilityReport | None
    flags: tuple[str, ...]
    robustness_score: float | None
    verdict_code: str


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _r_component(m: Metrics | None) -> float:
    if m is None or m.expectancy_r is None:
        return 0.0
    return _clamp(m.expectancy_r / FULL_MARKS_R, -1.0, 1.0)


def _robustness(
    full: Metrics,
    oos: Metrics | None,
    stressed: Metrics | None,
    stability: StabilityReport | None,
) -> float:
    """Weighted evidence score, 100 x:

        0.50 * clamp(OOS expectancy_r / 0.5R, -1, 1)
      + 0.20 * clamp(stressed (2x costs) expectancy_r / 0.5R, -1, 1)
      + 0.15 * (1 - max drawdown % / 100)           [full run]
      + 0.15 * (neighbours_positive_pct / 100)      [parameter stability]

    A missing component contributes zero: absent evidence earns nothing and is
    never filled in with an estimate. Range is about -70 to 100.
    """
    dd = 1.0 - _clamp(full.max_drawdown_pct, 0.0, 100.0) / 100.0
    neigh = 0.0
    if stability is not None and stability.neighbours_positive_pct is not None:
        neigh = stability.neighbours_positive_pct / 100.0
    return 100.0 * (
        0.50 * _r_component(oos) + 0.20 * _r_component(stressed) + 0.15 * dd + 0.15 * neigh
    )


def evaluate(
    name: str,
    *,
    full: Metrics,
    development: Metrics | None,
    out_of_sample: Metrics | None,
    stressed: Metrics | None,
    stability: StabilityReport | None,
) -> Scorecard:
    flags: list[str] = []
    e_full = full.expectancy_r

    if e_full is not None and e_full <= 0:
        flags.append(NEGATIVE_EXPECTANCY)

    insufficient = full.total_trades < MIN_FULL_TRADES or (
        out_of_sample is not None and out_of_sample.total_trades < MIN_OOS_TRADES
    )
    if insufficient:
        flags.append(INSUFFICIENT_TRADES)

    if full.max_drawdown_pct > MAX_ACCEPTABLE_DRAWDOWN_PCT:
        flags.append(EXCESSIVE_DRAWDOWN)

    if stressed is not None and e_full is not None and e_full > 0:
        collapsed = stressed.expectancy_r is None or stressed.expectancy_r <= 0
        eroded = stressed.net_return_pct < 0.5 * full.net_return_pct
        if collapsed or eroded:
            flags.append(COST_SENSITIVE)

    poor_oos = False
    if out_of_sample is not None and out_of_sample.expectancy_r is not None:
        e_oos = out_of_sample.expectancy_r
        e_dev = development.expectancy_r if development is not None else None
        poor_oos = e_oos <= 0 or (e_dev is not None and e_dev > 0 and e_oos < 0.5 * e_dev)
        strong_dev = e_dev is not None and e_dev > STRONG_DEV_EXPECTANCY_R
    else:
        strong_dev = False
    if poor_oos:
        flags.append(POOR_OUT_OF_SAMPLE)

    if (stability is not None and stability.isolated_peak) or (poor_oos and strong_dev):
        flags.append(POSSIBLE_OVERFITTING)

    if full.expectancy_t_stat is None or full.expectancy_t_stat < MIN_T_STAT:
        flags.append(NOT_SIGNIFICANT)

    if out_of_sample is None:
        flags.append(NO_OUT_OF_SAMPLE)

    if NEGATIVE_EXPECTANCY in flags or POOR_OUT_OF_SAMPLE in flags:
        verdict = "no_edge_detected"
    elif flags:
        verdict = "inconclusive"
    else:
        verdict = "candidate_edge"

    score = None if insufficient else _robustness(full, out_of_sample, stressed, stability)
    return Scorecard(
        name,
        full,
        development,
        out_of_sample,
        stressed,
        stability,
        tuple(flags),
        score,
        verdict,
    )


def rank(cards: Sequence[Scorecard]) -> list[Scorecard]:
    """Highest robustness first; unscored cards last; ties broken by name."""
    return sorted(
        cards,
        key=lambda c: (
            c.robustness_score is None,
            -(c.robustness_score if c.robustness_score is not None else 0.0),
            c.name,
        ),
    )
