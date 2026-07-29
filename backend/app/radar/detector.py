"""Category gates: does this belong on the Radar, and as what?

The scorer produces a number. This decides whether that number means anything
worth showing a user, and which of the five categories describes it.

Two rules shape every gate here:

**Market cap is never a qualification.** A $60k project with growing liquidity,
expanding volume and clean structure is a better opportunity than a $500k launch
with none of those, and the gates below contain no market-cap term at all. Size
appears in the API only as something to display.

**Elite is rare by construction, not by luck.** It requires several *independent*
dimensions to agree, not one very high score. A single strong axis is capped by
the scorer precisely so it cannot manufacture an Elite on its own.
"""

from __future__ import annotations

from decimal import Decimal

from app.radar.models import (
    OpportunityResult,
    RadarCategory,
    RadarDimension,
    RadarReason,
)

#: Nothing below this enters the Radar at all, whatever its category.
MIN_RADAR_SCORE = Decimal(55)

#: A reading built on too little of the model is not published, however high.
MIN_RADAR_CONFIDENCE = Decimal(25)

#: Risk is scored so that higher is safer. Below this a token is excluded
#: regardless of how good everything else looks — the Radar surfacing a project
#: whose pool cannot support an exit would be the single worst thing it could do.
MIN_RISK_FLOOR = Decimal(30)

#: Per-category thresholds. Priors, published at `/api/v1/radar/categories`.
BREAKOUT_TECHNICAL = Decimal(70)
EARLY_MOMENTUM_MOMENTUM = Decimal(65)
UNDERVALUED_HEALTH = Decimal(65)
UNDERVALUED_MOMENTUM_CEILING = Decimal(60)

ELITE_SCORE = Decimal(78)
ELITE_CONFIDENCE = Decimal(45)
#: How many dimensions must independently clear `ELITE_DIMENSION_FLOOR`.
ELITE_AGREEING_DIMENSIONS = 4
ELITE_DIMENSION_FLOOR = Decimal(65)


def _score_of(result: OpportunityResult, dimension: RadarDimension) -> Decimal | None:
    found = result.dimension(dimension)
    if found is None or not found.available:
        return None
    return found.score


def _agreeing(result: OpportunityResult, floor: Decimal) -> int:
    return sum(
        1
        for dimension in result.dimensions
        if dimension.available and dimension.score is not None and dimension.score >= floor
    )


def qualifies(result: OpportunityResult) -> bool:
    """Whether the token belongs on the Radar at all."""
    if result.score < MIN_RADAR_SCORE:
        return False
    if result.confidence < MIN_RADAR_CONFIDENCE:
        return False

    # An unknown risk reading is not treated as a pass. Where the platform
    # cannot see the danger it declines to advertise the opportunity.
    risk = _score_of(result, RadarDimension.RISK)
    return risk is not None and risk >= MIN_RISK_FLOOR


def classify(result: OpportunityResult) -> RadarCategory | None:
    """Which category describes this opportunity, if any.

    Ordered most-specific first. Elite outranks everything; a project that would
    also read as a breakout is reported as Elite because that is the more
    informative statement.
    """
    if not qualifies(result):
        return None

    momentum = _score_of(result, RadarDimension.MOMENTUM)
    tech = _score_of(result, RadarDimension.TECHNICAL)
    onchain = _score_of(result, RadarDimension.ONCHAIN_HEALTH)
    liquidity = _score_of(result, RadarDimension.LIQUIDITY_QUALITY)

    # --- Elite ---------------------------------------------------------------
    if (
        result.score >= ELITE_SCORE
        and result.confidence >= ELITE_CONFIDENCE
        and _agreeing(result, ELITE_DIMENSION_FLOOR) >= ELITE_AGREEING_DIMENSIONS
    ):
        return RadarCategory.ELITE

    # --- Breakout ------------------------------------------------------------
    #
    # Technical structure alone is not a breakout: without volume behind it the
    # move is a drift. Momentum carries that confirmation, so both are required.
    if (
        tech is not None
        and tech >= BREAKOUT_TECHNICAL
        and RadarReason.RESISTANCE_BROKEN in result.reasons
        and momentum is not None
        and momentum >= Decimal(55)
    ):
        return RadarCategory.BREAKOUT

    # --- Early momentum ------------------------------------------------------
    if momentum is not None and momentum >= EARLY_MOMENTUM_MOMENTUM:
        return RadarCategory.EARLY_MOMENTUM

    # --- Undervalued ---------------------------------------------------------
    #
    # Sound on-chain structure that the market has not yet moved on. The
    # momentum *ceiling* is the point: once momentum arrives it is no longer
    # undervalued, it is early momentum.
    if (
        onchain is not None
        and liquidity is not None
        and onchain >= UNDERVALUED_HEALTH
        and liquidity >= UNDERVALUED_HEALTH
        and (momentum is None or momentum <= UNDERVALUED_MOMENTUM_CEILING)
    ):
        return RadarCategory.UNDERVALUED

    # --- Strong community ----------------------------------------------------
    #
    # Unreachable in v1: the dimension has no data source, so it can never
    # satisfy a gate. Left in the ladder rather than deleted, so that adding a
    # social provider turns it on without a structural change — and so the
    # reachability report can state honestly that it is currently unreachable.

    # Qualified but uncategorised: still a Radar entry, still tracked.
    return RadarCategory.EARLY_MOMENTUM


def category_is_reachable(category: RadarCategory) -> bool:
    """Whether the current model can ever award this category.

    Published by the API. A category that silently never appears is
    indistinguishable from one nothing has qualified for yet, and the difference
    matters to anyone judging the platform's track record.
    """
    return category is not RadarCategory.STRONG_COMMUNITY
