"""EXPERIMENT INTEGRITY — is the Karthik wallet's result worth believing?

§11, and the one number in this whole feature that is easiest to get wrong.

── WHAT IT MEASURES, AND WHAT IT REFUSES TO MEASURE ─────────────────────

It scores **whether the experiment ran properly**, never whether it made
money. A wallet down 40% with complete data, fresh quotes and consistent
accounting scores near 100; a wallet up 300% that missed a third of its
opportunities and booked two targets it cannot evidence scores badly. Those are
the correct answers, and conflating them would turn a data-quality instrument
into a second P&L display nobody needs.

── EVERY DEDUCTION IS DECLARED, NOT INVENTED ────────────────────────────

The brief says "do not invent arbitrary values; use explicit, documented
deductions", so the score is not a weighted average of normalised factors — it
is 100 minus a list of named penalties, and the list is published in the API
response next to the number. A reader who disagrees with the score can see
exactly which line they disagree with.

── AN UNMEASURED FACTOR NEVER DEDUCTS, AND NEVER FLATTERS ───────────────

This follows `hq_ops`: "we looked and it is fine" and "we could not look" are
different answers and must not collapse. An unmeasured factor contributes zero
penalty *and* is counted in `unmeasured`, which is published beside the score.
When nothing at all could be measured the score is `None` — not 100, which
would be a claim, and not 0, which would be an accusation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

#: The bands, and where they start. Named rather than inlined so the panel and
#: the report cannot disagree about what "DEGRADED" means.
HEALTHY_AT = 90
DEGRADED_AT = 70

Band = Literal["HEALTHY", "DEGRADED", "UNRELIABLE", "NOT MEASURED"]


@dataclass(frozen=True, slots=True)
class Factor:
    """One thing that can make the experiment less trustworthy.

    `max_penalty` is the whole of a factor's influence. It is declared here so
    the worst possible score is arithmetic a reader can check — the seven
    factors sum to 100, so a completely broken experiment scores 0 and cannot
    go below it by accident.
    """

    key: str
    label: str
    max_penalty: int
    #: What a full penalty means, in a sentence. Published with the score.
    meaning: str


FACTORS: tuple[Factor, ...] = (
    Factor(
        key="event_completeness",
        label="Track Record event completeness",
        max_penalty=22,
        meaning="Eligible Track Record admissions that produced no Karthik decision at all.",
    ),
    Factor(
        key="duplicate_events",
        label="Duplicate-event rate",
        max_penalty=14,
        meaning="The same admission processed more than once, or two positions for one mint.",
    ),
    Factor(
        key="entry_latency",
        label="Entry-processing latency",
        max_penalty=12,
        meaning="Delay between a Track Record admission and Karthik's decision on it.",
    ),
    Factor(
        key="quote_freshness",
        label="Quote and monitoring freshness",
        max_penalty=18,
        meaning="Open positions being valued from prices older than the staleness window.",
    ),
    Factor(
        key="accounting_consistency",
        label="Accounting consistency",
        max_penalty=20,
        meaning="Cash plus executable open value failing to reconcile with reported equity.",
    ),
    Factor(
        key="target_provenance",
        label="Target execution provenance",
        max_penalty=8,
        meaning="A 1.25x fill that cannot name the observed price that triggered it.",
    ),
    Factor(
        key="worker_uptime",
        label="Worker uptime and unresolved incidents",
        max_penalty=6,
        meaning="Karthik's own loop not running, or incidents left open without a decision.",
    ),
)

FACTOR_BY_KEY = {factor.key: factor for factor in FACTORS}

#: Asserted at import. The factors are the whole of the score, so if somebody
#: adds one without rebalancing the others the failure should be a crash on
#: boot rather than a score that silently cannot reach 100 or can go negative.
_TOTAL = sum(factor.max_penalty for factor in FACTORS)
if _TOTAL != 100:  # pragma: no cover - guarded at import
    raise ValueError(f"integrity factors must sum to 100 penalty points, got {_TOTAL}")


@dataclass(frozen=True, slots=True)
class Deduction:
    """A factor's actual reading, for one evaluation."""

    factor: str
    label: str
    #: Points taken off. Zero for a factor that was measured and found clean.
    penalty: int
    #: False when the factor could not be read at all. Never rounded to clean.
    measured: bool
    #: The evidence, in a sentence. This is what makes the score arguable.
    detail: str


@dataclass(frozen=True, slots=True)
class Integrity:
    """The published score and everything behind it."""

    #: `None` when nothing could be measured. Never defaulted to a number.
    score: int | None
    band: Band
    #: One line for the room's signage and the report's headline.
    headline: str
    deductions: list[Deduction] = field(default_factory=list)
    unmeasured: int = 0


def unmeasured(reason: str) -> Integrity:
    """The score when there is nothing to score.

    Used whenever Karthik is unbound. It returns every factor as unmeasured
    rather than an empty list, because a panel showing seven greyed rows says
    "here is what would be measured" where an empty panel says "there is
    nothing to measure", and only the first of those is true.
    """
    return Integrity(
        score=None,
        band="NOT MEASURED",
        headline=reason,
        deductions=[
            Deduction(
                factor=factor.key,
                label=factor.label,
                penalty=0,
                measured=False,
                detail=reason,
            )
            for factor in FACTORS
        ],
        unmeasured=len(FACTORS),
    )


def score(deductions: list[Deduction]) -> Integrity:
    """Turn a list of readings into the published number.

    Clamps to 0 to 100 rather than trusting the caller. The factor totals already
    make an out-of-range value impossible, so the clamp is a guard on a future
    edit rather than on today's arithmetic — which is exactly when a clamp
    earns its line.
    """
    measured = [d for d in deductions if d.measured]
    missing = len(deductions) - len(measured)

    if not measured:
        return Integrity(
            score=None,
            band="NOT MEASURED",
            headline="No integrity factor could be measured.",
            deductions=deductions,
            unmeasured=missing,
        )

    for deduction in deductions:
        limit = FACTOR_BY_KEY[deduction.factor].max_penalty
        if deduction.penalty > limit:  # pragma: no cover - guarded by callers
            raise ValueError(
                f"{deduction.factor} deducted {deduction.penalty} of a permitted {limit}"
            )

    value = max(0, min(100, 100 - sum(d.penalty for d in measured)))
    band: Band = (
        "HEALTHY"
        if value >= HEALTHY_AT
        else "DEGRADED"
        if value >= DEGRADED_AT
        else "UNRELIABLE"
    )

    worst = max(measured, key=lambda d: d.penalty)
    headline = (
        f"{band} — no factor is deducting."
        if worst.penalty == 0
        else f"{band} — {worst.label.lower()} is the largest deduction ({worst.penalty})."
    )
    return Integrity(
        score=value,
        band=band,
        headline=headline,
        deductions=deductions,
        unmeasured=missing,
    )
