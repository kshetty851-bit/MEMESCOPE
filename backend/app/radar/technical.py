"""Technical structure: is the price building a base or breaking down?

Classical structure analysis over the observation window — higher highs and
higher lows, trend alignment, resistance breaks, volatility compression.

A deliberate limit: the Radar reads *snapshots taken at the enrichment tier's
cadence*, not exchange candles. A "high" here is the highest observed price in
the window, which is a sample of the true high. That makes this dimension a
description of observed structure, not a chart pattern detector, and the
docstrings say so rather than implying a precision the data cannot support.
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
from app.radar.normalise import clamp, ema, mean, sub_series

#: Structure needs enough points to have a shape at all. Below this the answer
#: is "not enough history", which is a real answer.
MIN_OBSERVATIONS = 12

#: Window the structure is read over.
WINDOW = 48

#: Segments the window is split into when looking for higher highs and lows.
SEGMENTS = 4


def _prices(observations: Sequence[Observation]) -> list[Decimal]:
    return [o.price_usd for o in observations if o.price_usd is not None and o.price_usd > 0]


def _segment_extremes(prices: Sequence[Decimal]) -> list[tuple[Decimal, Decimal]]:
    """(low, high) per segment, oldest first."""
    size = len(prices) // SEGMENTS
    if size == 0:
        return []
    extremes: list[tuple[Decimal, Decimal]] = []
    for index in range(SEGMENTS):
        start = index * size
        end = start + size if index < SEGMENTS - 1 else len(prices)
        chunk = prices[start:end]
        if chunk:
            extremes.append((min(chunk), max(chunk)))
    return extremes


def _rising(values: Sequence[Decimal]) -> Decimal:
    """Share of consecutive steps that rose, 0-1.

    A proportion rather than a boolean: "three of four segments made a higher
    high" is a far more useful signal than "the pattern is perfect", and real
    series are rarely perfect.
    """
    if len(values) < 2:
        return Decimal(0)
    steps = len(values) - 1
    risen = sum(1 for i in range(steps) if values[i + 1] > values[i])
    return Decimal(risen) / Decimal(steps)


def evaluate(series: RadarSeries) -> DimensionResult:
    observations = sub_series(series.observations, WINDOW)
    prices = _prices(observations)

    if len(prices) < MIN_OBSERVATIONS:
        return DimensionResult.unavailable(
            RadarDimension.TECHNICAL, reason=RadarReason.INSUFFICIENT_HISTORY
        )

    reasons: list[RadarReason] = []
    parts: list[tuple[Decimal, Decimal]] = []

    # --- Higher highs and higher lows ---------------------------------------
    extremes = _segment_extremes(prices)
    structure_score = Decimal(50)
    if len(extremes) >= 2:
        lows = [low for low, _ in extremes]
        highs = [high for _, high in extremes]
        rising_lows = _rising(lows)
        rising_highs = _rising(highs)
        structure = (rising_lows + rising_highs) / Decimal(2)
        structure_score = structure * Decimal(100)
        if rising_lows >= Decimal("0.66") and rising_highs >= Decimal("0.66"):
            reasons.append(RadarReason.HIGHER_HIGHS_AND_LOWS)
        elif rising_lows <= Decimal("0.34") and rising_highs <= Decimal("0.34"):
            reasons.append(RadarReason.STRUCTURE_BREAKING_DOWN)
    parts.append((Decimal("0.35"), structure_score))

    # --- Trend alignment -----------------------------------------------------
    #
    # Fast EMA above slow EMA above nothing else is the whole test. Two periods,
    # not three: a third adds a parameter without adding information at this
    # series length.
    fast = ema(prices, 8)
    slow = ema(prices, 21)
    trend_score = Decimal(50)
    if fast is not None and slow is not None and slow > 0:
        spread = (fast - slow) / slow
        # ±10% spread saturates. Beyond that the trend is not "more aligned",
        # it is just extended.
        trend_score = clamp(
            Decimal(50) + spread / Decimal("0.10") * Decimal(50), Decimal(0), Decimal(100)
        )
        if fast > slow:
            reasons.append(RadarReason.TREND_ALIGNED)
    parts.append((Decimal("0.25"), trend_score))

    # --- Resistance break ----------------------------------------------------
    #
    # "Resistance" is the highest price observed before the final segment. A
    # close above it is a break. Confirmation by volume is handled in momentum,
    # not duplicated here.
    segment = max(len(prices) // SEGMENTS, 1)
    prior = prices[:-segment]
    latest = prices[-1]
    breakout_score = Decimal(50)
    if prior:
        resistance = max(prior)
        if resistance > 0:
            margin = (latest - resistance) / resistance
            breakout_score = clamp(
                Decimal(50) + margin / Decimal("0.15") * Decimal(50),
                Decimal(0),
                Decimal(100),
            )
            if latest > resistance:
                reasons.append(RadarReason.RESISTANCE_BROKEN)
    parts.append((Decimal("0.25"), breakout_score))

    # --- Volatility compression ---------------------------------------------
    #
    # Narrowing range while holding level often precedes expansion. Scored
    # mildly: it is a setup, not a result, and weighting it heavily would put
    # dormant tokens on the Radar.
    average = mean(prices)
    compression_score = Decimal(50)
    dispersion: Decimal | None = None
    if average is not None and average > 0:
        spread = (max(prices) - min(prices)) / average
        dispersion = spread
        # A tight range (<20% of mean) reads as compressed.
        compression_score = clamp(
            Decimal(100) - spread / Decimal("0.60") * Decimal(100), Decimal(0), Decimal(100)
        )
        if spread <= Decimal("0.20"):
            reasons.append(RadarReason.VOLATILITY_COMPRESSED)
    parts.append((Decimal("0.15"), compression_score))

    # Seeded with Decimal(0) so the sum stays Decimal rather than widening
    # to float — money and scores never touch float in this codebase.
    total_weight = sum((weight for weight, _ in parts), Decimal(0))
    score = sum((weight * value for weight, value in parts), Decimal(0)) / total_weight

    return DimensionResult(
        id=RadarDimension.TECHNICAL,
        available=True,
        score=clamp(score, Decimal(0), Decimal(100)),
        reasons=tuple(reasons),
        raw={
            "ema_fast": fast,
            "ema_slow": slow,
            "dispersion": dispersion,
            "latest_price": latest,
        },
    )
