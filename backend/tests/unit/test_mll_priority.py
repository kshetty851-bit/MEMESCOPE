"""Collection priority and due-time planning (``priority.py``).

The properties: a busy meme is asked about more often than a quiet one; a
meme that is not due is not asked; a meme that is due but over the budget is
deferred *and recorded*, never dropped; the admission order is a total order,
so the same history always yields the same plan; and priority is a collection
concern only - no decision engine can read it.
"""

from __future__ import annotations

import ast
import random
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.lifecycle_lab import priority as p
from app.lifecycle_lab.domain import (
    CollectionRun,
    DataClass,
    LifecycleState,
    Source,
    SourceStatus,
)
from app.lifecycle_lab.priority import (
    Candidate,
    PriorityLevel,
    RunHistory,
    due_at,
    fold_history,
    gdelt_request_budget,
    plan_source,
    priority_for,
)

pytestmark = pytest.mark.unit

NOW = datetime(2026, 10, 3, 12, 0, tzinfo=UTC)
PACKAGE = Path(__file__).resolve().parents[2] / "app" / "lifecycle_lab"
HIGH, NORMAL, LOW = PriorityLevel.HIGH, PriorityLevel.NORMAL, PriorityLevel.LOW


# ---------------------------------------------------------------- levels


@pytest.mark.parametrize(
    ("state", "level"),
    [
        (LifecycleState.ACCELERATING, HIGH),
        (LifecycleState.PUMPING, HIGH),
        (LifecycleState.REVIVING, HIGH),
        (LifecycleState.SECOND_WAVE, HIGH),
        (LifecycleState.THIRD_WAVE, HIGH),
        (LifecycleState.EMERGING, NORMAL),
        (LifecycleState.ACTIVE, NORMAL),
        (LifecycleState.COOLING, NORMAL),
        (LifecycleState.DORMANT, LOW),
        (LifecycleState.DECAYING, LOW),
        (LifecycleState.DEAD, LOW),
    ],
)
def test_state_to_level(state: LifecycleState, level: PriorityLevel) -> None:
    got = priority_for(state_now=state, now=NOW, last_data_at=NOW)
    assert got.level is level and got.reason == f"state:{state.value}"
    assert got.interval == p.GDELT_INTERVALS[level]


def test_every_state_has_exactly_one_level() -> None:
    sets = (p.HIGH_STATES, p.NORMAL_STATES, p.LOW_STATES)
    for state in LifecycleState:
        assert sum(state in s for s in sets) == 1, state


def test_unknown_with_no_recent_data_is_low() -> None:
    for last in (None, NOW - p.RECENT_DATA - timedelta(seconds=1)):
        got = priority_for(state_now=LifecycleState.UNKNOWN, now=NOW, last_data_at=last)
        assert (got.level, got.reason) == (LOW, "unknown_no_recent_data")


def test_unknown_with_recent_data_is_normal() -> None:
    got = priority_for(
        state_now=LifecycleState.UNKNOWN, now=NOW, last_data_at=NOW - timedelta(hours=3)
    )
    assert (got.level, got.reason) == (NORMAL, "unknown_with_recent_data")


def test_a_low_meme_that_aged_out_keeps_its_last_known_level() -> None:
    """Collected every 6h, a dormant meme reads UNKNOWN between collections
    (its data is older than the 2h freshness budget). Promoting it to NORMAL
    for that would collect it hourly and defeat the reduced frequency."""
    got = priority_for(
        state_now=LifecycleState.UNKNOWN,
        now=NOW,
        last_data_at=NOW - timedelta(hours=4),
        state_at_last_data=LifecycleState.DORMANT,
    )
    assert (got.level, got.state, got.reason) == (
        LOW,
        LifecycleState.DORMANT,
        "last_known_state:dormant",
    )


# ---------------------------------------------------------------- due times


@pytest.mark.parametrize(
    ("level", "interval"),
    [(HIGH, timedelta(minutes=15)), (NORMAL, timedelta(hours=1)), (LOW, timedelta(hours=6))],
)
def test_gdelt_interval_by_level(level: PriorityLevel, interval: timedelta) -> None:
    history = RunHistory(last_success_at=NOW - timedelta(minutes=1))
    assert due_at(Source.GDELT, level, history, NOW) == history.last_success_at + interval  # type: ignore[operator]


