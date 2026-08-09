"""Durable, append-only persistence for future real execution attempts."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.real_wallet_execution import (
    RealWalletExecutionEvent,
    RealWalletKillSwitch,
    RealWalletLiveIntent,
)
from app.real_wallet.live_readiness import ExecutionState, assert_transition


class ConcurrentIntentTransitionError(RuntimeError):
    """A second worker tried to advance an intent after another worker won."""


class LiveIntentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_intent(self, **values: Any) -> RealWalletLiveIntent | None:
        """Create once; duplicate task delivery returns no new intent."""
        result = await self._session.execute(
            insert(RealWalletLiveIntent)
            .values(**values, state=ExecutionState.CREATED)
            .on_conflict_do_nothing(index_elements=[RealWalletLiveIntent.idempotency_key])
            .returning(RealWalletLiveIntent)
        )
        intent = result.scalar_one_or_none()
        if intent is not None:
            await self._event(intent.id, "created", {})
        return intent

    async def transition(
        self,
        *,
        intent: RealWalletLiveIntent,
        next_state: ExecutionState,
        detail: dict[str, object],
        at: datetime,
        **fields: object,
    ) -> None:
        assert_transition(current=intent.state, next_state=next_state)
        timestamp_field = {
            ExecutionState.ORDER_CREATED: "order_created_at",
            ExecutionState.SUBMITTED: "submitted_at",
            ExecutionState.CONFIRMED: "confirmed_at",
        }.get(next_state)
        if timestamp_field:
            fields[timestamp_field] = at
        result = await self._session.execute(
            update(RealWalletLiveIntent)
            .where(
                RealWalletLiveIntent.id == intent.id,
                RealWalletLiveIntent.state == intent.state,
            )
            .values(state=next_state, **fields)
        )
        if not isinstance(result, CursorResult) or result.rowcount != 1:
            raise ConcurrentIntentTransitionError("execution_intent_state_changed")
        intent.state = next_state
        await self._event(intent.id, next_state, detail)

    async def unresolved(self) -> list[RealWalletLiveIntent]:
        return list(
            (
                await self._session.scalars(
                    select(RealWalletLiveIntent).where(
                        RealWalletLiveIntent.state.in_(
                            [ExecutionState.SUBMITTED, ExecutionState.RECONCILIATION_REQUIRED]
                        )
                    )
                )
            ).all()
        )

    async def active_kill_switches(self) -> list[RealWalletKillSwitch]:
        return list(
            (
                await self._session.scalars(
                    select(RealWalletKillSwitch).where(RealWalletKillSwitch.active)
                )
            ).all()
        )

    async def activate_kill_switch(self, *, kind: str, reason: str, at: datetime) -> None:
        """Persist a fail-closed switch. Repeating activation preserves no secret data."""
        await self._session.execute(
            insert(RealWalletKillSwitch)
            .values(kind=kind, active=True, reason=reason, activated_at=at)
            .on_conflict_do_update(
                index_elements=[RealWalletKillSwitch.kind],
                set_={"active": True, "reason": reason, "activated_at": at},
            )
        )

    async def open_positions_count(self) -> int:
        from app.models.real_wallet_execution import RealWalletPosition

        rows = await self._session.scalars(
            select(RealWalletPosition.id).where(RealWalletPosition.status == "OPEN")
        )
        return len(rows.all())

    async def _event(
        self, intent_id: uuid.UUID, event_type: str, detail: dict[str, object]
    ) -> None:
        self._session.add(
            RealWalletExecutionEvent(intent_id=intent_id, event_type=event_type, detail=detail)
        )
