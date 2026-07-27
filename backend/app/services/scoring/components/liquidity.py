"""Liquidity depth - Sentinel. "Can you exit?"

Two sub-signals, weighted evenly, because either alone is gameable:

  * **Absolute depth.** $50k of liquidity is tradeable; $500 is a trap. But
    absolute depth alone rewards a large-cap token with a shallow pool.
  * **Depth ratio** (liquidity / market cap). Catches exactly that case, but
    alone it rewards a $300 pool sitting behind a $1k valuation, which is
    proportionally excellent and practically worthless.

The component is unavailable when the provider reports no liquidity at all -
including the known DexScreener gap for pump.fun bonding-curve pools (ADR 0001).
That is a real hole in what we know, so it is charged to coverage rather than
scored as zero.
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
    HUNDRED,
    anchors,
    interpolate,
    log_interpolate,
    ratio_of,
)

# Dollars of liquidity to score. Log-spaced: the step from $2k to $25k matters
# far more than the step from $1M to $1.02M.
ABSOLUTE_DEPTH = anchors(
    ("0", "0"), ("2000", "10"), ("25000", "50"), ("150000", "85"), ("1000000", "100")
)

# liquidity / market_cap. Below 1% the book cannot absorb an exit at anything
# like the quoted price; 30% is a deep, healthy pool.
DEPTH_RATIO = anchors(
    ("0", "0"), ("0.01", "5"), ("0.05", "45"), ("0.15", "85"), ("0.30", "100")
)

ABSOLUTE_SHARE = Decimal("0.5")
RATIO_SHARE = Decimal("0.5")

DEEP_ABOVE = Decimal("75")
THIN_BELOW = Decimal("35")


class LiquidityDepth(ScoreComponent):
    id = ComponentId.LIQUIDITY_DEPTH
    agent = AgentId.SENTINEL

    def evaluate(self, features: FeatureSet) -> ComponentResult:
        liquidity = features.liquidity_usd
        if liquidity is None:
            return ComponentResult.unavailable(
                self.id, self.agent, reason=ReasonCode.COMPONENT_NOT_YET_IMPLEMENTED
            )

        absolute = log_interpolate(liquidity, ABSOLUTE_DEPTH)
        depth_ratio = ratio_of(liquidity, features.market_cap)

        reasons: list[ReasonCode] = []
        if depth_ratio is None:
            # No valuation to measure against. Absolute depth is still a real
            # signal, so the component stays available on that alone rather than
            # discarding what we do know.
            score = absolute
            reasons.append(ReasonCode.DEPTH_RATIO_UNAVAILABLE)
        else:
            ratio_score = interpolate(depth_ratio, DEPTH_RATIO)
            score = absolute * ABSOLUTE_SHARE + ratio_score * RATIO_SHARE

        if score >= DEEP_ABOVE:
            reasons.append(ReasonCode.LIQUIDITY_DEEP)
        elif score < THIN_BELOW:
            reasons.append(ReasonCode.LIQUIDITY_THIN)
        else:
            reasons.append(ReasonCode.LIQUIDITY_ADEQUATE)

        return ComponentResult(
            id=self.id,
            agent=self.agent,
            available=True,
            score=min(score, HUNDRED),
            raw={
                "liquidity_usd": liquidity,
                "market_cap": features.market_cap,
                "depth_ratio": depth_ratio,
                "absolute_score": absolute,
            },
            reasons=tuple(reasons),
        )