def test_never_collected_is_due_now_for_every_scheduled_source() -> None:
    for source in (Source.GDELT, Source.WIKIPEDIA, Source.DEXSCREENER):
        assert due_at(source, LOW, RunHistory(), NOW) == NOW


def test_consecutive_errors_double_the_wait_capped_at_the_low_interval() -> None:
    last_error = NOW - timedelta(minutes=1)
    waits = [
        due_at(Source.GDELT, HIGH, RunHistory(None, last_error, k), NOW) - last_error
        for k in (1, 2, 3, 4, 5, 6, 10)
    ]
    assert waits == [
        timedelta(minutes=15),
        timedelta(minutes=30),
        timedelta(hours=1),
        timedelta(hours=2),
        timedelta(hours=4),
        timedelta(hours=6),  # capped
        timedelta(hours=6),
    ]


def test_daily_sources_are_due_once_per_utc_day() -> None:
    today = RunHistory(last_success_at=datetime(2026, 10, 3, 0, 30, tzinfo=UTC))
    yesterday = RunHistory(last_success_at=datetime(2026, 10, 2, 23, 59, tzinfo=UTC))
    for source in (Source.WIKIPEDIA, Source.DEXSCREENER):
        assert due_at(source, HIGH, today, NOW) == datetime(2026, 10, 4, tzinfo=UTC)
        assert due_at(source, LOW, yesterday, NOW) <= NOW


def test_pumpfun_probe_is_every_pass() -> None:
    history = RunHistory(last_success_at=NOW)
    assert due_at(Source.PUMPFUN_REPLIES, LOW, history, NOW) == NOW


# ---------------------------------------------------------------- history


def run(
    status: SourceStatus,
    at: datetime,
    *,
    reason: str | None = None,
    meme_id: str | None = "m1",
    mint: str | None = None,
    source: Source = Source.GDELT,
    data_class: DataClass = DataClass.FORWARD,
) -> CollectionRun:
    return CollectionRun(
        id=str(uuid.uuid4()),
        source=source,
        status=status,
        started_at=at,
        finished_at=at,
        data_class=data_class,
        reason=reason,
        meme_id=meme_id,
        mint_address=mint,
    )


def test_fold_history_counts_errors_since_the_last_success_only() -> None:
    runs = [
        run(SourceStatus.ERROR, NOW - timedelta(hours=5), reason="timeout"),
        run(SourceStatus.AVAILABLE, NOW - timedelta(hours=4)),
        run(SourceStatus.ERROR, NOW - timedelta(hours=3), reason="rate_limited"),
        run(SourceStatus.ERROR, NOW - timedelta(hours=2), reason="http_503"),
    ]
    random.Random(7).shuffle(runs)
    assert fold_history(runs, Source.GDELT)["m1"] == RunHistory(
        NOW - timedelta(hours=4), NOW - timedelta(hours=2), 2
    )


def test_a_deferred_run_is_not_a_success() -> None:
    """``deferred_budget`` means the source was never asked. Counting it as a
    success would push the meme's next turn out by a whole interval - the
    budget would starve the same memes pass after pass."""
    runs = [
        run(SourceStatus.AVAILABLE, NOW - timedelta(hours=7)),
        run(SourceStatus.UNAVAILABLE, NOW - timedelta(minutes=5), reason="deferred_budget"),
    ]
    assert fold_history(runs, Source.GDELT)["m1"].last_success_at == NOW - timedelta(hours=7)


def test_unavailable_with_a_real_answer_is_a_success() -> None:
    runs = [run(SourceStatus.UNAVAILABLE, NOW, reason="no_data_for_window")]
    assert fold_history(runs, Source.GDELT)["m1"].last_success_at == NOW


def test_global_backfill_and_other_source_runs_are_ignored() -> None:
    runs = [
        run(SourceStatus.AVAILABLE, NOW, meme_id=None),  # global
        run(SourceStatus.AVAILABLE, NOW, data_class=DataClass.BACKFILL),
        run(SourceStatus.AVAILABLE, NOW, source=Source.WIKIPEDIA),
    ]
    assert fold_history(runs, Source.GDELT) == {}


