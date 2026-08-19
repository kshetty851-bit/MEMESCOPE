"""Phase 2 manual-devnet execution workflow.

The only executable route is a tiny native-SOL transfer on verified Solana
devnet.  Jupiter is intentionally *not* invoked: its public swap routes do not
provide a reviewed devnet execution surface.  Quotes still use the same durable
shape, so a future provider that demonstrably supports devnet can be added
without weakening the signer or lifecycle boundaries.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.real_wallet_execution import RealWalletDevnetIntent, RealWalletDevnetQuote
from app.real_wallet.devnet_intent import DevnetIntentState
from app.real_wallet.devnet_repository import (
    DevnetIntentExpiredError,
    DevnetIntentNotFoundError,
    DevnetIntentRepository,
)
from app.real_wallet.devnet_transaction import (
    NATIVE_SOL_MINT,
    NativeTransferSpec,
    build_unsigned_native_transfer,
    inspect_native_transfer,
    transaction_fingerprint,
)
from app.real_wallet.network import (
    DevnetExecutionBlockedError,
    is_valid_wallet_address,
    require_verified_devnet,
)
from app.services.rpc.base import SolanaRPC

SYSTEM_TRANSFER_PROVIDER = "solana_system_program_devnet"
SYSTEM_TRANSFER_REFERENCE = "system-transfer:v1"
SYSTEM_TRANSFER_ESTIMATED_FEE_LAMPORTS = 5_000


class DevnetManualWorkflowError(RuntimeError):
    """A Phase 2 precondition failed without a recoverable server error."""


class DevnetApprovalRequiredError(DevnetManualWorkflowError):
    """The manual approval boundary has not been satisfied."""


def _now(now: datetime | None = None) -> datetime:
    return now or datetime.now(UTC)


def _rpc_endpoint() -> str:
    """Persist an endpoint identity without query-string credentials."""
    return settings.REAL_WALLET_RPC_URL.split("?", 1)[0]


def _require_configured_wallet() -> str:
    if settings.REAL_WALLET_NETWORK != "devnet":
        raise DevnetExecutionBlockedError("phase2_devnet_only")
    wallet = settings.REAL_WALLET_PUBLIC_KEY.strip()
    if not wallet or not is_valid_wallet_address(wallet):
        raise DevnetManualWorkflowError("devnet_wallet_public_key_not_configured")
    return wallet


class DevnetManualWorkflow:
    """Create, simulate, approve, submit, confirm, and reconcile one intent."""

    def __init__(self, session: AsyncSession, rpc: SolanaRPC) -> None:
        self._session = session
        self._rpc = rpc
        self._repository = DevnetIntentRepository(session)

    @property
    def repository(self) -> DevnetIntentRepository:
        return self._repository

    async def quote_native_transfer(
        self, *, destination_public_key: str, lamports: int, now: datetime | None = None
    ) -> RealWalletDevnetQuote:
        """Persist a read-only native-transfer quote; no signer or RPC call occurs."""
        at = _now(now)
        wallet = _require_configured_wallet()
        if not is_valid_wallet_address(destination_public_key):
            raise DevnetManualWorkflowError("invalid_transfer_destination")
        if destination_public_key == wallet:
            raise DevnetManualWorkflowError("self_transfer_not_permitted")
        if not 0 < lamports <= settings.PHASE2_DEVNET_MAX_TRANSFER_LAMPORTS:
            raise DevnetManualWorkflowError("transfer_amount_outside_devnet_limit")
        # Jupiter quote/swap APIs do not offer a reviewed devnet route. The
        # provider name says what was actually quoted rather than implying a
        # market route exists. A SOL transfer has zero price impact and exactly
        # one expected output: the recipient receives the quoted lamports.
        return await self._repository.create_quote(
            wallet_public_key=wallet,
            input_mint=NATIVE_SOL_MINT,
            output_mint=NATIVE_SOL_MINT,
            input_amount_raw=Decimal(lamports),
            expected_output_raw=Decimal(lamports),
            minimum_output_raw=Decimal(lamports),
            slippage_bps=0,
            price_impact_pct=Decimal("0"),
            estimated_fee_lamports=SYSTEM_TRANSFER_ESTIMATED_FEE_LAMPORTS,
            provider=SYSTEM_TRANSFER_PROVIDER,
            provider_reference=SYSTEM_TRANSFER_REFERENCE,
            route={
                "kind": "system_transfer",
                "destination": destination_public_key,
                "jupiter_devnet_supported": False,
                "provider_limitation": "Jupiter devnet swap routing is not used or implied.",
            },
            quoted_at=at,
            expires_at=at + timedelta(seconds=settings.PHASE2_DEVNET_QUOTE_TTL_SECONDS),
            provider_payload={
                "network": "devnet",
                "execution_path": "native_system_transfer",
                "raw_provider_reference": SYSTEM_TRANSFER_REFERENCE,
            },
        )

    async def create_intent(
        self,
        *,
        quote_id: uuid.UUID,
        idempotency_key: str,
        now: datetime | None = None,
    ) -> RealWalletDevnetIntent:
        """Create a DRAFT then attach one unexpired devnet transfer quote."""
        at = _now(now)
        wallet = _require_configured_wallet()
        if not idempotency_key.strip():
            raise DevnetManualWorkflowError("idempotency_key_required")
        quote = await self._quote_or_raise(quote_id)
        self._validate_native_quote(quote=quote, wallet=wallet, at=at)
        destination = str((quote.route or {}).get("destination") or "")
        intent = await self._repository.create_intent(
            idempotency_key=idempotency_key.strip(),
            wallet_public_key=wallet,
            action_type="SOL_TRANSFER",
            input_mint=quote.input_mint,
            output_mint=quote.output_mint,
            input_amount_raw=quote.input_amount_raw,
            destination_public_key=destination,
            at=at,
        )
        if intent is None:
            existing = await self._repository.intent_by_idempotency_key(
                idempotency_key.strip()
            )
            if existing is None:  # pragma: no cover - database invariant
                raise DevnetManualWorkflowError("idempotency_recovery_failed")
            return existing
        await self._repository.transition(
            intent=intent,
            next_state=DevnetIntentState.QUOTED,
            at=at,
            event_type="quote_attached",
            detail={"quote_id": str(quote.id), "provider": quote.provider},
            quote_id=quote.id,
            quote_expires_at=quote.expires_at,
        )
        return intent

    async def simulate(
        self, *, intent_id: uuid.UUID, now: datetime | None = None
    ) -> RealWalletDevnetIntent:
        """Build, allowlist-inspect, and simulate an unsigned transaction."""
        at = _now(now)
        intent = await self._intent_or_raise(intent_id)
        if intent.state == DevnetIntentState.AWAITING_APPROVAL:
            return intent  # idempotent replay; it already has a successful simulation.
        if intent.state != DevnetIntentState.QUOTED:
            raise DevnetManualWorkflowError("intent_not_ready_for_simulation")
        if await self._repository.expire_if_needed(intent=intent, at=at):
            raise DevnetIntentExpiredError("quote_expired")
        try:
            await require_verified_devnet(
                self._rpc, configured_network=settings.REAL_WALLET_NETWORK
            )
            quote = await self._quote_or_raise(intent.quote_id)
            self._validate_native_quote(quote=quote, wallet=intent.wallet_public_key, at=at)
            spec = self._spec_from_intent(intent)
            latest = await self._rpc.call("getLatestBlockhash", [{"commitment": "confirmed"}])
            blockhash, blockhash_slot = _latest_blockhash(latest)
            encoded = build_unsigned_native_transfer(spec=spec, blockhash=blockhash)
            inspected = inspect_native_transfer(encoded, expected=spec)
            pre_balances = await self._read_balances(spec)
            simulation = await self._rpc.call(
                "simulateTransaction",
                [
                    encoded,
                    {
                        "encoding": "base64",
                        "sigVerify": False,
                        "replaceRecentBlockhash": True,
                        "commitment": "confirmed",
                    },
                ],
            )
            outcome = _simulation_outcome(simulation)
        except (DevnetExecutionBlockedError, DevnetManualWorkflowError):
            raise
        except Exception as exc:
            await self._repository.fail(
                intent=intent,
                at=at,
                reason="simulation_precondition_failed",
                detail={"error": _safe_error(exc)},
            )
            raise DevnetManualWorkflowError("simulation_precondition_failed") from exc

        fields = {
            "transaction_base64": encoded,
            "transaction_fingerprint": inspected.fingerprint,
            "transaction_metadata": {
                **inspected.as_metadata(),
                "latest_blockhash_context_slot": blockhash_slot,
                "pre_balances_lamports": pre_balances,
            },
            "simulation_result": outcome["raw"],
            "simulation_logs": outcome["logs"],
            "simulation_units_consumed": outcome["units_consumed"],
            "simulation_context_slot": outcome["context_slot"],
            "simulation_blockhash": inspected.recent_blockhash,
            "simulated_at": at,
            "simulation_status": "SUCCESS" if outcome["success"] else "FAILED",
        }
        if not outcome["success"]:
            await self._repository.transition(
                intent=intent,
                next_state=DevnetIntentState.FAILED,
                at=at,
                event_type="simulation_failed",
                detail={"error": outcome["error"], "logs": outcome["logs"]},
                failure_reason="simulation_failed",
                **fields,
            )
            raise DevnetManualWorkflowError("simulation_failed")
        await self._repository.transition(
            intent=intent,
            next_state=DevnetIntentState.SIMULATED,
            at=at,
            event_type="simulated",
            detail={
                "units_consumed": outcome["units_consumed"],
                "context_slot": outcome["context_slot"],
            },
            **fields,
        )
        await self._repository.transition(
            intent=intent,
            next_state=DevnetIntentState.AWAITING_APPROVAL,
            at=at,
            event_type="awaiting_manual_approval",
            detail={"explicit_manual_action_required": True},
        )
        return intent

    async def approve(
        self,
        *,
        intent_id: uuid.UUID,
        approved_by_user_id: uuid.UUID,
        confirmation_phrase: str,
        now: datetime | None = None,
    ) -> RealWalletDevnetIntent:
        """An admin explicitly approves one successful, fresh simulation."""
        at = _now(now)
        intent = await self._intent_or_raise(intent_id)
        if intent.state == DevnetIntentState.APPROVED:
            return intent
        if intent.state != DevnetIntentState.AWAITING_APPROVAL:
            raise DevnetApprovalRequiredError("intent_not_awaiting_manual_approval")
        if confirmation_phrase != "APPROVE_DEVNET_TRANSFER":
            raise DevnetApprovalRequiredError("explicit_approval_phrase_required")
        if intent.simulation_status != "SUCCESS" or not intent.transaction_base64:
            raise DevnetApprovalRequiredError("successful_simulation_required")
        if await self._repository.expire_if_needed(intent=intent, at=at):
            raise DevnetIntentExpiredError("quote_expired")
        approval_expiry = at + timedelta(seconds=settings.PHASE2_DEVNET_APPROVAL_TTL_SECONDS)
        await self._repository.transition(
            intent=intent,
            next_state=DevnetIntentState.APPROVED,
            at=at,
            event_type="manually_approved",
            detail={
                "approved_by_user_id": str(approved_by_user_id),
                "expires_at": approval_expiry.isoformat(),
            },
            approval_status="APPROVED",
            approved_by_user_id=approved_by_user_id,
            approved_at=at,
            approval_expires_at=approval_expiry,
            signing_status="PENDING",
        )
        return intent

    async def submit(
        self, *, intent_id: uuid.UUID, now: datetime | None = None
    ) -> RealWalletDevnetIntent:
        """Commit a submit claim before one devnet JSON-RPC sendTransaction call."""
        at = _now(now)
        intent = await self._intent_or_raise(intent_id)
        if intent.state == DevnetIntentState.SUBMITTED:
            return intent
        if intent.state != DevnetIntentState.SIGNED:
            raise DevnetManualWorkflowError("intent_not_signed")
        if not intent.signed_transaction_base64 or not intent.transaction_signature:
            raise DevnetManualWorkflowError("signed_transaction_missing")
        if intent.simulation_status != "SUCCESS":
            raise DevnetManualWorkflowError("successful_simulation_required")
        if await self._repository.expire_if_needed(intent=intent, at=at):
            raise DevnetIntentExpiredError("approval_expired")
        spec = self._spec_from_intent(intent)
        try:
            inspected = inspect_native_transfer(
                intent.signed_transaction_base64, expected=spec
            )
            original_fingerprint = intent.transaction_fingerprint
            # Signing changes transaction bytes, so the stored unsigned digest
            # must differ. The semantic metadata, not a byte-identical digest,
            # is the invariant at this boundary.
            if not original_fingerprint or not intent.signer_validation:
                raise DevnetManualWorkflowError("signer_validation_missing")
            if intent.signer_validation.get(
                "signed_transaction_fingerprint"
            ) != transaction_fingerprint(intent.signed_transaction_base64):
                raise DevnetManualWorkflowError("signed_transaction_fingerprint_changed")
            if (
                intent.signer_validation.get("transaction_semantics")
                != inspected.as_metadata()
            ):
                raise DevnetManualWorkflowError("signed_transaction_changed")
            await require_verified_devnet(
                self._rpc, configured_network=settings.REAL_WALLET_NETWORK
            )
        except DevnetExecutionBlockedError:
            raise
        except Exception as exc:
            await self._repository.fail(
                intent=intent,
                at=at,
                reason="submission_validation_failed",
                detail={"error": _safe_error(exc)},
            )
            raise DevnetManualWorkflowError("submission_validation_failed") from exc
        # This is committed before wire I/O. A timeout is therefore uncertain
        # submission, never a cue to submit the same signed bytes again.
        await self._repository.transition(
            intent=intent,
            next_state=DevnetIntentState.SUBMITTED,
            at=at,
            event_type="submission_claimed",
            detail={"rpc_endpoint": _rpc_endpoint(), "retry_count": 1},
            submission_status="SUBMITTING",
            submission_retry_count=1,
            rpc_endpoint=_rpc_endpoint(),
            submitted_at=at,
        )
        await self._session.commit()
        try:
            returned_signature = await self._rpc.call(
                "sendTransaction",
                [
                    intent.signed_transaction_base64,
                    {
                        "encoding": "base64",
                        "skipPreflight": False,
                        "preflightCommitment": "confirmed",
                        "maxRetries": 0,
                    },
                ],
                attempts=1,
            )
            if (
                not isinstance(returned_signature, str)
                or returned_signature != intent.transaction_signature
            ):
                raise DevnetManualWorkflowError("unexpected_submission_signature")
            await self._repository.update_if_state(
                intent=intent,
                at=at,
                event_type="submitted",
                detail={"signature": intent.transaction_signature},
                submission_status="SUBMITTED",
                submission_error=None,
            )
        except Exception as exc:
            # The signed transaction may have reached the node even if its
            # response did not. Preserve SUBMITTED and only reconcile status.
            await self._repository.update_if_state(
                intent=intent,
                at=at,
                event_type="submission_response_unknown",
                detail={"error": _safe_error(exc)},
                submission_status="UNKNOWN",
                submission_error=_safe_error(exc),
            )
        return intent

    async def confirm_and_reconcile(
        self, *, intent_id: uuid.UUID, now: datetime | None = None
    ) -> RealWalletDevnetIntent:
        """Bounded status polling, then balance reconciliation after confirmation."""
        at = _now(now)
        intent = await self._intent_or_raise(intent_id)
        if intent.state == DevnetIntentState.CONFIRMED:
            if intent.reconciled_at is None:
                await self.reconcile(intent=intent, now=at)
            return intent
        if intent.state != DevnetIntentState.SUBMITTED or not intent.transaction_signature:
            raise DevnetManualWorkflowError("intent_not_submitted")
        await require_verified_devnet(
            self._rpc, configured_network=settings.REAL_WALLET_NETWORK
        )
        status: dict[str, Any] | None = None
        for attempt in range(1, settings.PHASE2_DEVNET_CONFIRM_RETRIES + 1):
            result = await self._rpc.call(
                "getSignatureStatuses",
                [[intent.transaction_signature], {"searchTransactionHistory": True}],
                attempts=1,
            )
            candidate = _signature_status(result)
            if candidate is not None:
                status = candidate
                if candidate.get("err") is not None or candidate.get("confirmationStatus") in {
                    "confirmed",
                    "finalized",
                }:
                    break
            if attempt < settings.PHASE2_DEVNET_CONFIRM_RETRIES:
                await asyncio.sleep(settings.PHASE2_DEVNET_CONFIRM_RETRY_SECONDS)
        if status is None:
            await self._repository.transition(
                intent=intent,
                next_state=DevnetIntentState.FAILED,
                at=at,
                event_type="confirmation_dropped",
                detail={"attempts": settings.PHASE2_DEVNET_CONFIRM_RETRIES},
                confirmation_status="DROPPED",
                failure_reason="confirmation_dropped",
            )
            return intent
        if status.get("err") is not None:
            await self._repository.transition(
                intent=intent,
                next_state=DevnetIntentState.FAILED,
                at=at,
                event_type="confirmation_failed",
                detail={"error": status.get("err")},
                confirmation_status="FAILED",
                confirmation_slot=_as_int(status.get("slot")),
                failure_reason="transaction_failed_on_chain",
            )
            return intent
        confirmation_status = str(status.get("confirmationStatus") or "processed")
        if confirmation_status not in {"confirmed", "finalized"}:
            # Bounded polling ended with a known but not final transaction. It
            # remains submitted and can be checked again; no duplicate send.
            await self._repository.update_if_state(
                intent=intent,
                at=at,
                event_type="confirmation_pending",
                detail={"confirmation_status": confirmation_status},
                confirmation_status=confirmation_status.upper(),
                confirmation_slot=_as_int(status.get("slot")),
            )
            return intent
        await self._repository.transition(
            intent=intent,
            next_state=DevnetIntentState.CONFIRMED,
            at=at,
            event_type="confirmed",
            detail={"confirmation_status": confirmation_status, "slot": status.get("slot")},
            confirmation_status=confirmation_status.upper(),
            confirmation_slot=_as_int(status.get("slot")),
            confirmed_at=at,
        )
        await self.reconcile(intent=intent, now=at)
        return intent

    async def reconcile(
        self, *, intent: RealWalletDevnetIntent, now: datetime | None = None
    ) -> None:
        """Read balances only after confirmed semantics and compare them to quote."""
        at = _now(now)
        if intent.state != DevnetIntentState.CONFIRMED:
            raise DevnetManualWorkflowError("confirmation_required_before_reconciliation")
        await require_verified_devnet(
            self._rpc, configured_network=settings.REAL_WALLET_NETWORK
        )
        spec = self._spec_from_intent(intent)
        try:
            balances = await self._read_balances(spec)
            metadata = intent.transaction_metadata or {}
            before = metadata.get("pre_balances_lamports") or {}
            payer_before = _as_int(before.get("payer"))
            destination_before = _as_int(before.get("destination"))
            payer_after = _as_int(balances["payer"])
            destination_after = _as_int(balances["destination"])
            if None in {payer_before, destination_before, payer_after, destination_after}:
                raise DevnetManualWorkflowError("pre_or_post_balance_missing")
            wallet_delta = payer_after - payer_before
            recipient_delta = destination_after - destination_before
            network_fee = max(0, -(wallet_delta + spec.lamports))
            quote = await self._quote_or_raise(intent.quote_id)
            estimated_fee = quote.estimated_fee_lamports
            reconciliation = {
                "network": "devnet",
                "expected_wallet_sol_delta_lamports": -spec.lamports - (estimated_fee or 0),
                "actual_wallet_sol_delta_lamports": wallet_delta,
                "expected_output_lamports": spec.lamports,
                "actual_output_lamports": recipient_delta,
                "token_delta": None,
                "estimated_network_fee_lamports": estimated_fee,
                "network_fee_lamports": network_fee,
                "execution_price": "1 SOL transfer unit / 1 SOL transfer unit",
                "slippage_bps": 0,
                "quote_vs_actual_output_lamports": recipient_delta - spec.lamports,
                "pre_balances_lamports": before,
                "post_balances_lamports": balances,
            }
            await self._repository.update_if_state(
                intent=intent,
                at=at,
                event_type="reconciled",
                detail=reconciliation,
                reconciliation=reconciliation,
                reconciled_at=at,
            )
        except Exception as exc:
            await self._repository.update_if_state(
                intent=intent,
                at=at,
                event_type="reconciliation_failed",
                detail={"error": _safe_error(exc)},
            )
            raise DevnetManualWorkflowError("reconciliation_failed") from exc

    async def _quote_or_raise(self, quote_id: uuid.UUID | None) -> RealWalletDevnetQuote:
        if quote_id is None:
            raise DevnetManualWorkflowError("intent_quote_missing")
        quote = await self._repository.quote_by_id(quote_id)
        if quote is None:
            raise DevnetManualWorkflowError("devnet_quote_not_found")
        return quote

    async def _intent_or_raise(self, intent_id: uuid.UUID) -> RealWalletDevnetIntent:
        intent = await self._repository.intent_by_id(intent_id)
        if intent is None:
            raise DevnetIntentNotFoundError("devnet_intent_not_found")
        return intent

    @staticmethod
    def _validate_native_quote(
        *, quote: RealWalletDevnetQuote, wallet: str, at: datetime
    ) -> None:
        if quote.network != "devnet" or quote.wallet_public_key != wallet:
            raise DevnetManualWorkflowError("quote_wallet_or_network_mismatch")
        if quote.provider != SYSTEM_TRANSFER_PROVIDER:
            raise DevnetManualWorkflowError("unsupported_devnet_quote_provider")
        if quote.expires_at <= at:
            raise DevnetIntentExpiredError("quote_expired")
        if quote.input_mint != NATIVE_SOL_MINT or quote.output_mint != NATIVE_SOL_MINT:
            raise DevnetManualWorkflowError("unexpected_quote_mint")
        if quote.input_amount_raw != quote.expected_output_raw:
            raise DevnetManualWorkflowError("unexpected_quote_amount")
        if quote.minimum_output_raw != quote.expected_output_raw or quote.slippage_bps != 0:
            raise DevnetManualWorkflowError("unexpected_quote_slippage")

    @staticmethod
    def _spec_from_intent(intent: RealWalletDevnetIntent) -> NativeTransferSpec:
        if intent.network != "devnet" or intent.action_type != "SOL_TRANSFER":
            raise DevnetManualWorkflowError("unsupported_devnet_intent")
        if intent.input_mint != NATIVE_SOL_MINT or intent.output_mint != NATIVE_SOL_MINT:
            raise DevnetManualWorkflowError("unexpected_intent_mint")
        if not intent.destination_public_key:
            raise DevnetManualWorkflowError("intent_destination_missing")
        lamports = int(intent.input_amount_raw)
        if not 0 < lamports <= settings.PHASE2_DEVNET_MAX_TRANSFER_LAMPORTS:
            raise DevnetManualWorkflowError("intent_amount_outside_devnet_limit")
        return NativeTransferSpec(
            fee_payer=intent.wallet_public_key,
            destination=intent.destination_public_key,
            lamports=lamports,
        )

    async def _read_balances(self, spec: NativeTransferSpec) -> dict[str, int]:
        payer = await self._rpc.call(
            "getBalance", [spec.fee_payer, {"commitment": "confirmed"}]
        )
        destination = await self._rpc.call(
            "getBalance", [spec.destination, {"commitment": "confirmed"}]
        )
        return {
            "payer": _balance_lamports(payer),
            "destination": _balance_lamports(destination),
        }


def _latest_blockhash(payload: Any) -> tuple[str, int | None]:
    if not isinstance(payload, dict):
        raise DevnetManualWorkflowError("invalid_latest_blockhash_response")
    value = payload.get("value")
    if not isinstance(value, dict) or not isinstance(value.get("blockhash"), str):
        raise DevnetManualWorkflowError("invalid_latest_blockhash_response")
    context = payload.get("context")
    return value["blockhash"], _as_int(context.get("slot")) if isinstance(
        context, dict
    ) else None


def _simulation_outcome(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise DevnetManualWorkflowError("invalid_simulation_response")
    value = payload.get("value")
    if not isinstance(value, dict):
        raise DevnetManualWorkflowError("invalid_simulation_response")
    context = payload.get("context")
    logs = value.get("logs")
    safe_logs = [str(item) for item in logs] if isinstance(logs, list) else []
    error = value.get("err")
    return {
        "success": error is None,
        "error": error,
        "logs": safe_logs,
        "units_consumed": _as_int(value.get("unitsConsumed")),
        "context_slot": _as_int(context.get("slot")) if isinstance(context, dict) else None,
        "raw": {"context": context if isinstance(context, dict) else {}, "value": value},
    }


def _signature_status(payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    value = payload.get("value")
    if not isinstance(value, list) or not value:
        return None
    return value[0] if isinstance(value[0], dict) else None


def _balance_lamports(payload: Any) -> int:
    if not isinstance(payload, dict):
        raise DevnetManualWorkflowError("invalid_balance_response")
    value = payload.get("value")
    if not isinstance(value, int) or value < 0:
        raise DevnetManualWorkflowError("invalid_balance_response")
    return value


def _as_int(value: Any) -> int | None:
    return value if isinstance(value, int) else None


def _safe_error(exc: Exception) -> str:
    """A bounded domain code, never a provider response or secret-bearing URL."""
    return type(exc).__name__[:80]
