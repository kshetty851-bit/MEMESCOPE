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
from app.real_wallet.live_repository import LiveIntentRepository, SettlementEvidenceError
from app.real_wallet.sol_price import SolUsdPriceSource
from app.services.rpc.base import RpcError, SolanaRPC


class ChainOutcome(StrEnum):
    CONFIRMED = "confirmed"
    FAILED = "failed"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ChainReceipt:
    outcome: ChainOutcome
    signature: str | None = None
    actual_input_amount: str | None = None
    actual_input_decimals: int | None = None
    actual_output_amount: str | None = None
    actual_output_decimals: int | None = None
    network_fee_lamports: int | None = None

    @property
    def has_settlement_evidence(self) -> bool:
        """Confirmation without exact wallet deltas is not a settled execution."""
        try:
            return (
                bool(self.signature)
                and int(self.actual_input_amount or "0") > 0
                and int(self.actual_output_amount or "0") > 0
                and self.actual_input_decimals is not None
                and self.actual_input_decimals >= 0
                and self.actual_output_decimals is not None
                and self.actual_output_decimals >= 0
            )
        except ValueError:
            return False


@dataclass(frozen=True, slots=True)
class WalletBalanceDelta:
    mint: str
    raw_delta: int
    decimals: int


def extract_wallet_token_delta(
    *, transaction: dict[str, object], wallet_public_key: str, mint: str
) -> WalletBalanceDelta | None:
    """Return a wallet-owned mint delta only when token metadata is unambiguous.

    Multiple associated accounts are summed; conflicting decimals or malformed
    entries return ``None`` rather than inventing an execution quantity.
    """
    meta = transaction.get("meta")
    if not isinstance(meta, dict):
        return None
    totals: dict[int, int] = {}
    decimals: int | None = None
    for key, sign in (("postTokenBalances", 1), ("preTokenBalances", -1)):
        rows = meta.get(key)
        if not isinstance(rows, list):
            return None
        for row in rows:
            if (
                not isinstance(row, dict)
                or row.get("owner") != wallet_public_key
                or row.get("mint") != mint
            ):
                continue
            amount = row.get("uiTokenAmount")
            if not isinstance(amount, dict) or not isinstance(amount.get("amount"), str):
                return None
            try:
                index = int(row["accountIndex"])
                row_decimals = int(amount["decimals"])
                raw = int(amount["amount"])
            except (KeyError, TypeError, ValueError):
                return None
            if decimals is not None and decimals != row_decimals:
                return None
            decimals = row_decimals
            totals[index] = totals.get(index, 0) + sign * raw
    if decimals is None:
        return None
    return WalletBalanceDelta(mint=mint, raw_delta=sum(totals.values()), decimals=decimals)


class TransactionReconciler:
    """Protocol boundary; an RPC implementation arrives in a later release."""

    async def inspect(self, intent: RealWalletLiveIntent) -> ChainReceipt:
        del intent
        return ChainReceipt(outcome=ChainOutcome.UNKNOWN)


