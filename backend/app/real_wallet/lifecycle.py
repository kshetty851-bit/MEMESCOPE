"""Test-only durable lifecycle for the separately approved execution boundary.

This module deliberately has no default Jupiter client, RPC client, signer, or
task registration. Tests supply every effect. Its job is to make the durable
state machine safe before a separately reviewed live release can attach real
adapters: a submission attempt is committed before an adapter is called, and a
restart only reconciles it.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.models.real_wallet_execution import RealWalletLiveIntent
from app.real_wallet.live_readiness import ExecutionState
from app.real_wallet.live_repository import LiveIntentRepository
from app.real_wallet.live_transport import JupiterExecuteOutcome, JupiterExecutionResult
from app.real_wallet.reconciliation import (
    RealWalletReconciliationService,
    TransactionReconciler,
)

logger = get_logger(__name__)


class TestOnlyLifecycleError(RuntimeError):
    """The mock lifecycle was reached outside the isolated test environment."""


class InvalidPreparedOrderError(RuntimeError):
    """A test order did not match the persisted intent pair and request id."""


@dataclass(frozen=True, slots=True)
class PreparedTestOrder:
    """Ephemeral order material; the transaction payload never reaches storage."""

    request_id: str
    input_mint: str
    output_mint: str
    unsigned_transaction: str
    evidence: dict[str, object]


class TestOrderFactory(Protocol):
    async def prepare(self, intent: RealWalletLiveIntent) -> PreparedTestOrder: ...


class TestTransactionSigner(Protocol):
    def sign(self, unsigned_transaction: str) -> str: ...


class TestSubmissionTransport(Protocol):
    async def execute(
        self, *, signed_transaction: str, request_id: str
    ) -> JupiterExecutionResult: ...


class TestOnlyRealWalletLifecycle:
    """Drive a mock BUY/SELL exactly once through persisted lifecycle boundaries."""

    __test__ = False

    def __init__(
        self,
        session: AsyncSession,
        *,
        order_factory: TestOrderFactory,
        signer: TestTransactionSigner,
        transport: TestSubmissionTransport,
        reconciler: TransactionReconciler,
    ) -> None:
        self._require_test_environment()
        self._session = session
        self._repository = LiveIntentRepository(session)
        self._order_factory = order_factory
        self._signer = signer
        self._transport = transport
        self._reconciler = reconciler

    @staticmethod
    def _require_test_environment() -> None:
        if settings.ENVIRONMENT != "test":
            raise TestOnlyLifecycleError(
                "real_wallet_mock_lifecycle_requires_test_environment"
            )

    async def create_buy(
        self,
        *,
        idempotency_key: str,
        mint_address: str,
        strategy_id: str,
        strategy_version: str,
        wallet_public_key: str,
        requested_usd: Decimal,
    ) -> RealWalletLiveIntent:
        """Persist exactly one BUY intent, without producing an order yet."""
        if requested_usd <= 0:
            raise ValueError("requested_usd_must_be_positive")
        intent = await self._repository.create_intent(
            idempotency_key=idempotency_key,
            mint_address=mint_address,
            side="BUY",
            strategy_id=strategy_id,
            strategy_version=strategy_version,
            wallet_public_key=wallet_public_key,
            requested_usd=requested_usd,
            input_mint=settings.JUPITER_USDC_MINT,
            output_mint=mint_address,
        )
        if intent is None:
            found = await self._repository.by_idempotency_key(idempotency_key)
            if found is None:  # pragma: no cover - defensive database invariant
                raise RuntimeError("buy_idempotency_lookup_failed")
            return found
        await self._checkpoint()
        return intent

    async def create_sell(
        self, *, idempotency_key: str, position_id: uuid.UUID
    ) -> RealWalletLiveIntent:
        """Persist a SELL that is permanently bound to the confirmed position quantity."""
        position = await self._repository.open_position(position_id)
        if position is None:
            # The repository gives the same deliberately opaque reason for a
            # concurrently reserved or closed position.
            from app.real_wallet.live_repository import PositionExitAlreadyRequestedError

            raise PositionExitAlreadyRequestedError("real_position_not_open")
        intent = await self._repository.create_sell_intent(
            idempotency_key=idempotency_key,
            position_id=position.id,
            strategy_id=position.strategy_id or "test_strategy",
            strategy_version=position.strategy_version or "test",
            wallet_public_key=position.wallet_public_key or "",
            output_mint=settings.JUPITER_USDC_MINT,
        )
        await self._checkpoint()
        return intent

    async def advance(self, intent_id: uuid.UUID, *, at: datetime | None = None) -> str:
        """Advance one intent safely; submitted intents are never sent a second time."""
        now = at or datetime.now(UTC)
        intent = await self._repository.by_id(intent_id)
        if intent is None:
            raise ValueError("real_wallet_intent_not_found")
        state = ExecutionState(intent.state)
        if state is ExecutionState.CREATED:
            await self._repository.transition(
                intent=intent,
                next_state=ExecutionState.SAFETY_APPROVED,
                at=now,
                detail={"test_only": True},
            )
            await self._checkpoint()
            return ExecutionState.SAFETY_APPROVED
        if state is ExecutionState.SAFETY_APPROVED:
            active_switches = await self._repository.active_kill_switches()
            if active_switches:
                await self._repository.transition(
                    intent=intent,
                    next_state=ExecutionState.BLOCKED,
                    at=now,
                    detail={"kill_switches": [switch.kind for switch in active_switches]},
                    failure_reason="kill_switch_active",
                )
                await self._checkpoint()
                return ExecutionState.BLOCKED
            return await self._prepare_sign_and_submit(intent, now=now)
        if state in {ExecutionState.ORDER_CREATED, ExecutionState.SIGNED}:
            # We intentionally never persist a transaction payload. A process
            # restart at either point cannot know it is safe/fresh to sign or
            # submit again, so it fails terminally rather than guessing.
            await self._repository.transition(
                intent=intent,
                next_state=ExecutionState.FAILED,
                at=now,
                detail={"recovery": True, "reason": "ephemeral_order_payload_lost"},
                failure_reason="crash_before_submission",
            )
            await self._repository.record_execution_failure(
                reason="crash_before_submission", at=now
            )
            await self._checkpoint()
            return ExecutionState.FAILED
        # SUBMITTED and RECONCILIATION_REQUIRED deliberately do nothing here:
        # they must flow through ``recover`` and independent chain evidence.
        return str(state)

    async def recover(self, *, at: datetime | None = None) -> dict[str, int]:
        """Recover crashes without recreating orders or re-submitting anything."""
        now = at or datetime.now(UTC)
        stranded = await self._repository.stranded_before_submission()
        failed = 0
        for intent in stranded:
            await self.advance(intent.id, at=now)
            failed += 1
        unresolved = await self._repository.unresolved()
        reconciled = 0
        service = RealWalletReconciliationService(self._repository, self._reconciler)
        for intent in unresolved:
            await service.reconcile(intent=intent, at=now)
            reconciled += 1
        if failed or reconciled:
            await self._checkpoint()
        logger.info(
            "real_wallet_test_recovery_completed",
            stranded_failed=failed,
            unresolved_reconciled=reconciled,
        )
        return {"stranded_failed": failed, "unresolved_reconciled": reconciled}

    async def _prepare_sign_and_submit(
        self, intent: RealWalletLiveIntent, *, now: datetime
    ) -> str:
        prepared = await self._order_factory.prepare(intent)
        self._validate_prepared_order(intent, prepared)
        await self._repository.transition(
            intent=intent,
            next_state=ExecutionState.ORDER_CREATED,
            at=now,
            detail={"request_id": prepared.request_id, "test_only": True},
            jupiter_request_id=prepared.request_id,
            order_evidence=_safe_evidence(prepared.evidence),
        )
        await self._checkpoint()
        signed_transaction = self._signer.sign(prepared.unsigned_transaction)
        if not signed_transaction:
            raise InvalidPreparedOrderError("test_signer_returned_empty_transaction")
        await self._repository.transition(
            intent=intent,
            next_state=ExecutionState.SIGNED,
            at=now,
            detail={"request_id": prepared.request_id},
        )
        await self._checkpoint()

        active_switches = await self._repository.active_kill_switches()
        if active_switches:
            await self._repository.transition(
                intent=intent,
                next_state=ExecutionState.BLOCKED,
                at=now,
                detail={"kill_switches": [switch.kind for switch in active_switches]},
                failure_reason="kill_switch_active",
            )
            await self._checkpoint()
            return ExecutionState.BLOCKED

        # This commit is the critical crash boundary. Any timeout or process
        # death after it is an uncertain submitted transaction, never a retry.
        await self._repository.transition(
            intent=intent,
            next_state=ExecutionState.SUBMITTED,
            at=now,
            detail={"submission_started": True, "request_id": prepared.request_id},
        )
        await self._checkpoint()
        try:
            result = await self._transport.execute(
                signed_transaction=signed_transaction,
                request_id=prepared.request_id,
            )
        except Exception:
            await self._repository.record_submission_result(
                intent=intent, signature=None, outcome="unknown"
            )
            await self._checkpoint()
            logger.warning(
                "real_wallet_test_submission_unknown",
                intent_id=str(intent.id),
                request_id=prepared.request_id,
            )
            return ExecutionState.SUBMITTED

        await self._repository.record_submission_result(
            intent=intent,
            signature=result.signature,
            outcome=result.outcome,
        )
        if result.outcome is JupiterExecuteOutcome.FAILED:
            await self._repository.transition(
                intent=intent,
                next_state=ExecutionState.FAILED,
                at=now,
                detail={"submission_failed": True, "error_code": result.error_code},
                failure_reason=result.error_code or "jupiter_execute_failed",
            )
            await self._repository.record_execution_failure(
                reason=result.error_code or "jupiter_execute_failed", at=now
            )
            await self._checkpoint()
            return ExecutionState.FAILED
        await self._checkpoint()
        return ExecutionState.SUBMITTED

    @staticmethod
    def _validate_prepared_order(
        intent: RealWalletLiveIntent, order: PreparedTestOrder
    ) -> None:
        if (
            not order.request_id
            or not order.unsigned_transaction
            or order.input_mint != intent.input_mint
            or order.output_mint != intent.output_mint
        ):
            raise InvalidPreparedOrderError("prepared_order_does_not_match_intent")

    async def _checkpoint(self) -> None:
        """Persist each lifecycle boundary before the next side effect."""
        await self._session.commit()


def _safe_evidence(value: dict[str, object]) -> dict[str, object]:
    """Remove transaction, signer, and secret-shaped fields before persistence/logging."""
    blocked = ("transaction", "signed", "private", "secret", "keypair")

    def clean(item: object) -> object:
        if isinstance(item, dict):
            return {
                str(key): clean(child)
                for key, child in item.items()
                if not any(word in str(key).lower() for word in blocked)
            }
        if isinstance(item, list):
            return [clean(child) for child in item]
        return item

    cleaned = clean(value)
    return cleaned if isinstance(cleaned, dict) else {}
