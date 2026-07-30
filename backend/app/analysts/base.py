"""The analyst contract.

Phase 15 asks for six specialists behind one interface. The interface is the
point: once every analyst returns the same shape, the orchestrator can combine
them without knowing what any of them measures, and a seventh can be added
without touching the combination logic.

## The contract

Every analyst returns a `Reading`:

    score       0-100, or None when the analyst cannot see its subject
    confidence  0-100, how much the analyst trusts its own score
    evidence    the observations behind it, as named figures
    reason      one finished sentence, rendered here and displayed verbatim
    warnings    reasons *not* to act on this reading

`score` and `confidence` are separate on purpose and the distinction carries
most of the platform's honesty. A liquidity score of 80 built on four
observations and a liquidity score of 80 built on ninety are not the same
claim, and collapsing them into one number is how a product ends up sounding
certain about things it has barely seen.

## What an analyst may not do

No analyst returns a recommendation. `reason` describes what was observed;
it never says buy, sell, hold, or "consider". A test asserts this across every
analyst, because the boundary erodes through prose long before anyone writes
the word "buy".

## Purity

Analysts perform no I/O. They receive a `RadarSeries` — a projection of stored
observations — and return a `Reading`. No database, no network, no clock, no
randomness; time enters as an explicit `now` where it is needed at all. This is
the same discipline `services/scoring` and `app/radar` already hold, and
`test_analysts_purity.py` enforces it by parsing the AST.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from decimal import Decimal


class AnalystId(enum.StrEnum):
    """The six specialists. Persisted in API responses, so append-only."""

    LIQUIDITY = "liquidity"
    MOMENTUM = "momentum"
    HOLDERS = "holders"
    LIFECYCLE = "lifecycle"
    RISK = "risk"
    RESEARCH = "research"


class Severity(enum.StrEnum):
    """How loudly a warning should read."""

    INFO = "info"
    CAUTION = "caution"
    CRITICAL = "critical"


@dataclass(frozen=True, slots=True)
class RiskWarning:
    """A reason not to act on a reading.

    Not named `Warning` — that shadows the builtin, and a package that later
    imports the stdlib `warnings` module would be a debugging session nobody
    needs.
    """

    code: str
    severity: Severity
    message: str


@dataclass(frozen=True, slots=True)
class Evidence:
    """One observation behind a score, as a label and a figure.

    Deliberately not a free-form dict. A named, ordered list is what lets the
    UI render "liquidity grew 18% across 42 observations" without the client
    inventing the sentence, and it keeps the evidence auditable.
    """

    label: str
    value: str
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class Reading:
    """One analyst's complete verdict on one project."""

    analyst: AnalystId
    #: 0-100. `None` exactly when the analyst has no data source for this
    #: subject — never 0, because "cannot see" and "saw nothing" are different
    #: claims and only one of them is about the project.
    score: Decimal | None
    #: 0-100. How much the analyst trusts its own score. `None` when `score` is.
    confidence: Decimal | None
    #: A finished sentence. Rendered here; the client displays it verbatim.
    reason: str
    evidence: tuple[Evidence, ...] = ()
    warnings: tuple[RiskWarning, ...] = ()

    @property
    def available(self) -> bool:
        return self.score is not None

    @property
    def worst_severity(self) -> Severity | None:
        if not self.warnings:
            return None
        order = {Severity.INFO: 0, Severity.CAUTION: 1, Severity.CRITICAL: 2}
        return max(self.warnings, key=lambda w: order[w.severity]).severity

    @classmethod
    def unavailable(
        cls,
        analyst: AnalystId,
        *,
        reason: str,
        warnings: tuple[RiskWarning, ...] = (),
    ) -> Reading:
        """A reading from an analyst that has no data source.

        Reported rather than omitted. A missing analyst is invisible; an
        analyst that says "I cannot see this" is a fact the user can weigh,
        and it is the difference between a platform that is honest about its
        coverage and one that quietly looks complete.
        """
        return cls(
            analyst=analyst,
            score=None,
            confidence=None,
            reason=reason,
            warnings=warnings,
        )


def clamp(value: Decimal, low: Decimal = Decimal(0), high: Decimal = Decimal(100)) -> Decimal:
    """Bound a score to its declared range."""
    return max(low, min(high, value))


@dataclass(frozen=True, slots=True)
class AnalystMeta:
    """What an analyst is, published so its role is checkable."""

    id: AnalystId
    name: str
    question: str
    #: False when the platform holds no data for it at all.
    operational: bool
    #: Why it cannot operate, when it cannot.
    unavailable_reason: str | None = None
    evidence_fields: tuple[str, ...] = field(default_factory=tuple)
