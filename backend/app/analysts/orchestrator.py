"""Radar orchestration — six analysts, one verdict.

## What orchestration actually has to do

Running six analysts is trivial. The work is in what happens when they
disagree, and the rules below are the substance of Phase 15.

**Conflict resolution is asymmetric, on purpose.** A critical risk warning
overrides every favourable reading. If Liquidity says 90 and Risk says the
token is vetoed, the verdict is not 70-ish — it is "vetoed, and here is what
liquidity looked like anyway". Averaging a veto away is precisely how a
platform ends up recommending a rug with a confident-looking number attached.

**Unavailable is not zero.** An analyst with no data source is excluded from
the combination and reported separately. Scoring Holder Intelligence as 0 would
drag every project down equally and tell a user nothing, while looking like a
measurement.

**Confidence is capped by coverage.** With one of six analysts dark, the
ensemble cannot be more certain than its blind spots allow. Coverage caps the
combined confidence rather than merely reducing it, so the ceiling is visible.

## Determinism

Pure. Given the same readings, the same verdict, every time — no clock, no
randomness, no I/O. The orchestrator is the one place that could smuggle in a
hidden weighting, so its weights are declared as a module constant and
published through `model()`.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.analysts import holders, lifecycle, liquidity, momentum, research, risk
from app.analysts.base import AnalystId, AnalystMeta, Reading, RiskWarning, Severity
from app.analysts.research import ResearchPriority
from app.radar.models import RadarSeries

#: Declared priors, not fitted parameters — the same posture the scoring engine
#: takes about its own weights. Research is absent: it reads the others and
#: ranks attention, so folding it back in would double-count them.
WEIGHTS: dict[AnalystId, Decimal] = {
    AnalystId.LIQUIDITY: Decimal("0.30"),
    AnalystId.MOMENTUM: Decimal("0.28"),
    AnalystId.RISK: Decimal("0.24"),
    AnalystId.LIFECYCLE: Decimal("0.10"),
    AnalystId.HOLDERS: Decimal("0.08"),
}

ANALYSTS: tuple[AnalystMeta, ...] = (
    liquidity.META,
    momentum.META,
    holders.META,
    lifecycle.META,
    risk.META,
    research.META,
)


@dataclass(frozen=True, slots=True)
class Verdict:
    """The orchestrator's combined output for one project."""

    mint_address: str
    readings: dict[AnalystId, Reading]
    #: Weighted combination over available analysts only. None when none could read.
    score: Decimal | None
    #: Capped by coverage — the ensemble cannot outrun its blind spots.
    confidence: Decimal | None
    #: Share of declared weight that could actually be applied, 0-100.
    coverage: Decimal
    mission_state: lifecycle.MissionState
    priority: ResearchPriority
    #: Every warning any analyst raised, worst first.
    warnings: tuple[RiskWarning, ...]
    #: One sentence: the headline of the whole assessment.
    summary: str
    #: Names of analysts that had no data source for this project.
    unavailable: tuple[str, ...]


def model() -> dict[str, object]:
    """Publish the ensemble, so its claims are checkable rather than asserted."""
    return {
        "weights": {a.value: str(w) for a, w in WEIGHTS.items()},
        "declared_weight_total": str(sum(WEIGHTS.values())),
        "available_weight_total": str(
            sum(w for a, w in WEIGHTS.items() if a is not AnalystId.HOLDERS)
        ),
        "analysts": [
            {
                "id": meta.id.value,
                "name": meta.name,
                "question": meta.question,
                "operational": meta.operational,
                "unavailable_reason": meta.unavailable_reason,
            }
            for meta in ANALYSTS
        ],
    }


