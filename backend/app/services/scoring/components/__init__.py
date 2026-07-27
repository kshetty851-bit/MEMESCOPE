"""Component registry.

Maps every declared `ComponentId` to the object that evaluates it. A model
version references components by id, so this registry is what makes adding a
Day 5 signal a matter of writing one module and swapping a placeholder - no
engine, schema, or API change.

Components declared in a model but absent here would be a silent hole in the
weight vector, so `ModelConfig` validates against this mapping at import time.
"""

from __future__ import annotations

from app.services.scoring.components.base import (
    ComponentId,
    ComponentResult,
    NotYetImplemented,
    ScoreComponent,
)
from app.services.scoring.components.liquidity import LiquidityDepth
from app.services.scoring.components.market_risk import MarketRisk, RiskAssessment
from app.services.scoring.components.momentum import Momentum
from app.services.scoring.components.survival import SurvivalAge
from app.services.scoring.components.trade_flow import TradeFlow
from app.services.scoring.components.valuation import ValuationStructure
from app.services.scoring.explain import AgentId

COMPONENT_REGISTRY: dict[ComponentId, ScoreComponent] = {
    ComponentId.LIQUIDITY_DEPTH: LiquidityDepth(),
    ComponentId.MOMENTUM: Momentum(),
    ComponentId.TRADE_FLOW: TradeFlow(),
    ComponentId.VALUATION_STRUCTURE: ValuationStructure(),
    ComponentId.SURVIVAL_AGE: SurvivalAge(),
    # Declared with real weight, no data source until Days 5-7. Their presence
    # is what makes the missing signals visible in coverage rather than absent
    # from the weight table.
    ComponentId.CONTRACT_SAFETY: NotYetImplemented(
        ComponentId.CONTRACT_SAFETY, AgentId.SENTINEL
    ),
    ComponentId.HOLDER_DISTRIBUTION: NotYetImplemented(
        ComponentId.HOLDER_DISTRIBUTION, AgentId.TITAN
    ),
    ComponentId.SMART_MONEY: NotYetImplemented(ComponentId.SMART_MONEY, AgentId.TITAN),
    ComponentId.NARRATIVE: NotYetImplemented(ComponentId.NARRATIVE, AgentId.ECHO),
}

RISK_GATE = MarketRisk()

__all__ = [
    "COMPONENT_REGISTRY",
    "RISK_GATE",
    "ComponentId",
    "ComponentResult",
    "MarketRisk",
    "NotYetImplemented",
    "RiskAssessment",
    "ScoreComponent",
]
