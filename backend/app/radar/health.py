"""On-chain health, liquidity quality and risk.

Three dimensions that read the *current* structure of a pool rather than its
direction over time. Momentum asks "is this improving?"; these ask "is what
exists sound?" — a project can be improving from a dangerous base, and the
Radar has to be able to say both things at once.
"""

from __future__ import annotations

from decimal import Decimal

from app.radar.models import (
    DimensionResult,
    RadarDimension,
    RadarReason,
    RadarSeries,
)
from app.radar.normalise import clamp, mean, sub_series

#: Below this, a pool cannot absorb even a small position without moving hard.
#: Stated prior, published in the model document, not a fitted parameter.
THIN_LIQUIDITY_USD = Decimal(5_000)
CRITICAL_LIQUIDITY_USD = Decimal(1_000)

#: Liquidity as a share of market cap. Very low means the float is unbacked.
HEALTHY_LIQUIDITY_RATIO = Decimal("0.08")


def _latest_with(series: RadarSeries, attribute: str) -> Decimal | None:
    """Most recent non-null value for an attribute.

    The provider intermittently omits fields; falling back through the series
    is the difference between "we do not know" and "we did not look".
    """
    for observation in reversed(series.observations):
        value: Decimal | None = getattr(observation, attribute)
        if value is not None:
            return value
    return None


def evaluate_liquidity_quality(series: RadarSeries) -> DimensionResult:
    """How well the pool supports the valuation it carries."""
    liquidity = _latest_with(series, "liquidity_usd")
    market_cap = _latest_with(series, "market_cap")

    if liquidity is None:
        # The dominant real case: DexScreener reports no liquidity for
        # bonding-curve pools, which is most brand-new tokens. Declared
        # unavailable rather than scored as zero — those are different claims.
        return DimensionResult.unavailable(
            RadarDimension.LIQUIDITY_QUALITY,
            reason=RadarReason.SIGNAL_NOT_AVAILABLE,
        )

    reasons: list[RadarReason] = []

    # Absolute depth, saturating at $100k — beyond that more depth stops
    # differentiating opportunities at this end of the market.
    depth_score = clamp(liquidity / Decimal(100_000) * Decimal(100), Decimal(0), Decimal(100))
    if liquidity <= CRITICAL_LIQUIDITY_USD:
        reasons.append(RadarReason.LIQUIDITY_CRITICALLY_THIN)
    elif liquidity <= THIN_LIQUIDITY_USD:
        reasons.append(RadarReason.LIQUIDITY_THIN_FOR_SIZE)

    parts: list[tuple[Decimal, Decimal]] = [(Decimal("0.6"), depth_score)]

    ratio: Decimal | None = None
    if market_cap is not None and market_cap > 0:
        ratio = liquidity / market_cap
        ratio_score = clamp(
            ratio / HEALTHY_LIQUIDITY_RATIO * Decimal(100), Decimal(0), Decimal(100)
        )
        parts.append((Decimal("0.4"), ratio_score))
        if ratio >= HEALTHY_LIQUIDITY_RATIO:
            reasons.append(RadarReason.LIQUIDITY_DEEP_FOR_SIZE)
        elif ratio <= HEALTHY_LIQUIDITY_RATIO / Decimal(4):
            reasons.append(RadarReason.LIQUIDITY_THIN_FOR_SIZE)

    total = sum((weight for weight, _ in parts), Decimal(0))
    score = sum((weight * value for weight, value in parts), Decimal(0)) / total

    return DimensionResult(
        id=RadarDimension.LIQUIDITY_QUALITY,
        available=True,
        score=clamp(score, Decimal(0), Decimal(100)),
        reasons=tuple(reasons),
        raw={"liquidity_usd": liquidity, "liquidity_to_mcap": ratio},
    )