class SolanaRpcTransactionReconciler(TransactionReconciler):
    """Independent RPC confirmation; unavailable evidence stays unknown.

    A landed transaction is not enough to settle a real position. The wallet's
    owned token accounts are aggregated for both sides of the order so every
    BUY quantity and every SELL proceeds value comes from confirmed evidence.
    """

    def __init__(self, rpc: SolanaRPC) -> None:
        self._rpc = rpc

    async def inspect(self, intent: RealWalletLiveIntent) -> ChainReceipt:
        signature = intent.transaction_signature
        if not signature:
            return ChainReceipt(outcome=ChainOutcome.UNKNOWN)
        try:
            transaction = await self._rpc.get_transaction(signature, attempts=1)
        except RpcError:
            return ChainReceipt(outcome=ChainOutcome.UNKNOWN, signature=signature)
        if not transaction:
            return ChainReceipt(outcome=ChainOutcome.UNKNOWN, signature=signature)
        meta = transaction.get("meta")
        if not isinstance(meta, dict):
            return ChainReceipt(outcome=ChainOutcome.UNKNOWN, signature=signature)
        if meta.get("err") is not None:
            return ChainReceipt(outcome=ChainOutcome.FAILED, signature=signature)
        if not intent.input_mint or not intent.output_mint:
            return ChainReceipt(outcome=ChainOutcome.UNKNOWN, signature=signature)
        input_delta = extract_wallet_token_delta(
            transaction=transaction,
            wallet_public_key=intent.wallet_public_key,
            mint=intent.input_mint,
        )
        output_delta = extract_wallet_token_delta(
            transaction=transaction,
            wallet_public_key=intent.wallet_public_key,
            mint=intent.output_mint,
        )
        if (
            input_delta is None
            or output_delta is None
            or input_delta.raw_delta >= 0
            or output_delta.raw_delta <= 0
        ):
            return ChainReceipt(outcome=ChainOutcome.UNKNOWN, signature=signature)
        fee = meta.get("fee")
        network_fee = fee if isinstance(fee, int) and fee >= 0 else None
        return ChainReceipt(
            outcome=ChainOutcome.CONFIRMED,
            signature=signature,
            actual_input_amount=str(-input_delta.raw_delta),
            actual_input_decimals=input_delta.decimals,
            actual_output_amount=str(output_delta.raw_delta),
            actual_output_decimals=output_delta.decimals,
            network_fee_lamports=network_fee,
        )


class RealWalletReconciliationService:
    def __init__(
        self,
        repository: LiveIntentRepository,
        reconciler: TransactionReconciler,
        *,
        sol_price_source: SolUsdPriceSource | None = None,
    ) -> None:
        self._repository = repository
        self._reconciler = reconciler
        # Optional on purpose. A settlement must still be recorded when SOL/USD
        # is unavailable — it keeps its measured gross figure and claims no net
        # figure — because refusing to settle a confirmed on-chain trade would
        # leave a real position invisible to the ledger.
        self._sol_price_source = sol_price_source

    async def reconcile(self, *, intent: RealWalletLiveIntent, at: datetime) -> ChainOutcome:
        receipt = await self._reconciler.inspect(intent)
        if receipt.outcome is ChainOutcome.CONFIRMED and receipt.has_settlement_evidence:
            sol_price = (
                None
                if self._sol_price_source is None
                else await self._sol_price_source.current(now=at)
            )
            try:
                await self._repository.confirm_settlement(
                    sol_price=sol_price,
                    intent=intent,
                    signature=receipt.signature or "",
                    actual_input_amount_raw=int(receipt.actual_input_amount or "0"),
                    actual_input_decimals=receipt.actual_input_decimals or 0,
                    actual_output_amount_raw=int(receipt.actual_output_amount or "0"),
                    actual_output_decimals=receipt.actual_output_decimals or 0,
                    network_fee_lamports=receipt.network_fee_lamports,
                    at=at,
                )
            except SettlementEvidenceError as exc:
                if intent.state == ExecutionState.SUBMITTED:
                    await self._repository.transition(
                        intent=intent,
                        next_state=ExecutionState.RECONCILIATION_REQUIRED,
                        at=at,
                        detail={
                            "reconciled": True,
                            "outcome": "unsettled",
                            "reason": str(exc),
                        },
                    )
                return ChainOutcome.UNKNOWN
            await self._repository.record_execution_success(at=at)
        elif receipt.outcome is ChainOutcome.FAILED:
            await self._repository.transition(
                intent=intent,
                next_state=ExecutionState.FAILED,
                at=at,
                detail={"reconciled": True},
                failure_reason="on_chain_execution_failed",
            )
            await self._repository.record_execution_failure(
                reason="on_chain_execution_failed", at=at
            )
        elif intent.state == ExecutionState.SUBMITTED:
            await self._repository.transition(
                intent=intent,
                next_state=ExecutionState.RECONCILIATION_REQUIRED,
                at=at,
                detail={
                    "reconciled": True,
                    "outcome": "unknown",
                    "confirmed_evidence_complete": receipt.has_settlement_evidence,
                },
            )
        if receipt.outcome is ChainOutcome.CONFIRMED and not receipt.has_settlement_evidence:
            return ChainOutcome.UNKNOWN
        return receipt.outcome