def assess(
    series: RadarSeries,
    *,
    current_multiple: Decimal | None = None,
    peak_multiple: Decimal | None = None,
    days_since_detection: Decimal = Decimal(0),
    exit_severity: str | None = None,
    has_veto: bool = False,
    clone_risk: str | None = None,
    sharing_name: int = 1,
    change_count: int = 0,
) -> Verdict:
    """Run every analyst and combine them. Pure."""
    observations = len(series.observations)

    readings: dict[AnalystId, Reading] = {
        AnalystId.LIQUIDITY: liquidity.analyse(series),
        AnalystId.MOMENTUM: momentum.analyse(series),
        AnalystId.HOLDERS: holders.analyse(series),
        AnalystId.LIFECYCLE: lifecycle.analyse(
            current_multiple=current_multiple,
            peak_multiple=peak_multiple,
            days_since_detection=days_since_detection,
            exit_severity=exit_severity,
            has_veto=has_veto,
            observations=observations,
        ),
        AnalystId.RISK: risk.analyse(
            series,
            has_veto=has_veto,
            exit_severity=exit_severity,
            clone_risk=clone_risk,
            sharing_name=sharing_name,
        ),
    }

    # Research reads the other five, so it runs last and is not weighted back in.
    readings[AnalystId.RESEARCH] = research.analyse(readings, change_count=change_count)

    combined, coverage = _combine(readings)

    warnings = _ordered_warnings(readings)
    state = lifecycle.classify(
        current_multiple=current_multiple,
        peak_multiple=peak_multiple,
        days_since_detection=days_since_detection,
        exit_severity=exit_severity,
        has_veto=has_veto,
        observations=observations,
    )
    priority = _priority_of(readings[AnalystId.RESEARCH])

    # Confidence is the mean of what each available analyst claimed, capped by
    # coverage. Six analysts at 90% with two dark is not 90% certain.
    confidences = [r.confidence for r in readings.values() if r.confidence is not None]
    confidence = (
        min(coverage, sum(confidences) / Decimal(len(confidences))) if confidences else None
    )

    return Verdict(
        mint_address=series.mint_address,
        readings=readings,
        score=combined,
        confidence=confidence,
        coverage=coverage,
        mission_state=state,
        priority=priority,
        warnings=warnings,
        summary=_summarise(state, priority, warnings, coverage),
        unavailable=tuple(
            meta.name
            for meta in ANALYSTS
            if not readings[meta.id].available and meta.id is not AnalystId.RESEARCH
        ),
    )


def _combine(readings: dict[AnalystId, Reading]) -> tuple[Decimal | None, Decimal]:
    """Weighted mean over available analysts, renormalised.

    Unavailable analysts are dropped from both numerator and denominator rather
    than contributing zero, and the weight they would have carried is reported
    as lost coverage.
    """
    applied = Decimal(0)
    total = Decimal(0)

    for analyst, weight in WEIGHTS.items():
        reading = readings.get(analyst)
        if reading is None or reading.score is None:
            continue
        applied += weight
        total += weight * reading.score

    declared = sum(WEIGHTS.values())
    coverage = applied / declared * 100 if declared else Decimal(0)

    if applied == 0:
        return None, coverage

    return total / applied, coverage


def _ordered_warnings(readings: dict[AnalystId, Reading]) -> tuple[RiskWarning, ...]:
    """Every warning, worst first, deduplicated by code."""
    rank = {Severity.CRITICAL: 0, Severity.CAUTION: 1, Severity.INFO: 2}
    seen: dict[str, RiskWarning] = {}
    for reading in readings.values():
        for warning in reading.warnings:
            seen.setdefault(warning.code, warning)
    return tuple(sorted(seen.values(), key=lambda w: rank[w.severity]))


def _priority_of(reading: Reading) -> ResearchPriority:
    for evidence in reading.evidence:
        if evidence.label == "Research priority":
            return ResearchPriority(evidence.value.lower())
    return ResearchPriority.LOW


def _summarise(
    state: lifecycle.MissionState,
    priority: ResearchPriority,
    warnings: tuple[RiskWarning, ...],
    coverage: Decimal,
) -> str:
    """The headline sentence.

    Risk leads when it exists. A summary that opened with a favourable reading
    and mentioned the veto afterwards would be technically complete and
    practically misleading.
    """
    critical = [w for w in warnings if w.severity is Severity.CRITICAL]
    label = state.value.replace("_", " ").title()

    if critical:
        return (
            f"{label}, with {len(critical)} critical "
            f"{'warning' if len(critical) == 1 else 'warnings'}. "
            f"Research priority {priority.value}."
        )

    if coverage < 50:
        return (
            f"{label}, but fewer than half the analysts could read this project — "
            f"treat any conclusion as provisional. Research priority {priority.value}."
        )

    return f"{label}. Research priority {priority.value}."
