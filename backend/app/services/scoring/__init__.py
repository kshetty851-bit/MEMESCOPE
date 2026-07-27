"""AI Scoring Engine - the pure core.

Everything in this package is a pure function of its arguments. No database, no
network, no clock, no randomness, no FastAPI, no Redis. The persistence and
worker integration that will call it live elsewhere, deliberately: the engine
knows nothing about enrichment, which is what makes it testable without fixtures
and relocatable without a refactor.

Entry point:

    from app.services.scoring import evaluate, get_model

    result = evaluate(feature_set, get_model())

See docs/AI_SCORING_DESIGN.md for the design and its rationale.
"""

from app.services.scoring.components.base import ComponentId, ComponentResult
from app.services.scoring.engine import ComponentBreakdown, ScoreResult, evaluate
from app.services.scoring.evidence import EvidenceAssessment
from app.services.scoring.explain import AgentId, Explanation, ReasonCode, Severity
from app.services.scoring.features import FeatureSet, Observation, build_feature_set
from app.services.scoring.freshness import confidence_of, freshness_of
from app.services.scoring.grading import EliteGate, GradeBands
from app.services.scoring.models.base import ComponentWeight, ModelConfig
from app.services.scoring.models.registry import (
    MODEL_REGISTRY,
    UnknownModelError,
    get_model,
)

__all__ = [
    "MODEL_REGISTRY",
    "AgentId",
    "ComponentBreakdown",
    "ComponentId",
    "ComponentResult",
    "ComponentWeight",
    "EliteGate",
    "EvidenceAssessment",
    "Explanation",
    "FeatureSet",
    "GradeBands",
    "ModelConfig",
    "Observation",
    "ReasonCode",
    "ScoreResult",
    "Severity",
    "UnknownModelError",
    "build_feature_set",
    "confidence_of",
    "evaluate",
    "freshness_of",
    "get_model",
]
