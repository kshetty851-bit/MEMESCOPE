"""The MEMESCOPE Opportunity Score.

Combines the six dimensions into one 0-100 figure, and — more importantly —
reports how much of the model it was actually able to apply.

The mechanism mirrors `services/scoring` deliberately rather than inventing a
second one: declare every dimension with a weight, mark the ones with no data
source unavailable, renormalise across what remains, and charge the gap to
coverage. Two engines with two different notions of "confidence" would be a
worse outcome than either engine being slightly wrong.

Available weight sums to **0.85** in v1 — community is the missing 0.15 — so
coverage is capped at 85 and confidence below that. The Elite gate needs more
than the cap allows on evidence alone, which is why Elite additionally requires
several independent dimensions to agree.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from app.radar import community, health, momentum, technical
from app.radar.models import (
    DimensionResult,
    OpportunityResult,
    RadarDimension,
    RadarReason,
    RadarSeries,
)
from app.radar.normalise import clamp

MODEL_VERSION = "radar-v1"

#: Declared weights. Priors, not fitted parameters — published verbatim at
#: `GET /api/v1/radar/categories` so the claim is checkable rather than asserted.
WEIGHTS: dict[RadarDimension, Decimal] = {
    RadarDimension.MOMENTUM: Decimal("0.28"),
    RadarDimension.TECHNICAL: Decimal("0.22"),
    RadarDimension.LIQUIDITY_QUALITY: Decimal("0.18"),
    RadarDimension.ONCHAIN_HEALTH: Decimal("0.12"),
    RadarDimension.RISK: Decimal("0.05"),
    # Declared with real weight; no data source. See community.py.
    RadarDimension.COMMUNITY: Decimal("0.15"),
}

#: Below this share of applicable weight the result is not worth publishing.
MIN_APPLICABLE_WEIGHT = Decimal("0.30")

#: No single dimension may exceed this share of the final score, so one strong
#: axis cannot carry a token onto the Radar by itself.
MAX_SINGLE_SHARE = Decimal("0.40")

#: Observations behind a full-confidence reading.
CONFIDENT_OBSERVATIONS = Decimal(48)


def _evaluate_dimensions(series: RadarSeries) -> tuple[DimensionResult, ...]:
    return (
        momentum.evaluate(series),
        technical.evaluate(series),
        health.evaluate_liquidity_quality(series),
        health.evaluate_onchain_health(series),
        health.evaluate_risk(series),
        community.evaluate(series),
    )


def _renormalise(
    dimensions: tuple[DimensionResult, ...],
) -> tuple[dict[RadarDimension, Decimal], Decimal]:
    """Effective weights over the available dimensions, and applicable weight.

    Excess above the per-dimension cap is redistributed proportionally across
    the others rather than discarded, so the weights still sum to one and the
    score stays on a 0-100 scale.
    """
    available = [d for d in dimensions if d.available]
    applicable = sum((WEIGHTS[d.id] for d in available), Decimal(0))
    if applicable <= 0:
        return {}, Decimal(0)

    effective = {d.id: WEIGHTS[d.id] / applicable for d in available}

    # Cap, then redistribute the excess across the uncapped remainder.
    excess = Decimal(0)
    for dimension_id, weight in list(effective.items()):
        if weight > MAX_SINGLE_SHARE:
            excess += weight - MAX_SINGLE_SHARE
            effective[dimension_id] = MAX_SINGLE_SHARE

    if excess > 0:
        uncapped = {k: v for k, v in effective.items() if v < MAX_SINGLE_SHARE}
        pool = sum(uncapped.values(), Decimal(0))
        if pool > 0:
            for dimension_id, weight in uncapped.items():
                effective[dimension_id] = weight + excess * (weight / pool)

    return effective, applicable


def _confidence(coverage: Decimal, observations: int) -> Decimal:
    """Coverage tempered by how much history stood behind it.

    A token seen four times and a token seen two hundred times can produce the
    same score from the same coverage; they do not deserve the same confidence.
    Depth saturates rather than growing without bound — the two-hundredth
    observation adds nothing the fiftieth did not.
    """
    depth = clamp(Decimal(observations) / CONFIDENT_OBSERVATIONS, Decimal(0), Decimal(1))
    return clamp(coverage * depth, Decimal(0), Decimal(100))


def evaluate(series: RadarSeries, *, now: datetime) -> OpportunityResult | None:
    """Score one token. Returns `None` when too little of the model applies.

    Pure: a function of `(series, MODEL_VERSION, now)`. `now` is required rather
    than defaulted from a clock, which is what keeps backfill and shadow
    evaluation exact and these tests fixture-free.
    """
    dimensions = _evaluate_dimensions(series)
    effective, applicable = _renormalise(dimensions)

    if applicable < MIN_APPLICABLE_WEIGHT:
        return None

    declared = sum(WEIGHTS.values(), Decimal(0))
    coverage = clamp(applicable / declared * Decimal(100), Decimal(0), Decimal(100))

    score = Decimal(0)
    for dimension in dimensions:
        if dimension.available and dimension.score is not None:
            score += effective[dimension.id] * dimension.score

    score = clamp(score, Decimal(0), Decimal(100))
    confidence = _confidence(coverage, len(series))

    reasons: list[RadarReason] = []
    for dimension in dimensions:
        reasons.extend(dimension.reasons)

    return OpportunityResult(
        mint_address=series.mint_address,
        score=score,
        coverage=coverage,
        confidence=confidence,
        category=None,  # Assigned by detector.classify, which owns the gates.
        dimensions=dimensions,
        reasons=tuple(reasons),
        model_version=MODEL_VERSION,
        evaluated_at=now,
        observations=len(series),
    )


def effective_weights(
    dimensions: tuple[DimensionResult, ...],
) -> dict[RadarDimension, Decimal]:
    """Exposed for the API's explainability payload."""
    effective, _ = _renormalise(dimensions)
    return effective
