"""Model config validation and the version registry.

Validation runs at import, so a malformed model refuses to load rather than
producing wrong scores at runtime - the same fail-fast posture as
`Settings._enforce_production_hardening`.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.services.scoring.components.base import ComponentId
from app.services.scoring.models.base import ComponentWeight, ModelConfig
from app.services.scoring.models.registry import (
    MODEL_REGISTRY,
    UnknownModelError,
    get_model,
    register_model,
)
from app.services.scoring.models.v1 import MODEL_V1
from app.services.scoring.normalisers import ONE, ZERO

pytestmark = pytest.mark.unit


def _valid_components() -> tuple[ComponentWeight, ...]:
    return (
        ComponentWeight(ComponentId.LIQUIDITY_DEPTH, Decimal("0.6")),
        ComponentWeight(ComponentId.MOMENTUM, Decimal("0.4")),
    )


# --- v1 ------------------------------------------------------------------------


def test_v1_weights_sum_to_one() -> None:
    total = sum((entry.weight for entry in MODEL_V1.components), start=ZERO)
    assert total == ONE


def test_v1_available_weight_is_the_documented_sixty_five_percent() -> None:
    """The number that caps evidence, and therefore keeps Elite unreachable."""
    available = {
        ComponentId.LIQUIDITY_DEPTH,
        ComponentId.MOMENTUM,
        ComponentId.TRADE_FLOW,
        ComponentId.VALUATION_STRUCTURE,
        ComponentId.SURVIVAL_AGE,
    }
    total = sum(
        (entry.weight for entry in MODEL_V1.components if entry.id in available),
        start=ZERO,
    )
    assert total == Decimal("0.65")


def test_v1_declares_every_component() -> None:
    assert set(MODEL_V1.declared_weights) == set(ComponentId)


def test_weight_for_an_undeclared_component_is_zero() -> None:
    minimal = ModelConfig(version="minimal", components=_valid_components())
    assert minimal.weight_for(ComponentId.NARRATIVE) == ZERO


# --- Validation ----------------------------------------------------------------


def test_weights_must_sum_to_one() -> None:
    with pytest.raises(ValueError, match="weights sum to"):
        ModelConfig(
            version="bad-sum",
            components=(ComponentWeight(ComponentId.MOMENTUM, Decimal("0.5")),),
        )


def test_a_component_cannot_be_declared_twice() -> None:
    with pytest.raises(ValueError, match="twice"):
        ModelConfig(
            version="duplicate",
            components=(
                ComponentWeight(ComponentId.MOMENTUM, Decimal("0.5")),
                ComponentWeight(ComponentId.MOMENTUM, Decimal("0.5")),
            ),
        )


def test_a_model_needs_a_version() -> None:
    with pytest.raises(ValueError, match="version is required"):
        ModelConfig(version="", components=_valid_components())


def test_a_model_needs_components() -> None:
    with pytest.raises(ValueError, match="at least one component"):
        ModelConfig(version="empty", components=())


def test_negative_weights_are_rejected() -> None:
    with pytest.raises(ValueError, match="negative weight"):
        ComponentWeight(ComponentId.MOMENTUM, Decimal("-0.1"))


@pytest.mark.parametrize("value", ["-0.1", "1.5"])
def test_risk_lambda_must_be_a_fraction(value: str) -> None:
    with pytest.raises(ValueError, match="risk_lambda"):
        ModelConfig(
            version="bad-lambda",
            components=_valid_components(),
            risk_lambda=Decimal(value),
        )


@pytest.mark.parametrize("value", ["0", "1.5"])
def test_the_contribution_cap_must_be_in_range(value: str) -> None:
    with pytest.raises(ValueError, match="max_single_contribution"):
        ModelConfig(
            version="bad-cap",
            components=_valid_components(),
            max_single_contribution=Decimal(value),
        )


def test_a_model_cannot_declare_an_unregistered_component() -> None:
    """A component with weight but no implementation would be a silent hole."""

    class Fake:
        value = "not_a_component"

    with pytest.raises(ValueError, match="unregistered"):
        ModelConfig(
            version="ghost",
            components=(ComponentWeight(Fake.value, ONE),),  # type: ignore[arg-type]
        )


def test_models_are_immutable() -> None:
    with pytest.raises(AttributeError):
        MODEL_V1.version = "v2"  # type: ignore[misc]


# --- Registry ------------------------------------------------------------------


def test_the_default_version_resolves() -> None:
    assert get_model().version == "v1"


def test_an_explicit_version_resolves() -> None:
    assert get_model("v1") is MODEL_V1


def test_an_unknown_version_fails_loudly() -> None:
    """Never a silent fallback: a typo must not ship an unchosen model."""
    with pytest.raises(UnknownModelError, match="unknown scoring model"):
        get_model("v99")


def test_the_error_lists_what_is_registered() -> None:
    with pytest.raises(UnknownModelError, match="registered: v1"):
        get_model("nope")


def test_registering_a_model_makes_it_resolvable() -> None:
    model = ModelConfig(version="test-registered", components=_valid_components())
    try:
        register_model(model)
        assert get_model("test-registered") is model
    finally:
        MODEL_REGISTRY.pop("test-registered", None)


def test_a_version_cannot_be_registered_twice() -> None:
    """Stored scores carry their version; reusing one would rewrite history."""
    with pytest.raises(ValueError, match="already registered"):
        register_model(MODEL_V1)
