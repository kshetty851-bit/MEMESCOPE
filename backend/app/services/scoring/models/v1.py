"""Scoring model v1.

The weights below are **priors, not fitted parameters**. They encode a
defensible ordering - liquidity structure matters more than momentum, momentum
more than raw trade counts, and everything is subordinate to not being in a rug -
and nothing more. There are no labels yet: the platform has not been collecting
long enough to know which tokens rugged or ran, so anything claiming to be
"trained" would be these same judgements wearing a lab coat.

They are exposed read-only through the API precisely so the claim is inspectable
rather than asserted. When labels exist, fitting replaces judgement and the
result ships as `v2` alongside `v1` - never as a silent edit to these numbers.

Declared weights sum to 1.00. Available weights sum to **0.65**, which is the
ceiling on coverage, and therefore on evidence, for every token scored by v1.
The four unavailable components are not padding: their weight is what makes the
missing security and holder picture visible in every score.
"""

from __future__ import annotations

from decimal import Decimal

from app.services.scoring.components.base import ComponentId
from app.services.scoring.models.base import ComponentWeight, ModelConfig

MODEL_V1 = ModelConfig(
    version="v1",
    components=(
        # --- Available in v1 (0.65 of declared weight) -----------------------
        ComponentWeight(ComponentId.LIQUIDITY_DEPTH, Decimal("0.20")),
        ComponentWeight(ComponentId.MOMENTUM, Decimal("0.15")),
        ComponentWeight(ComponentId.TRADE_FLOW, Decimal("0.12")),
        ComponentWeight(ComponentId.VALUATION_STRUCTURE, Decimal("0.10")),
        ComponentWeight(ComponentId.SURVIVAL_AGE, Decimal("0.08")),
        # --- Declared, unavailable until Days 5-7 (0.35) ---------------------
        ComponentWeight(ComponentId.CONTRACT_SAFETY, Decimal("0.15")),
        ComponentWeight(ComponentId.HOLDER_DISTRIBUTION, Decimal("0.12")),
        ComponentWeight(ComponentId.SMART_MONEY, Decimal("0.05")),
        ComponentWeight(ComponentId.NARRATIVE, Decimal("0.03")),
    ),
    risk_lambda=Decimal("0.8"),
    veto_ceiling=Decimal(35),
    max_single_contribution=Decimal("0.35"),
    min_scorable_weight=Decimal("0.15"),
)
