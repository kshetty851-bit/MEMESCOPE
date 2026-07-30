"""Event, brief and mission-log routes.

The brief is generated **entirely from the stored event log** and never
re-derives analyst logic. That is the point of having a log: if the brief
recomputed readings it could disagree with the events it is summarising, and a
user reading both would have no way to know which was right.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Path, Query

from app.api.deps import CurrentUser, DbSession
from app.core.exceptions import NotFoundError
from app.events.repository import EventRepository
from app.models.intelligence import EventKind, IntelligenceEvent
from app.schemas.intelligence import (
    BriefCounts,
    BriefRead,
    EventPage,
    EventRead,
)

router = APIRouter(tags=["events"])

MINT_PATTERN = r"^[1-9A-HJ-NP-Za-km-z]{32,44}$"

#: Which event kinds roll up into which brief line. Kinds absent from this map
#: land in `other` rather than being dropped — a silently discarded event is
#: worse than an uncategorised one.
BRIEF_BUCKETS: dict[str, tuple[EventKind, ...]] = {
    "new_opportunities": (EventKind.FIRST_ANALYSED,),
    "promotions": (EventKind.MISSION_PROMOTED, EventKind.PRIORITY_INCREASED),
    "demotions": (EventKind.MISSION_DOWNGRADED, EventKind.PRIORITY_DECREASED),
    "risk_increases": (
        EventKind.RISK_INCREASED,
        EventKind.EXIT_WATCH_ACTIVATED,
        EventKind.MOMENTUM_WEAKENED,
        EventKind.LIQUIDITY_WEAKENED,
    ),
    "risk_resolutions": (
        EventKind.RISK_RESOLVED,
        EventKind.EXIT_WATCH_CLEARED,
        EventKind.LIQUIDITY_IMPROVED,
        EventKind.MOMENTUM_IMPROVED,
    ),
    "clone_warnings": (EventKind.CLONE_DETECTED,),
}


@router.get("/events", response_model=EventPage, summary="Filtered event history")
async def list_events(
    session: DbSession,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
    kind: Annotated[list[str] | None, Query(description="Repeatable.")] = None,
    mint: Annotated[str | None, Query(pattern=MINT_PATTERN)] = None,
    severity: Annotated[Literal["info", "notable", "urgent"] | None, Query()] = None,
    hours: Annotated[int | None, Query(ge=1, le=24 * 90)] = None,
    order: Annotated[Literal["newest", "oldest"], Query()] = "newest",
) -> EventPage:
    """Every filter is applied in SQL, never after the fact.

    `applied_filters` is echoed so an empty page caused by a strict filter is
    distinguishable from an empty log — the convention `/scores/top` set.
    """
    repository = EventRepository(session)
    since = datetime.now(UTC) - timedelta(hours=hours) if hours else None
    mints = [mint] if mint else None

    total = await repository.count_events(since=since, kinds=kind, mints=mints)
    rows = await repository.search_events(
        offset=(page - 1) * page_size,
        limit=page_size,
        since=since,
        kinds=kind,
        mints=mints,
        severity=severity,
        newest_first=order == "newest",
    )

    return EventPage(
        items=[EventRead.model_validate(row, from_attributes=True) for row in rows],
        total=total,
        page=page,
        page_size=page_size,
        pages=max(1, -(-total // page_size)),
        applied_filters={
            "kind": ",".join(kind) if kind else None,
            "mint": mint,
            "severity": severity,
            "hours": str(hours) if hours else None,
            "order": order,
        },
    )


@router.get(
    "/events/token/{mint}", response_model=list[EventRead], summary="One token's history"
)
async def token_events(
    session: DbSession,
    mint: Annotated[str, Path(pattern=MINT_PATTERN)],
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[EventRead]:
    rows = await EventRepository(session).events_for(mint, limit=limit)
    return [EventRead.model_validate(row, from_attributes=True) for row in rows]


@router.get("/events/{event_id}", response_model=EventRead, summary="One event")
async def get_event(session: DbSession, event_id: Annotated[uuid.UUID, Path()]) -> EventRead:
    found = await EventRepository(session).event_by_id(event_id)
    if found is None:
        raise NotFoundError("Event not found.")
    return EventRead.model_validate(found, from_attributes=True)


@router.get("/brief", response_model=BriefRead, summary="Since your last visit")
async def personal_brief(
    session: DbSession,
    user: CurrentUser,
    hours: Annotated[int, Query(ge=1, le=24 * 30)] = 24,
    watched_only: Annotated[bool, Query()] = True,
) -> BriefRead:
    """The brief, built only from stored events.

    Scoped to the user's watched tokens by default. A brief covering 23,000
    projects is a feed, and the whole purpose of this endpoint is to be short
    enough to read.
    """
    repository = EventRepository(session)
    since = datetime.now(UTC) - timedelta(hours=hours)

    mints = await repository.watched_mints(user.id) if watched_only else None
    # An empty watchlist with `watched_only` would otherwise fall through to
    # "no filter" and return the whole platform's activity.
    if watched_only and not mints:
        return _empty_brief(since, watching_nothing=True)

    rows = await repository.events_since(since, limit=200, mints=mints)
    counts = _bucket(rows)
    entries = [EventRead.model_validate(row, from_attributes=True) for row in rows[:50]]

    return BriefRead(
        since=since,
        generated_at=datetime.now(UTC),
        counts=counts,
        entries=entries,
        quiet=not rows,
        summary=_summarise(counts, quiet=not rows, watching_nothing=False),
    )


@router.get("/brief/changes", response_model=list[EventRead], summary="Just the changes")
async def brief_changes(
    session: DbSession,
    user: CurrentUser,
    hours: Annotated[int, Query(ge=1, le=24 * 30)] = 24,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[EventRead]:
    repository = EventRepository(session)
    mints = await repository.watched_mints(user.id)
    if not mints:
        return []
    since = datetime.now(UTC) - timedelta(hours=hours)
    rows = await repository.events_since(since, limit=limit, mints=mints)
    return [EventRead.model_validate(row, from_attributes=True) for row in rows]


@router.get("/mission-log", response_model=EventPage, summary="The whole platform's log")
async def mission_log(
    session: DbSession,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
    hours: Annotated[int, Query(ge=1, le=24 * 90)] = 24,
) -> EventPage:
    """Unscoped and chronological — the operator's view, not the user's brief."""
    repository = EventRepository(session)
    since = datetime.now(UTC) - timedelta(hours=hours)

    total = await repository.count_events(since=since)
    rows = await repository.search_events(
        offset=(page - 1) * page_size, limit=page_size, since=since
    )

    return EventPage(
        items=[EventRead.model_validate(row, from_attributes=True) for row in rows],
        total=total,
        page=page,
        page_size=page_size,
        pages=max(1, -(-total // page_size)),
        applied_filters={"hours": str(hours)},
    )


def _bucket(rows: Sequence[IntelligenceEvent]) -> BriefCounts:
    """Roll events into the brief's lines. Uncategorised kinds land in `other`."""
    tally = dict.fromkeys(BRIEF_BUCKETS, 0)
    other = 0

    for row in rows:
        for bucket, kinds in BRIEF_BUCKETS.items():
            if row.kind in kinds:
                tally[bucket] += 1
                break
        else:
            other += 1

    return BriefCounts(**tally, other=other)


