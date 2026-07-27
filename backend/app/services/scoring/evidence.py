"""Evidence: how much of the picture we actually have.

Evidence is the time-invariant half of confidence. It answers "how much do we
know about this token?" and is stored. The other half - freshness, "how recently
did we look?" - decays with wall-clock time and is applied at read time, because
a stored freshness is stale the moment it is written.

Two factors, multiplied rather than added:

  * **coverage** - the share of declared model weight that could actually be
    evaluated. In v1 this cannot exceed 0.65, because contract safety, holder
    distribution, smart money, and narrative have no data source yet.
  * **depth** - whether we have enough observations for the window-based signals
    to mean anything.

Multiplicative because either being zero should collapse the result. A token
with flawless market data and one observation has been seen for one instant; a
token with rich history and no liquidity data is half-invisible. Adding would
let a strong factor mask an absent one, which is the failure this axis exists to
prevent.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal

from app.services.scoring.components.base import ComponentId, ComponentResult
from app.services.scoring.explain import ReasonCode
from app.services.scoring.normalisers import HUNDRED, ONE, ZERO, clamp, power

#: Depth is discounted more gently than coverage: a short history is a weaker
#: objection than a missing signal, since observations accumulate on their own.
DEPTH_EXPONENT = Decimal("0.75")
COVERAGE_EXPONENT = ONE


@dataclass(frozen=True, slots=True)
class EvidenceAssessment:
    coverage: Decimal  # 0-1
    depth: Decimal  # 0-1
    evidence: Decimal  # 0-100
    limiting_reason: ReasonCode | None

    @property
    def coverage_score(self) -> Decimal:
        """Coverage on the 0-100 scale the database stores."""
        return self.coverage * HUNDRED


def coverage_of(
    results: Sequence[ComponentResult], declared: Mapping[ComponentId, Decimal]
) -> Decimal:
    """Share of declared weight that produced a usable score."""
    total = sum(declared.values(), start=ZERO)
    if total <= ZERO:
        return ZERO
    available = sum(
        (declared.get(result.id, ZERO) for result in results if result.available),
        start=ZERO,
    )
    return clamp(available / total, ZERO, ONE)


def depth_of(observations: int, required: int) -> Decimal:
    """How close the window is to holding enough observations."""
    if required <= 0:
        return ONE
    return clamp(Decimal(max(observations, 0)) / Decimal(required), ZERO, ONE)


def assess(
    results: Sequence[ComponentResult],
    declared: Mapping[ComponentId, Decimal],
    *,
    observations: int,
    required_observations: int,
) -> EvidenceAssessment:
    """Combine coverage and depth into a stored evidence figure.

    The limiting factor is reported so the UI can say *why* confidence is low
    rather than showing an unexplained number. Ties go to coverage, which is the
    harder problem: more observations arrive by waiting, missing signals do not.
    """
    coverage = coverage_of(results, declared)
    depth = depth_of(observations, required_observations)

    evidence = HUNDRED * power(coverage, COVERAGE_EXPONENT) * power(depth, DEPTH_EXPONENT)

    limiting: ReasonCode | None = None
    if coverage < ONE or depth < ONE:
        limiting = (
            ReasonCode.CONFIDENCE_LIMITED_BY_COVERAGE
            if coverage <= depth
            else ReasonCode.CONFIDENCE_LIMITED_BY_HISTORY
        )

    return EvidenceAssessment(
        coverage=coverage,
        depth=depth,
        evidence=clamp(evidence),
        limiting_reason=limiting,
    )
