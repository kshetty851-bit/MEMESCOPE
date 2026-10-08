"""Run source adapters and record every attempt.

Each adapter yields one *global* ``CollectionRun`` (``meme_id`` None) and one
run per subject it reported on. A disabled adapter, a failed adapter and an
adapter that raised all still produce a run: absence is a recorded status, not
a gap and never a zero.

A *scheduled* pass (``schedule``, built from ``priority.plan_source``) narrows
what each source is asked about:

* subjects not due are not sent and get no run - their last run stands;
* subjects due but beyond the request budget get a per-subject
  ``UNAVAILABLE deferred_budget`` run - never silently dropped;
* a source with nothing due at all is not called and records nothing this
  pass. A run means "we asked"; a run claiming to speak for every meme when
  nobody was asked would be false (``pit`` lets a global run speak for every
  meme);
* the global run's ``detail`` carries the plan summary
  (due / not_due / deferred / planned_requests).

I/O module: run ids are uuid4. Everything it persists goes through the
``LabStore`` protocol (implemented by the repository).
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any, Protocol

from app.core.logging import get_logger
from app.lifecycle_lab.adapters.base import AdapterResult, SourceAdapter, Subject
from app.lifecycle_lab.adapters.pumpfun_replies import PumpfunRepliesAdapter
from app.lifecycle_lab.domain import (
    CollectionRun,
    DataClass,
    MarketPoint,
    Observation,
    Source,
    SourceStatus,
)

logger = get_logger(__name__)


class LabStore(Protocol):
    async def insert_observations(self, rows: Sequence[Observation]) -> int: ...

    async def record_run(self, run: CollectionRun) -> None: ...

    async def upsert_candles(
        self, points: Sequence[MarketPoint], *, source: str, retrieved_at: datetime
    ) -> int: ...

    async def pumpfun_social_latest_observed_at(self) -> datetime | None: ...


@dataclass(frozen=True, slots=True)
class SourceSchedule:
    """One source's share of a scheduled pass."""

    #: What the adapter is asked about (meme-keyed: due memes; mint-keyed:
    #: subjects narrowed to their due mints).
    subjects: tuple[Subject, ...]
    #: Subject keys (meme ids or mints) due but beyond the budget.
    deferred: tuple[str, ...] = ()
    summary: dict[str, int] = field(default_factory=dict)


def _new_id() -> str:
    return str(uuid.uuid4())


async def collect_once(
    *,
    repo: LabStore,
    adapters: Sequence[SourceAdapter],
    subjects: Sequence[Subject],
    now: datetime,
    data_class: DataClass = DataClass.FORWARD,
    clock: Callable[[], datetime] | None = None,
    schedule: Mapping[Source, SourceSchedule] | None = None,
) -> list[CollectionRun]:
    """One collection pass over every adapter, in source-name order. A source
    present in ``schedule`` is asked only about its scheduled subjects (see
    the module docstring); one absent from it is asked about all of them."""
    runs: list[CollectionRun] = []
    finish = clock or (lambda: now)
    meme_ids = {s.meme.id for s in subjects}

    for adapter in sorted(adapters, key=lambda a: a.source.value):
        run_class = (
            data_class if adapter.data_class == DataClass.FORWARD else adapter.data_class
        )
        planned = None if schedule is None else schedule.get(adapter.source)
        new_runs = await _collect_adapter(
            repo, adapter, subjects, meme_ids, now, run_class, finish, planned
        )
        for run in new_runs:
            await repo.record_run(run)
        runs.extend(new_runs)
    return runs


