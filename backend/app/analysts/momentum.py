"""Momentum Intelligence — is the move sustainable, or just a move?

Wraps `radar/momentum.py` for the same reason the liquidity analyst wraps
`radar/health.py`: that engine is already pure, already tested and already what
the Radar's score is built from. Re-deriving momentum here would create a
second opinion with no rule for choosing between them.

What this adds is the distinction the brief asks for — **sustainable** momentum
rather than momentum. A price rising on falling volume and thinning liquidity
is a move without support, and it reads very differently from the same price
action with both behind it. The dimension result cannot express that; the
warnings below can.
"""

from __future__ import annotations

from decimal import Decimal

from app.analysts.base import AnalystId, AnalystMeta, Evidence, Reading, RiskWarning, Severity
from app.radar.models import RadarSeries
from app.radar.momentum import evaluate as evaluate_momentum

META = AnalystMeta(
    id=AnalystId.MOMENTUM,
    name="Momentum Intelligence",
    question="Is the move supported by volume and liquidity, or unsupported?",
    operational=True,
    evidence_fields=("price_trend", "volume_trend", "buy_sell_ratio"),
)

#: Fewer readings than this and a "trend" is two points and an opinion.
MIN_OBSERVATIONS = 8


def _first_last(values: list[Decimal]) -> tuple[Decimal, Decimal] | None:
    return (values[0], values[-1]) if len(values) >= 2 else None


def analyse(series: RadarSeries) -> Reading:
    dimension = evaluate_momentum(series)

    prices = [o.price_usd for o in series.observations if o.price_usd is not None]
    volumes = [o.volume_24h for o in series.observations if o.volume_24h is not None]
    liquidity = [o.liquidity_usd for o in series.observations if o.liquidity_usd is not None]

    if not dimension.available or len(prices) < 2:
        return Reading.unavailable(
            AnalystId.MOMENTUM,
            reason="Too few price observations to say whether anything is moving.",
            warnings=(
                RiskWarning(
                    code="MOMENTUM_INSUFFICIENT_HISTORY",
                    severity=Severity.INFO,
                    message="Momentum needs a window; this token has barely been observed.",
                ),
            ),
        )

    evidence: list[Evidence] = []
    warnings: list[RiskWarning] = []

    price_pair = _first_last(prices)
    price_change = Decimal(0)
    if price_pair and price_pair[0] > 0:
        price_change = (price_pair[1] - price_pair[0]) / price_pair[0] * 100
        evidence.append(Evidence("Price across window", f"{price_change:+.1f}%"))

    volume_change: Decimal | None = None
    volume_pair = _first_last(volumes)
    if volume_pair and volume_pair[0] > 0:
        volume_change = (volume_pair[1] - volume_pair[0]) / volume_pair[0] * 100
        evidence.append(Evidence("Volume across window", f"{volume_change:+.1f}%"))

    liquidity_change: Decimal | None = None
    liquidity_pair = _first_last(liquidity)
    if liquidity_pair and liquidity_pair[0] > 0:
        liquidity_change = (liquidity_pair[1] - liquidity_pair[0]) / liquidity_pair[0] * 100

    # The distinction the brief asks for: a rise with nothing behind it.
    rising = price_change > 0
    if rising and volume_change is not None and volume_change < 0:
        warnings.append(
            RiskWarning(
                code="MOMENTUM_UNSUPPORTED_BY_VOLUME",
                severity=Severity.CAUTION,
                message=(
                    "Price is rising while volume falls. Fewer participants are "
                    "behind each move up than were behind the last one."
                ),
            )
        )
    if rising and liquidity_change is not None and liquidity_change < 0:
        warnings.append(
            RiskWarning(
                code="MOMENTUM_UNSUPPORTED_BY_LIQUIDITY",
                severity=Severity.CAUTION,
                message=(
                    "Price is rising while liquidity leaves. The move is happening "
                    "on a thinner book than it started on."
                ),
            )
        )

    buys = sum(o.buy_count_24h or 0 for o in series.observations)
    sells = sum(o.sell_count_24h or 0 for o in series.observations)
    if buys + sells > 0:
        ratio = Decimal(buys) / Decimal(buys + sells) * 100
        evidence.append(
            Evidence("Buy share of trades", f"{ratio:.0f}%", f"{buys} buys, {sells} sells.")
        )

    observations = len(prices)
    if observations < MIN_OBSERVATIONS:
        warnings.append(
            RiskWarning(
                code="MOMENTUM_SHORT_WINDOW",
                severity=Severity.INFO,
                message=(
                    f"Only {observations} price readings — enough to describe, not "
                    "enough to call a trend."
                ),
            )
        )

    confidence = min(Decimal(80), Decimal(25) + Decimal(observations) * Decimal(3))
    if warnings:
        # An unsupported move is a less trustworthy reading, not just a warned one.
        confidence = max(Decimal(20), confidence - Decimal(15))

    supported = "with volume behind it" if not warnings else "without clear support"
    return Reading(
        analyst=AnalystId.MOMENTUM,
        score=dimension.score,
        confidence=confidence,
        reason=f"Price has moved {price_change:+.1f}% across the window, {supported}.",
        evidence=tuple(evidence),
        warnings=tuple(warnings),
    )
