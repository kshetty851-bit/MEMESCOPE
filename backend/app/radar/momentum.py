"""Momentum: is this project getting stronger?

Reads the direction and slope of liquidity, volume, price and trade balance
across the observation window. Deliberately *not* a price predictor — it
measures what has already changed, which is the only thing the data can support.

All arithmetic is `Decimal` inside the caller's context, matching the scoring
engine: money and scores never touch float.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from app.radar.models import (
    DimensionResult,
    Observation,
    RadarDimension,
    RadarReason,
    RadarSeries,
)
from app.radar.normalise import clamp, ratio_to_score, sub_series

#: Below this many observations the slopes are noise rather than trend.
MIN_OBSERVATIONS = 6

#: How much of the window forms the "recent" half when comparing halves.
_HALF = 2


def _mean(values: Sequence[Decimal]) -> Decimal | None:
    usable = [v for v in values if v is not None]
    if not usable:
        return None
    return sum(usable, Decimal(0)) / Decimal(len(usable))


def _growth(earlier: Decimal | None, later: Decimal | None) -> Decimal | None:
    """Later relative to earlier, as a multiple. `None` when undefined.

    Guards division by zero explicitly rather than letting a token with no
    liquidity in the first half produce an infinite growth rate — which would
    otherwise be the single easiest way to game the Radar.
    """
    if earlier is None or later is None or earlier <= 0:
        return None
    return later / earlier


def _half_means(
    observations: Sequence[Observation], attribute: str
) -> tuple[Decimal | None, Decimal | None]:
    """Mean of the attribute over the older half and the newer half."""
    values = [getattr(o, attribute) for o in observations]
    midpoint = len(values) // _HALF
    older = _mean([v for v in values[:midpoint] if v is not None])
    newer = _mean([v for v in values[midpoint:] if v is not None])
    return older, newer


def evaluate(series: RadarSeries) -> DimensionResult:
    """Score momentum 0-100 from the shape of the series."""
    observations = series.observations
    if len(observations) < MIN_OBSERVATIONS:
        return DimensionResult.unavailable(
            RadarDimension.MOMENTUM, reason=RadarReason.INSUFFICIENT_HISTORY
        )

    window = sub_series(observations, 48)
    reasons: list[RadarReason] = []

    # --- Liquidity, volume and price direction ------------------------------
    #
    # Comparing half-means rather than first-to-last: a single anomalous
    # snapshot at either end would otherwise decide the verdict, and the
    # provider does occasionally return a zero.
    liq_old, liq_new = _half_means(window, "liquidity_usd")
    vol_old, vol_new = _half_means(window, "volume_24h")
    price_old, price_new = _half_means(window, "price_usd")

    liquidity_growth = _growth(liq_old, liq_new)
    volume_growth = _growth(vol_old, vol_new)
    price_growth = _growth(price_old, price_new)

    # Each sub-signal maps a growth multiple onto 0-100 through the same curve,
    # so "doubled" means the same thing on every axis.
    liquidity_score = ratio_to_score(liquidity_growth)
    volume_score = ratio_to_score(volume_growth)
    price_score = ratio_to_score(price_growth)

    if liquidity_growth is not None:
        if liquidity_growth >= Decimal("1.15"):
            reasons.append(RadarReason.LIQUIDITY_GROWING)
        elif liquidity_growth <= Decimal("0.85"):
            reasons.append(RadarReason.LIQUIDITY_SHRINKING)

    if volume_growth is not None:
        if volume_growth >= Decimal("1.25"):
            reasons.append(RadarReason.VOLUME_EXPANDING)
        elif volume_growth <= Decimal("0.75"):
            reasons.append(RadarReason.VOLUME_FADING)

    if price_growth is not None:
        if price_growth >= Decimal("1.10"):
            reasons.append(RadarReason.PRICE_TRENDING_UP)
        elif price_growth <= Decimal("0.90"):
            reasons.append(RadarReason.PRICE_TRENDING_DOWN)

    # --- Trade balance -------------------------------------------------------
    latest = window[-1]
    buys = latest.buy_count_24h
    sells = latest.sell_count_24h
    flow_score: Decimal | None = None
    if buys is not None and sells is not None and (buys + sells) > 0:
        share = Decimal(buys) / Decimal(buys + sells)
        # 0.5 is balanced and maps to 50; the ends map to 0 and 100.
        flow_score = clamp(share * Decimal(100), Decimal(0), Decimal(100))
        if share >= Decimal("0.60"):
            reasons.append(RadarReason.BUY_PRESSURE_DOMINANT)
        elif share <= Decimal("0.40"):
            reasons.append(RadarReason.SELL_PRESSURE_DOMINANT)

    # --- Combine -------------------------------------------------------------
    #
    # Liquidity is weighted highest of the four because it is the hardest to
    # fake: volume can be wash-traded and price can be moved with very little
    # capital on a thin pool, but liquidity growth means somebody committed
    # capital that stays committed.
    parts: list[tuple[Decimal, Decimal]] = []
    if liquidity_score is not None:
        parts.append((Decimal("0.35"), liquidity_score))
    if volume_score is not None:
        parts.append((Decimal("0.25"), volume_score))
    if price_score is not None:
        parts.append((Decimal("0.25"), price_score))
    if flow_score is not None:
        parts.append((Decimal("0.15"), flow_score))

    if not parts:
        return DimensionResult.unavailable(
            RadarDimension.MOMENTUM, reason=RadarReason.SIGNAL_NOT_AVAILABLE
        )

    # Seeded with Decimal(0) so the sum stays Decimal rather than widening
    # to float — money and scores never touch float in this codebase.
    total_weight = sum((weight for weight, _ in parts), Decimal(0))
    score = sum((weight * value for weight, value in parts), Decimal(0)) / total_weight

    return DimensionResult(
        id=RadarDimension.MOMENTUM,
        available=True,
        score=clamp(score, Decimal(0), Decimal(100)),
        reasons=tuple(reasons),
        raw={
            "liquidity_growth": liquidity_growth,
            "volume_growth": volume_growth,
            "price_growth": price_growth,
            "buy_share": flow_score,
        },
    )
