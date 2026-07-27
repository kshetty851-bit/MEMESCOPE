"""Model version registry.

Same pattern as the market provider registry (ADR 0001), for the same reason:
selection happens through configuration, and an unknown name fails loudly rather
than silently falling back to a default. A typo in `SCORING_MODEL_VERSION` must
not quietly ship scores computed by a model nobody chose.

Every model that has ever served traffic stays registered. Stored scores carry
their `model_version`, and reproducing a historical score means being able to
load the model that produced it - deleting an old entry would make its history
uninterpretable.
"""

from __future__ import annotations

from app.services.scoring.models.base import ModelConfig
from app.services.scoring.models.v1 import MODEL_V1


class UnknownModelError(ValueError):
    """Raised when a configured model version does not exist."""


MODEL_REGISTRY: dict[str, ModelConfig] = {
    MODEL_V1.version: MODEL_V1,
}


def get_model(version: str | None = None) -> ModelConfig:
    """Look up a model by version, defaulting to the configured one.

    Settings are read lazily here rather than at import so that tests can
    exercise the registry without a configured environment, and so an import
    cycle between config and the scoring package cannot arise.
    """
    if version is None:
        from app.core.config import settings

        version = settings.SCORING_MODEL_VERSION

    try:
        return MODEL_REGISTRY[version]
    except KeyError:
        known = ", ".join(sorted(MODEL_REGISTRY))
        raise UnknownModelError(
            f"unknown scoring model '{version}'; registered: {known}"
        ) from None


def register_model(model: ModelConfig) -> None:
    """Register a model version. Used by tests and by future model rollouts."""
    if model.version in MODEL_REGISTRY:
        raise ValueError(f"model '{model.version}' is already registered")
    MODEL_REGISTRY[model.version] = model