def evaluate_onchain_health(series: RadarSeries) -> DimensionResult:
    """Whether trading activity is proportionate to the pool behind it."""
    liquidity = _latest_with(series, "liquidity_usd")
    volume = _latest_with(series, "volume_24h")

    if liquidity is None or volume is None:
        return DimensionResult.unavailable(
            RadarDimension.ONCHAIN_HEALTH, reason=RadarReason.SIGNAL_NOT_AVAILABLE
        )

    reasons: list[RadarReason] = []

    # Turnover: daily volume against pool depth. Some turnover is life; a great
    # deal of it against a thin pool is usually the same few dollars going round
    # rather than genuine interest.
    turnover: Decimal | None = None
    if liquidity > 0:
        turnover = volume / liquidity
        if turnover >= Decimal(20):
            # Extreme turnover against thin liquidity is a warning, not a win.
            reasons.append(RadarReason.VOLUME_WITHOUT_LIQUIDITY)
            turnover_score = Decimal(25)
        elif turnover >= Decimal("0.5"):
            reasons.append(RadarReason.TURNOVER_HEALTHY)
            turnover_score = Decimal(85)
        else:
            turnover_score = clamp(
                turnover / Decimal("0.5") * Decimal(70), Decimal(0), Decimal(70)
            )
    else:
        turnover_score = Decimal(0)

    # Consistency: a pool that is present in every observation is a healthier
    # thing than one that appears and disappears.
    observed = sub_series(series.observations, 24)
    present = [Decimal(1) if o.liquidity_usd is not None else Decimal(0) for o in observed]
    consistency = mean(present) or Decimal(0)
    consistency_score = consistency * Decimal(100)

    score = turnover_score * Decimal("0.65") + consistency_score * Decimal("0.35")

    return DimensionResult(
        id=RadarDimension.ONCHAIN_HEALTH,
        available=True,
        score=clamp(score, Decimal(0), Decimal(100)),
        reasons=tuple(reasons),
        raw={"turnover": turnover, "observation_consistency": consistency},
    )


def evaluate_risk(series: RadarSeries) -> DimensionResult:
    """Structural danger in what is observable.

    **Scored so that higher is safer**, matching every other dimension, because
    a mixed convention inside one weighted sum is how sign errors get shipped.

    Holder concentration, mint and freeze authority and LP burn are the signals
    that would make this authoritative, and none of them are collected. What
    remains is liquidity structure, which catches the crudest failures and is
    honest about being partial — the Radar's risk reading is a floor, not a
    clearance.
    """
    liquidity = _latest_with(series, "liquidity_usd")
    volume = _latest_with(series, "volume_24h")

    if liquidity is None:
        return DimensionResult.unavailable(
            RadarDimension.RISK, reason=RadarReason.SIGNAL_NOT_AVAILABLE
        )

    reasons: list[RadarReason] = []
    score = Decimal(70)

    if liquidity <= CRITICAL_LIQUIDITY_USD:
        score = Decimal(10)
        reasons.append(RadarReason.LIQUIDITY_CRITICALLY_THIN)
    elif liquidity <= THIN_LIQUIDITY_USD:
        score = Decimal(40)
        reasons.append(RadarReason.LIQUIDITY_THIN_FOR_SIZE)
    else:
        score = clamp(
            Decimal(55) + liquidity / Decimal(200_000) * Decimal(45),
            Decimal(55),
            Decimal(100),
        )

    if volume is not None and liquidity > 0 and volume / liquidity >= Decimal(20):
        # Churning far more than the pool holds. Halved rather than vetoed:
        # this dimension describes, the category gate decides.
        score = score / Decimal(2)
        if RadarReason.VOLUME_WITHOUT_LIQUIDITY not in reasons:
            reasons.append(RadarReason.VOLUME_WITHOUT_LIQUIDITY)

    return DimensionResult(
        id=RadarDimension.RISK,
        available=True,
        score=clamp(score, Decimal(0), Decimal(100)),
        reasons=tuple(reasons),
        raw={"liquidity_usd": liquidity},
    )
