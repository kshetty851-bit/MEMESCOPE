"""Durable state and audit evidence for the Phase 2 manual-devnet workflow.

This repository deliberately knows no signer file, HTTP endpoint, Paper Wallet
table, strategy, or background scheduler.  Each caller supplies the effect it
is about to record; this module makes an audit event and optimistic state
transition inseparable from that effect's durable result.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, cast

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.real_wallet_execution import (
    RealWalletDevnetEvent,
    RealWalletDevnetIntent,
    RealWalletDevnetQuote,
)
from app.real_wallet.devnet_intent import (
    DevnetIntentState,
    DevnetIntentTransitionError,
    require_transition,
)


class DevnetIntentNotFoundError(ValueError):
    """The requested manual-devnet intent does not exist."""


class DevnetConcurrentTransitionError(RuntimeError):
    """Another request or signer won the state transition."""


class DevnetIntentExpiredError(RuntimeError):
    """An expired quote or approval may never reach a signing boundary."""


class DevnetIntentRepository:
    """Append-only evidence plus compare-and-swap intent lifecycle updates."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_quote(
        self,
        *,
        wallet_public_key: str,
        input_mint: str,
        output_mint: str,
        input_amount_raw: Decimal,
        expected_output_raw: Decimal,
        minimum_output_raw: Decimal,
        slippage_bps: int,
        price_impact_pct: Decimal | None,
        estimated_fee_lamports: int | None,
        provider: str,
        provider_reference: str | None,
        route: dict[str, Any],
        quoted_at: datetime,
        expires_at: datetime,
        provider_payload: dict[str, Any] | None,
    ) -> RealWalletDevnetQuote:
        quote = RealWalletDevnetQuote(
            network="devnet",
            wallet_public_key=wallet_public_key,
            input_mint=input_mint,
            output_mint=output_mint,
            input_amount_raw=input_amount_raw,
            expected_output_raw=expected_output_raw,
            minimum_output_raw=minimum_output_raw,
            slippage_bps=slippage_bps,
            price_impact_pct=price_impact_pct,
            estimated_fee_lamports=estimated_fee_lamports,
            provider=provider,
            provider_reference=provider_reference,
            route=route,
            quoted_at=quoted_at,
            expires_at=expires_at,
            provider_payload=provider_payload,
        )
        self._session.add(quote)
        await self._session.flush()
        return quote

    async def quote_by_id(self, quote_id: uuid.UUID) -> RealWalletDevnetQuote | None:
        return cast(
            RealWalletDevnetQuote | None,
            await self._session.scalar(
                select(RealWalletDevnetQuote).where(RealWalletDevnetQuote.id == quote_id)
            ),
        )

    async def create_intent(
        self,
        *,
        idempotency_key: str,
        wallet_public_key: str,
        action_type: str,
        input_mint: str,
        output_mint: str | None,
        input_amount_raw: Decimal,
        destination_public_key: str | None,
        at: datetime,
    ) -> RealWalletDevnetIntent | None:
        result = await self._session.execute(
            insert(RealWalletDevnetIntent)
            .values(
                idempotency_key=idempotency_key,
                wallet_public_key=wallet_public_key,
                network="devnet",
                action_type=action_type,
                input_mint=input_mint,
                output_mint=output_mint,
                input_amount_raw=input_amount_raw,
                destination_public_key=destination_public_key,
                state=DevnetIntentState.DRAFT,
                created_at=at,
                updated_at=at,
            )
            .on_conflict_do_nothing(index_elements=[RealWalletDevnetIntent.idempotency_key])
            .returning(RealWalletDevnetIntent)
        )
        intent = result.scalar_one_or_none()
        if intent is not None:
            await self.event(intent.id, "created", {"state": DevnetIntentState.DRAFT})
        return intent

    async def intent_by_id(self, intent_id: uuid.UUID) -> RealWalletDevnetIntent | None:
        return cast(
            RealWalletDevnetIntent | None,
            await self._session.scalar(
                select(RealWalletDevnetIntent).where(RealWalletDevnetIntent.id == intent_id)
            ),
        )

    async def intent_by_idempotency_key(self, key: str) -> RealWalletDevnetIntent | None:
        return cast(
            RealWalletDevnetIntent | None,
            await self._session.scalar(
                select(RealWalletDevnetIntent).where(
                    RealWalletDevnetIntent.idempotency_key == key
                )
            ),
        )

    async def intents(self, *, limit: int = 50) -> list[RealWalletDevnetIntent]:
        return list(
            (
                await self._session.scalars(
                    select(RealWalletDevnetIntent)
                    .order_by(RealWalletDevnetIntent.created_at.desc())
                    .limit(limit)
                )
            ).all()
        )

    async def events(self, intent_id: uuid.UUID) -> list[RealWalletDevnetEvent]:
        return list(
            (
                await self._session.scalars(
                    select(RealWalletDevnetEvent)
                    .where(RealWalletDevnetEvent.intent_id == intent_id)
                    .order_by(
                        RealWalletDevnetEvent.event_order.asc(),
                    )
                )
            ).all()
        )

    async def transition(
        self,
        *,
        intent: RealWalletDevnetIntent,
        next_state: DevnetIntentState,
        at: datetime,
        event_type: str | None = None,
        detail: dict[str, Any] | None = None,
        **fields: Any,
    ) -> None:
        """Compare-and-swap one legal transition and append its audit event."""
        require_transition(current=intent.state, next_state=next_state)
        before = str(intent.state)
        values = {"state": next_state, "updated_at": at, **fields}
        result = await self._session.execute(
            update(RealWalletDevnetIntent)
            .where(
                RealWalletDevnetIntent.id == intent.id,
                RealWalletDevnetIntent.state == intent.state,
            )
            .values(**values)
        )
        if result.rowcount != 1:
            raise DevnetConcurrentTransitionError("devnet_intent_state_changed")
        intent.state = str(next_state)
        for name, value in fields.items():
            setattr(intent, name, value)
        await self.event(
            intent.id,
            event_type or str(next_state).lower(),
            {"from": before, "to": str(next_state), **(detail or {})},
        )

    async def update_if_state(
        self,
        *,
        intent: RealWalletDevnetIntent,
        at: datetime,
        event_type: str,
        detail: dict[str, Any],
        **fields: Any,
    ) -> None:
        """Persist evidence without permitting a state transition or race."""
        result = await self._session.execute(
            update(RealWalletDevnetIntent)
            .where(
                RealWalletDevnetIntent.id == intent.id,
                RealWalletDevnetIntent.state == intent.state,
            )
            .values(updated_at=at, **fields)
        )
        if result.rowcount != 1:
            raise DevnetConcurrentTransitionError("devnet_intent_state_changed")
        for name, value in fields.items():
            setattr(intent, name, value)
        await self.event(intent.id, event_type, detail)

    async def claim_signing(self, *, intent: RealWalletDevnetIntent, at: datetime) -> bool:
        """Durably reserve the one permitted signing attempt before key access."""
        result = await self._session.execute(
            update(RealWalletDevnetIntent)
            .where(
                RealWalletDevnetIntent.id == intent.id,
                RealWalletDevnetIntent.state == DevnetIntentState.APPROVED,
                RealWalletDevnetIntent.signing_status == "PENDING",
            )
            .values(signing_status="SIGNING", updated_at=at)
        )
        if result.rowcount != 1:
            return False
        intent.signing_status = "SIGNING"
        await self.event(intent.id, "signing_claimed", {"single_signing_attempt": True})
        return True

    async def fail(
        self,
        *,
        intent: RealWalletDevnetIntent,
        at: datetime,
        reason: str,
        detail: dict[str, Any] | None = None,
    ) -> None:
        """Record a validation/transport failure without hiding the reason."""
        try:
            await self.transition(
                intent=intent,
                next_state=DevnetIntentState.FAILED,
                at=at,
                event_type="failed",
                detail={"reason": reason, **(detail or {})},
                failure_reason=reason,
            )
        except DevnetIntentTransitionError:
            await self.event(
                intent.id, "failure_observed", {"reason": reason, **(detail or {})}
            )

    async def event(
        self, intent_id: uuid.UUID, event_type: str, detail: dict[str, Any]
    ) -> None:
        self._session.add(
            RealWalletDevnetEvent(
                intent_id=intent_id,
                event_type=event_type,
                detail=detail,
            )
        )
        await self._session.flush()

    async def expire_if_needed(self, *, intent: RealWalletDevnetIntent, at: datetime) -> bool:
        expiries = [
            expiry
            for expiry in (intent.quote_expires_at, intent.approval_expires_at)
            if expiry is not None
        ]
        expiry = min(expiries) if expiries else None
        if expiry is None or expiry > at:
            return False
        if intent.state in {
            DevnetIntentState.CONFIRMED,
            DevnetIntentState.FAILED,
            DevnetIntentState.CANCELLED,
            DevnetIntentState.EXPIRED,
        }:
            return intent.state == DevnetIntentState.EXPIRED
        await self.transition(
            intent=intent,
            next_state=DevnetIntentState.EXPIRED,
            at=at,
            event_type="expired",
            detail={"expires_at": expiry.isoformat()},
            failure_reason="intent_expired",
        )
        return True
