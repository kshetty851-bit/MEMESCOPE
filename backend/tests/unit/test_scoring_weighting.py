"""Weighting tests, including the exhaustive subset sweep.

The design calls for covering every subset of available components. With nine
declared components that is 512 cases, which is cheap and total - so the
renormalisation algorithm is verified for every combination that can occur in
production rather than for the handful anyone thought to write down.
"""

from __future__ import annotations

from decimal import Decimal
from itertools import combinations

import pytest

from app.services.scoring.components.base import ComponentId
from app.services.scoring.models.v1 import MODEL_V1
from app.services.scoring.normalisers import ONE, ZERO
from app.services.scoring.weighting import MAX_PASSES, solve_weights

pytestmark = pytest.mark.unit

CAP = Decimal("0.35")
# Renormalisation divides, so sums land within Decimal rounding of 1, not on it.
TOLERANCE = Decimal("0.0000000000000000000000001")


def _all_subsets() -> list[dict[ComponentId, Decimal]]:
    declared = MODEL_V1.declared_weights
    subsets: list[dict[ComponentId, Decimal]] = []
    ids = list(declared)
    for size in range(1, len(ids) + 1):
        for combo in combinations(ids, size):
            subsets.append({key: declared[key] for key in combo})
    return subsets


SUBSETS = _all_subsets()


def test_the_sweep_is_actually_exhaustive() -> None:
    assert len(SUBSETS) == 2 ** len(MODEL_V1.declared_weights) - 1


@pytest.mark.parametrize("subset", SUBSETS, ids=lambda s: "+".join(sorted(str(k) for k in s)))
def test_weights_always_sum_to_one(subset: dict[ComponentId, Decimal]) -> None:
    """The invariant that stops missing signals from depressing every score."""
    solution = solve_weights(subset, CAP)
    assert abs(solution.total - ONE) <= TOLERANCE


@pytest.mark.parametrize("subset", SUBSETS, ids=lambda s: "+".join(sorted(str(k) for k in s)))
def test_no_weight_is_negative_or_absent(subset: dict[ComponentId, Decimal]) -> None:
    solution = solve_weights(subset, CAP)
    assert set(solution.weights) == set(subset)
    assert all(weight >= ZERO for weight in solution.weights.values())


@pytest.mark.parametrize("subset", SUBSETS, ids=lambda s: "+".join(sorted(str(k) for k in s)))
def test_cap_is_respected_whenever_it_is_satisfiable(
    subset: dict[ComponentId, Decimal],
) -> None:
    """With n components, a cap of c is only reachable when n * c >= 1."""
    solution = solve_weights(subset, CAP)
    satisfiable = Decimal(len(subset)) * CAP >= ONE

    if satisfiable:
        assert not solution.cap_relaxed
        assert all(weight <= CAP + TOLERANCE for weight in solution.weights.values())
    else:
        assert solution.cap_relaxed


def test_relaxation_splits_evenly() -> None:
    """Two components under a 0.35 cap can only reach 0.70; even split instead."""
    subset = {
        ComponentId.LIQUIDITY_DEPTH: Decimal("0.20"),
        ComponentId.MOMENTUM: Decimal("0.15"),
    }
    solution = solve_weights(subset, CAP)

    assert solution.cap_relaxed
    assert set(solution.weights.values()) == {ONE / Decimal(2)}


def test_ordering_is_preserved_so_results_are_deterministic() -> None:
    subset = {
        ComponentId.SURVIVAL_AGE: Decimal("0.08"),
        ComponentId.LIQUIDITY_DEPTH: Decimal("0.20"),
        ComponentId.MOMENTUM: Decimal("0.15"),
    }
    assert list(solve_weights(subset, CAP).weights) == list(subset)


def test_relative_ordering_survives_renormalisation() -> None:
    """A heavier declared weight must stay heavier once uncapped."""
    subset = {
        ComponentId.LIQUIDITY_DEPTH: Decimal("0.20"),
        ComponentId.MOMENTUM: Decimal("0.15"),
        ComponentId.TRADE_FLOW: Decimal("0.12"),
        ComponentId.VALUATION_STRUCTURE: Decimal("0.10"),
    }
    weights = solve_weights(subset, ONE).weights
    assert (
        weights[ComponentId.LIQUIDITY_DEPTH]
        > weights[ComponentId.MOMENTUM]
        > weights[ComponentId.TRADE_FLOW]
        > weights[ComponentId.VALUATION_STRUCTURE]
    )


def test_the_v1_available_set_lands_on_the_documented_weights() -> None:
    """The five available components renormalise from 0.65 to 1.0."""
    available = {
        ComponentId.LIQUIDITY_DEPTH: Decimal("0.20"),
        ComponentId.MOMENTUM: Decimal("0.15"),
        ComponentId.TRADE_FLOW: Decimal("0.12"),
        ComponentId.VALUATION_STRUCTURE: Decimal("0.10"),
        ComponentId.SURVIVAL_AGE: Decimal("0.08"),
    }
    weights = solve_weights(available, CAP).weights

    assert weights[ComponentId.LIQUIDITY_DEPTH].quantize(Decimal("0.001")) == Decimal("0.308")
    assert weights[ComponentId.MOMENTUM].quantize(Decimal("0.001")) == Decimal("0.231")
    assert weights[ComponentId.SURVIVAL_AGE].quantize(Decimal("0.001")) == Decimal("0.123")


def test_capping_redistributes_rather_than_orphaning_weight() -> None:
    """The gap the design review found: capped excess must go somewhere."""
    subset = {
        ComponentId.LIQUIDITY_DEPTH: Decimal("0.90"),
        ComponentId.MOMENTUM: Decimal("0.05"),
        ComponentId.TRADE_FLOW: Decimal("0.05"),
        ComponentId.VALUATION_STRUCTURE: Decimal("0.05"),
    }
    solution = solve_weights(subset, CAP)

    assert abs(solution.total - ONE) <= TOLERANCE
    assert solution.weights[ComponentId.LIQUIDITY_DEPTH] <= CAP + TOLERANCE
    # The excess landed on the others rather than vanishing.
    assert solution.weights[ComponentId.MOMENTUM] > Decimal("0.05")


def test_empty_input_is_well_defined() -> None:
    solution = solve_weights({}, CAP)
    assert solution.weights == {}
    assert solution.total == ZERO


def test_zero_total_falls_back_to_an_even_split() -> None:
    subset = {ComponentId.LIQUIDITY_DEPTH: ZERO, ComponentId.MOMENTUM: ZERO}
    solution = solve_weights(subset, CAP)

    assert solution.cap_relaxed
    assert abs(solution.total - ONE) <= TOLERANCE


def test_single_component_takes_everything() -> None:
    solution = solve_weights({ComponentId.SURVIVAL_AGE: Decimal("0.08")}, CAP)
    assert solution.cap_relaxed
    assert solution.weights[ComponentId.SURVIVAL_AGE] == ONE


def test_convergence_is_bounded() -> None:
    """The loop must terminate; four passes is the declared ceiling."""
    assert MAX_PASSES == 4
