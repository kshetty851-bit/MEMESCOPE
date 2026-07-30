"""Change detection — the difference between two observations of a project.

## The only question this module answers

*Is this change worth interrupting someone for?*

Almost nothing is. A platform that emits an event whenever a number moves
teaches users to ignore it within a week, and an ignored alert channel is worse
than no alert channel because it also carries the ones that mattered. So the
default here is silence, and every event has to earn its place past an explicit
threshold.

## What is deliberately not an event

**Price.** It is the single noisiest series the platform holds and the one
users can already see everywhere else. A price move that means something shows
up here as a *momentum* or *liquidity* change detected by an analyst — with the
evidence attached — or it does not show up at all.

**Score drift.** Scores move continuously as observations arrive. Only a move
past `MATERIAL_SCORE_DELTA` counts, which is the scoring engine's own
materiality threshold, reused rather than re-decided so this module and
`token_score_history` agree about the word "changed".

## Purity

`detect()` is a pure function of `(previous, current)`. No I/O, no clock —
the timestamp is supplied by the caller — and no randomness. Given the same
two states it returns the same events in the same order, every time, which is
what makes deduplication possible at all.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from app.analysts.lifecycle import MissionState
from app.analysts.research import ResearchPriority
from app.models.intelligence import EventKind, EventSeverity

#: The scoring engine's own bar for a material score movement, from
#: `services/scoring/materiality.py`. Reused, not re-decided.
MATERIAL_SCORE_DELTA = Decimal("2.0")

#: Confidence is coarser than score and moves less, so it needs a wider band
#: before a change is worth reporting.
MATERIAL_CONFIDENCE_DELTA = Decimal("10.0")

#: A single analyst's dimension moving by less than this is noise.
MATERIAL_DIMENSION_DELTA = Decimal("15.0")

#: Ascending order of "how much has gone right". Used only to decide whether a
#: mission change is a promotion or a downgrade — never to rank quality.
MISSION_RANK: dict[MissionState, int] = {
    MissionState.LOST_CONTACT: 0,
    MissionState.RE_ENTRY: 1,
    MissionState.RECON: 2,
    MissionState.HOLDING_PATTERN: 3,
    MissionState.LAUNCH_WINDOW: 4,
    MissionState.ORBIT: 5,
    MissionState.ASCENT: 6,
}

#: Ascending urgency.
PRIORITY_RANK: dict[ResearchPriority, int] = {
    ResearchPriority.LOW: 0,
    ResearchPriority.MEDIUM: 1,
    ResearchPriority.HIGH: 2,
    ResearchPriority.CRITICAL: 3,
}


@dataclass(frozen=True, slots=True)
class TokenState:
    """Everything events are derived from, for one token at one moment.

    Deliberately narrow. The full analyst readings are recomputable at any time
    because the analysts are pure, so caching them would be duplicated state
    that could drift from its source.
    """

    mint_address: str
    mission_state: MissionState | None = None
    research_priority: ResearchPriority | None = None
    combined_score: Decimal | None = None
    confidence: Decimal | None = None
    liquidity_score: Decimal | None = None
    momentum_score: Decimal | None = None
    risk_score: Decimal | None = None
    clone_risk: str | None = None
    exit_severity: str | None = None
    warning_codes: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True, slots=True)
class DetectedEvent:
    """One change worth recording."""

    mint_address: str
    kind: EventKind
    severity: EventSeverity
    summary: str
    previous_value: str | None = None
    current_value: str | None = None
    #: Which analyst detected it. None for ensemble-level changes.
    analyst: str | None = None


def detect(previous: TokenState | None, current: TokenState) -> list[DetectedEvent]:
    """Every meaningful change between two observations.

    `previous` is None the first time a token is analysed, which produces a
    single `FIRST_ANALYSED` event rather than a burst of "changes" against
    nothing. A first sighting is not an improvement.
    """
    if previous is None:
        return [
            DetectedEvent(
                mint_address=current.mint_address,
                kind=EventKind.FIRST_ANALYSED,
                severity=EventSeverity.INFO,
                summary="LETZMOON analysed this project for the first time.",
                current_value=(current.mission_state.value if current.mission_state else None),
            )
        ]

    events: list[DetectedEvent] = []
    events.extend(_mission(previous, current))
    events.extend(_priority(previous, current))
    events.extend(_exit_watch(previous, current))
    events.extend(_clone(previous, current))
    events.extend(_dimensions(previous, current))
    events.extend(_confidence(previous, current))
    return events


def _mission(previous: TokenState, current: TokenState) -> list[DetectedEvent]:
    before, after = previous.mission_state, current.mission_state
    if before is None or after is None or before is after:
        return []

    promoted = MISSION_RANK[after] > MISSION_RANK[before]
    label_before = before.value.replace("_", " ").title()
    label_after = after.value.replace("_", " ").title()

    return [
        DetectedEvent(
            mint_address=current.mint_address,
            kind=EventKind.MISSION_PROMOTED if promoted else EventKind.MISSION_DOWNGRADED,
            # A downgrade is the more actionable direction: something a user may
            # hold has deteriorated, which is worth more attention than the same
            # move upward.
            severity=EventSeverity.NOTABLE if promoted else EventSeverity.URGENT,
            summary=(f"Mission status moved from {label_before} to {label_after}."),
            previous_value=before.value,
            current_value=after.value,
            analyst="lifecycle",
        )
    ]


def _priority(previous: TokenState, current: TokenState) -> list[DetectedEvent]:
    before, after = previous.research_priority, current.research_priority
    if before is None or after is None or before is after:
        return []

    increased = PRIORITY_RANK[after] > PRIORITY_RANK[before]
    return [
        DetectedEvent(
            mint_address=current.mint_address,
            kind=(EventKind.PRIORITY_INCREASED if increased else EventKind.PRIORITY_DECREASED),
            severity=(
                EventSeverity.URGENT
                if after is ResearchPriority.CRITICAL
                else EventSeverity.NOTABLE
                if increased
                else EventSeverity.INFO
            ),
            summary=(
                f"Research priority {'rose' if increased else 'fell'} from "
                f"{before.value} to {after.value}."
            ),
            previous_value=before.value,
            current_value=after.value,
            analyst="research",
        )
    ]


def _exit_watch(previous: TokenState, current: TokenState) -> list[DetectedEvent]:
    before = previous.exit_severity or "clear"
    after = current.exit_severity or "clear"
    if before == after:
        return []

    activated = before == "clear" and after != "clear"
    cleared = before != "clear" and after == "clear"
    if not (activated or cleared):
        # watch -> elevated and back. Real, but reported as a risk change
        # rather than an activation, so the wording stays true.
        return [
            DetectedEvent(
                mint_address=current.mint_address,
                kind=(
                    EventKind.RISK_INCREASED
                    if after == "elevated"
                    else EventKind.RISK_RESOLVED
                ),
                severity=EventSeverity.NOTABLE,
                summary=f"Exit Watch severity moved from {before} to {after}.",
                previous_value=before,
                current_value=after,
                analyst="risk",
            )
        ]

    return [
        DetectedEvent(
            mint_address=current.mint_address,
            kind=(
                EventKind.EXIT_WATCH_ACTIVATED if activated else EventKind.EXIT_WATCH_CLEARED
            ),
            severity=EventSeverity.URGENT if activated else EventSeverity.NOTABLE,
            summary=(
                f"Exit Watch activated at {after}. It is a warning system, never "
                "a sell signal — it knows nothing about your position."
                if activated
                else "Exit Watch cleared: the deterioration it was reporting has stopped."
            ),
            previous_value=before,
            current_value=after,
            analyst="risk",
        )
    ]


def _clone(previous: TokenState, current: TokenState) -> list[DetectedEvent]:
    before = previous.clone_risk or "none"
    after = current.clone_risk or "none"
    if before == after:
        return []

    serious = {"moderate", "high"}
    detected = before not in serious and after in serious
    resolved = before in serious and after not in serious
    if not (detected or resolved):
        return []

    return [
        DetectedEvent(
            mint_address=current.mint_address,
            kind=EventKind.CLONE_DETECTED if detected else EventKind.CLONE_RESOLVED,
            severity=EventSeverity.URGENT if detected else EventSeverity.INFO,
            summary=(
                f"Clone risk rose to {after}: another token now shares this name "
                "and was discovered first."
                if detected
                else f"Clone risk fell to {after}."
            ),
            previous_value=before,
            current_value=after,
            analyst="risk",
        )
    ]


def _dimensions(previous: TokenState, current: TokenState) -> list[DetectedEvent]:
    """Per-analyst score moves, for the analysts whose direction is meaningful."""
    events: list[DetectedEvent] = []

    checks = (
        (
            "liquidity",
            previous.liquidity_score,
            current.liquidity_score,
            EventKind.LIQUIDITY_IMPROVED,
            EventKind.LIQUIDITY_WEAKENED,
        ),
        (
            "momentum",
            previous.momentum_score,
            current.momentum_score,
            EventKind.MOMENTUM_IMPROVED,
            EventKind.MOMENTUM_WEAKENED,
        ),
        (
            "risk",
            previous.risk_score,
            current.risk_score,
            # Risk scores higher-is-safer, so a rise resolves rather than raises.
            EventKind.RISK_RESOLVED,
            EventKind.RISK_INCREASED,
        ),
    )

    for analyst, before, after, up_kind, down_kind in checks:
        if before is None or after is None:
            continue
        delta = after - before
        if abs(delta) < MATERIAL_DIMENSION_DELTA:
            continue

        improved = delta > 0
        events.append(
            DetectedEvent(
                mint_address=current.mint_address,
                kind=up_kind if improved else down_kind,
                severity=EventSeverity.NOTABLE if improved else EventSeverity.URGENT,
                summary=(
                    f"{analyst.title()} Intelligence moved "
                    f"{before:.0f} to {after:.0f} ({delta:+.0f})."
                ),
                previous_value=f"{before:.0f}",
                current_value=f"{after:.0f}",
                analyst=analyst,
            )
        )

    return events


def _confidence(previous: TokenState, current: TokenState) -> list[DetectedEvent]:
    before, after = previous.confidence, current.confidence
    if before is None or after is None:
        return []

    delta = after - before
    if abs(delta) < MATERIAL_CONFIDENCE_DELTA:
        return []

    increased = delta > 0
    return [
        DetectedEvent(
            mint_address=current.mint_address,
            kind=(
                EventKind.CONFIDENCE_INCREASED if increased else EventKind.CONFIDENCE_DECREASED
            ),
            severity=EventSeverity.INFO,
            summary=(
                f"Confidence {'rose' if increased else 'fell'} from {before:.0f}% "
                f"to {after:.0f}%. This describes how much LETZMOON could read, "
                "not how the project performed."
            ),
            previous_value=f"{before:.0f}",
            current_value=f"{after:.0f}",
        )
    ]
