"""Crash-safe reconciliation for future submitted real-wallet intents.

No retry function appears here. An unknown submitted transaction must be
reconciled from durable evidence, never sent again merely because a worker
restarted.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from app.models.real_wallet_execution import RealWalletLiveIntent
from app.real_wallet.live_readiness import ExecutionState
from app.real_wallet.live_repository import LiveIntentRepository


class ChainOutcome(StrEnum):
    CONFIRMED = "confirmed"
    FAILED = "failed"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ChainReceipt:
    outcome: ChainOutcome
    signature: str | None = None
    actual_input_amount: str | None = None
    actual_output_amount: str | None = None
    network_fee_lamports: int | None = None


class TransactionReconciler:
    """Protocol boundary; an RPC implementation arrives in a later release."""

    async def inspect(self, intent: RealWalletLiveIntent) -> ChainReceipt:
        del intent
        return ChainReceipt(outcome=ChainOutcome.UNKNOWN)


class RealWalletReconciliationService:
    def __init__(
        self, repository: LiveIntentRepository, reconciler: TransactionReconciler
    ) -> None:
        self._repository = repository
        self._reconciler = reconciler

    async def reconcile(self, *, intent: RealWalletLiveIntent, at: datetime) -> ChainOutcome:
        receipt = await self._reconciler.inspect(intent)
        if receipt.outcome is ChainOutcome.CONFIRMED:
            await self._repository.transition(
                intent=intent,
                next_state=ExecutionState.CONFIRMED,
                at=at,
                detail={"signature": receipt.signature, "reconciled": True},
                transaction_signature=receipt.signature,
            )
        elif receipt.outcome is ChainOutcome.FAILED:
            await self._repository.transition(
                intent=intent,
                next_state=ExecutionState.FAILED,
                at=at,
                detail={"reconciled": True},
                failure_reason="on_chain_execution_failed",
            )
        elif intent.state == ExecutionState.SUBMITTED:
            await self._repository.transition(
                intent=intent,
                next_state=ExecutionState.RECONCILIATION_REQUIRED,
                at=at,
                detail={"reconciled": True, "outcome": "unknown"},
            )
        return receipt.outcome