def _empty_brief(since: datetime, *, watching_nothing: bool) -> BriefRead:
    counts = BriefCounts(**dict.fromkeys(BRIEF_BUCKETS, 0), other=0)
    return BriefRead(
        since=since,
        generated_at=datetime.now(UTC),
        counts=counts,
        entries=[],
        quiet=True,
        summary=_summarise(counts, quiet=True, watching_nothing=watching_nothing),
    )


def _summarise(counts: BriefCounts, *, quiet: bool, watching_nothing: bool) -> str:
    if watching_nothing:
        return (
            "You are not watching any projects yet. Add one to a watchlist and "
            "LETZMOON will tell you when its assessment changes."
        )
    if quiet:
        return (
            "Nothing you watch has changed materially. Silence here is a reading, "
            "not a failure to check."
        )

    parts: list[str] = []
    if counts.risk_increases:
        parts.append(f"{counts.risk_increases} risk increase(s)")
    if counts.clone_warnings:
        parts.append(f"{counts.clone_warnings} clone warning(s)")
    if counts.demotions:
        parts.append(f"{counts.demotions} demotion(s)")
    if counts.promotions:
        parts.append(f"{counts.promotions} promotion(s)")
    if counts.risk_resolutions:
        parts.append(f"{counts.risk_resolutions} risk resolution(s)")
    if counts.new_opportunities:
        parts.append(f"{counts.new_opportunities} newly analysed")

    # Risk first, deliberately: a brief that opened with the good news and
    # mentioned the deterioration afterwards would be technically complete and
    # practically misleading.
    return "Since your last visit: " + ", ".join(parts) + "."
