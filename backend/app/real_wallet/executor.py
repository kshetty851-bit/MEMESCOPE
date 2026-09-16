"""The production execution runner: the one place the real collaborators meet.

Every piece of the real rail was built and correct — the safety gate, the order
factory, the isolated signer, the twenty-two-condition guard, the transport, the
reconciler — and nothing composed them. The only object that walked an intent
from CREATED to CONFIRMED was `TestOnlyRealWalletLifecycle`, which refuses
outright unless `ENVIRONMENT == "test"`. So the driver could create an intent and
that intent would sit at CREATED for ever.

This is that runner, and it is deliberately thin. It owns no rule of its own: it
asks the safety gate whether the mint is tradeable, asks the factory to build the
order, asks the SIGNER to sign — by id, so the signer reloads and re-verifies
rather than trusting anything assembled here — asks the guard whether every
condition holds, and only then hands the bytes to the transport, which asks the
transport policy again before it will construct a request.

## What it cannot do

It cannot authorise. `LiveSubmissionGuard` and `ExecutionTransportPolicy` are the
authorities, and both still refuse on mainnet: the transport policy asserts
`MAINNET_EXECUTION_DISABLED` regardless of mode and enable flags, and
`LIVE_TRANSPORT_RELEASE_APPROVED` is a module constant that has to be changed in
a reviewed diff. Running this to completion today ends in a recorded refusal, not
a transaction, which is exactly what makes it safe to build and to run before
those constants are ever touched.

## The signed transaction never rests

The signer returns bytes that are bearer-grade: whoever holds them can broadcast
them. They are held in a local for the length of one call and handed straight to
the transport. Nothing here persists or logs them — the SIGNED row records a
fingerprint and a signature, never the transaction.

## A sell is not a buy

The autotrade switch, SEC-2 and the entry limits decide what gets BOUGHT. None
of them can make an open position safer to hold, so a SELL passes all three:
switched OFF, the wallet stops buying and still sells what it holds, on time,
into whatever pool is left. The kill switch still freezes everything, and the
order still carries its own bounds — a fresh quote, the slippage cap, the exit
impact cap and the re-check of what Jupiter built.

## One step per call

`advance` performs at most one state transition and returns the state it reached.
A caller that wants an intent driven to completion calls it repeatedly. That is
what makes a crash mid-flight recoverable: every state is a committed row, and
the transition out of SUBMITTED is the reconciler's to make from chain evidence
rather than from anything this process remembers.
"""

from __future__ import annotations

import uuid
from base64 import b64decode
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from solders.transaction import VersionedTransaction
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from sqlalchemy import select

from app.models.real_wallet_execution import RealWalletLiveIntent
from app.models.real_wallet_safety import RealWalletSafetyEvaluation
from app.real_wallet.autotrade import AutotradeSwitchService
from app.real_wallet.balance import ExecutionWalletBalanceService
from app.real_wallet.live_readiness import (
    ExecutionState,
    LiveSubmissionGuard,
    SubmissionFacts,
)
from app.real_wallet import sol_price
from app.real_wallet.live_repository import (
    LiveIntentRepository,
    SettlementEvidenceError,
)
from app.real_wallet.live_transport import (
    JupiterExecuteOutcome,
    JupiterExecuteTransportError,
    JupiterLiveExecutionTransport,
    LiveTransportBlockedError,
)
from app.real_wallet.mainnet_signer_client import (
    MainnetSignerRejectedError,
    MainnetSignerUnavailableError,
    UnixMainnetSignerClient,
)
from app.real_wallet.order_evidence import OrderEvidenceRejectedError
from app.real_wallet.network import require_verified_network
from app.real_wallet.policy import AutonomousExecutionPolicy, PolicyState
from app.real_wallet.production_order import (
    JupiterV2OrderUnavailableError,
    ProductionOrderFactory,
)
from app.real_wallet.reconciliation import (
    ChainOutcome,
    SolanaRpcTransactionReconciler,
)
from app.real_wallet.transport_policy import LIVE_TRANSPORT_RELEASE_APPROVED
from app.real_wallet.tx_inspect import lamports_from_sol
from app.real_wallet import market_refresh
from app.real_wallet_safety.service import RealWalletSafetyGate
from app.services.rpc.standard import StandardSolanaRPC

logger = get_logger(__name__)

#: How old an order may be when it is signed. Jupiter's transaction carries a
#: recent blockhash that dies in about ninety seconds, so an order older than
#: this is not merely stale — it cannot land.
MAX_ORDER_AGE_SECONDS = 45

