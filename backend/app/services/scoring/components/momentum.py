"""Momentum - Pulse. "Is activity accelerating?"

Three terms against a uniform-rate baseline: if a token's 24-hour volume were
spread evenly, each five-minute bucket would hold `volume_24h / 288` and each
hour `volume_24h / 24`. Doing several times that in the most recent bucket is
the signal Pulse exists to catch.

The price-trend term needs at least three observations to mean anything. Rather
than fabricate a trend from two points, the term is dropped and its weight
redistributed across the volume terms, with `INSUFFICIENT_HISTORY` recorded so
the omission is visible in the explanation rather than hidden in the arithmetic.
"""

from __future__ import annotations

from decimal import Decimal

from app.services.scoring.components.base import (
    ComponentId,
    ComponentResult,
    ScoreComponent,
)
from app.services.scoring.explain import AgentId, ReasonCode
from app.services.scoring.features import FeatureSet
from app.services.scoring.normalisers import (
    ZERO,
    anchors,
    interpolate,
    saturating_ratio,
)

FIVE_MINUTE_BUCKETS_PER_DAY = Decimal(288)
HOURS_PER_DAY = Decimal(24)

WEIGHT_5M = Decimal("0.40")
WEIGHT_1H = Decimal("0.35")
WEIGHT_TREND = Decimal("0.25")

MIN_TREND_OBSERVATIONS = 3

# Percentage price change across the window.
PRICE_TREND = anchors(
    ("-90", "0"), ("-50", "10"), ("-10", "35"), ("0", "50"), ("25", "75"), ("100", "100")
)

# Mean gap between observations beyond which the trend is coarse enough to
# qualify. An old token's window spans days by design (see features.py), so this
# fires routinely there - which is the honest outcome, not a defect.
COARSE_SPACING_SECONDS = Decimal(3600)

ACCELERATING_ABOVE = Decimal("65")
DECAYING_BELOW = Decimal("35")


class Momentum(ScoreComponent):
    id = ComponentId.MOMENTUM
    agent = AgentId.PULSE

    def evaluate(self, features: FeatureSet) -> ComponentResult:
        daily_volume = features.volume_24h
        if daily_volume is None or daily_volume <= ZERO:
            # No flow to measure. Not a failure - a token minutes old routinely
            # has no recorded 24h volume.
            return ComponentResult.unavailable(
                self.id,
                self.agent,
                reason=ReasonCode.COMPONENT_NOT_YET_IMPLEMENTED,
                raw={"volume_24h": daily_volume},
            )

        reasons: list[ReasonCode] = []

        five_minute = saturating_ratio(
            features.volume_5m or ZERO, daily_volume / FIVE_MINUTE_BUCKETS_PER_DAY
        )
        hourly = saturating_ratio(features.volume_1h or ZERO, daily_volume / HOURS_PER_DAY)

        trend_score, price_change = self._price_trend(features)
        if trend_score is None:
            reasons.append(ReasonCode.INSUFFICIENT_HISTORY)
            # Redistribute the trend weight proportionally rather than letting
            # the score sum to less than one and silently depress every young
            # token's momentum.
            volume_weight = WEIGHT_5M + WEIGHT_1H
            score = (five_minute * WEIGHT_5M + hourly * WEIGHT_1H) / volume_weight
        else:
            score = five_minute * WEIGHT_5M + hourly * WEIGHT_1H + trend_score * WEIGHT_TREND

        spacing = features.mean_spacing_seconds()
        if spacing is not None and spacing > COARSE_SPACING_SECONDS:
            reasons.append(ReasonCode.MOMENTUM_COARSE_SAMPLING)

        if score >= ACCELERATING_ABOVE:
            reasons.append(ReasonCode.MOMENTUM_ACCELERATING)
        elif score < DECAYING_BELOW:
            reasons.append(ReasonCode.MOMENTUM_DECAYING)
        else:
            reasons.append(ReasonCode.MOMENTUM_STEADY)

        return ComponentResult(
            id=self.id,
            agent=self.agent,
            available=True,
            score=score,
            raw={
                "volume_24h": daily_volume,
                "volume_1h": features.volume_1h,
                "volume_5m": features.volume_5m,
                "burst_5m_score": five_minute,
                "burst_1h_score": hourly,
                "price_change_pct": price_change,
            },
            reasons=tuple(reasons),
        )

    @staticmethod
    def _price_trend(features: FeatureSet) -> tuple[Decimal | None, Decimal | None]:
        """Percentage price change across the window, oldest to newest."""
        priced = features.priced_observations()
        if len(priced) < MIN_TREND_OBSERVATIONS:
            return None, None

        newest = priced[0].price_usd
        oldest = priced[-1].price_usd
        if newest is None or oldest is None or oldest <= ZERO:
            return None, None

        change = (newest - oldest) / oldest * Decimal(100)
        return interpolate(change, PRICE_TREND), change
