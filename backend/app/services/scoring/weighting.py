"""Turning declared weights into effective ones when components are missing.

The model declares a full target weight vector including signals that do not
exist yet. When only some components are available, their weights are
renormalised to sum to 1.0 - otherwise every score would be systematically
depressed by the missing mass, which would look like "this token is mediocre"
rather than "we cannot see most of it".

Renormalisation alone is not enough. Pushing a single component to a dominant
share would turn the engine into a one-signal oracle exactly when it knows
least, so `max_single_contribution` caps any one weight. That cap creates the
question this module exists to answer: **where does the capped excess go?**

The algorithm:

  1. Renormalise available weights to sum to 1.0.
  2. Cap anything above the limit; record the excess.
  3. Redistribute the excess proportionally among the uncapped components.
  4. Repeat from 2 until stable, at most `MAX_PASSES` times.
  5. If the cap is arithmetically unsatisfiable (`n * cap < 1`), relax it and
     split evenly - and say so, via `WEIGHT_CAP_RELAXED`.

Weights sum to 1.0 up to Decimal rounding at 28 significant digits - `1/3`
summed three times is not exactly one, and pretending otherwise would make a
false invariant. The *exact* reconciliation guarantee lives one level up, in the
engine's quantisation step, where the rounding residual is absorbed deliberately
rather than hoped away.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal

from app.services.scoring.components.base import ComponentId
from app.services.scoring.normalisers import ONE, ZERO

MAX_PASSES = 4


@dataclass(frozen=True, slots=True)
class WeightSolution:
    weights: Mapping[ComponentId, Decimal]
    cap_relaxed: bool

    @property
    def total(self) -> Decimal:
        return sum(self.weights.values(), start=ZERO)


def solve_weights(declared: Mapping[ComponentId, Decimal], cap: Decimal) -> WeightSolution:
    """Renormalise `declared` to sum to 1.0, respecting `cap` where possible.

    `declared` holds only the *available* components' declared weights. Insertion
    order is preserved so the result is deterministic; a dict comprehension over
    an unordered set would make the residual land somewhere different run to run.
    """
    if not declared:
        return WeightSolution(weights={}, cap_relaxed=False)

    total = sum(declared.values(), start=ZERO)
    if total <= ZERO:
        # Degenerate but well-defined: split evenly rather than divide by zero.
        even = ONE / Decimal(len(declared))
        return WeightSolution(weights=dict.fromkeys(declared, even), cap_relaxed=True)

    weights = {key: value / total for key, value in declared.items()}

    # With n components, no allocation can respect the cap unless n * cap >= 1.
    # Two components under a 0.35 cap can only ever reach 0.70 between them.
    if Decimal(len(weights)) * cap < ONE:
        even = ONE / Decimal(len(weights))
        return WeightSolution(weights=dict.fromkeys(weights, even), cap_relaxed=True)

    for _ in range(MAX_PASSES):
        excess = ZERO
        uncapped: list[ComponentId] = []
        for key, value in weights.items():
            if value > cap:
                excess += value - cap
                weights[key] = cap
            else:
                uncapped.append(key)

        if excess <= ZERO or not uncapped:
            break

        headroom = sum((cap - weights[key] for key in uncapped), start=ZERO)
        if headroom <= ZERO:  # pragma: no cover - unreachable, see below
            # Zero headroom needs every uncapped weight sitting exactly at the
            # cap while another exceeds it, which would put the total above
            # `n * cap >= 1` - impossible once the weights have been
            # renormalised to sum to 1. Kept so that a future change to the
            # guard above fails safe instead of dividing by zero.
            break

        # Proportional to remaining headroom, so no component is pushed over the
        # cap by the redistribution itself.
        for key in uncapped:
            weights[key] += excess * (cap - weights[key]) / headroom

    return WeightSolution(weights=weights, cap_relaxed=False)
