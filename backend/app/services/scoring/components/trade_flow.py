"""Trade flow - Pulse. "Who is on which side, and how many of them?"

Buy share alone is the classic trap on a fresh launch: three buys and no sells
is a 100% buy ratio and means nothing. The participation factor is what fixes
it - the buy-share score is scaled by how many trades produced it, so a ratio
computed from a handful of fills cannot read as conviction.

That participation term is also where average trade size *would* live. It does
not: one $50k swap and fifty $1k swaps are indistinguishable under it, and it is
trivially wash-traded, so shipping it as whale intelligence would overstate what
the platform knows. Titan stays silent until Day 5 (design section 6.4).
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
    ZERO,
    anchors,
    interpolate,
    log_interpolate,
)

# Share of trades that were buys.
BUY_SHARE = anchors(
    ("0", "0"),
    ("0.25", "5"),
    ("0.35", "20"),
    ("0.5", "50"),
    ("0.65", "80"),
    ("0.75", "95"),
    ("1", "100"),
)

# How much the ratio above should be trusted, by trade count.
PARTICIPATION = anchors(("0", "0"), ("10", "25"), ("100", "60"), ("2000", "100"))

BUY_DOMINANT_ABOVE = Decimal("0.65")
SELL_DOMINANT_ABOVE = Decimal("0.65")
THIN_PARTICIPATION_BELOW = Decimal("25")


class TradeFlow(ScoreComponent):
    id = ComponentId.TRADE_FLOW
    agent = AgentId.PULSE

    def evaluate(self, features: FeatureSet) -> ComponentResult:
        buys = features.buy_count_24h
        sells = features.sell_count_24h

        if buys is None and sells is None:
            return ComponentResult.unavailable(
                self.id, self.agent, reason=ReasonCode.COMPONENT_NOT_YET_IMPLEMENTED
            )

        buy_count = Decimal(buys or 0)
        sell_count = Decimal(sells or 0)
        total = buy_count + sell_count

        if total <= ZERO:
            return ComponentResult.unavailable(
                self.id,
                self.agent,
                reason=ReasonCode.COMPONENT_NOT_YET_IMPLEMENTED,
                raw={"buy_count_24h": buy_count, "sell_count_24h": sell_count},
            )

        buy_share = buy_count / total
        sell_share = sell_count / total
        share_score = interpolate(buy_share, BUY_SHARE)
        participation = log_interpolate(total, PARTICIPATION)

        # Multiplicative, not additive: no amount of one-sided buying should
        # score highly on three trades.
        score = share_score * participation / HUNDRED

        reasons: list[ReasonCode] = []
        if participation < THIN_PARTICIPATION_BELOW:
            reasons.append(ReasonCode.PARTICIPATION_THIN)
        if buy_share >= BUY_DOMINANT_ABOVE:
            reasons.append(ReasonCode.BUY_PRESSURE_DOMINANT)
        elif sell_share >= SELL_DOMINANT_ABOVE:
            reasons.append(ReasonCode.SELL_PRESSURE_DOMINANT)

        return ComponentResult(
            id=self.id,
            agent=self.agent,
            available=True,
            score=score,
            raw={
                "buy_count_24h": buy_count,
                "sell_count_24h": sell_count,
                "buy_share": buy_share,
                "sell_share": sell_share,
                "participation_score": participation,
            },
            reasons=tuple(reasons),
        )
