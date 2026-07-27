"""Grade bands and the Elite gate.

Grades exist so the product has a stable label to render. A score drifting from
68.2 to 69.1 should not look like news, and a band absorbs that while the raw
number stays available underneath.

`ScoreGrade` is imported from the persistence layer rather than redefined here.
That is a deliberate coupling: the grade is written to a native Postgres enum,
and a parallel definition would eventually drift from the column it is stored in.
No database access is implied - the import is an enum, not a session.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from itertools import pairwise

from app.models.score import ScoreGrade
from app.services.scoring.normalisers import ZERO


@dataclass(frozen=True, slots=True)
class GradeBands:
    """Lower bound of each band. Product-visible, hence configurable per model.

    Boundaries are still an open product question in the design (section 21.1);
    keeping them in `ModelConfig` means settling them is a config change, not a
    code change, and a change is visible in the model version.
    """

    weak_from: Decimal = Decimal(30)
    watch_from: Decimal = Decimal(50)
    strong_from: Decimal = Decimal(65)
    high_conviction_from: Decimal = Decimal(80)

    def __post_init__(self) -> None:
        bounds = (
            self.weak_from,
            self.watch_from,
            self.strong_from,
            self.high_conviction_from,
        )
        if any(later <= earlier for earlier, later in pairwise(bounds)):
            raise ValueError("grade bands must ascend strictly")
        if self.weak_from < ZERO:
            raise ValueError("grade bands must be non-negative")


@dataclass(frozen=True, slots=True)
class EliteGate:
    """What it takes to earn gold.

    Deliberately hard to satisfy. The design bible reserves gold exclusively for
    Elite events, and gold that appears often is not gold. Note that
    `min_evidence` is above v1's arithmetic ceiling of 65, so **no token can be
    certified Elite until the Day 6 components land** - that is the intended
    outcome, not an oversight to tune away.
    """

    min_score: Decimal = Decimal(85)
    min_evidence: Decimal = Decimal(70)
    max_risk_penalty: Decimal = Decimal("0.2")
    min_liquidity_usd: Decimal = Decimal(25000)
    sustain_evaluations: int = 3


def grade_for(score: Decimal, bands: GradeBands) -> ScoreGrade:
    """Map a 0-100 score onto its band."""
    if score < bands.weak_from:
        return ScoreGrade.CRITICAL
    if score < bands.watch_from:
        return ScoreGrade.WEAK
    if score < bands.strong_from:
        return ScoreGrade.WATCH
    if score < bands.high_conviction_from:
        return ScoreGrade.STRONG
    return ScoreGrade.HIGH_CONVICTION


def qualifies_for_elite(
    *,
    score: Decimal,
    evidence: Decimal,
    risk_penalty: Decimal,
    liquidity_usd: Decimal | None,
    vetoed: bool,
    gate: EliteGate,
) -> bool:
    """Whether this single evaluation meets the bar. Says nothing about sustain."""
    if vetoed:
        return False
    if liquidity_usd is None or liquidity_usd < gate.min_liquidity_usd:
        return False
    return (
        score >= gate.min_score
        and evidence >= gate.min_evidence
        and risk_penalty <= gate.max_risk_penalty
    )


def elite_status(*, qualifies: bool, prior_streak: int, gate: EliteGate) -> tuple[bool, int]:
    """Advance the sustain streak and decide certification.

    Returns `(is_elite, streak)`. The prior streak is an input rather than
    internal state: it comes from stored history, which is what makes the
    outcome replay-reproducible instead of dependent on how many times the
    engine happened to run.
    """
    streak = prior_streak + 1 if qualifies else 0
    return streak >= gate.sustain_evaluations, streak
