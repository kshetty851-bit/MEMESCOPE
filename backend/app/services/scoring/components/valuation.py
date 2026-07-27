"""Valuation structure - Oracle. "Is the valuation coherent?"

Two questions:

  * **Is the supply actually circulating?** `market_cap / FDV` near 1.0 means
    what you see is what exists. A large gap means most of the supply is held
    back and can arrive on the market later, which is a structural overhang the
    price does not yet reflect.
  * **Is the number plausible at all?** Both dust and absurdity are informative:
    a $200 valuation is noise, and a $500M fully-diluted valuation on a token a
    few hours old is a supply figure, not a market.

The second curve is deliberately non-monotone - the middle is the good part -
which is why anchor tables are allowed to fall as well as rise.
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
    log_interpolate,
    ratio_of,
)

# market_cap / fully_diluted_valuation.
CIRCULATING_SHARE = anchors(
    ("0", "10"), ("0.3", "20"), ("0.6", "55"), ("0.85", "85"), ("1", "100")
)

# Absolute fully-diluted valuation. Rises out of dust, peaks in the range a real
# early-stage token occupies, then falls away as the figure stops being credible.
FDV_SANITY = anchors(
    ("0", "5"),
    ("1000", "20"),
    ("50000", "80"),
    ("5000000", "90"),
    ("50000000", "50"),
    ("500000000", "20"),
)

SHARE_WEIGHT = Decimal("0.6")
SANITY_WEIGHT = Decimal("0.4")

OVERHANG_BELOW = Decimal("0.5")
COHERENT_ABOVE = Decimal("0.85")
IMPLAUSIBLE_BELOW = Decimal("35")


class ValuationStructure(ScoreComponent):
    id = ComponentId.VALUATION_STRUCTURE
    agent = AgentId.ORACLE

    def evaluate(self, features: FeatureSet) -> ComponentResult:
        market_cap = features.market_cap
        fdv = features.fully_diluted_valuation

        if market_cap is None and fdv is None:
            return ComponentResult.unavailable(
                self.id, self.agent, reason=ReasonCode.COMPONENT_NOT_YET_IMPLEMENTED
            )

        # Either figure alone still supports the sanity band; only the
        # circulating-share term needs both.
        headline = fdv if fdv is not None and fdv > ZERO else market_cap
        sanity = log_interpolate(headline or ZERO, FDV_SANITY)

        circulating = ratio_of(market_cap, fdv)
        reasons: list[ReasonCode] = []

        if circulating is None:
            score = sanity
        else:
            share_score = interpolate(circulating, CIRCULATING_SHARE)
            score = share_score * SHARE_WEIGHT + sanity * SANITY_WEIGHT
            if circulating < OVERHANG_BELOW:
                reasons.append(ReasonCode.SUPPLY_OVERHANG)
            elif circulating >= COHERENT_ABOVE:
                reasons.append(ReasonCode.VALUATION_COHERENT)

        if sanity < IMPLAUSIBLE_BELOW:
            reasons.append(ReasonCode.VALUATION_IMPLAUSIBLE)

        return ComponentResult(
            id=self.id,
            agent=self.agent,
            available=True,
            score=score,
            raw={
                "market_cap": market_cap,
                "fully_diluted_valuation": fdv,
                "circulating_share": circulating,
                "sanity_score": sanity,
            },
            reasons=tuple(reasons),
        )
