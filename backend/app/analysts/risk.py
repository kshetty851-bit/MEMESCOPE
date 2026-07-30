"""Risk Intelligence — reasons *not* to investigate.

The only analyst whose job is to argue against its subject. Every other
specialist looks for what is working; this one looks for what would make
looking a waste of time, or worse.

## Why a dedicated adversary

Five analysts hunting for signal will find some in almost anything — that is
what looking for signal does. Without a specialist whose success condition is
finding a reason to walk away, the ensemble drifts toward always having
something encouraging to say, and a platform that never discourages is not
assessing anything.

So this analyst's score is inverted relative to the others: **higher is safer**.
The convention is stated because a mixed one inside an ensemble is how sign
errors ship, and `radar/scorer.py` already learned that lesson.

## What it cannot see

Contract safety, holder concentration and wallet behaviour are not collected.
This analyst therefore reports a **floor on risk, never a clearance** — the
absence of a warning here means nothing was found in what could be read, not
that nothing is there. That sentence is carried on every reading rather than
left in documentation.
"""

from __future__ import annotations

from decimal import Decimal

from app.analysts.base import AnalystId, AnalystMeta, Evidence, Reading, RiskWarning, Severity
from app.radar.health import evaluate_risk
from app.radar.models import RadarSeries

META = AnalystMeta(
    id=AnalystId.RISK,
    name="Risk Intelligence",
    question="What would make this a poor use of research time?",
    operational=True,
    evidence_fields=("liquidity_floor", "veto", "exit_severity", "clone_risk"),
)

FLOOR_DISCLAIMER = (
    "Contract safety, holder concentration and wallet behaviour are not "
    "collected, so this is a floor on risk and never a clearance."
)


def analyse(
    series: RadarSeries,
    *,
    has_veto: bool = False,
    exit_severity: str | None = None,
    clone_risk: str | None = None,
    sharing_name: int = 1,
) -> Reading:
    dimension = evaluate_risk(series)

    warnings: list[RiskWarning] = []
    evidence: list[Evidence] = []
    penalty = Decimal(0)

    if has_veto:
        penalty += Decimal(50)
        warnings.append(
            RiskWarning(
                code="RISK_VETO",
                severity=Severity.CRITICAL,
                message=(
                    "The risk gate vetoed this token. Its score is capped outright, "
                    "regardless of how strong every other signal is."
                ),
            )
        )
        evidence.append(Evidence("Risk gate", "Vetoed"))

    if exit_severity == "elevated":
        penalty += Decimal(35)
        warnings.append(
            RiskWarning(
                code="RISK_EXIT_ELEVATED",
                severity=Severity.CRITICAL,
                message=(
                    "Exit Watch is at elevated: several independent signals are "
                    "deteriorating at once. It is a warning, never a sell signal."
                ),
            )
        )
    elif exit_severity == "watch":
        penalty += Decimal(15)
        warnings.append(
            RiskWarning(
                code="RISK_EXIT_WATCH",
                severity=Severity.CAUTION,
                message="Exit Watch has begun reporting deterioration.",
            )
        )
    if exit_severity:
        evidence.append(Evidence("Exit Watch", exit_severity.title()))

    if clone_risk == "high":
        penalty += Decimal(30)
        warnings.append(
            RiskWarning(
                code="RISK_CLONE_HIGH",
                severity=Severity.CRITICAL,
                message=(
                    f"{sharing_name} tokens share this name and this one is not the "
                    "earliest. Buying the wrong one is a total loss with no market "
                    "move required."
                ),
            )
        )
    elif clone_risk == "moderate":
        penalty += Decimal(12)
        warnings.append(
            RiskWarning(
                code="RISK_CLONE_MODERATE",
                severity=Severity.CAUTION,
                message="Earlier tokens already used this name.",
            )
        )
    if clone_risk:
        evidence.append(Evidence("Clone risk", clone_risk.title()))

    # The Radar's own risk dimension, where it could be read. Higher is safer
    # there too, so it composes without a sign flip.
    dimension_score = dimension.score if dimension.available else None
    readable = dimension_score is not None
    base = dimension_score if dimension_score is not None else Decimal(50)
    if not readable:
        warnings.append(
            RiskWarning(
                code="RISK_STRUCTURE_UNREADABLE",
                severity=Severity.INFO,
                message=(
                    "Pool structure could not be read, so the structural half of "
                    "this assessment defaults to neutral rather than safe."
                ),
            )
        )

    score = max(Decimal(0), min(Decimal(100), base - penalty))

    if warnings:
        worst = max(w.severity for w in warnings)
        reason = (
            f"{len(warnings)} reason{'s' if len(warnings) != 1 else ''} not to "
            f"investigate, the most serious being {worst.value}. {FLOOR_DISCLAIMER}"
        )
    else:
        reason = f"Nothing disqualifying was found in what could be read. {FLOOR_DISCLAIMER}"

    # Confidence here is confidence in the *warnings*, which is high when they
    # fire — a veto is a fact, not an inference. It is low when nothing fires,
    # because silence across four uncollected signals is weak evidence.
    confidence = Decimal(85) if warnings else Decimal(35)

    return Reading(
        analyst=AnalystId.RISK,
        score=score,
        confidence=confidence,
        reason=reason,
        evidence=tuple(evidence),
        warnings=tuple(warnings),
    )
