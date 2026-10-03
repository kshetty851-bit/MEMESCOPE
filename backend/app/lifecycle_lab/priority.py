"""Collection priority and per-source due-time planning. Pure.

**Collection frequency only.** A priority decides how often a source is asked
about a meme. It is never an input to a decision: ``strategy.py`` and
``replay.py`` must not import this module (test-enforced). What it changes is
*how much* forward data exists, which the point-in-time gate then treats like
any other data.

Priority levels, from the meme's lifecycle state computed point-in-time
(``states.classify_state`` at ``now`` from visible data; if that is UNKNOWN
because the newest reading has aged out of the freshness budget, the state at
the moment of the newest attention reading, when that was within
``RECENT_DATA``):

  HIGH    ACCELERATING, PUMPING, REVIVING, SECOND_WAVE, THIRD_WAVE
  NORMAL  EMERGING, ACTIVE, COOLING, UNKNOWN (with recent data)
  LOW     DORMANT, DECAYING, DEAD, UNKNOWN with no recent data

Per-source cadence (``POLICIES``):

  GDELT       interval by level: HIGH 15 min, NORMAL 60 min, LOW 6 h
  Wikipedia   once per UTC day for every meme (the data is daily)
  DexScreener once per UTC day per mint; a never-collected (newly linked) mint
              is due immediately
  pump.fun    every pass (a freshness probe; no network)

A subject is *due* when its last success (an AVAILABLE / UNAVAILABLE / PARTIAL
per-subject run - a ``deferred_budget`` run is not a success, the source was
never asked) is older than its cadence. After ``k`` consecutive ERROR runs it is
retried ``base * 2**(k-1)`` after the last error, capped at the LOW interval.

Budget: due subjects are ordered by (priority desc, last success asc - never
collected first, slug, key) and admitted while the request budget lasts.
Subjects that share a request (identical GDELT query strings) share one unit.
Everything due but beyond the budget is *deferred* - recorded by the collector
as ``UNAVAILABLE deferred_budget``, never silently dropped.

Pure: no I/O, no clock, no randomness.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from app.lifecycle_lab.domain import (
    CollectionRun,
    DataClass,
    LifecycleState,
    Source,
    SourceStatus,
)


class PriorityLevel(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"


RANK: dict[PriorityLevel, int] = {
    PriorityLevel.LOW: 0,
    PriorityLevel.NORMAL: 1,
    PriorityLevel.HIGH: 2,
}

HIGH_STATES: frozenset[LifecycleState] = frozenset(
    {
        LifecycleState.ACCELERATING,
        LifecycleState.PUMPING,
        LifecycleState.REVIVING,
        LifecycleState.SECOND_WAVE,
        LifecycleState.THIRD_WAVE,
    }
)
NORMAL_STATES: frozenset[LifecycleState] = frozenset(
    {
        LifecycleState.EMERGING,
        LifecycleState.ACTIVE,
        LifecycleState.COOLING,
        LifecycleState.UNKNOWN,
    }
)
LOW_STATES: frozenset[LifecycleState] = frozenset(
    {LifecycleState.DORMANT, LifecycleState.DECAYING, LifecycleState.DEAD}
)

#: An UNKNOWN meme with no attention reading retrieved within this is LOW.
RECENT_DATA = timedelta(hours=24)

#: Reason codes (stable; prose is rendered elsewhere).
REASON_STATE = "state"  # rendered as f"state:{state}"
REASON_LAST_KNOWN = "last_known_state"  # f"last_known_state:{state}"
REASON_UNKNOWN_RECENT = "unknown_with_recent_data"
REASON_UNKNOWN_NO_RECENT = "unknown_no_recent_data"


@dataclass(frozen=True, slots=True)
class CollectionPriority:
    level: PriorityLevel
    #: The state the level was derived from.
    state: LifecycleState
    reason: str
    #: GDELT's interval at this level - the only level-dependent cadence.
    interval: timedelta


def _level_for(state: LifecycleState) -> PriorityLevel:
    if state in HIGH_STATES:
        return PriorityLevel.HIGH
    if state in LOW_STATES:
        return PriorityLevel.LOW
    return PriorityLevel.NORMAL


def priority_for(
    *,
    state_now: LifecycleState,
    now: datetime,
    last_data_at: datetime | None,
    state_at_last_data: LifecycleState | None = None,
) -> CollectionPriority:
    """The collection priority of one meme at ``now``.

    ``last_data_at`` is the newest attention reading's ``retrieved_at`` (or
    None); ``state_at_last_data`` is ``classify_state`` evaluated at that
    instant, used only when ``state_now`` is UNKNOWN. A LOW meme collected
    every six hours ages out of the two-hour freshness budget between
    collections and reads UNKNOWN; without this it would be promoted to NORMAL
    and collected hourly, defeating the reduced frequency.
    """
    recent = last_data_at is not None and timedelta(0) <= now - last_data_at <= RECENT_DATA

    def make(level: PriorityLevel, state: LifecycleState, reason: str) -> CollectionPriority:
        return CollectionPriority(level, state, reason, interval_for(Source.GDELT, level))

    if state_now is not LifecycleState.UNKNOWN:
        return make(_level_for(state_now), state_now, f"{REASON_STATE}:{state_now.value}")
    if not recent:
        return make(PriorityLevel.LOW, state_now, REASON_UNKNOWN_NO_RECENT)
    if state_at_last_data is not None and state_at_last_data is not LifecycleState.UNKNOWN:
        return make(
            _level_for(state_at_last_data),
            state_at_last_data,
            f"{REASON_LAST_KNOWN}:{state_at_last_data.value}",
        )
    return make(PriorityLevel.NORMAL, state_now, REASON_UNKNOWN_RECENT)


# --------------------------------------------------------------------------
# Per-source policy
# --------------------------------------------------------------------------


class Cadence(StrEnum):
    EVERY_PASS = "every_pass"  # noqa: S105 - a cadence, not a credential
    INTERVAL = "interval"
    UTC_DAILY = "utc_daily"


class KeyedBy(StrEnum):
    MEME = "meme"
    MINT = "mint"


@dataclass(frozen=True, slots=True)
class SourcePolicy:
    cadence: Cadence
    keyed_by: KeyedBy
    #: INTERVAL cadence: the interval per level.
    intervals: Mapping[PriorityLevel, timedelta] | None = None
    #: First retry delay after an ERROR, for cadences without a level interval.
    retry_base: timedelta = timedelta(hours=1)


GDELT_INTERVALS: dict[PriorityLevel, timedelta] = {
    PriorityLevel.HIGH: timedelta(minutes=15),
    PriorityLevel.NORMAL: timedelta(minutes=60),
    PriorityLevel.LOW: timedelta(hours=6),
}
#: Backoff never waits longer than the slowest regular cadence.
BACKOFF_CAP = GDELT_INTERVALS[PriorityLevel.LOW]

POLICIES: dict[Source, SourcePolicy] = {
    Source.GDELT: SourcePolicy(Cadence.INTERVAL, KeyedBy.MEME, GDELT_INTERVALS),
    Source.WIKIPEDIA: SourcePolicy(Cadence.UTC_DAILY, KeyedBy.MEME),
    Source.DEXSCREENER: SourcePolicy(Cadence.UTC_DAILY, KeyedBy.MINT),
    Source.PUMPFUN_REPLIES: SourcePolicy(Cadence.EVERY_PASS, KeyedBy.MEME),
}

#: How far back run history must be read for every due decision above: the
#: longest cadence (one UTC day) plus slack. Older history cannot change any
#: decision - a success older than this is "due" either way.
HISTORY_LOOKBACK = timedelta(hours=26)


def interval_for(source: Source, level: PriorityLevel) -> timedelta:
    policy = POLICIES.get(source)
    if policy is None or policy.intervals is None:
        return timedelta(days=1) if policy is not None else timedelta(0)
    return policy.intervals[level]


# --------------------------------------------------------------------------
# Run history -> due time
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RunHistory:
    last_success_at: datetime | None = None
    last_error_at: datetime | None = None
    #: ERROR runs since the last success.
    consecutive_errors: int = 0


EMPTY_HISTORY = RunHistory()

_SUCCESS = frozenset({SourceStatus.AVAILABLE, SourceStatus.UNAVAILABLE, SourceStatus.PARTIAL})
#: UNAVAILABLE reasons that mean "we did not ask", so are not a success.
NOT_ASKED_REASONS = frozenset({"deferred_budget"})


def fold_history(runs: Iterable[CollectionRun], source: Source) -> dict[str, RunHistory]:
    """Per subject key (meme id, or mint for mint-keyed sources): last success,
    last error and the consecutive-error count after that success. FORWARD
    per-subject runs only; order is (finished_at, started_at, id)."""
    policy = POLICIES.get(source)
    by_mint = policy is not None and policy.keyed_by is KeyedBy.MINT
    relevant = sorted(
        (
            r
            for r in runs
            if r.source is source
            and r.data_class is DataClass.FORWARD
            and (r.mint_address if by_mint else r.meme_id) is not None
        ),
        key=lambda r: (r.finished_at, r.started_at, r.id),
    )
    out: dict[str, RunHistory] = {}
    for run in relevant:
        key = run.mint_address if by_mint else run.meme_id
        assert key is not None
        held = out.get(key, EMPTY_HISTORY)
        if run.status in _SUCCESS and run.reason not in NOT_ASKED_REASONS:
            out[key] = RunHistory(run.finished_at, held.last_error_at, 0)
        elif run.status is SourceStatus.ERROR:
            out[key] = RunHistory(
                held.last_success_at, run.finished_at, held.consecutive_errors + 1
            )
    return out


def _next_utc_midnight(t: datetime) -> datetime:
    day = t.astimezone(UTC).date()
    return datetime(day.year, day.month, day.day, tzinfo=UTC) + timedelta(days=1)


def due_at(
    source: Source, level: PriorityLevel, history: RunHistory, now: datetime
) -> datetime:
    """When the subject is next due (``<= now`` means due now)."""
    policy = POLICIES.get(source)
    if policy is None or policy.cadence is Cadence.EVERY_PASS:
        return now
    base = (
        policy.intervals[level]
        if policy.cadence is Cadence.INTERVAL and policy.intervals is not None
        else policy.retry_base
    )
    if history.consecutive_errors > 0 and history.last_error_at is not None:
        backoff = min(base * (1 << (history.consecutive_errors - 1)), BACKOFF_CAP)
        return history.last_error_at + backoff
    if history.last_success_at is None:
        return now
    if policy.cadence is Cadence.UTC_DAILY:
        return _next_utc_midnight(history.last_success_at)
    return history.last_success_at + base


# --------------------------------------------------------------------------
# Planning one source's pass
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Candidate:
    #: Meme id or mint.
    key: str
    #: Tie-break after priority and last success: deterministic and readable.
    slug: str
    level: PriorityLevel
    history: RunHistory = EMPTY_HISTORY
    #: Candidates with the same non-None group share one request.
    group: str | None = None


@dataclass(frozen=True, slots=True)
class SourcePlan:
    source: Source
    #: Keys to attempt this pass, in admission order.
    due: tuple[str, ...]
    #: Keys not due yet - not attempted, not recorded (their last run stands).
    not_due: tuple[str, ...]
    #: Keys due but beyond the budget - recorded as UNAVAILABLE deferred_budget.
    deferred: tuple[str, ...]
    #: Requests the admitted keys will cost (shared groups count once).
    requests: int

    def summary(self) -> dict[str, int]:
        return {
            "due": len(self.due),
            "not_due": len(self.not_due),
            "deferred": len(self.deferred),
            "planned_requests": self.requests,
        }


_NEVER = datetime.min.replace(tzinfo=UTC)


def admission_order(candidate: Candidate) -> tuple[int, datetime, str, str]:
    """(priority desc, last success asc - never collected first, slug, key)."""
    return (
        -RANK[candidate.level],
        candidate.history.last_success_at or _NEVER,
        candidate.slug,
        candidate.key,
    )


def plan_source(
    source: Source,
    candidates: Sequence[Candidate],
    *,
    now: datetime,
    budget: int | None = None,
) -> SourcePlan:
    """Which candidates to attempt now. ``budget`` caps distinct requests
    (``None``: unbounded)."""
    due: list[Candidate] = []
    not_due: list[str] = []
    for c in candidates:
        if due_at(source, c.level, c.history, now) <= now:
            due.append(c)
        else:
            not_due.append(c.key)
    admitted: list[str] = []
    deferred: list[str] = []
    groups: set[str] = set()
    requests = 0
    for c in sorted(due, key=admission_order):
        if c.group is not None and c.group in groups:
            admitted.append(c.key)  # rides on a request already admitted
            continue
        if budget is not None and requests >= budget:
            deferred.append(c.key)
            continue
        requests += 1
        if c.group is not None:
            groups.add(c.group)
        admitted.append(c.key)
    return SourcePlan(
        source, tuple(admitted), tuple(sorted(not_due)), tuple(deferred), requests
    )


def gdelt_request_budget(
    task_time_limit_seconds: float, margin_seconds: float, min_interval_seconds: float
) -> int:
    """floor((task_time_limit - margin) / MLL_GDELT_MIN_INTERVAL_SECONDS): the
    requests one pass can space politely inside the task's hard limit. A zero
    interval (tests) is treated as one second so the budget stays finite."""
    usable = max(0.0, float(task_time_limit_seconds) - float(margin_seconds))
    return int(usable // max(1.0, float(min_interval_seconds)))