async def _collect_adapter(
    repo: LabStore,
    adapter: SourceAdapter,
    subjects: Sequence[Subject],
    meme_ids: set[str],
    now: datetime,
    data_class: DataClass,
    finish: Callable[[], datetime],
    planned: SourceSchedule | None = None,
) -> list[CollectionRun]:
    source = adapter.source
    global_id = _new_id()
    if planned is not None:
        subjects = planned.subjects

    def run(
        run_id: str,
        status: SourceStatus,
        reason: str | None,
        *,
        subject_key: str | None = None,
        written: int = 0,
        detail: dict[str, Any] | None = None,
    ) -> CollectionRun:
        is_meme = subject_key is not None and subject_key in meme_ids
        return CollectionRun(
            id=run_id,
            source=source,
            status=status,
            started_at=now,
            finished_at=finish(),
            data_class=data_class,
            reason=reason,
            meme_id=subject_key if is_meme else None,
            mint_address=subject_key if subject_key is not None and not is_meme else None,
            observations_written=written,
            detail=detail,
        )

    try:
        enabled, why = adapter.enabled()
        if not enabled:
            return [run(global_id, SourceStatus.DISABLED, why or "disabled_by_config")]

        if planned is not None and not planned.subjects:
            if not planned.deferred:
                return []  # nothing due: nobody was asked, so nothing to record
            # Everything due was beyond the budget: the source was not asked.
            return [
                run(
                    global_id,
                    SourceStatus.UNAVAILABLE,
                    "deferred_budget",
                    detail={"schedule": dict(planned.summary)},
                ),
                *_deferred_runs(run, planned),
            ]

        if isinstance(adapter, PumpfunRepliesAdapter):
            adapter.set_latest_observed_at(await repo.pumpfun_social_latest_observed_at())

        result: AdapterResult = await adapter.collect(subjects, now=now)
    except Exception as exc:  # an adapter bug must not stop the other sources
        logger.exception("lifecycle_adapter_failed", source=source.value)
        return [
            run(
                global_id,
                SourceStatus.ERROR,
                "adapter_exception",
                detail={"exception": type(exc).__name__},
            )
        ]

    # Group by subject so each per-subject run reports what it really wrote.
    grouped: dict[str, list[Observation]] = {}
    for obs in result.observations:
        key = obs.meme_id or obs.mint_address or ""
        grouped.setdefault(key, []).append(replace(obs, collection_run_id=global_id))

    written: dict[str, int] = {}
    candles = 0
    try:
        for key, rows in grouped.items():
            written[key] = await repo.insert_observations(rows)
        if result.market_points:
            candles = await repo.upsert_candles(
                result.market_points, source=Source.GECKOTERMINAL.value, retrieved_at=now
            )
    except Exception as exc:
        logger.exception("lifecycle_write_failed", source=source.value)
        return [
            run(
                global_id,
                SourceStatus.ERROR,
                "write_failed",
                written=sum(written.values()),
                detail={"exception": type(exc).__name__},
            )
        ]

    detail: dict[str, Any] = dict(result.detail or {})
    if result.market_points:
        detail.update(
            {"candles_upserted": candles, "candles_fetched": len(result.market_points)}
        )
    if planned is not None:
        detail["schedule"] = dict(planned.summary)
    runs = [
        run(
            global_id,
            result.status,
            result.reason,
            written=sum(written.values()),
            detail=detail or None,
        )
    ]
    for key in sorted(result.per_subject):
        status, reason = result.per_subject[key]
        runs.append(
            run(
                _new_id(),
                status,
                reason,
                subject_key=key,
                written=written.get(key, 0),
                detail=result.per_subject_detail.get(key),
            )
        )
    if planned is not None:
        runs.extend(_deferred_runs(run, planned, skip=frozenset(result.per_subject)))
    return runs


def _deferred_runs(
    run: Callable[..., CollectionRun],
    planned: SourceSchedule,
    *,
    skip: frozenset[str] = frozenset(),
) -> list[CollectionRun]:
    """One ``UNAVAILABLE deferred_budget`` run per subject the budget left out."""
    return [
        run(_new_id(), SourceStatus.UNAVAILABLE, "deferred_budget", subject_key=key)
        for key in sorted(set(planned.deferred) - skip)
    ]
