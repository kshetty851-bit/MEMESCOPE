"""Research Intelligence — where an hour of attention is likely to pay.

The sixth analyst, and the only one that reads the other five. It answers "what
should you look at first", never "what should you buy" — those are different
questions and only the first is one the platform can honestly take on, because
it knows nothing about anyone's position, cost basis or intent.

## Information value, not desirability

The distinction is load-bearing. A project ranks CRITICAL when it is *falling
apart*: a veto, an elevated Exit Watch or a clone warning on something a user
may already hold is among the most valuable things this product can surface.
Ranking by desirability would bury exactly those, and a test asserts a
deteriorating project outranks a healthy quiet one.

## Why it reads the others

Research value is a property of the ensemble, not of any single dimension. A
project where four analysts agree needs less investigation than one where two
disagree loudly — the second is where a human eye actually adds something.
Disagreement is therefore a *positive* contributor here, which is the opposite
of how it behaves in a scoring model.
"""

from __future__ import annotations

import enum
from decimal import Decimal

from app.analysts.base import (
    AnalystId,
    AnalystMeta,
    Evidence,
    Reading,
    RiskWarning,
    Severity,
)


class ResearchPriority(enum.StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


META = AnalystMeta(
    id=AnalystId.RESEARCH,
    name="Research Intelligence",
    question="If you have one hour today, does this deserve part of it?",
    operational=True,
    evidence_fields=("priority", "disagreement", "warning_count", "coverage"),
)

PRIORITY_MEANING: dict[ResearchPriority, str] = {
    ResearchPriority.CRITICAL: (
        "Something here needs looking at today — either a risk that could cost "
        "you, or a change large enough that yesterday's read is stale."
    ),
    ResearchPriority.HIGH: "Worth investigating before the rest of the board.",
    ResearchPriority.MEDIUM: "Worth a look if time allows.",
    ResearchPriority.LOW: "Nothing has changed enough to justify attention today.",
}


def analyse(readings: dict[AnalystId, Reading], *, change_count: int = 0) -> Reading:
    """Rank a project by expected research value, from the other five readings."""
    evidence: list[Evidence] = []
    warnings: list[RiskWarning] = []
    score = Decimal(0)

    critical = [
        w
        for reading in readings.values()
        for w in reading.warnings
        if w.severity is Severity.CRITICAL
    ]
    cautions = [
        w
        for reading in readings.values()
        for w in reading.warnings
        if w.severity is Severity.CAUTION
    ]

    # Stakes first. Unexamined risk is the expensive kind.
    if critical:
        score += Decimal(45)
        evidence.append(Evidence("Critical warnings", str(len(critical))))
    if cautions:
        score += min(Decimal(20), Decimal(len(cautions)) * Decimal(7))
        evidence.append(Evidence("Cautions", str(len(cautions))))

    # Newness. A stale read is worth less than a fresh one.
    if change_count > 0:
        score += min(Decimal(24), Decimal(change_count) * Decimal(8))
        evidence.append(Evidence("Material changes", str(change_count)))

    # Disagreement. Where the analysts diverge is where a human adds most.
    scored = [r.score for r in readings.values() if r.score is not None]
    disagreement = Decimal(0)
    if len(scored) >= 2:
        disagreement = max(scored) - min(scored)
        score += min(Decimal(15), disagreement / Decimal(6))
        evidence.append(
            Evidence(
                "Analyst disagreement",
                f"{disagreement:.0f} points",
                "The spread between the most and least favourable reading.",
            )
        )

    # Coverage. A project nothing can see is a poor use of an hour, however
    # interesting it looks.
    operational = [r for r in readings.values() if r.available]
    coverage = (
        Decimal(len(operational)) / Decimal(len(readings)) * 100 if readings else Decimal(0)
    )
    score += coverage / Decimal(8)
    evidence.append(
        Evidence("Analyst coverage", f"{len(operational)} of {len(readings)} could read this")
    )

    if coverage < 50:
        warnings.append(
            RiskWarning(
                code="RESEARCH_THIN_COVERAGE",
                severity=Severity.INFO,
                message=(
                    "Fewer than half the analysts could read this project, so any "
                    "conclusion rests on a narrow base."
                ),
            )
        )

    bounded = max(Decimal(0), min(Decimal(100), score))

    # A critical warning reaches CRITICAL on its own. Letting a high score
    # elsewhere dilute it would defeat the point of surfacing it.
    if critical:
        priority = ResearchPriority.CRITICAL
    elif bounded >= 55:
        priority = ResearchPriority.HIGH
    elif bounded >= 30:
        priority = ResearchPriority.MEDIUM
    else:
        priority = ResearchPriority.LOW

    return Reading(
        analyst=AnalystId.RESEARCH,
        score=bounded,
        confidence=min(Decimal(90), Decimal(40) + coverage / Decimal(2)),
        reason=PRIORITY_MEANING[priority],
        evidence=(Evidence("Research priority", priority.value.title()), *evidence),
        warnings=tuple(warnings),
    )
