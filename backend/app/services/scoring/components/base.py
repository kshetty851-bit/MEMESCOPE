"""The component contract.

A component turns a `FeatureSet` into one 0-100 sub-score plus the reasons for
it. Components are stateless singletons: they hold no data, so evaluating the
same features twice cannot produce different answers.

`available=False` is the contract's most important feature. A component that
cannot speak - because the provider indexed no pool, or because the signal is
Day 5 work - says so, and the engine charges the gap to coverage rather than
imputing a value. That is the mechanism that keeps "we do not know" from being
silently rendered as "it is fine".
"""

from __future__ import annotations

import enum
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Protocol

from app.services.scoring.explain import AgentId, ReasonCode
from app.services.scoring.features import FeatureSet


class ComponentId(enum.StrEnum):
    """Every signal the model declares, available or not.

    Members are persisted inside `token_score_history.components`, so this enum
    is append-only for the same reason `ReasonCode` is.
    """

    LIQUIDITY_DEPTH = "liquidity_depth"
    MOMENTUM = "momentum"
    TRADE_FLOW = "trade_flow"
    VALUATION_STRUCTURE = "valuation_structure"
    SURVIVAL_AGE = "survival_age"
    # Declared with real weight but not implemented until the data exists. They
    # evaluate to unavailable, which is what caps evidence at 0.65 in v1.
    CONTRACT_SAFETY = "contract_safety"
    HOLDER_DISTRIBUTION = "holder_distribution"
    SMART_MONEY = "smart_money"
    NARRATIVE = "narrative"


@dataclass(frozen=True, slots=True)
class ComponentResult:
    """One component's verdict.

    `score` is `None` exactly when `available` is `False`; the engine asserts
    this rather than trusting it, because a component returning an available
    `None` would poison the weighted sum.
    """

    id: ComponentId
    agent: AgentId
    available: bool
    score: Decimal | None
    raw: Mapping[str, Decimal | None] = field(default_factory=dict)
    reasons: tuple[ReasonCode, ...] = ()

    @classmethod
    def unavailable(
        cls,
        component_id: ComponentId,
        agent: AgentId,
        *,
        reason: ReasonCode,
        raw: Mapping[str, Decimal | None] | None = None,
    ) -> ComponentResult:
        return cls(
            id=component_id,
            agent=agent,
            available=False,
            score=None,
            raw=raw or {},
            reasons=(reason,),
        )


class ScoreComponent(Protocol):
    """What the engine requires of anything in the component registry."""

    id: ComponentId
    agent: AgentId

    def evaluate(self, features: FeatureSet) -> ComponentResult: ...


class NotYetImplemented:
    """Placeholder for a declared component whose data source does not exist.

    Not a stub to be filled in casually: it carries real weight in the model, so
    its presence is what makes the missing signal visible in every score's
    coverage figure instead of quietly absent from the weight table.
    """

    def __init__(self, component_id: ComponentId, agent: AgentId) -> None:
        self.id = component_id
        self.agent = agent

    def evaluate(self, features: FeatureSet) -> ComponentResult:
        return ComponentResult.unavailable(
            self.id, self.agent, reason=ReasonCode.COMPONENT_NOT_YET_IMPLEMENTED
        )
