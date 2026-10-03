"""Scheduled collection passes: what is recorded when not everyone is asked.

The rule: a run means "we asked". A meme that is not due gets no run (its last
run still stands); a meme that is due but over the budget gets an UNAVAILABLE
``deferred_budget`` run so the gap is visible, never silently dropped; and a
source with nothing due records nothing at all - a global run claiming to
speak for every meme when nobody was asked would be false.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.lifecycle_lab.adapters.base import AdapterResult, Subject
from app.lifecycle_lab.collector import SourceSchedule, collect_once
from app.lifecycle_lab.domain import (
    CollectionRun,
    DataClass,
    MarketPoint,
    Meme,
    Metric,
    Observation,
    Source,
    SourceStatus,
    ValueKind,
)

pytestmark = pytest.mark.unit

NOW = datetime(2026, 10, 3, 12, 0, tzinfo=UTC)


class FakeRepo:
    def __init__(self) -> None:
        self.rows: list[Observation] = []
        self.runs: list[CollectionRun] = []

    async def insert_observations(self, rows: Sequence[Observation]) -> int:
        self.rows.extend(rows)
        return len(rows)

    async def record_run(self, run: CollectionRun) -> None:
        self.runs.append(run)

    async def upsert_candles(
        self, points: Sequence[MarketPoint], *, source: str, retrieved_at: datetime
    ) -> int:
        return 0

    async def pumpfun_social_latest_observed_at(self) -> datetime | None:
        return None


def subject(meme_id: str) -> Subject:
    return Subject(
        meme=Meme(id=meme_id, slug=meme_id, display_name=meme_id, tracking_started_at=NOW)
    )


def obs(meme_id: str) -> Observation:
    return Observation(
        source=Source.GDELT,
        metric=Metric.MENTIONS,
        value_kind=ValueKind.WINDOW_COUNT,
        data_class=DataClass.FORWARD,
        source_timestamp=NOW - timedelta(minutes=15),
        observed_at=NOW,
        retrieved_at=NOW,
        raw_value=Decimal(3),
        meme_id=meme_id,
        window_start=NOW - timedelta(minutes=15),
        window_end=NOW,
        query=meme_id,
    )


class Spy:
    source = Source.GDELT
    data_class = DataClass.FORWARD

    def __init__(self) -> None:
        self.asked: list[list[str]] = []

    def enabled(self) -> tuple[bool, str | None]:
        return True, None

    async def collect(self, subjects: Sequence[Subject], *, now: datetime) -> AdapterResult:
        ids = [s.meme.id for s in subjects]
        self.asked.append(ids)
        return AdapterResult(
            Source.GDELT,
            SourceStatus.AVAILABLE,
            None,
            tuple(obs(i) for i in ids),
            dict.fromkeys(ids, (SourceStatus.AVAILABLE, None)),
            detail={"requests": len(ids)},
        )


ALL = [subject("a"), subject("b"), subject("c")]


async def test_only_due_subjects_are_asked_and_deferred_ones_are_recorded() -> None:
    repo, spy = FakeRepo(), Spy()
    plan = SourceSchedule(
        subjects=(ALL[0],),
        deferred=("b",),
        summary={"due": 2, "not_due": 1, "deferred": 1, "planned_requests": 1},
    )
    runs = await collect_once(
        repo=repo, adapters=[spy], subjects=ALL, now=NOW, schedule={Source.GDELT: plan}
    )
    assert spy.asked == [["a"]]
    by_meme = {r.meme_id: r for r in runs}
    assert set(by_meme) == {None, "a", "b"}  # "c" was not due: no run at all
    assert (by_meme["b"].status, by_meme["b"].reason) == (
        SourceStatus.UNAVAILABLE,
        "deferred_budget",
    )
    assert by_meme["b"].observations_written == 0
    glob = by_meme[None]
    assert glob.status is SourceStatus.AVAILABLE
    assert glob.detail == {
        "requests": 1,
        "schedule": {"due": 2, "not_due": 1, "deferred": 1, "planned_requests": 1},
    }
    assert [r.meme_id for r in repo.rows] == ["a"]


async def test_nothing_due_records_nothing_and_does_not_call_the_adapter() -> None:
    repo, spy = FakeRepo(), Spy()
    runs = await collect_once(
        repo=repo,
        adapters=[spy],
        subjects=ALL,
        now=NOW,
        schedule={Source.GDELT: SourceSchedule(subjects=())},
    )
    assert runs == [] and repo.runs == [] and spy.asked == []


async def test_everything_deferred_is_a_recorded_unavailable_pass() -> None:
    repo, spy = FakeRepo(), Spy()
    runs = await collect_once(
        repo=repo,
        adapters=[spy],
        subjects=ALL,
        now=NOW,
        schedule={Source.GDELT: SourceSchedule(subjects=(), deferred=("a", "b"))},
    )
    assert spy.asked == []
    assert {(r.meme_id, r.status, r.reason) for r in runs} == {
        (None, SourceStatus.UNAVAILABLE, "deferred_budget"),
        ("a", SourceStatus.UNAVAILABLE, "deferred_budget"),
        ("b", SourceStatus.UNAVAILABLE, "deferred_budget"),
    }


async def test_a_source_absent_from_the_schedule_is_asked_about_everyone() -> None:
    spy = Spy()
    await collect_once(
        repo=FakeRepo(),
        adapters=[spy],
        subjects=ALL,
        now=NOW,
        schedule={Source.WIKIPEDIA: SourceSchedule(subjects=())},
    )
    assert spy.asked == [["a", "b", "c"]]


async def test_a_disabled_source_is_disabled_whatever_the_schedule() -> None:
    class Off(Spy):
        def enabled(self) -> tuple[bool, str | None]:
            return False, "disabled_by_config"

    runs = await collect_once(
        repo=FakeRepo(),
        adapters=[Off()],
        subjects=ALL,
        now=NOW,
        schedule={Source.GDELT: SourceSchedule(subjects=(), deferred=("a",))},
    )
    assert [(r.meme_id, r.status, r.reason) for r in runs] == [
        (None, SourceStatus.DISABLED, "disabled_by_config")
    ]


async def test_per_subject_failure_detail_lands_on_that_subjects_run() -> None:
    class Failing(Spy):
        async def collect(
            self, subjects: Sequence[Subject], *, now: datetime
        ) -> AdapterResult:
            return AdapterResult(
                Source.GDELT,
                SourceStatus.ERROR,
                "gdelt_query_error",
                (),
                {"a": (SourceStatus.ERROR, "gdelt_query_error")},
                per_subject_detail={"a": {"body_head": "The specified phrase is too short."}},
            )

    runs = await collect_once(repo=FakeRepo(), adapters=[Failing()], subjects=ALL[:1], now=NOW)
    by_meme = {r.meme_id: r for r in runs}
    assert by_meme["a"].detail == {"body_head": "The specified phrase is too short."}
    assert by_meme[None].detail is None


# ---------------------------------------------------------------- the beat


def test_scheduler_budget_is_derived_from_the_task_hard_limit() -> None:
    """600 s hard limit - 180 s margin, over 6 s spacing: 70 requests a pass."""
    from app.core.config import settings
    from app.lifecycle_lab import scheduler
    from app.workers.celery_app import celery_app

    limit = float(celery_app.conf.task_time_limit)
    spacing = max(1.0, float(settings.MLL_GDELT_MIN_INTERVAL_SECONDS))
    assert scheduler.gdelt_budget() == int(
        (limit - scheduler.COLLECT_MARGIN_SECONDS) // spacing
    )
    if limit == 600 and spacing == 6:
        assert scheduler.gdelt_budget() == 70


class _Session:
    async def __aenter__(self) -> _Session:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def scalar(self, _stmt: object) -> bool:
        return True  # the advisory lock is free

    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        return None


@pytest.mark.parametrize("plan_fails", [False, True])
async def test_collect_tick_plans_once_and_falls_back_loudly(
    monkeypatch: pytest.MonkeyPatch, plan_fails: bool
) -> None:
    """The plan is computed once per tick and handed to every per-source
    commit. If planning itself fails, the tick still collects - unscheduled,
    as before the scheduler - rather than collecting nothing."""
    from app.core.config import settings
    from app.lifecycle_lab import scheduler

    plans: list[object] = []
    seen: list[tuple[Source, object]] = []
    plan = {Source.GDELT: SourceSchedule(subjects=(), summary={"due": 0})}

    class FakeService:
        def __init__(self, _session: object) -> None:
            pass

        @staticmethod
        def build_adapters(_client: object) -> list[Spy]:
            return [Spy()]

        async def plan_collection(
            self, now: datetime, adapters: object, **kw: object
        ) -> object:
            plans.append(kw)
            if plan_fails:
                raise RuntimeError("planner bug")
            return plan

        async def collect(
            self, now: datetime, adapters: Sequence[Spy], **kw: object
        ) -> list[CollectionRun]:
            seen.append((adapters[0].source, kw["schedule"]))
            return []

    monkeypatch.setattr(settings, "FEATURE_LIFECYCLE_LAB_ENABLED", True)
    monkeypatch.setattr(scheduler, "SessionFactory", _Session)
    monkeypatch.setattr(scheduler, "LifecycleLabService", FakeService)
    out = await scheduler._collect_tick()
    assert len(plans) == 1 and plans[0]["gdelt_budget"] == scheduler.gdelt_budget()  # type: ignore[index]
    if plan_fails:
        assert seen == [(Source.GDELT, None)] and out["schedule"] == "unscheduled"
    else:
        assert seen == [(Source.GDELT, plan)]
        assert out["sources"] == {"gdelt": "not_due"}
        assert out["schedule"] == {"gdelt": {"due": 0}}
