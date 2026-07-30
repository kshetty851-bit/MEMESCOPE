"""Event and watchlist persistence. The package's only I/O seam.

Two guarantees are enforced here rather than trusted:

  * **Events are append-only.** There is no update or delete path. "What
    changed last week" is only worth asking if the answer cannot be revised
    afterwards, which is the same reason `radar_tokens` refuses to upsert its
    first-detection block.
  * **Events deduplicate.** `ON CONFLICT DO NOTHING` against
    `(mint_address, kind, occurred_at)` means a cycle that runs twice — a
    retry, a restart, two workers racing — records each change once.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysts.lifecycle import MissionState
from app.analysts.research import ResearchPriority
from app.events.detector import DetectedEvent, TokenState
from app.models.intelligence import (
    AnalystReadingCache,
    IntelligenceEvent,
    Watchlist,
    WatchlistItem,
)


class EventRepository:
    """All event and watchlist persistence. Holds a session; owns no transaction."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # --- The reading cache: what makes detection incremental -----------------

    async def cached_states(self, mints: Sequence[str]) -> dict[str, TokenState]:
        """Previous state per mint, for the mints about to be re-analysed.

        One query for the batch. The alternative — a lookup per token — is what
        turns an incremental cycle back into a full scan.
        """
        if not mints:
            return {}

        statement = select(AnalystReadingCache).where(
            AnalystReadingCache.mint_address.in_(list(dict.fromkeys(mints)))
        )
        rows = (await self._session.scalars(statement)).all()

        return {
            row.mint_address: TokenState(
                mint_address=row.mint_address,
                mission_state=(MissionState(row.mission_state) if row.mission_state else None),
                research_priority=(
                    ResearchPriority(row.research_priority) if row.research_priority else None
                ),
                combined_score=row.combined_score,
                confidence=row.confidence,
                liquidity_score=row.liquidity_score,
                momentum_score=row.momentum_score,
                risk_score=row.risk_score,
                clone_risk=row.clone_risk,
                exit_severity=row.exit_severity,
                warning_codes=frozenset(row.warning_codes or []),
            )
            for row in rows
        }

    async def remember_state(self, state: TokenState, *, observed_at: datetime) -> None:
        """Overwrite the cached state for one token.

        Mutable by design, unlike the event log. This row is a pointer to "where
        we were", not a record of history — history lives in
        `intelligence_events` and is never touched.
        """
        values = {
            "mint_address": state.mint_address,
            "mission_state": state.mission_state.value if state.mission_state else None,
            "research_priority": (
                state.research_priority.value if state.research_priority else None
            ),
            "combined_score": state.combined_score,
            "confidence": state.confidence,
            "liquidity_score": state.liquidity_score,
            "momentum_score": state.momentum_score,
            "risk_score": state.risk_score,
            "clone_risk": state.clone_risk,
            "exit_severity": state.exit_severity,
            "warning_codes": sorted(state.warning_codes),
            "observed_at": observed_at,
        }

        statement = (
            insert(AnalystReadingCache)
            .values(**values)
            .on_conflict_do_update(
                index_elements=[AnalystReadingCache.mint_address],
                set_={k: v for k, v in values.items() if k != "mint_address"},
            )
        )
        await self._session.execute(statement)

    # --- Events: append-only -------------------------------------------------

    async def record(self, events: Sequence[DetectedEvent], *, occurred_at: datetime) -> int:
        """Append events, ignoring any already recorded. Returns how many landed."""
        if not events:
            return 0

        rows = [
            {
                "mint_address": event.mint_address,
                "kind": event.kind,
                "severity": event.severity,
                "analyst": event.analyst,
                "previous_value": event.previous_value,
                "current_value": event.current_value,
                "summary": event.summary,
                "occurred_at": occurred_at,
            }
            for event in events
        ]

        statement = (
            insert(IntelligenceEvent)
            .values(rows)
            .on_conflict_do_nothing(
                index_elements=[
                    IntelligenceEvent.mint_address,
                    IntelligenceEvent.kind,
                    IntelligenceEvent.occurred_at,
                ]
            )
            .returning(IntelligenceEvent.id)
        )
        return len((await self._session.scalars(statement)).all())

    async def events_since(
        self, since: datetime, *, limit: int = 100, mints: Sequence[str] | None = None
    ) -> Sequence[IntelligenceEvent]:
        statement = (
            select(IntelligenceEvent)
            .where(IntelligenceEvent.occurred_at >= since)
            .order_by(IntelligenceEvent.occurred_at.desc())
            .limit(limit)
        )
        if mints:
            statement = statement.where(
                IntelligenceEvent.mint_address.in_(list(dict.fromkeys(mints)))
            )
        return (await self._session.scalars(statement)).all()

    async def events_for(
        self, mint_address: str, *, limit: int = 100
    ) -> Sequence[IntelligenceEvent]:
        statement = (
            select(IntelligenceEvent)
            .where(IntelligenceEvent.mint_address == mint_address)
            .order_by(IntelligenceEvent.occurred_at.desc())
            .limit(limit)
        )
        return (await self._session.scalars(statement)).all()

    async def counts_by_kind(self, since: datetime) -> dict[str, int]:
        """Event tallies for the personal brief."""
        statement = (
            select(IntelligenceEvent.kind, func.count())
            .where(IntelligenceEvent.occurred_at >= since)
            .group_by(IntelligenceEvent.kind)
        )
        return {
            str(kind.value): count
            for kind, count in (await self._session.execute(statement)).all()
        }

    # --- Watchlists ----------------------------------------------------------

    async def lists_for_user(self, user_id: uuid.UUID) -> Sequence[Watchlist]:
        statement = (
            select(Watchlist)
            .where(Watchlist.user_id == user_id)
            .order_by(Watchlist.created_at.asc())
        )
        return (await self._session.scalars(statement)).all()

    async def create_list(
        self, *, user_id: uuid.UUID, name: str, description: str | None, alert_on: list[str]
    ) -> Watchlist | None:
        """Create a list. Returns None when the user already has that name."""
        statement = (
            insert(Watchlist)
            .values(user_id=user_id, name=name, description=description, alert_on=alert_on)
            .on_conflict_do_nothing(index_elements=[Watchlist.user_id, Watchlist.name])
            .returning(Watchlist)
        )
        created: Watchlist | None = await self._session.scalar(statement)
        return created

    async def get_list(self, list_id: uuid.UUID, user_id: uuid.UUID) -> Watchlist | None:
        """Scoped by user, so one account cannot read another's lists."""
        found: Watchlist | None = await self._session.scalar(
            select(Watchlist).where(Watchlist.id == list_id, Watchlist.user_id == user_id)
        )
        return found

    async def delete_list(self, list_id: uuid.UUID, user_id: uuid.UUID) -> bool:
        result = await self._session.execute(
            delete(Watchlist)
            .where(Watchlist.id == list_id, Watchlist.user_id == user_id)
            .returning(Watchlist.id)
        )
        return result.scalar_one_or_none() is not None

    async def items(self, list_id: uuid.UUID) -> Sequence[WatchlistItem]:
        statement = (
            select(WatchlistItem)
            .where(WatchlistItem.watchlist_id == list_id)
            .order_by(WatchlistItem.created_at.desc())
        )
        return (await self._session.scalars(statement)).all()

    async def add_item(
        self,
        *,
        list_id: uuid.UUID,
        mint_address: str,
        note: str | None,
        mission_state: str | None,
        priority: str | None,
        score: Decimal | None,
    ) -> WatchlistItem | None:
        """Add a token. Returns None when it is already on the list.

        The state at the moment of adding is captured so the timeline can answer
        "what has changed since I started watching?" without re-deriving it.
        """
        statement = (
            insert(WatchlistItem)
            .values(
                watchlist_id=list_id,
                mint_address=mint_address,
                note=note,
                added_mission_state=mission_state,
                added_priority=priority,
                added_score=score,
            )
            .on_conflict_do_nothing(
                index_elements=[WatchlistItem.watchlist_id, WatchlistItem.mint_address]
            )
            .returning(WatchlistItem)
        )
        added: WatchlistItem | None = await self._session.scalar(statement)
        return added

    async def remove_item(self, list_id: uuid.UUID, mint_address: str) -> bool:
        result = await self._session.execute(
            delete(WatchlistItem)
            .where(
                WatchlistItem.watchlist_id == list_id,
                WatchlistItem.mint_address == mint_address,
            )
            .returning(WatchlistItem.id)
        )
        return result.scalar_one_or_none() is not None

    async def watched_mints(self, user_id: uuid.UUID) -> list[str]:
        """Every mint the user watches, across all their lists."""
        statement = (
            select(WatchlistItem.mint_address)
            .join(Watchlist, Watchlist.id == WatchlistItem.watchlist_id)
            .where(Watchlist.user_id == user_id)
            .distinct()
        )
        return list((await self._session.scalars(statement)).all())
