"""Liquidity Intelligence — is there capital to trade against, and is it growing?

## Wrapping, not re-deciding

This analyst does not measure liquidity. `radar/health.py` already does, it is
already pure, and it is already the thing the Radar's own score is built from.
Measuring it a second time here would put two liquidity opinions in one product
with no rule for choosing between them — the failure `lib/intelligence.ts` was
deleted for, reproduced on the backend where it would be harder to spot.

So this adapts: it calls `evaluate_liquidity_quality`, then adds what the
dimension result alone cannot express — the trend across the window, the
confidence that follows from how much was observed, and the warnings a user
needs before trusting the number.

## The gap that shapes every reading here

DexScreener reports no liquidity for pump.fun bonding-curve pools, which is
most of the feed. A token with no liquidity figure is **not** a token with
zero liquidity, and this analyst refuses to score it rather than reporting a
zero that would read as "drained".
"""

from __future__ import annotations

from decimal import Decimal

from app.analysts.base import AnalystId, AnalystMeta, Evidence, Reading, RiskWarning, Severity
from app.radar.health import evaluate_liquidity_quality
from app.radar.models import RadarSeries

META = AnalystMeta(
    id=AnalystId.LIQUIDITY,
    name="Liquidity Intelligence",
    question="Is there capital to trade against, and is it growing?",
    operational=True,
    evidence_fields=("current_liquidity", "liquidity_trend", "observations"),
)

#: Below this many observations the trend is noise rather than a trend.
MIN_TREND_OBSERVATIONS = 6

#: A pool this thin cannot absorb a position without moving the price.
THIN_POOL_USD = Decimal(5_000)


def analyse(series: RadarSeries) -> Reading:
    dimension = evaluate_liquidity_quality(series)

    liquid = [o.liquidity_usd for o in series.observations if o.liquidity_usd is not None]

    if not dimension.available or not liquid:
        return Reading.unavailable(
            AnalystId.LIQUIDITY,
            reason=(
                "No liquidity figure is reported for this pool. That is an absence "
                "of data, not an absence of liquidity — DexScreener does not "
                "publish it for bonding-curve pools, which is most new tokens."
            ),
            warnings=(
                RiskWarning(
                    code="LIQUIDITY_UNREPORTED",
                    severity=Severity.CAUTION,
                    message=(
                        "Liquidity could not be read, so depth is unknown rather "
                        "than confirmed."
                    ),
                ),
            ),
        )

    current = liquid[-1]
    first = liquid[0]
    observations = len(liquid)

    evidence = [
        Evidence("Current liquidity", f"${current:,.0f}"),
        Evidence("Observations", str(observations), "Readings behind this assessment."),
    ]

    warnings: list[RiskWarning] = []

    if observations >= MIN_TREND_OBSERVATIONS and first > 0:
        change = (current - first) / first * 100
        evidence.append(
            Evidence(
                "Trend across window",
                f"{change:+.1f}%",
                "Measured from the oldest observation in the window to the newest.",
            )
        )
        trend_phrase = f"liquidity has moved {change:+.1f}% across {observations} observations"
    else:
        trend_phrase = f"only {observations} liquidity readings exist so far"
        warnings.append(
            RiskWarning(
                code="LIQUIDITY_TREND_UNKNOWN",
                severity=Severity.INFO,
                message=(
                    f"Fewer than {MIN_TREND_OBSERVATIONS} readings, so no trend can "
                    "be established yet."
                ),
            )
        )

    if current < THIN_POOL_USD:
        warnings.append(
            RiskWarning(
                code="LIQUIDITY_THIN",
                severity=Severity.CRITICAL,
                message=(
                    f"At ${current:,.0f} the pool is thin enough that a normal "
                    "position would move the price against you on the way in and "
                    "again on the way out."
                ),
            )
        )

    # Confidence follows observation depth, capped: liquidity is one figure from
    # one vendor, and no amount of repetition makes a single source certain.
    confidence = min(Decimal(85), Decimal(35) + Decimal(observations) * Decimal(2))

    return Reading(
        analyst=AnalystId.LIQUIDITY,
        score=dimension.score,
        confidence=confidence,
        reason=f"At ${current:,.0f}, {trend_phrase}.",
        evidence=tuple(evidence),
        warnings=tuple(warnings),
    )
