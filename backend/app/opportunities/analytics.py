"""How each provider has actually performed. Derived, never stored.

Every figure here is computed from `opportunity_signals` and `opportunities` at
read time. Nothing is written, no counter is incremented anywhere in the write
path, and no table is added: a stored counter is a second copy of a fact the
history already holds, and the two drift the first time a backfill, a replay or
a failed transaction touches one and not the other. The permanent record is the
record; analytics is a question asked of it.

Pure, like the providers it measures. Raw counts arrive from the repository and
the derivations happen here, so every ratio can be exercised against literals —
including the ones that must refuse to answer.

**Precision is defined over predictive signals only.** "Of the calls this
provider made, how many turned out right" is a question about a *prediction*,
and half the shipped signals are not predictions — a fresh graduation reports a
change that already completed. Scoring those for precision would divide a
structurally-zero numerator by its invalidations and publish 0.00 against a
provider that never made a forecast to miss: arithmetically correct, completely
false, and the worst kind of number this platform can emit.

So a provider that emits no predictive signal type reports precision
unavailable, with that as the reason. A provider that emits one reports it as
soon as an outcome lands, and reports unavailable — never zero — until then.
See `outcomes.py` for which types are predictive and why.

Invalidations on factual signals are counted separately as **contradictions**:
a graduated token seen back on a bonding curve says the reading was an indexing
artefact. That is a data correction and belongs nowhere near a hit rate.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

#: Why precision cannot be answered yet. Carried in the response rather than
#: documented elsewhere, so a reader of the API sees the reason at the point of
#: the gap.
NO_OUTCOMES_REASON = (
    "No predictive signal from this provider has resolved yet. Precision needs "
    "a realised or invalidated outcome to divide by."
)

#: Why precision does not apply at all. A different fact from "not yet
#: measured", and reported differently so nobody waits for a number that will
#: never come.
NOT_PREDICTIVE_REASON = (
    "This provider reports changes that have already completed, not forecasts. "
    "There is no prediction to be right or wrong about, so precision does not "
    "apply to it."
)

_HUNDREDTH = Decimal("0.01")


@dataclass(frozen=True, slots=True)
class ProviderTotals:
    """Raw counts for one provider, exactly as the database reports them.

    A projection, not a metric: every field is a count or a sum the repository
    can produce in one grouped pass. Keeping the aggregation this dumb is what
    lets the derivations below stay pure and literal-testable.
    """

    provider_id: str
    signals: int = 0
    opportunities: int = 0
    confirmed: int = 0
    expired: int = 0
    closed: int = 0
    #: Outcomes on *predictive* signals only — the precision denominator.
    realised: int = 0
    invalidated: int = 0
    #: Invalidations on factual signals. A correction to an observation, never
    #: a failed forecast, so it is kept out of every ratio.
    contradicted: int = 0
    #: Sum of confidence over every signal the provider has emitted. Summed
    #: rather than averaged in SQL so the divisor is visible here.
    confidence_total: Decimal = Decimal(0)
    #: Sum of (closed_at - detected_at) in seconds, over closed generations
    #: only. An opportunity that is still live has no lifetime yet, and
    #: counting it as zero would drag the average toward a claim nobody made.
    lifetime_seconds_total: Decimal = Decimal(0)
    lifetime_samples: int = 0


@dataclass(frozen=True, slots=True)
class ProviderAnalytics:
    """One provider's measured record. Every ratio is optional on purpose."""

    provider_id: str
    name: str
    operational: bool
    #: Why the provider cannot run at all, if it cannot. Distinct from a metric
    #: being unavailable: this one is about the input, not the outcome.
    unavailable_reason: str | None
    signals: int
    opportunities: int
    confirmed: int
    expired: int
    closed: int
    contradicted: int
    average_confidence: Decimal | None
    average_lifetime_seconds: int | None
    hit_rate: Decimal | None
    precision: Decimal | None
    precision_unavailable_reason: str | None


def _ratio(numerator: int, denominator: int) -> Decimal | None:
    """A share of a whole, or `None` when there is no whole.

    Zero and unknown are different claims. A provider that has emitted nothing
    has not achieved a hit rate of zero — it has no hit rate, and reporting 0.00
    would read as "tried and failed" rather than "never ran".
    """
    if denominator <= 0:
        return None
    return (Decimal(numerator) / Decimal(denominator)).quantize(
        _HUNDREDTH, rounding=ROUND_HALF_UP
    )


def _precision_gap(predictive: bool, outcomes: int) -> str | None:
    """Why there is no precision, when there is none. Two distinct reasons."""
    if not predictive:
        return NOT_PREDICTIVE_REASON
    return None if outcomes > 0 else NO_OUTCOMES_REASON


def _mean(total: Decimal, samples: int) -> Decimal | None:
    if samples <= 0:
        return None
    return (total / Decimal(samples)).quantize(_HUNDREDTH, rounding=ROUND_HALF_UP)


def summarise(
    totals: ProviderTotals,
    *,
    name: str,
    operational: bool,
    unavailable_reason: str | None,
    predictive: bool = True,
) -> ProviderAnalytics:
    """Turn one provider's raw counts into its measured record.

    `predictive` says whether this provider forecasts anything at all. It comes
    from the provider's declared `emits`, not from whether outcomes happen to
    exist — a provider that has simply not resolved a signal yet is a different
    fact from one that never could.
    """
    outcomes = totals.realised + totals.invalidated
    lifetime = _mean(totals.lifetime_seconds_total, totals.lifetime_samples)

    return ProviderAnalytics(
        provider_id=totals.provider_id,
        name=name,
        operational=operational,
        unavailable_reason=unavailable_reason,
        signals=totals.signals,
        opportunities=totals.opportunities,
        confirmed=totals.confirmed,
        expired=totals.expired,
        closed=totals.closed,
        contradicted=totals.contradicted,
        average_confidence=_mean(totals.confidence_total, totals.signals),
        # Seconds are integral in the response: the average lifetime of a
        # 48-hour signal does not become more truthful with two decimal places.
        average_lifetime_seconds=int(lifetime) if lifetime is not None else None,
        # Reached the confirmation bar at least once, over everything emitted.
        # A claim about the provider's own consistency — not about whether the
        # market agreed, which is precision's question and cannot be answered.
        hit_rate=_ratio(totals.confirmed, totals.signals),
        precision=_ratio(totals.realised, outcomes) if predictive else None,
        precision_unavailable_reason=_precision_gap(predictive, outcomes),
    )
