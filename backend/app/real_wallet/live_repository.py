"""Durable, append-only persistence for future real execution attempts."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, cast

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.real_wallet_execution import (
    RealWalletExecutionEvent,
    RealWalletExecutionHealth,
    RealWalletKillSwitch,
    RealWalletKillSwitchEvent,
    RealWalletLiveIntent,
    RealWalletPosition,
)
from app.real_wallet.live_readiness import ExecutionState, assert_transition
from app.real_wallet.sol_price import (
    NET_UNAVAILABLE_NO_FEE,
    NET_UNAVAILABLE_NO_PRICE,
    SolUsdPrice,
    fee_usd,
)


class ConcurrentIntentTransitionError(RuntimeError):
    """A second worker tried to advance an intent after another worker won."""


class PositionExitAlreadyRequestedError(RuntimeError):
    """A sell must remain bound to its one confirmed open position."""


class SettlementEvidenceError(RuntimeError):
    """Confirmed RPC data did not prove the exact intended settlement."""


class OpenPositionExistsError(RuntimeError):
    """A second BUY attempted to open the same mint concurrently."""


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

    async def by_id(self, intent_id: uuid.UUID) -> RealWalletLiveIntent | None:
        return cast(
            RealWalletLiveIntent | None,
            await self._session.scalar(
                select(RealWalletLiveIntent).where(RealWalletLiveIntent.id == intent_id)
            ),
        )

    async def by_idempotency_key(self, key: str) -> RealWalletLiveIntent | None:
        return cast(
            RealWalletLiveIntent | None,
            await self._session.scalar(
                select(RealWalletLiveIntent).where(RealWalletLiveIntent.idempotency_key == key)
            ),
        )

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

    async def stranded_before_submission(self) -> list[RealWalletLiveIntent]:
        """Orders/signatures survive a crash only as a fail-closed terminal failure.

        An unsigned transaction is deliberately never stored. Therefore a
        worker that dies after order creation or signing cannot know that the
        old order remains fresh, and it may not recreate or submit it.
        """
        return list(
            (
                await self._session.scalars(
                    select(RealWalletLiveIntent).where(
                        RealWalletLiveIntent.state.in_(
                            [ExecutionState.ORDER_CREATED, ExecutionState.SIGNED]
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

    async def health(self) -> RealWalletExecutionHealth | None:
        return cast(
            RealWalletExecutionHealth | None,
            await self._session.scalar(
                select(RealWalletExecutionHealth).where(
                    RealWalletExecutionHealth.scope == "execution"
                )
            ),
        )

    async def activate_kill_switch(
        self, *, kind: str, reason: str, at: datetime, actor: str | None = None
    ) -> None:
        """Persist a fail-closed switch. Repeating activation preserves no secret data."""
        await self._session.execute(
            insert(RealWalletKillSwitch)
            .values(
                kind=kind,
                active=True,
                reason=reason,
                activated_at=at,
                actor=actor,
            )
            .on_conflict_do_update(
                index_elements=[RealWalletKillSwitch.kind],
                set_={
                    "active": True,
                    "reason": reason,
                    "activated_at": at,
                    "actor": actor,
                },
            )
        )
        self._session.add(
            RealWalletKillSwitchEvent(
                kind=kind, action="armed", actor=actor, reason=reason, created_at=at
            )
        )

    async def clear_kill_switch(
        self, *, kind: str, actor: str, reason: str, at: datetime
    ) -> bool:
        """Clear one armed switch, attributed. Returns False when none was armed.

        **This clears exactly one barrier and nothing else.** Every other
        condition — mode, the three enable flags, the release constant, the
        submission guard, the canary limits, SEC-2 freshness, mainnet
        verification — is evaluated independently and is unaffected by this
        call. That is deliberate: an operator clearing a switch after
        investigating a failure must not thereby re-authorise execution, and
        the only way to guarantee that is for this to have no reach beyond its
        own row.

        The consecutive-failure counter is *not* reset here either. It armed
        this switch; zeroing it as a side effect would let a repeating fault
        re-arm from a clean slate every time instead of tripping immediately.
        """
        if not actor or not reason:
            raise ValueError("kill_switch_clear_requires_actor_and_reason")
        result = await self._session.execute(
            update(RealWalletKillSwitch)
            .where(RealWalletKillSwitch.kind == kind, RealWalletKillSwitch.active)
            .values(
                active=False, cleared_at=at, cleared_by=actor, cleared_reason=reason
            )
        )
        cleared = isinstance(result, CursorResult) and result.rowcount == 1
        if cleared:
            self._session.add(
                RealWalletKillSwitchEvent(
                    kind=kind, action="cleared", actor=actor, reason=reason, created_at=at
                )
            )
        return cleared

    async def kill_switch_history(self, *, limit: int = 50) -> list[RealWalletKillSwitchEvent]:
        return list(
            (
                await self._session.scalars(
                    select(RealWalletKillSwitchEvent)
                    .order_by(RealWalletKillSwitchEvent.created_at.desc())
                    .limit(limit)
                )
            ).all()
        )

    async def record_execution_failure(self, *, reason: str, at: datetime) -> int:
        """Atomically increment failure state and arm the durable kill switch.

        The counter is database-backed so a worker restart cannot silently
        clear a run of execution failures.
        """
        result = await self._session.execute(
            insert(RealWalletExecutionHealth)
            .values(
                scope="execution",
                consecutive_failures=1,
                last_failure_reason=reason,
                last_failure_at=at,
            )
            .on_conflict_do_update(
                index_elements=[RealWalletExecutionHealth.scope],
                set_={
                    "consecutive_failures": RealWalletExecutionHealth.consecutive_failures + 1,
                    "last_failure_reason": reason,
                    "last_failure_at": at,
                    "updated_at": at,
                },
            )
            .returning(RealWalletExecutionHealth.consecutive_failures)
        )
        failures = int(result.scalar_one())
        if failures >= settings.REAL_WALLET_MAX_CONSECUTIVE_EXECUTION_FAILURES:
            await self.activate_kill_switch(
                kind="consecutive_execution_failures",
                reason="failure_threshold_reached",
                at=at,
            )
        return failures

    async def record_execution_success(self, *, at: datetime) -> None:
        await self._session.execute(
            insert(RealWalletExecutionHealth)
            .values(scope="execution", consecutive_failures=0)
            .on_conflict_do_update(
                index_elements=[RealWalletExecutionHealth.scope],
                set_={
                    "consecutive_failures": 0,
                    "last_failure_reason": None,
                    "last_failure_at": None,
                    "updated_at": at,
                },
            )
        )

    async def open_positions_count(self) -> int:
        rows = await self._session.scalars(
            select(RealWalletPosition.id).where(RealWalletPosition.status == "OPEN")
        )
        return len(rows.all())

    async def open_position(self, position_id: uuid.UUID) -> RealWalletPosition | None:
        return cast(
            RealWalletPosition | None,
            await self._session.scalar(
                select(RealWalletPosition).where(
                    RealWalletPosition.id == position_id,
                    RealWalletPosition.status == "OPEN",
                )
            ),
        )

    async def positions(self, *, limit: int = 30) -> list[RealWalletPosition]:
        return list(
            (
                await self._session.scalars(
                    select(RealWalletPosition)
                    .order_by(RealWalletPosition.opened_at.desc())
                    .limit(limit)
                )
            ).all()
        )

    async def create_sell_intent(
        self,
        *,
        idempotency_key: str,
        position_id: uuid.UUID,
        strategy_id: str,
        strategy_version: str,
        wallet_public_key: str,
        output_mint: str,
    ) -> RealWalletLiveIntent:
        """Bind one SELL to the confirmed position quantity under a row lock."""
        position = await self._session.scalar(
            select(RealWalletPosition)
            .where(RealWalletPosition.id == position_id)
            .with_for_update()
        )
        if position is None or position.status != "OPEN":
            raise PositionExitAlreadyRequestedError("real_position_not_open")
        existing = await self.by_idempotency_key(idempotency_key)
        if existing is not None:
            return existing
        if position.exit_intent_id is not None:
            raise PositionExitAlreadyRequestedError("real_position_exit_already_requested")
        intent = await self.create_intent(
            idempotency_key=idempotency_key,
            mint_address=position.mint_address,
            side="SELL",
            strategy_id=strategy_id,
            strategy_version=strategy_version,
            wallet_public_key=wallet_public_key,
            position_id=position.id,
            requested_token_quantity=position.quantity,
            input_mint=position.mint_address,
            output_mint=output_mint,
        )
        if intent is None:
            found = await self.by_idempotency_key(idempotency_key)
            if found is None:  # pragma: no cover - defensive database invariant
                raise ConcurrentIntentTransitionError("sell_idempotency_lookup_failed")
            return found
        position.exit_intent_id = intent.id
        return intent

    async def record_signature_before_submission(
        self, *, intent: RealWalletLiveIntent, signature: str, at: datetime
    ) -> None:
        """Persist the signature at `SIGNED`, before any network call happens.

        This is the difference between a lost `/execute` response being
        *recoverable* and being permanently unknown. An ed25519 signature is
        deterministic in the key and the message, so the signer knows it before
        anything is sent; storing it here means a timeout leaves behind the one
        value reconciliation needs to ask the chain what actually happened.

        Never a licence to resend. The transaction bytes are still not stored,
        and no caller can rebuild them from this.

        The unique partial index on the column is the replay guard: recording
        the same signature against a second intent raises rather than quietly
        creating a duplicate path to the same on-chain transaction.
        """
        if not signature:
            raise SettlementEvidenceError("signature_required_before_submission")
        result = await self._session.execute(
            update(RealWalletLiveIntent)
            .where(
                RealWalletLiveIntent.id == intent.id,
                RealWalletLiveIntent.state == ExecutionState.SIGNED,
                RealWalletLiveIntent.transaction_signature.is_(None),
            )
            .values(transaction_signature=signature)
        )
        if not isinstance(result, CursorResult) or result.rowcount != 1:
            raise ConcurrentIntentTransitionError("execution_intent_already_signed")
        intent.transaction_signature = signature
        # The signature itself is public on-chain data, not secret material.
        await self._event(intent.id, "signed", {"signature": signature, "at": str(at)})

    async def record_submission_result(
        self,
        *,
        intent: RealWalletLiveIntent,
        signature: str | None,
        outcome: str,
    ) -> None:
        """Record only safe submission facts; transaction bytes are never stored.

        A signature already stored at `SIGNED` is **kept**, not overwritten. An
        unknown outcome carries `signature=None`, and writing that None would
        erase the one value reconciliation needs — turning the exact failure
        this system is built to survive into a permanently unresolvable intent.
        """
        result = await self._session.execute(
            update(RealWalletLiveIntent)
            .where(
                RealWalletLiveIntent.id == intent.id,
                RealWalletLiveIntent.state == ExecutionState.SUBMITTED,
            )
            .values(
                transaction_signature=func.coalesce(
                    signature, RealWalletLiveIntent.transaction_signature
                )
            )
        )
        if not isinstance(result, CursorResult) or result.rowcount != 1:
            raise ConcurrentIntentTransitionError("execution_intent_submission_changed")
        # Assign only when there is something to assign. Reading the attribute
        # first to build a fallback would refresh an instance the last commit
        # expired, which is a lazy load in an async context; and there is
        # nothing to fall back to anyway — the COALESCE above already kept it.
        if signature:
            intent.transaction_signature = signature
        await self._event(
            intent.id,
            "submission_result",
            {"outcome": outcome, "signature": signature},
        )

    async def confirm_settlement(
        self,
        *,
        intent: RealWalletLiveIntent,
        signature: str,
        actual_input_amount_raw: int,
        actual_input_decimals: int,
        actual_output_amount_raw: int,
        actual_output_decimals: int,
        network_fee_lamports: int | None,
        at: datetime,
        sol_price: SolUsdPrice | None = None,
    ) -> RealWalletPosition:
        """Atomically persist one confirmed settlement and its ledger effect.

        `sol_price` is optional and its absence is recorded rather than assumed:
        a settlement whose fee cannot be priced keeps its measured gross figure
        and carries no net figure at all.
        """
        if intent.state not in {
            ExecutionState.SUBMITTED,
            ExecutionState.RECONCILIATION_REQUIRED,
        }:
            raise SettlementEvidenceError("intent_not_reconcilable")
        if (
            actual_input_amount_raw <= 0
            or actual_output_amount_raw <= 0
            or actual_input_decimals < 0
            or actual_output_decimals < 0
            or not intent.input_mint
            or not intent.output_mint
        ):
            raise SettlementEvidenceError("incomplete_confirmed_settlement_evidence")
        if intent.transaction_signature and intent.transaction_signature != signature:
            raise SettlementEvidenceError("transaction_signature_changed")
        if intent.side == "BUY":
            position = await self._open_confirmed_position(
                intent=intent,
                signature=signature,
                actual_input_amount_raw=actual_input_amount_raw,
                actual_input_decimals=actual_input_decimals,
                actual_output_amount_raw=actual_output_amount_raw,
                actual_output_decimals=actual_output_decimals,
                network_fee_lamports=network_fee_lamports,
                at=at,
                sol_price=sol_price,
            )
        elif intent.side == "SELL":
            position = await self._close_confirmed_position(
                intent=intent,
                signature=signature,
                actual_input_amount_raw=actual_input_amount_raw,
                actual_input_decimals=actual_input_decimals,
                actual_output_amount_raw=actual_output_amount_raw,
                actual_output_decimals=actual_output_decimals,
                network_fee_lamports=network_fee_lamports,
                at=at,
                sol_price=sol_price,
            )
        else:
            raise SettlementEvidenceError("unsupported_execution_side")

        assert_transition(current=intent.state, next_state=ExecutionState.CONFIRMED)
        result = await self._session.execute(
            update(RealWalletLiveIntent)
            .where(
                RealWalletLiveIntent.id == intent.id,
                RealWalletLiveIntent.state == intent.state,
            )
            .values(
                state=ExecutionState.CONFIRMED,
                confirmed_at=at,
                transaction_signature=signature,
                actual_input_amount_raw=actual_input_amount_raw,
                actual_input_decimals=actual_input_decimals,
                actual_output_amount_raw=actual_output_amount_raw,
                actual_output_decimals=actual_output_decimals,
                network_fee_lamports=network_fee_lamports,
                position_id=position.id,
            )
        )
        if not isinstance(result, CursorResult) or result.rowcount != 1:
            raise ConcurrentIntentTransitionError("execution_intent_state_changed")
        intent.state = ExecutionState.CONFIRMED
        intent.confirmed_at = at
        intent.transaction_signature = signature
        intent.position_id = position.id
        await self._event(
            intent.id,
            ExecutionState.CONFIRMED,
            {
                "signature": signature,
                "actual_input_amount_raw": str(actual_input_amount_raw),
                "actual_output_amount_raw": str(actual_output_amount_raw),
            },
        )
        return position

    async def _open_confirmed_position(
        self,
        *,
        intent: RealWalletLiveIntent,
        signature: str,
        actual_input_amount_raw: int,
        actual_input_decimals: int,
        actual_output_amount_raw: int,
        actual_output_decimals: int,
        network_fee_lamports: int | None,
        at: datetime,
        sol_price: SolUsdPrice | None = None,
    ) -> RealWalletPosition:
        if (
            intent.input_mint != settings.JUPITER_USDC_MINT
            or intent.output_mint != intent.mint_address
        ):
            raise SettlementEvidenceError("buy_pair_is_not_usdc_to_intent_mint")
        input_amount = _ui_amount(actual_input_amount_raw, actual_input_decimals)
        output_amount = _ui_amount(actual_output_amount_raw, actual_output_decimals)
        position = RealWalletPosition(
            mint_address=intent.mint_address,
            status="OPEN",
            opened_intent_id=None,
            opened_live_intent_id=intent.id,
            quantity=output_amount,
            entry_price_usd=input_amount / output_amount,
            opened_at=at,
            wallet_public_key=intent.wallet_public_key,
            strategy_id=intent.strategy_id,
            strategy_version=intent.strategy_version,
            entry_safety_evaluation_id=intent.safety_evaluation_id,
            entry_transaction_signature=signature,
            entry_actual_input_amount=input_amount,
            entry_actual_output_amount=output_amount,
            entry_network_fee_lamports=network_fee_lamports,
            # The reading is stored with the figure it produced, so a later
            # price cannot silently restate a settled entry cost.
            entry_network_fee_usd=fee_usd(lamports=network_fee_lamports, price=sol_price),
            entry_sol_price_usd=(None if sol_price is None else sol_price.usd),
            entry_sol_price_at=(None if sol_price is None else sol_price.observed_at),
            sol_price_source=(None if sol_price is None else sol_price.source),
        )
        self._session.add(position)
        await self._session.flush()
        existing = await self._session.scalar(
            select(RealWalletPosition).where(
                RealWalletPosition.mint_address == intent.mint_address,
                RealWalletPosition.status == "OPEN",
                RealWalletPosition.id != position.id,
            )
        )
        if existing is not None:
            raise OpenPositionExistsError("open_real_position_already_exists")
        return position

    async def _close_confirmed_position(
        self,
        *,
        intent: RealWalletLiveIntent,
        signature: str,
        actual_input_amount_raw: int,
        actual_input_decimals: int,
        actual_output_amount_raw: int,
        actual_output_decimals: int,
        network_fee_lamports: int | None,
        at: datetime,
        sol_price: SolUsdPrice | None = None,
    ) -> RealWalletPosition:
        if intent.position_id is None:
            raise SettlementEvidenceError("sell_missing_position")
        position = await self._session.scalar(
            select(RealWalletPosition)
            .where(RealWalletPosition.id == intent.position_id)
            .with_for_update()
        )
        if (
            position is None
            or position.status != "OPEN"
            or position.exit_intent_id != intent.id
            or intent.input_mint != position.mint_address
            or intent.output_mint != settings.JUPITER_USDC_MINT
        ):
            raise SettlementEvidenceError("sell_position_binding_invalid")
        input_amount = _ui_amount(actual_input_amount_raw, actual_input_decimals)
        output_amount = _ui_amount(actual_output_amount_raw, actual_output_decimals)
        if (
            input_amount != position.quantity
            or intent.requested_token_quantity != position.quantity
        ):
            raise SettlementEvidenceError("sell_quantity_does_not_match_confirmed_position")
        if position.entry_actual_input_amount is None:
            raise SettlementEvidenceError("position_missing_confirmed_entry_cost")
        realised_gross = output_amount - position.entry_actual_input_amount
        position.status = "CLOSED"
        position.closed_at = at
        position.exit_transaction_signature = signature
        position.exit_actual_input_amount = input_amount
        position.exit_actual_output_amount = output_amount
        position.exit_network_fee_lamports = network_fee_lamports
        position.realised_gross_pnl_usd = realised_gross

        # Net is the gross result less every fee this trade demonstrably paid.
        # Both legs count: an entry fee is as real as an exit fee, and charging
        # only the one in front of us would understate the cost of every trade.
        exit_fee = fee_usd(lamports=network_fee_lamports, price=sol_price)
        if sol_price is not None:
            position.exit_network_fee_usd = exit_fee
            position.exit_sol_price_usd = sol_price.usd
            position.exit_sol_price_at = sol_price.observed_at
            position.sol_price_source = sol_price.source

        entry_fee = position.entry_network_fee_usd
        if exit_fee is None or entry_fee is None:
            # Refused rather than approximated. This field previously held the
            # gross figure under a `net` name, which reads as measured; a null
            # with a reason is the honest shape when a fee could not be priced.
            position.realised_net_pnl_usd = None
            position.net_pnl_unavailable_reason = (
                NET_UNAVAILABLE_NO_PRICE
                if sol_price is None or position.entry_sol_price_usd is None
                else NET_UNAVAILABLE_NO_FEE
            )
        else:
            position.realised_net_pnl_usd = realised_gross - entry_fee - exit_fee
            position.net_pnl_unavailable_reason = None
        return position

    async def _event(
        self, intent_id: uuid.UUID, event_type: str, detail: dict[str, object]
    ) -> None:
        self._session.add(
            RealWalletExecutionEvent(intent_id=intent_id, event_type=event_type, detail=detail)
        )


def _ui_amount(raw_amount: int, decimals: int) -> Decimal:
    return Decimal(raw_amount).scaleb(-decimals)