#: How old the safety verdict may be when the order is built. SEC-2 reads a
#: market snapshot, and a verdict from five minutes ago describes a market that
#: no longer exists.
MAX_SAFETY_AGE_SECONDS = 120

#: How long a sent transaction may stay unseen before it is asked whether it
#: can still land. Its blockhash dies in about ninety seconds; this waits
#: well past that so a slow node reads as slow, not as dropped.
DROPPED_AFTER_SECONDS = 300


@dataclass(frozen=True, slots=True)
class AdvanceOutcome:
    state: str
    intent_id: str
    changed: bool
    reason: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {"state": self.state, "intent_id": self.intent_id,
                "changed": self.changed, "reason": self.reason}


class RealWalletExecutor:
    """Walk one intent forward by exactly one state, using real collaborators."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        order_factory: ProductionOrderFactory | None = None,
        signer: UnixMainnetSignerClient | None = None,
        transport: JupiterLiveExecutionTransport | None = None,
    ) -> None:
        self._session = session
        self._repository = LiveIntentRepository(session)
        self._orders = order_factory or ProductionOrderFactory()
        self._signer = signer or UnixMainnetSignerClient()
        self._transport = transport or JupiterLiveExecutionTransport()

    async def advance(
        self, intent_id: uuid.UUID, *, now: datetime | None = None
    ) -> AdvanceOutcome:
        now = now or datetime.now(UTC)
        intent = await self._repository.by_id(intent_id)
        if intent is None:
            return AdvanceOutcome("unknown", str(intent_id), False, "intent_not_found")

        # STOP is re-read at every step, not once at the start of the flight.
        # An operator who presses it while a BUY is in motion stops that buy,
        # which is the only thing that makes the control worth having. A SELL
        # carries on: OFF means "no more", and a sell is how "no more" ends.
        switch = await AutotradeSwitchService(self._session).state()
        if (not switch.enabled and intent.state != ExecutionState.SUBMITTED
                and not _is_sell(intent)):
            return await self._block(intent, now, "autotrade_switch_off")

        if await self._repository.active_kill_switches():
            if intent.state == ExecutionState.SUBMITTED:
                # Already in flight. The chain does not care about our switches,
                # so this must be reconciled, never abandoned.
                return await self._reconcile(intent, now)
            return await self._block(intent, now, "kill_switch_active")

        handler = {
            ExecutionState.CREATED: self._run_safety,
            ExecutionState.SAFETY_APPROVED: self._build_order,
            ExecutionState.ORDER_CREATED: self._sign_and_submit,
            ExecutionState.SUBMITTED: self._reconcile,
        }.get(ExecutionState(intent.state))
        if handler is None:
            return AdvanceOutcome(intent.state, str(intent.id), False, "terminal_state")
        return await handler(intent, now)

    # --- CREATED -> SAFETY_APPROVED -----------------------------------------

    async def _run_safety(
        self, intent: RealWalletLiveIntent, now: datetime
    ) -> AdvanceOutcome:
        """SEC-2's verdict, from the same evaluator Paper uses."""
        if _is_sell(intent):
            # SEC-2 asks whether a token is safe to buy. Refusing the sell
            # because the pool collapsed is how a collapse becomes a total loss.
            await self._repository.transition(
                intent=intent, next_state=ExecutionState.SAFETY_APPROVED, at=now,
                detail={"safety": "not_applied_to_a_sell"},
            )
            return AdvanceOutcome(ExecutionState.SAFETY_APPROVED, str(intent.id), True)
        # The gate judges the newest reading there is; make sure there is one.
        # Graduations are bought before enrichment reaches them on its own.
        reading = await market_refresh.ensure_fresh(
            self._session, intent.mint_address, now=now)
        if reading.status != "fresh":
            logger.info("real_wallet_market_refreshed", intent_id=str(intent.id),
                        mint=intent.mint_address, result=reading.status)
        if reading.captured_at is not None and reading.captured_at > now:
            # Judged from the moment the reading exists. From `now` it would
            # sit in the future, and the gate refuses that as stale.
            now = reading.captured_at
        decision = await RealWalletSafetyGate(self._session).evaluate(
            mint_address=intent.mint_address,
            trade_size_usd=Decimal(str(intent.requested_usd)),
            now=now,
        )
        # "ALLOW", not "ALLOWED". This compared against a verdict the gate never
        # returns, so EVERY intent was blocked — and with an empty reason string,
        # because an allowed decision carries no reason codes. It read as
        # "safety:" and named nothing. Found by walking a real intent in ARMED,
        # which is the only reason it was not found with money on the line.
        if decision.decision.upper() != "ALLOW":
            return await self._block(
                intent, now,
                "safety:" + (",".join(decision.reason_codes[:3]) or "unspecified"),
            )
        await self._repository.transition(
            intent=intent,
            next_state=ExecutionState.SAFETY_APPROVED,
            at=now,
            detail={"policy_version": decision.policy_version,
                    "evaluation_id": str(decision.evaluation_id or "")},
            # The verdict's own timestamp lives on the evaluation row, which is
            # the audit record; the intent points at it rather than copying it.
            safety_evaluation_id=decision.evaluation_id,
        )
        return AdvanceOutcome(ExecutionState.SAFETY_APPROVED, str(intent.id), True)

    # --- SAFETY_APPROVED -> ORDER_CREATED -----------------------------------

    async def _build_order(
        self, intent: RealWalletLiveIntent, now: datetime
    ) -> AdvanceOutcome:
        """Real Jupiter order. Read-only: it builds an UNSIGNED transaction."""
        if not _is_sell(intent) and not self._fresh(
                await self._safety_at(intent), now, MAX_SAFETY_AGE_SECONDS):
            # Back to the gate rather than forward on a stale verdict. Blocking
            # is the honest outcome: the intent's own decision has expired.
            return await self._block(intent, now, "safety_verdict_stale")
        try:
            prepared = await self._orders.prepare(intent)
        except JupiterV2OrderUnavailableError as exc:
            return await self._block(intent, now, f"order_unavailable:{exc}")
        except OrderEvidenceRejectedError as exc:
            # The order came back and FAILED its re-check — a different thing
            # from the order being unavailable, and it escaped uncaught. The
            # intent stayed at SAFETY_APPROVED and was retried every minute
            # against a market that had already refused it, for ever.
            return await self._block(intent, now, f"order_rejected:{exc}")
        await self._repository.transition(
            intent=intent,
            next_state=ExecutionState.ORDER_CREATED,
            at=now,
            detail={"request_id": prepared.request_id},
            jupiter_request_id=prepared.request_id,
            order_evidence=prepared.evidence,
        )
        return AdvanceOutcome(ExecutionState.ORDER_CREATED, str(intent.id), True)

    # --- ORDER_CREATED -> SUBMITTED -----------------------------------------

    async def _sign_and_submit(
        self, intent: RealWalletLiveIntent, now: datetime
    ) -> AdvanceOutcome:
        """Sign, ask the guard, submit. One call, because the bytes must not rest.

        The signature comes back from a process this one cannot read the key of,
        over a socket, in exchange for an id. The signer reloads the intent and
        re-verifies it, so nothing assembled here decides what gets signed.
        """
        if not self._fresh(intent.order_created_at, now, MAX_ORDER_AGE_SECONDS):
            # The blockhash is dead; submitting would waste a fee to be told so.
            return await self._block(intent, now, "order_expired")

        facts = await self._facts(intent, now)
        guard = LiveSubmissionGuard().evaluate(facts)
        if not guard.allowed:
            # The expected outcome today, and the whole point: a complete,
            # honest walk that ends in a recorded refusal rather than a spend.
            return await self._block(intent, now, "guard:" + ",".join(guard.reasons[:3]))

        try:
            signed = await self._signer.sign(intent.id)
        except MainnetSignerUnavailableError as exc:
            return await self._block(intent, now, f"signer_unavailable:{exc}")
        except MainnetSignerRejectedError as exc:
            return await self._block(intent, now, f"signer_refused:{exc}")

        await self._repository.transition(
            intent=intent,
            next_state=ExecutionState.SIGNED,
            at=now,
            # Fingerprint only. The transaction itself is bearer material and
            # never touches a row or a log line.
            detail={"message_fingerprint": signed["message_fingerprint"]},
        )
        # Its own method because it owns the replay guard: a unique partial
        # index means the same signature cannot attach to a second intent. It
        # is stored BEFORE the network call, which is what makes a lost
        # `/execute` response recoverable instead of permanently unknown.
        await self._repository.record_signature_before_submission(
            intent=intent, signature=signed["signature"], at=now
        )

        # The crash boundary. Committed BEFORE the request goes out, so a
        # process death after this is an uncertain submission to reconcile and
        # never a retry — a retried swap is a second swap.
        await self._repository.transition(
            intent=intent,
            next_state=ExecutionState.SUBMITTED,
            at=now,
            detail={"request_id": intent.jupiter_request_id},
        )
        await self._session.commit()

        try:
            result = await self._transport.execute_signed_order(
                signed_transaction=signed["signed_transaction"],
                request_id=intent.jupiter_request_id or "",
                guard=guard,
            )
        except (LiveTransportBlockedError, JupiterExecuteTransportError) as exc:
            # In flight as far as this process knows: the request may or may not
            # have reached the network. Only the chain can say, and the
            # signature stored above is what lets it be asked.
            await self._repository.record_execution_failure(reason=str(exc)[:64], at=now)
            logger.warning("real_wallet_submission_uncertain",
                           intent_id=str(intent.id), error=str(exc))
            return AdvanceOutcome(ExecutionState.SUBMITTED, str(intent.id), True,
                                  f"submission_uncertain:{exc}")

        # A reply, not a settlement. `record_submission_result` keeps the
        # signature already stored and never overwrites it with the None an
        # unknown outcome carries — erasing it would turn the exact failure this
        # system exists to survive into an unresolvable intent. What the chain
        # actually did is the reconciler's to establish on the next call.
        await self._repository.record_submission_result(
            intent=intent, signature=result.signature, outcome=str(result.outcome)
        )
        if result.outcome is JupiterExecuteOutcome.SUCCESS:
            await self._repository.record_execution_success(at=now)
        else:
            await self._repository.record_execution_failure(
                reason=f"execute:{result.outcome}", at=now
            )
        logger.warning("real_wallet_submitted", intent_id=str(intent.id),
                       outcome=str(result.outcome))
        return AdvanceOutcome(ExecutionState.SUBMITTED, str(intent.id), True,
                              str(result.outcome))

    # --- SUBMITTED -> CONFIRMED / FAILED ------------------------------------

    async def _reconcile(
        self, intent: RealWalletLiveIntent, now: datetime
    ) -> AdvanceOutcome:
        """Ask the chain, never this process's memory of what it sent."""
        rpc = StandardSolanaRPC(rpc_url=settings.REAL_WALLET_RPC_URL)
        async with rpc:
            receipt = await SolanaRpcTransactionReconciler(rpc).inspect(intent)
        if receipt.outcome is ChainOutcome.UNKNOWN:
            if await self._never_landing(intent, now):
                # Nothing happened on chain and nothing can, so the exit that
                # was waiting on it may be asked for again.
                await self._repository.transition(
                    intent=intent, next_state=ExecutionState.FAILED, at=now,
                    detail={"chain": "expired_unlanded"},
                    failure_reason="expired_unlanded",
                )
                return AdvanceOutcome(ExecutionState.FAILED, str(intent.id), True,
                                      "expired_unlanded")
            return AdvanceOutcome(intent.state, str(intent.id), False, "chain_unknown")
        if receipt.outcome is ChainOutcome.FAILED:
            await self._repository.transition(
                intent=intent, next_state=ExecutionState.FAILED, at=now,
                detail={"chain": "failed"}, failure_reason="chain_reported_failure",
            )
            return AdvanceOutcome(ExecutionState.FAILED, str(intent.id), True)
        if not receipt.has_settlement_evidence:
            # Landed, but without the exact wallet deltas. A position recorded
            # from an assumed fill is a position that is wrong by an unknown
            # amount, so this waits for evidence instead.
            await self._repository.transition(
                intent=intent, next_state=ExecutionState.RECONCILIATION_REQUIRED,
                at=now, detail={"chain": "confirmed_without_deltas"},
            )
            return AdvanceOutcome(ExecutionState.RECONCILIATION_REQUIRED,
                                  str(intent.id), True)
        # One atomic call: the confirmed intent and the position it opens are
        # the same fact, and writing them separately would allow a settled
        # transaction with no position behind it. Priced when a fresh SOL
        # reading exists — without one, gross is still recorded and net is not.
        try:
            await self._repository.confirm_settlement(
                intent=intent,
                signature=receipt.signature or intent.transaction_signature or "",
                actual_input_amount_raw=int(receipt.actual_input_amount or 0),
                actual_input_decimals=int(receipt.actual_input_decimals or 0),
                actual_output_amount_raw=int(receipt.actual_output_amount or 0),
                actual_output_decimals=int(receipt.actual_output_decimals or 0),
                network_fee_lamports=receipt.network_fee_lamports,
                at=now,
                sol_price=await sol_price.current(now),
            )
        except SettlementEvidenceError as exc:
            # Landed, and the chain disagrees with what was authorised. That
            # is a person's to read, not a loop's to retry every few seconds.
            logger.error("real_wallet_settlement_disputed",
                         intent_id=str(intent.id), reason=str(exc))
            await self._repository.transition(
                intent=intent, next_state=ExecutionState.RECONCILIATION_REQUIRED,
                at=now, detail={"chain": "confirmed", "unsettled": str(exc)},
            )
            return AdvanceOutcome(ExecutionState.RECONCILIATION_REQUIRED,
                                  str(intent.id), True, str(exc))
        return AdvanceOutcome(ExecutionState.CONFIRMED, str(intent.id), True)

    async def _never_landing(self, intent: RealWalletLiveIntent, now: datetime) -> bool:
        """True only when this transaction provably cannot land any more.

        Both must hold, and only once it has been gone a while: its blockhash
        has expired on the confirmed chain, and no node has any record of the
        signature. The signer makes the wallet the only signer and fee payer,
        so that signature IS the transaction id. Anything unreadable is False,
        which leaves the intent waiting rather than risking a second sell.
        """
        encoded = (intent.order_evidence or {}).get("unsigned_transaction")
        signature = intent.transaction_signature
        sent = intent.submitted_at
        if not encoded or not signature or sent is None:
            return False
        if sent.tzinfo is None:
            sent = sent.replace(tzinfo=UTC)
        if (now - sent).total_seconds() < DROPPED_AFTER_SECONDS:
            return False
        try:
            blockhash = str(VersionedTransaction.from_bytes(
                b64decode(encoded)).message.recent_blockhash)
            rpc = StandardSolanaRPC(rpc_url=settings.REAL_WALLET_RPC_URL)
            async with rpc:
                valid = await rpc.call(
                    "isBlockhashValid", [blockhash, {"commitment": "confirmed"}])
                status = await rpc.call(
                    "getSignatureStatuses",
                    [[signature], {"searchTransactionHistory": True}])
        except Exception as exc:  # unreadable is not dropped
            logger.warning("executor_drop_check_unreadable", error=str(exc)[:120])
            return False
        return (isinstance(valid, dict) and valid.get("value") is False
                and isinstance(status, dict) and status.get("value") == [None])

    # --- shared --------------------------------------------------------------

    async def _facts(
        self, intent: RealWalletLiveIntent, now: datetime
    ) -> SubmissionFacts:
        """Measure every condition for THIS attempt. Unmeasurable stays refusing."""
        identity: dict = {}
        try:
            identity = await self._signer.identity()
        except (MainnetSignerUnavailableError, MainnetSignerRejectedError):
            identity = {}

        network_verified = False
        balance_lamports: int | None = None
        try:
            rpc = StandardSolanaRPC(rpc_url=settings.REAL_WALLET_RPC_URL)
            async with rpc:
                status = await require_verified_network(
                    rpc,
                    configured_network=settings.REAL_WALLET_NETWORK,
                    rpc_url=settings.REAL_WALLET_RPC_URL,
                    allowed_rpc_hosts=settings.REAL_WALLET_ALLOWED_RPC_HOSTS,
                )
                network_verified = bool(status.verified)
                sol = (await ExecutionWalletBalanceService(rpc).get_sol_balance(
                    intent.wallet_public_key
                )).sol
                balance_lamports = lamports_from_sol(Decimal(str(sol)))
        except Exception as exc:  # noqa: BLE001 - unreadable chain refuses
            logger.warning("executor_chain_unreadable", error=str(exc))

        sell = _is_sell(intent)
        # The entry limits bound what is BOUGHT. A sell has no dollar size to
        # judge and only ever shrinks the book, so it is not asked.
        limits_ok = sell or await self._entry_limits_ok(intent, now, balance_lamports)
        switch = await AutotradeSwitchService(self._session).state()
        safety_at = await self._safety_at(intent)
        evidence = intent.order_evidence or {}
        return SubmissionFacts(
            signer_ready=bool(identity.get("can_sign")),
            signer_matches_pinned_key=bool(identity.get("matches_pinned_key")),
            safety_passed=sell or intent.safety_evaluation_id is not None,
            safety_fresh=sell or self._fresh(safety_at, now, MAX_SAFETY_AGE_SECONDS),
            policy_passed=limits_ok,
            valid_intent=bool(intent.input_mint and intent.output_mint
                              and intent.jupiter_request_id),
            not_previously_submitted=intent.submitted_at is None,
            order_fresh=self._fresh(
                intent.order_created_at, now, MAX_ORDER_AGE_SECONDS
            ),
            market_fresh=sell or self._fresh(safety_at, now, MAX_SAFETY_AGE_SECONDS),
            kill_switch_active=bool(await self._repository.active_kill_switches()),
            daily_loss_within_limit=limits_ok,
            open_position_within_limit=limits_ok,
            trade_size_within_limit=limits_ok,
            mainnet_verified=network_verified,
            # The order factory verified the assembled programs and fingerprint
            # when it built this; the signer verifies them again before signing.
            transaction_approved=bool(evidence.get("intent_fingerprint")),
            not_previously_signed=intent.transaction_signature is None,
            canary_limits_satisfied=limits_ok,
            transport_release_approved=LIVE_TRANSPORT_RELEASE_APPROVED,
            autotrade_switch_on=switch.enabled or sell,
        )

    async def _entry_limits_ok(
        self, intent: RealWalletLiveIntent, now: datetime,
        balance_lamports: int | None,
    ) -> bool:
        """Every bound a BUY must satisfy at the moment it is sent."""
        open_positions = await self._repository.open_positions_count()
        entry_usd = Decimal(str(intent.requested_usd))
        # Equity, recomputed here rather than trusted from the row, because the
        # ladder scales the caps this re-check enforces. Without it the
        # executor would judge a grown account against BASE bounds and refuse
        # the size the driver had just correctly authorised.
        #
        # A missing price leaves it None, which holds the caps at base — the
        # safe direction, and it refuses rather than silently widening.
        price = await sol_price.current_usd(now)
        equity_usd = (
            (Decimal(balance_lamports) / Decimal(1_000_000_000) * price
             + await self._repository.open_exposure_usd())
            if price is not None and balance_lamports is not None else None
        )
        # The spend as the ROW records it, not as anything recomputed here: the
        # floor has to judge the amount that will actually be signed. `None`
        # stays `None` rather than becoming 0 — a missing spend is unmeasured
        # and must refuse, whereas 0 would sail through a subtraction.
        raw_spend = intent.actual_input_amount_raw
        canary = AutonomousExecutionPolicy().evaluate_canary_entry(
            requested_usd=entry_usd,
            state=PolicyState(
                open_positions=open_positions,
                exposure_usd=Decimal(open_positions) * entry_usd,
                daily_notional_usd=Decimal(0),
                # Measured again here, not trusted from the driver: a sell can
                # settle in the seconds between the two.
                daily_realised_loss_usd=await self._repository.realised_loss_today(now),
                daily_trades=0,
                wallet_balance_lamports=balance_lamports,
                equity_usd=equity_usd,
                side=str(intent.side or "BUY"),
                spend_lamports=None if raw_spend is None else int(raw_spend),
            ),
        )
        return canary.allowed

    async def _safety_at(self, intent: RealWalletLiveIntent) -> datetime | None:
        """When SEC-2 actually looked. Read from the evaluation row, because
        that row is the audit record and the intent only points at it."""
        if intent.safety_evaluation_id is None:
            return None
        return await self._session.scalar(
            select(RealWalletSafetyEvaluation.evaluated_at).where(
                RealWalletSafetyEvaluation.id == intent.safety_evaluation_id
            )
        )

    @staticmethod
    def _fresh(at: datetime | None, now: datetime, max_age_seconds: int) -> bool:
        """Unmeasured is not fresh. A missing timestamp refuses."""
        if at is None:
            return False
        if at.tzinfo is None:
            at = at.replace(tzinfo=UTC)
        return 0 <= (now - at).total_seconds() <= max_age_seconds

    async def _block(
        self, intent: RealWalletLiveIntent, now: datetime, reason: str
    ) -> AdvanceOutcome:
        await self._repository.transition(
            intent=intent, next_state=ExecutionState.BLOCKED, at=now,
            detail={"reason": reason}, failure_reason=reason[:64],
        )
        logger.warning("real_wallet_intent_blocked",
                       intent_id=str(intent.id), reason=reason)
        return AdvanceOutcome(ExecutionState.BLOCKED, str(intent.id), True, reason)


def _is_sell(intent: RealWalletLiveIntent) -> bool:
    """Exactly "SELL". Anything else is treated as a buy and gets every check."""
    return intent.side == "SELL"


__all__ = ["AdvanceOutcome", "RealWalletExecutor"]
