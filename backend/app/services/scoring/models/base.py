"""Model configuration: the weight vector and its guard rails.

Weights live in code, as frozen dataclasses, deliberately. Storing them in a
database table would make them mutable at runtime, invisible to code review,
uncovered by tests, and would make any stored score unreproducible - you could
never answer "what did the model think last Tuesday?" if the model itself had
changed underneath. Transparency is served instead by exposing the active config
read-only through the API.

Validation runs in `__post_init__`, so a malformed model fails at import rather
than at the first token scored. That matches the project's existing fail-fast
posture in `Settings._enforce_production_hardening`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from app.services.scoring.components import COMPONENT_REGISTRY
from app.services.scoring.components.base import ComponentId
from app.services.scoring.grading import EliteGate, GradeBands
from app.services.scoring.normalisers import ONE, ZERO

#: Declared weights must sum to 1.0. The tolerance covers literals that are
#: exact in decimal (0.15, 0.12) - it is not licence for a vector that does not
#: add up.
WEIGHT_SUM_TOLERANCE = Decimal("0.000001")


@dataclass(frozen=True, slots=True)
class ComponentWeight:
    id: ComponentId
    weight: Decimal

    def __post_init__(self) -> None:
        if self.weight < ZERO:
            raise ValueError(f"{self.id} has a negative weight")


@dataclass(frozen=True, slots=True)
class ModelConfig:
    """One immutable, versioned scoring model."""

    version: str
    components: tuple[ComponentWeight, ...]

    #: How hard the risk gate bites. `score = opportunity * (1 - lambda * risk)`.
    risk_lambda: Decimal = Decimal("0.8")
    #: Hard ceiling applied when the risk gate vetoes.
    veto_ceiling: Decimal = Decimal(35)
    #: No single component may carry more than this share of the final score,
    #: even after renormalisation - losing signals must not turn the engine into
    #: a one-signal oracle.
    max_single_contribution: Decimal = Decimal("0.35")
    #: Below this much available weight, decline to score at all. Scoring a token
    #: on a single component is worse than admitting we cannot.
    min_scorable_weight: Decimal = Decimal("0.15")

    grade_bands: GradeBands = field(default_factory=GradeBands)
    elite_gate: EliteGate = field(default_factory=EliteGate)

    def __post_init__(self) -> None:
        if not self.version:
            raise ValueError("a model version is required")
        if not self.components:
            raise ValueError("a model needs at least one component")

        ids = [entry.id for entry in self.components]
        if len(set(ids)) != len(ids):
            raise ValueError(f"model {self.version} declares a component twice")

        missing = [entry.id for entry in self.components if entry.id not in COMPONENT_REGISTRY]
        if missing:
            raise ValueError(
                f"model {self.version} declares unregistered components: {missing}"
            )

        total = sum((entry.weight for entry in self.components), start=ZERO)
        if abs(total - ONE) > WEIGHT_SUM_TOLERANCE:
            raise ValueError(f"model {self.version} weights sum to {total}, expected 1.0")

        if not ZERO <= self.risk_lambda <= ONE:
            raise ValueError("risk_lambda must be between 0 and 1")
        if not ZERO < self.max_single_contribution <= ONE:
            raise ValueError("max_single_contribution must be in (0, 1]")

    @property
    def declared_weights(self) -> dict[ComponentId, Decimal]:
        """Every declared component, available or not. The coverage denominator."""
        return {entry.id: entry.weight for entry in self.components}

    def weight_for(self, component_id: ComponentId) -> Decimal:
        return self.declared_weights.get(component_id, ZERO)
