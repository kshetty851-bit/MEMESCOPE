"""Watchlist routes — the backend replacement for client-side storage.

Every route is scoped to the authenticated user *in SQL*, not by filtering
after the fact. `get_list` takes the user id, so a request for someone else's
list returns 404 rather than 403: confirming a resource exists to a caller who
cannot read it is itself a leak.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Path, Query, status
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.core.exceptions import ConflictError, NotFoundError
from app.events.repository import EventRepository
from app.models.user import User
from app.schemas.intelligence import (
    EventRead,
    WatchlistCreate,
    WatchlistItemCreate,
    WatchlistItemRead,
    WatchlistRead,
    WatchlistUpdate,
)

router = APIRouter(prefix="/watchlists", tags=["watchlists"])

MINT_PATTERN = r"^[1-9A-HJ-NP-Za-km-z]{32,44}$"


async def _require_persisted(session: DbSession, user: CurrentUser) -> None:
    """Refuse to own data on behalf of a principal that has no row.

    `DEVELOPMENT_BYPASS_AUTH` produces a transient developer principal that is
    deliberately never written to `users` — a real row would outlive the flag.
    Watchlists are the first user-owned resource on the platform, so they are
    the first thing to meet that decision.

    Without this guard the insert fails on the foreign key and the caller gets
    an opaque 500. A named 409 that explains the cause is the difference between
    a developer losing an afternoon and losing a minute.
    """
    exists = await session.scalar(select(User.id).where(User.id == user.id))
    if exists is None:
        raise ConflictError(
            "Watchlists belong to a real account, and this request is "
            "authenticated by the development auth bypass, whose principal is "
            "never persisted. Sign in with a seeded account (`make seed`) or set "
            "DEVELOPMENT_BYPASS_AUTH=false."
        )


@router.get("", response_model=list[WatchlistRead], summary="Your watchlists")
async def list_watchlists(session: DbSession, user: CurrentUser) -> list[WatchlistRead]:
    repository = EventRepository(session)
    lists = await repository.lists_for_user(user.id)

    out: list[WatchlistRead] = []
    for watchlist in lists:
        items = await repository.items(watchlist.id)
        out.append(
            WatchlistRead(
                id=watchlist.id,
                name=watchlist.name,
                description=watchlist.description,
                alert_on=watchlist.alert_on,
                item_count=len(items),
                created_at=watchlist.created_at,
                updated_at=watchlist.updated_at,
            )
        )
    return out


@router.post(
    "",
    response_model=WatchlistRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a watchlist",
)
async def create_watchlist(
    payload: WatchlistCreate, session: DbSession, user: CurrentUser
) -> WatchlistRead:
    await _require_persisted(session, user)

    repository = EventRepository(session)
    created = await repository.create_list(
        user_id=user.id,
        name=payload.name,
        description=payload.description,
        alert_on=payload.alert_on,
    )
    if created is None:
        # Two lists called "Recovery" is a bug the user cannot see until they
        # add to the wrong one.
        raise ConflictError(f"You already have a watchlist called {payload.name!r}.")

    await session.commit()
    return WatchlistRead(
        id=created.id,
        name=created.name,
        description=created.description,
        alert_on=created.alert_on,
        item_count=0,
        created_at=created.created_at,
        updated_at=created.updated_at,
    )


@router.patch("/{list_id}", response_model=WatchlistRead, summary="Rename or reconfigure")
async def update_watchlist(
    payload: WatchlistUpdate,
    session: DbSession,
    user: CurrentUser,
    list_id: Annotated[uuid.UUID, Path()],
) -> WatchlistRead:
    repository = EventRepository(session)
    watchlist = await repository.get_list(list_id, user.id)
    if watchlist is None:
        raise NotFoundError("Watchlist not found.")

    if payload.name is not None:
        watchlist.name = payload.name
    if payload.description is not None:
        watchlist.description = payload.description
    if payload.alert_on is not None:
        watchlist.alert_on = payload.alert_on

    await session.commit()
    # `updated_at` carries `onupdate=func.now()`, so after the UPDATE it is a
    # server-side value the session has not seen. Reading it would trigger an
    # implicit lazy fetch outside greenlet context and raise MissingGreenlet, so
    # the refresh is explicit and awaited.
    await session.refresh(watchlist)

    items = await repository.items(watchlist.id)
    return WatchlistRead(
        id=watchlist.id,
        name=watchlist.name,
        description=watchlist.description,
        alert_on=watchlist.alert_on,
        item_count=len(items),
        created_at=watchlist.created_at,
        updated_at=watchlist.updated_at,
    )


@router.delete(
    "/{list_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a watchlist"
)
async def delete_watchlist(
    session: DbSession, user: CurrentUser, list_id: Annotated[uuid.UUID, Path()]
) -> None:
    deleted = await EventRepository(session).delete_list(list_id, user.id)
    if not deleted:
        raise NotFoundError("Watchlist not found.")
    await session.commit()


@router.get(
    "/{list_id}/tokens",
    response_model=list[WatchlistItemRead],
    summary="Tokens on a watchlist, with live state",
)
async def list_tokens(
    session: DbSession,
    user: CurrentUser,
    list_id: Annotated[uuid.UUID, Path()],
) -> list[WatchlistItemRead]:
    repository = EventRepository(session)
    if await repository.get_list(list_id, user.id) is None:
        raise NotFoundError("Watchlist not found.")

    items = await repository.items(list_id)
    if not items:
        return []

    mints = [item.mint_address for item in items]
    # Live state and the latest change, both batched rather than per row.
    cached = await repository.cached_states(mints)
    latest = await repository.latest_event_per_mint(mints)

    out: list[WatchlistItemRead] = []
    for item in items:
        state = cached.get(item.mint_address)
        event = latest.get(item.mint_address)
        out.append(
            WatchlistItemRead(
                mint_address=item.mint_address,
                note=item.note,
                added_mission_state=item.added_mission_state,
                added_priority=item.added_priority,
                added_score=item.added_score,
                created_at=item.created_at,
                current_mission_state=(
                    state.mission_state.value if state and state.mission_state else None
                ),
                current_priority=(
                    state.research_priority.value
                    if state and state.research_priority
                    else None
                ),
                current_score=state.combined_score if state else None,
                last_change=event.summary if event else None,
                last_change_at=event.occurred_at if event else None,
            )
        )
    return out


@router.post(
    "/{list_id}/tokens",
    response_model=WatchlistItemRead,
    status_code=status.HTTP_201_CREATED,
    summary="Add a token to a watchlist",
)
async def add_token(
    payload: WatchlistItemCreate,
    session: DbSession,
    user: CurrentUser,
    list_id: Annotated[uuid.UUID, Path()],
) -> WatchlistItemRead:
    repository = EventRepository(session)
    if await repository.get_list(list_id, user.id) is None:
        raise NotFoundError("Watchlist not found.")

    # Capture state at the moment of adding, so the timeline can later answer
    # "what changed since I started watching this?" without re-deriving it.
    cached = (await repository.cached_states([payload.mint_address])).get(payload.mint_address)

    added = await repository.add_item(
        list_id=list_id,
        mint_address=payload.mint_address,
        note=payload.note,
        mission_state=(
            cached.mission_state.value if cached and cached.mission_state else None
        ),
        priority=(
            cached.research_priority.value if cached and cached.research_priority else None
        ),
        score=cached.combined_score if cached else None,
    )
    if added is None:
        raise ConflictError("That token is already on this watchlist.")

    await session.commit()
    return WatchlistItemRead(
        mint_address=added.mint_address,
        note=added.note,
        added_mission_state=added.added_mission_state,
        added_priority=added.added_priority,
        added_score=added.added_score,
        created_at=added.created_at,
        current_mission_state=added.added_mission_state,
        current_priority=added.added_priority,
        current_score=added.added_score,
    )


@router.delete(
    "/{list_id}/tokens/{mint}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a token from a watchlist",
)
async def remove_token(
    session: DbSession,
    user: CurrentUser,
    list_id: Annotated[uuid.UUID, Path()],
    mint: Annotated[str, Path(pattern=MINT_PATTERN)],
) -> None:
    repository = EventRepository(session)
    if await repository.get_list(list_id, user.id) is None:
        raise NotFoundError("Watchlist not found.")
    if not await repository.remove_item(list_id, mint):
        raise NotFoundError("That token is not on this watchlist.")
    await session.commit()


@router.get(
    "/{list_id}/events",
    response_model=list[EventRead],
    summary="Recent changes for the tokens on a watchlist",
)
async def list_events(
    session: DbSession,
    user: CurrentUser,
    list_id: Annotated[uuid.UUID, Path()],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[EventRead]:
    repository = EventRepository(session)
    if await repository.get_list(list_id, user.id) is None:
        raise NotFoundError("Watchlist not found.")

    items = await repository.items(list_id)
    mints = [item.mint_address for item in items]
    if not mints:
        return []

    events = await repository.events_for_mints(mints, limit=limit)
    return [EventRead.model_validate(event, from_attributes=True) for event in events]