def test_dexscreener_history_is_per_mint() -> None:
    runs = [
        run(SourceStatus.AVAILABLE, NOW, meme_id=None, mint="MINT", source=Source.DEXSCREENER)
    ]
    assert set(fold_history(runs, Source.DEXSCREENER)) == {"MINT"}


# ---------------------------------------------------------------- planning


def cand(
    key: str,
    level: PriorityLevel = NORMAL,
    *,
    last: datetime | None = None,
    group: str | None = None,
) -> Candidate:
    return Candidate(key, key, level, RunHistory(last_success_at=last), group or f'"{key}"')


def test_not_due_memes_are_skipped_and_reported() -> None:
    plan = plan_source(
        Source.GDELT,
        [
            cand("fresh", last=NOW - timedelta(minutes=10)),
            cand("old", last=NOW - timedelta(hours=2)),
        ],
        now=NOW,
    )
    assert plan.due == ("old",) and plan.not_due == ("fresh",) and plan.deferred == ()


def test_admission_is_priority_then_oldest_success_then_slug() -> None:
    candidates = [
        cand("b-normal-old", NORMAL, last=NOW - timedelta(hours=5)),
        cand("a-normal-old", NORMAL, last=NOW - timedelta(hours=5)),
        cand("high-recent", HIGH, last=NOW - timedelta(minutes=20)),
        cand("normal-never", NORMAL),
        cand("low-ancient", LOW, last=NOW - timedelta(days=1)),
    ]
    plan = plan_source(Source.GDELT, candidates, now=NOW, budget=3)
    assert plan.due == ("high-recent", "normal-never", "a-normal-old")
    assert plan.deferred == ("b-normal-old", "low-ancient")
    for seed in range(5):  # a total order: input order cannot leak in
        shuffled = list(candidates)
        random.Random(seed).shuffle(shuffled)
        assert plan_source(Source.GDELT, shuffled, now=NOW, budget=3) == plan


def test_identical_queries_cost_one_request_against_the_budget() -> None:
    candidates = [
        cand("a", HIGH, group='"pepe"'),
        cand("b", HIGH, group='"pepe"'),
        cand("c", NORMAL, group='"doge"'),
        cand("d", NORMAL, group='"wif"'),
    ]
    plan = plan_source(Source.GDELT, candidates, now=NOW, budget=2)
    assert plan.due == ("a", "b", "c") and plan.deferred == ("d",) and plan.requests == 2
    assert plan.summary() == {"due": 3, "not_due": 0, "deferred": 1, "planned_requests": 2}


def test_budget_math_for_twenty_memes() -> None:
    """Defaults: 600 s hard limit, 180 s margin, 6 s spacing -> 70 requests.
    Twenty memes all HIGH (worst case) fit in one pass with room to spare."""
    budget = gdelt_request_budget(600, 180, 6)
    assert budget == 70
    plan = plan_source(
        Source.GDELT, [cand(f"m{i:02d}", HIGH) for i in range(20)], now=NOW, budget=budget
    )
    assert len(plan.due) == 20 and plan.deferred == ()
    assert gdelt_request_budget(600, 180, 0) == 420  # zero spacing stays finite
    assert gdelt_request_budget(100, 180, 6) == 0


# ---------------------------------------------------------------- isolation


def _imports(path: Path) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
            found.update(f"{node.module}.{alias.name}" for alias in node.names)
    return found


@pytest.mark.parametrize(
    "module",
    [
        "strategy.py",
        "replay.py",
        "portfolio.py",
        "exits.py",
        "events.py",
        "states.py",
        "attention.py",
        "pit.py",
        "market.py",
    ],
)
def test_no_decision_engine_can_read_collection_priority(module: str) -> None:
    """Priority shapes how often we ask, never what we decide. If a strategy
    could read it, a meme's collection frequency would become a hidden signal
    that no replay over stored rows could reproduce."""
    imported = _imports(PACKAGE / module)
    assert not any("priority" in name for name in imported), imported
