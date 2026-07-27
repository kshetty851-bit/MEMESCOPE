"""Market risk - Sentinel. The gate, not a component.

This does not contribute to the weighted sum. It returns a penalty that
*multiplies* the composite, plus hard vetoes that cap it outright.

The distinction is the whole point. Under a linear sum, strong momentum can
offset a fatal liquidity structure - and we have direct evidence it does: the
comment at `frontend/src/lib/intelligence.ts:124` records that the first linear
formulation capped total risk at 0.75, so a textbook rug (a few dollars of
liquidity behind a multi-million-dollar valuation) scored "moderate". A product
cannot be out-voted; a sum can.

Liquidity drawdown is the one genuine security signal available on Day 4, and it
exists only because Day 3 chose to store immutable snapshot history. It is split
by recency: a 70% decline inside the risk window is a rug in progress and vetoes
the score, while the same decline spread over three days is ordinary decay and
earns a penalty. Conflating them would veto every slowly-dying old token.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.services.scoring.explain import ReasonCode
from app.services.scoring.features import FeatureSet
from app.services.scoring.normalisers import ONE, ZERO, clamp, ratio_of

ACUTE_DRAWDOWN_PENALTY_AT = Decimal("0.40")
ACUTE_DRAWDOWN_VETO_AT = Decimal("0.70")
GRADUAL_DRAWDOWN_PENALTY_AT = Decimal("0.70")

DEPTH_RATIO_FLOOR = Decimal("0.01")
LIQUIDITY_FLOOR_USD = Decimal("500")
SELL_DOMINANCE_FROM = Decimal("0.65")

PENALTY_ACUTE_DRAWDOWN = Decimal("0.35")
PENALTY_GRADUAL_DRAWDOWN = Decimal("0.20")
PENALTY_DEPTH_RATIO = Decimal("0.30")
PENALTY_SELL_DOMINANCE = Decimal("0.20")
PENALTY_METADATA = Decimal("0.10")
PENALTY_LIQUIDITY_FLOOR = Decimal("0.25")

HUNDRED = Decimal(100)


@dataclass(frozen=True, slots=True)
class RiskAssessment:
    """The gate's verdict.

    `penalty` is 0-1 and multiplies the composite. `vetoed` is categorically
    different: it clamps the score to the model's ceiling regardless of how
    strong everything else looks, and it disqualifies the token from Elite.
    """

    penalty: Decimal
    vetoed: bool
    reasons: tuple[ReasonCode, ...]
    raw: dict[str, Decimal | None]

    @property
    def as_score(self) -> Decimal:
        """The penalty on the 0-100 scale the database stores."""
        return self.penalty * HUNDRED


class MarketRisk:
    """Evaluates observable danger. Never returns "unavailable".

    A token we know nothing about is not a safe token, so absent data produces a
    small penalty rather than an exemption - the opposite of how the opportunity
    components treat a gap.
    """

    def evaluate(self, features: FeatureSet) -> RiskAssessment:
        penalty = ZERO
        reasons: list[ReasonCode] = []
        raw: dict[str, Decimal | None] = {}
        vetoed = False

        acute, gradual = self._drawdowns(features)
        raw["acute_drawdown"] = acute
        raw["gradual_drawdown"] = gradual

        if acute is not None and acute >= ACUTE_DRAWDOWN_VETO_AT:
            vetoed = True
            penalty += PENALTY_ACUTE_DRAWDOWN
            reasons.append(ReasonCode.LIQUIDITY_DRAWDOWN_ACUTE)
        elif acute is not None and acute >= ACUTE_DRAWDOWN_PENALTY_AT:
            penalty += PENALTY_ACUTE_DRAWDOWN
            reasons.append(ReasonCode.LIQUIDITY_DRAWDOWN_ACUTE)
        elif gradual is not None and gradual >= GRADUAL_DRAWDOWN_PENALTY_AT:
            penalty += PENALTY_GRADUAL_DRAWDOWN
            reasons.append(ReasonCode.LIQUIDITY_DRAWDOWN_GRADUAL)

        if features.trading_status == "inactive":
            vetoed = True
            reasons.append(ReasonCode.POOL_INACTIVE)

        depth_ratio = ratio_of(features.liquidity_usd, features.market_cap)
        raw["depth_ratio"] = depth_ratio
        if depth_ratio is not None and depth_ratio < DEPTH_RATIO_FLOOR:
            penalty += PENALTY_DEPTH_RATIO
            reasons.append(ReasonCode.DEPTH_RATIO_CRITICAL)

        sell_share = self._sell_share(features)
        raw["sell_share"] = sell_share
        if sell_share is not None and sell_share > SELL_DOMINANCE_FROM:
            # Scaled, not a step: 0.66 is a lean, 0.95 is an exit queue.
            severity = (sell_share - SELL_DOMINANCE_FROM) / (ONE - SELL_DOMINANCE_FROM)
            penalty += PENALTY_SELL_DOMINANCE * severity
            reasons.append(ReasonCode.SELL_PRESSURE_DOMINANT)

        if not features.metadata_resolved:
            penalty += PENALTY_METADATA
            reasons.append(ReasonCode.METADATA_UNRESOLVED)

        liquidity = features.liquidity_usd
        raw["liquidity_usd"] = liquidity
        if liquidity is not None and liquidity < LIQUIDITY_FLOOR_USD:
            penalty += PENALTY_LIQUIDITY_FLOOR
            reasons.append(ReasonCode.LIQUIDITY_THIN)

        return RiskAssessment(
            penalty=clamp(penalty, ZERO, ONE),
            vetoed=vetoed,
            reasons=tuple(reasons),
            raw=raw,
        )

    @staticmethod
    def _drawdowns(
        features: FeatureSet,
    ) -> tuple[Decimal | None, Decimal | None]:
        """Decline from peak liquidity, inside and across the window.

        Returns `(acute, gradual)` as fractions in 0-1, or `None` where there is
        no peak to measure against.
        """
        current = features.liquidity_usd
        if current is None:
            return None, None

        def decline(peak: Decimal | None) -> Decimal | None:
            if peak is None or peak <= ZERO or peak <= current:
                return None
            return (peak - current) / peak

        acute_peak = features.liquidity_peak(within_seconds=features.risk_window_seconds)
        gradual_peak = features.liquidity_peak()
        return decline(acute_peak), decline(gradual_peak)

    @staticmethod
    def _sell_share(features: FeatureSet) -> Decimal | None:
        buys = features.buy_count_24h
        sells = features.sell_count_24h
        if buys is None and sells is None:
            return None
        total = Decimal((buys or 0) + (sells or 0))
        if total <= ZERO:
            return None
        return Decimal(sells or 0) / total
