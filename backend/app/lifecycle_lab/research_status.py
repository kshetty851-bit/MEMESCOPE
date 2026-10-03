"""Meme Lifecycle Lab — the research-status state machine and minimum-evidence gate.

docs/MEME_LIFECYCLE_LAB.md, "RESEARCH VERDICT STATES" and "MINIMUM EVIDENCE
REQUIREMENTS", implemented as written. The gate answers one question: *is
there enough forward evidence for an analysis to mean anything?* It does not
answer whether the strategy works, and nothing here can.

**The verdict is always UNCERTAIN.** The verdict engine (EDGE EXISTS / NO EDGE
/ WEAK EDGE / OVERFIT) is not built in this phase, so the two states that
presuppose one — ANALYZING and AUTHORITATIVE_RESULT — are *unreachable*:
``evaluate`` never returns them (``UNREACHABLE_STATES``), and the furthest it
can go is READY_FOR_ANALYSIS. They stay in the enum because the API contract
names them; the day an analysis run exists, they become reachable by adding a
transition here, in the open, not by a flag flipped elsewhere.

**Thresholds are fixed, a priori, and not tuned.** They were written into the
design doc before any result existed, from conventions already used in this
repo (the 25/50/100/200/500 sample ladder, the V6 protocol's >=100-trade
promotion floor and top-trade concentration rule). Loosening one after seeing a
result is precisely the selection bias the registry exists to prevent, so
``tests/unit/test_mll_research_status.py`` pins every constant to the doc's
table: a quiet edit fails the suite.

**Unmeasurable is unmet.** A requirement whose fact could not be measured is
``met=False`` with a reason; it is never assumed, and never read as zero.

Pure: no I/O, no clock, no randomness. ``now`` is a parameter.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import ROUND_HALF_EVEN, Decimal
from enum import StrEnum

# --------------------------------------------------------------------------
# Thresholds — pinned to the doc's "MINIMUM EVIDENCE REQUIREMENTS" table.
# --------------------------------------------------------------------------

#: Forward observation period: the experiment horizon (``MLL_EXPERIMENT_HORIZON_DAYS``
#: default). The 70/15/15 split is defined over it; an unfinished test segment
#: is not out-of-sample, so the span AND the experiment's ``data_cutoff`` must
#: both have passed. When the experiment is registered, its own horizon
#: (``data_cutoff - forward_start``) is what is enforced.
FORWARD_HORIZON_DAYS = 90
#: Independent forward meme events (one per episode). Below 100 the
#: event-level return distribution is anecdotal.
MIN_INDEPENDENT_EVENTS = 100
#: Revival + second-wave + third-wave events. The core hypothesis is about
#: *re*-activation; first waves alone cannot test it.
MIN_REVIVAL_EVENTS = 30
#: Closed baseline-arm trades, all segments: the repo-wide promotion floor
#: (V6 protocol).
MIN_BASELINE_TRADES = 100
#: Closed out-of-sample (test-segment) trades: the smallest OOS sample where a
#: profit factor is not dominated by a single trade.
MIN_OOS_TRADES = 30
#: Distinct memes with a trade. Guards against "it works because of one meme".
MIN_DISTINCT_MEMES = 10
#: The top meme's share of closed baseline trades. Same reason.
MAX_TOP_MEME_SHARE = Decimal("0.25")
#: Control arms B, C and D must have completed over the same window as the
#: baseline: "adds information" is only answerable against controls.
REQUIRED_CONTROL_ARMS: tuple[str, ...] = ("B", "C", "D")

#: COLLECTING while the forward span is shorter than this (too early to judge
#: any requirement); INSUFFICIENT_DATA afterwards until every requirement is met.
COLLECTING_DAYS = 7

#: A revival and a wave detected for one meme within this span are one episode:
#: a revival is, by construction, a wave that follows observed dormancy.
EPISODE_MERGE_WINDOW = timedelta(hours=24)

VERDICT_UNCERTAIN = "UNCERTAIN"
#: The verdict engine is not built in this phase.
VERDICT_ENGINE_AVAILABLE = False


class ResearchState(StrEnum):
    NOT_STARTED = "NOT_STARTED"
    COLLECTING = "COLLECTING"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    READY_FOR_ANALYSIS = "READY_FOR_ANALYSIS"
    #: Unreachable in this phase (no analysis run exists).
    ANALYZING = "ANALYZING"
    #: Unreachable in this phase (no verdict engine exists).
    AUTHORITATIVE_RESULT = "AUTHORITATIVE_RESULT"


#: States ``evaluate`` can never return until a verdict engine exists.
UNREACHABLE_STATES: frozenset[ResearchState] = frozenset(
    {ResearchState.ANALYZING, ResearchState.AUTHORITATIVE_RESULT}
)

#: Event types that open a wave: one per wave by ``events.py``'s episode keys.
WAVE_EVENT_TYPES = frozenset({"new_attention_wave", "second_wave", "third_wave"})
REVIVAL_EVENT_TYPE = "meme_revival"
#: What the revival requirement counts (doc: MEME_REVIVAL + SECOND_WAVE + THIRD_WAVE).
LATER_WAVE_EVENT_TYPES = frozenset({"meme_revival", "second_wave", "third_wave"})
#: Everything the repository must fetch to answer both event requirements.
EPISODE_EVENT_TYPES = WAVE_EVENT_TYPES | {REVIVAL_EVENT_TYPE}

# Requirement keys, in display order.
KEY_FORWARD_PERIOD = "forward_period"
KEY_INDEPENDENT_EVENTS = "independent_events"
KEY_REVIVAL_EVENTS = "revival_events"
KEY_BASELINE_TRADES = "baseline_trades"
KEY_OOS_TRADES = "oos_trades"
KEY_DISTINCT_MEMES = "distinct_memes"
KEY_CONCENTRATION = "concentration"
KEY_CONTROL_ARMS = "control_arms"

REQUIREMENT_KEYS: tuple[str, ...] = (
    KEY_FORWARD_PERIOD,
    KEY_INDEPENDENT_EVENTS,
    KEY_REVIVAL_EVENTS,
    KEY_BASELINE_TRADES,
    KEY_OOS_TRADES,
    KEY_DISTINCT_MEMES,
    KEY_CONCENTRATION,
    KEY_CONTROL_ARMS,
)

_LABELS: dict[str, str] = {
    KEY_FORWARD_PERIOD: "Forward observation period",
    KEY_INDEPENDENT_EVENTS: "Independent meme events",
    KEY_REVIVAL_EVENTS: "Revival and later-wave events",
    KEY_BASELINE_TRADES: "Closed trades (baseline arm, all segments)",
    KEY_OOS_TRADES: "Closed out-of-sample trades (test segment)",
    KEY_DISTINCT_MEMES: "Distinct memes with trades",
    KEY_CONCENTRATION: "Single-meme concentration",
    KEY_CONTROL_ARMS: "Control arms completed",
}


# --------------------------------------------------------------------------
# Inputs
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ExperimentRef:
    """The pre-registered baseline experiment, as far as the gate cares."""

    experiment_key: str
    #: End of the pre-registered horizon. None if the row carries none.
    data_cutoff: datetime | None


@dataclass(frozen=True, slots=True)
class GateFacts:
    """What the database says, measured at ``now`` and never past it.

    ``None`` means *could not be measured* (not zero): the matching
    requirement is unmet, with ``reasons[key]`` (or a generic one) as the
    explanation.
    """

    forward_span: timedelta | None = None
    independent_events: int | None = None
    revival_events: int | None = None
    baseline_trades: int | None = None
    oos_trades: int | None = None
    distinct_memes: int | None = None
    #: Top meme's share of closed baseline trades, 0..1.
    top_meme_share: Decimal | None = None
    #: Arms among ``REQUIRED_CONTROL_ARMS`` whose forward run completed over
    #: the baseline's window.
    control_arms_completed: frozenset[str] | None = None
    #: Requirement key -> why its fact is None.
    reasons: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Requirement:
    key: str
    label: str
    threshold: str
    observed: str | None
    met: bool
    reason: str | None


@dataclass(frozen=True, slots=True)
class ResearchStatus:
    state: ResearchState
    verdict: str
    verdict_engine_available: bool
    forward_start: datetime | None
    forward_days: float | None
    experiment_key: str | None
    requirements: tuple[Requirement, ...]
    explanation: str


# --------------------------------------------------------------------------
# Episode counting (pure, so it is testable without a database)
# --------------------------------------------------------------------------

EpisodeEvent = tuple[str, str, datetime]  # (meme_id, event_type, detected_at)


def count_independent_events(events: Iterable[EpisodeEvent]) -> int:
    """Episodes, not rows.

    Wave events fire once per wave (``events.py`` episode keys), so each is an
    episode. A revival detected within ``EPISODE_MERGE_WINDOW`` of a wave on
    the same meme is that wave seen from another detector — one episode; a
    revival with no wave beside it stands alone. Duplicate rows (the same
    meme, type and instant written under two detector versions) are one.
    """
    unique = set(events)
    waves: dict[str, list[datetime]] = {}
    for meme_id, event_type, at in unique:
        if event_type in WAVE_EVENT_TYPES:
            waves.setdefault(meme_id, []).append(at)
    count = sum(len(v) for v in waves.values())
    for meme_id, event_type, at in unique:
        if event_type != REVIVAL_EVENT_TYPE:
            continue
        if not any(abs(at - w) <= EPISODE_MERGE_WINDOW for w in waves.get(meme_id, ())):
            count += 1
    return count


def count_later_wave_events(events: Iterable[EpisodeEvent]) -> int:
    """Revival + second wave + third wave rows, deduplicated as above."""
    return sum(1 for _m, event_type, _t in set(events) if event_type in LATER_WAVE_EVENT_TYPES)


# --------------------------------------------------------------------------
# The gate
# --------------------------------------------------------------------------


def _days(span: timedelta) -> Decimal:
    return (Decimal(span.total_seconds()) / Decimal(86400)).quantize(
        Decimal("0.1"), rounding=ROUND_HALF_EVEN
    )


def _pct(fraction: Decimal) -> str:
    return f"{(fraction * 100).quantize(Decimal('0.1'), rounding=ROUND_HALF_EVEN)}%"


def _requirement(
    key: str, threshold: str, observed: str | None, unmet: str | None
) -> Requirement:
    """A measured requirement: ``unmet`` is the reason it is not met, or None if it is."""
    return Requirement(
        key=key,
        label=_LABELS[key],
        threshold=threshold,
        observed=observed,
        met=unmet is None,
        reason=unmet,
    )


def _unmeasured(key: str, threshold: str, facts: GateFacts, default: str) -> Requirement:
    return Requirement(
        key=key,
        label=_LABELS[key],
        threshold=threshold,
        observed=None,
        met=False,
        reason=facts.reasons.get(key, default),
    )


def _at_least(
    key: str, threshold_n: int, observed: int | None, facts: GateFacts
) -> Requirement:
    threshold = f"at least {threshold_n}"
    if observed is None:
        return _unmeasured(key, threshold, facts, "Could not be measured.")
    met = observed >= threshold_n
    return Requirement(
        key=key,
        label=_LABELS[key],
        threshold=threshold,
        observed=str(observed),
        met=met,
        reason=None if met else f"{observed} of {threshold_n} observed.",
    )


def _horizon_days(forward_start: datetime | None, experiment: ExperimentRef | None) -> int:
    if (
        forward_start is not None
        and experiment is not None
        and experiment.data_cutoff is not None
    ):
        return max(1, (experiment.data_cutoff - forward_start).days)
    return FORWARD_HORIZON_DAYS


def _forward_period(
    *,
    now: datetime,
    forward_start: datetime | None,
    experiment: ExperimentRef | None,
    facts: GateFacts,
) -> Requirement:
    key = KEY_FORWARD_PERIOD
    horizon = _horizon_days(forward_start, experiment)
    threshold = f"{horizon} days and data_cutoff passed"
    if facts.forward_span is None:
        return _unmeasured(key, threshold, facts, "Forward span could not be measured.")
    observed = f"{_days(facts.forward_span)} days"
    span_days = _days(facts.forward_span)
    if facts.forward_span < timedelta(days=horizon):
        return _requirement(
            key, threshold, observed, f"{span_days} of {horizon} days observed."
        )
    if experiment is None or experiment.data_cutoff is None:
        return _requirement(
            key,
            threshold,
            observed,
            "No pre-registered experiment with a data cutoff exists yet.",
        )
    if now < experiment.data_cutoff:
        return _requirement(
            key,
            threshold,
            observed,
            f"The data cutoff ({experiment.data_cutoff.isoformat()}) has not passed.",
        )
    return _requirement(key, threshold, observed, None)


def _concentration(facts: GateFacts) -> Requirement:
    key = KEY_CONCENTRATION
    threshold = f"top meme at most {_pct(MAX_TOP_MEME_SHARE)} of trades"
    if facts.top_meme_share is None:
        return _unmeasured(key, threshold, facts, "No closed baseline trades to measure.")
    met = facts.top_meme_share <= MAX_TOP_MEME_SHARE
    return Requirement(
        key=key,
        label=_LABELS[key],
        threshold=threshold,
        observed=_pct(facts.top_meme_share),
        met=met,
        reason=None if met else "One meme accounts for too large a share of trades.",
    )


def _control_arms(facts: GateFacts) -> Requirement:
    key = KEY_CONTROL_ARMS
    threshold = ", ".join(REQUIRED_CONTROL_ARMS)
    done = facts.control_arms_completed
    if done is None:
        return _unmeasured(key, threshold, facts, "Control arms could not be measured.")
    have = [a for a in REQUIRED_CONTROL_ARMS if a in done]
    met = len(have) == len(REQUIRED_CONTROL_ARMS)
    missing = [a for a in REQUIRED_CONTROL_ARMS if a not in done]
    return Requirement(
        key=key,
        label=_LABELS[key],
        threshold=threshold,
        observed=", ".join(have) if have else "none",
        met=met,
        reason=None
        if met
        else f"Not completed over the baseline window: {', '.join(missing)}.",
    )


def _requirements(
    *,
    now: datetime,
    forward_start: datetime | None,
    experiment: ExperimentRef | None,
    facts: GateFacts,
) -> tuple[Requirement, ...]:
    return (
        _forward_period(
            now=now, forward_start=forward_start, experiment=experiment, facts=facts
        ),
        _at_least(
            KEY_INDEPENDENT_EVENTS, MIN_INDEPENDENT_EVENTS, facts.independent_events, facts
        ),
        _at_least(KEY_REVIVAL_EVENTS, MIN_REVIVAL_EVENTS, facts.revival_events, facts),
        _at_least(KEY_BASELINE_TRADES, MIN_BASELINE_TRADES, facts.baseline_trades, facts),
        _at_least(KEY_OOS_TRADES, MIN_OOS_TRADES, facts.oos_trades, facts),
        _at_least(KEY_DISTINCT_MEMES, MIN_DISTINCT_MEMES, facts.distinct_memes, facts),
        _concentration(facts),
        _control_arms(facts),
    )


def _not_started_reason(
    *, now: datetime, lab_enabled: bool, forward_start: datetime | None
) -> str | None:
    if not lab_enabled:
        return "The lifecycle lab is switched off."
    if forward_start is None:
        return "MLL_FORWARD_START is not set."
    if forward_start > now:
        return f"The forward start ({forward_start.isoformat()}) is in the future."
    return None


def evaluate(
    *,
    now: datetime,
    lab_enabled: bool,
    forward_start: datetime | None,
    experiment: ExperimentRef | None,
    facts: GateFacts,
) -> ResearchStatus:
    """The research state at ``now``.

    ``NOT_STARTED`` -> ``COLLECTING`` (forward span < 7 days) ->
    ``INSUFFICIENT_DATA`` (any requirement unmet) -> ``READY_FOR_ANALYSIS``
    (every requirement met, data cutoff passed). Never ``ANALYZING`` or
    ``AUTHORITATIVE_RESULT``, and the verdict is always ``UNCERTAIN``.
    """
    experiment_key = None if experiment is None else experiment.experiment_key

    blocked = _not_started_reason(
        now=now, lab_enabled=lab_enabled, forward_start=forward_start
    )
    if blocked is not None:
        # Nothing before the epoch counts, so nothing can be said to be met —
        # whatever the facts happen to contain.
        reqs = tuple(
            Requirement(
                r.key, r.label, r.threshold, None, False, "Forward collection has not started."
            )
            for r in _requirements(
                now=now, forward_start=forward_start, experiment=experiment, facts=GateFacts()
            )
        )
        return ResearchStatus(
            state=ResearchState.NOT_STARTED,
            verdict=VERDICT_UNCERTAIN,
            verdict_engine_available=VERDICT_ENGINE_AVAILABLE,
            forward_start=forward_start,
            forward_days=None
            if forward_start is None
            else round(max(0.0, (now - forward_start).total_seconds() / 86400.0), 2),
            experiment_key=experiment_key,
            requirements=reqs,
            explanation=f"Forward collection has not started. {blocked} "
            "No data counts toward a verdict yet; the verdict is UNCERTAIN.",
        )

    assert forward_start is not None  # NOT_STARTED covers None
    span = facts.forward_span if facts.forward_span is not None else now - forward_start
    facts = GateFacts(
        forward_span=span,
        independent_events=facts.independent_events,
        revival_events=facts.revival_events,
        baseline_trades=facts.baseline_trades,
        oos_trades=facts.oos_trades,
        distinct_memes=facts.distinct_memes,
        top_meme_share=facts.top_meme_share,
        control_arms_completed=facts.control_arms_completed,
        reasons=facts.reasons,
    )
    reqs = _requirements(
        now=now, forward_start=forward_start, experiment=experiment, facts=facts
    )
    unmet = [r for r in reqs if not r.met]
    forward_days = round(max(0.0, span.total_seconds() / 86400.0), 2)
    since = f"{forward_start:%Y-%m-%d}"

    if span < timedelta(days=COLLECTING_DAYS):
        state = ResearchState.COLLECTING
        explanation = (
            f"Forward collection began {since}; {_days(span)} days observed. It is too "
            f"early to judge any requirement (the gate is evaluated from {COLLECTING_DAYS} "
            "days). The verdict is UNCERTAIN."
        )
    elif unmet:
        state = ResearchState.INSUFFICIENT_DATA
        explanation = (
            f"{len(reqs) - len(unmet)} of {len(reqs)} minimum-evidence requirements are met "
            f"after {_days(span)} days of forward data. Unmet: "
            + "; ".join(r.label for r in unmet)
            + ". The verdict is UNCERTAIN."
        )
    else:
        state = ResearchState.READY_FOR_ANALYSIS
        explanation = (
            f"Every minimum-evidence requirement is met and the data cutoff has passed "
            f"({_days(span)} days of forward data). The verdict engine is not built in "
            "this phase, so the verdict remains UNCERTAIN."
        )

    # The two states below presuppose a verdict engine. They are not reachable
    # from any branch above; this makes that a checked fact, not a hope.
    assert state not in UNREACHABLE_STATES
    return ResearchStatus(
        state=state,
        verdict=VERDICT_UNCERTAIN,
        verdict_engine_available=VERDICT_ENGINE_AVAILABLE,
        forward_start=forward_start,
        forward_days=forward_days,
        experiment_key=experiment_key,
        requirements=reqs,
        explanation=explanation,
    )
