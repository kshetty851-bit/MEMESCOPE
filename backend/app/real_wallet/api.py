"""Admin-only, read-only dedicated execution-wallet status."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import AdminUser, DbSession
from app.core.config import settings
from app.core.exceptions import ConflictError, NotFoundError, ServiceUnavailableError
from app.models.real_wallet_execution import RealWalletDevnetIntent, RealWalletDevnetQuote
from app.real_wallet.balance import ExecutionWalletBalanceService
from app.real_wallet.devnet_intent import DevnetIntentState, DevnetIntentTransitionError
from app.real_wallet.devnet_repository import DevnetIntentExpiredError, DevnetIntentRepository
from app.real_wallet.devnet_signer_client import (
    DevnetSignerRejectedError,
    DevnetSignerUnavailableError,
    UnixDevnetSignerClient,
)
from app.real_wallet.devnet_workflow import (
    DevnetApprovalRequiredError,
    DevnetManualWorkflow,
    DevnetManualWorkflowError,
)
from app.real_wallet.live_repository import LiveIntentRepository
from app.real_wallet.network import (
    DevnetExecutionBlockedError,
    is_valid_wallet_address,
    verify_wallet_network,
)
from app.real_wallet.funding_readiness import as_dict as readiness_as_dict
from app.real_wallet.funding_readiness import evaluate as evaluate_funding_readiness
from app.real_wallet.autotrade import AutotradeSwitchService, UnknownStrategyError
from app.real_wallet.rehearsal import as_dict as rehearsal_as_dict
from app.real_wallet.rehearsal import rehearse
from app.real_wallet.policy import configured_entry_size_usd
from app.real_wallet.repository import RealWalletExecutionRepository
from app.real_wallet.sol_price import JupiterSolUsdPriceSource, SolUsdPrice
from app.real_wallet.transport_policy import readiness as transport_readiness
from app.real_wallet.tx_inspect import DEFAULT_ALLOWED_PROGRAMS, lamports_from_sol
from app.repositories.token import TokenRepository
from app.security import entry_policy
from app.services.rpc.standard import StandardSolanaRPC

router = APIRouter(prefix="/real-wallet", tags=["real-wallet"])


def _allowed_programs() -> frozenset[str]:
    """The effective program allowlist: the reviewed defaults plus configuration."""
    extra = {
        program.strip()
        for program in settings.REAL_WALLET_ALLOWED_PROGRAM_IDS
        if program.strip()
    }
    return DEFAULT_ALLOWED_PROGRAMS | extra


class NativeTransferQuoteIn(BaseModel):
    destination_public_key: str = Field(min_length=32, max_length=44)
    lamports: int = Field(gt=0)


class DevnetIntentIn(BaseModel):
    quote_id: uuid.UUID
    idempotency_key: str = Field(min_length=8, max_length=160)


class ManualApprovalIn(BaseModel):
    confirmation_phrase: Literal["APPROVE_DEVNET_TRANSFER"]


class KillSwitchClearIn(BaseModel):
    """Clearing a kill switch is an authorised, attributed, explained act.

    The confirmation phrase is not ceremony. This is the one control in the
    product that removes a safety barrier, and a bare POST is something a
    mis-scoped script or a stray click can perform. A required literal cannot
    be sent by accident, and `reason` is what the audit row is for — a cleared
    switch with no stated reason is a cleared switch nobody can review.
    """

    confirmation_phrase: Literal["CLEAR_REAL_WALLET_KILL_SWITCH"]
    reason: str = Field(min_length=8, max_length=256)


class DevnetIntentSummary(BaseModel):
    id: uuid.UUID
    state: str
    action_type: str
    wallet_public_key: str
    destination_public_key: str | None
    input_mint: str
    output_mint: str | None
    input_amount_raw: str
    quote_id: uuid.UUID | None
    quote_expires_at: datetime | None
    simulation_status: str | None
    approval_status: str | None
    approval_expires_at: datetime | None
    signing_status: str | None
    transaction_signature: str | None
    submission_status: str | None
    submission_retry_count: int
    confirmation_status: str | None
    confirmation_slot: int | None
    failure_reason: str | None
    reconciliation: dict[str, object] | None
    created_at: datetime
    updated_at: datetime


def _decimal(value: Decimal) -> str:
    return format(value, "f")


def _fee_accounting_readiness(
    price: SolUsdPrice | None, *, now: datetime
) -> dict[str, object]:
    """Whether a settled trade could be given an honest net figure right now.

    `fee_accounting_ready` is about capability, not about any one trade: a fresh
    SOL/USD reading means a fee paid in SOL can be stated in the USD every limit
    here is written in. Without it a settlement keeps its measured gross figure
    and claims no net figure at all.
    """
    fresh = price is not None and price.is_fresh(
        now, max_age_seconds=settings.EXECUTION_SOL_PRICE_MAX_AGE_SECONDS
    )
    return {
        "sol_price_provider": settings.EXECUTION_SOL_PRICE_PROVIDER,
        "sol_price_source": None if price is None else price.source,
        "sol_price_usd": None if price is None else _decimal(price.usd),
        "sol_price_observed_at": None if price is None else price.observed_at,
        "sol_price_age_seconds": (None if price is None else _decimal(price.age_seconds(now))),
        "sol_price_fresh": fresh,
        "max_age_seconds": settings.EXECUTION_SOL_PRICE_MAX_AGE_SECONDS,
        "min_sol_fee_reserve": _decimal(settings.REAL_WALLET_MIN_SOL_FEE_RESERVE),
        "priority_fee_sol": _decimal(settings.EXECUTION_PRIORITY_FEE_SOL),
        "exit_fee_reserve_multiplier": settings.EXECUTION_EXIT_FEE_RESERVE_MULTIPLIER,
        "fee_accounting_ready": fresh,
        "unavailable_reason": (
            None if fresh else "No fresh SOL/USD reading; net figures would be gross."
        ),
    }


class AutotradeStartIn(BaseModel):
    """Starting requires naming a strategy and a reason. Both are recorded."""

    strategy_id: str = Field(min_length=2, max_length=16)
    reason: str = Field(min_length=3, max_length=256)


class AutotradeStopIn(BaseModel):
    reason: str = Field(min_length=3, max_length=256)


@router.get("/autotrade", summary="Read the operator start/stop control")
async def read_autotrade(_admin: AdminUser, session: DbSession) -> dict[str, object]:
    service = AutotradeSwitchService(session)
    state = await service.state()
    return {
        **state.as_dict(),
        "history": [
            {"action": e.action, "actor": e.actor, "reason": e.reason,
             "nominated_strategy": e.nominated_strategy,
             "occurred_at": e.occurred_at.isoformat()}
            for e in await service.history(limit=20)
        ],
    }


@router.post("/autotrade/start", summary="Record the intent to trade autonomously")
async def start_autotrade(
    payload: AutotradeStartIn, admin: AdminUser, session: DbSession
) -> dict[str, object]:
    """**This authorises nothing.**

    Every barrier is evaluated independently and is untouched here: mode, the
    three enable flags, the release constant, the mainnet clause, the submission
    guard, SEC-2 freshness, network verification and the canary limits. Starting
    records that an operator intends to trade and names which strategy; on
    today's deployment submission remains exactly as impossible as before.
    """
    service = AutotradeSwitchService(session)
    try:
        state = await service.start(
            actor=admin.email, reason=payload.reason,
            strategy_id=payload.strategy_id, at=datetime.now(UTC),
        )
    except UnknownStrategyError as exc:
        raise HTTPException(
            status_code=422, detail=f"unknown strategy: {exc}"
        ) from exc
    await session.commit()
    return state.as_dict()


@router.post("/autotrade/stop", summary="Stop autonomous trading, unconditionally")
async def stop_autotrade(
    payload: AutotradeStopIn, admin: AdminUser, session: DbSession
) -> dict[str, object]:
    """Stop. This can never be refused and needs no other condition to be true.

    A control an operator cannot trust to stop is a control they will be afraid
    to start, so this path has no barrier of its own and takes effect on the
    next guard evaluation.
    """
    service = AutotradeSwitchService(session)
    state = await service.stop(
        actor=admin.email, reason=payload.reason, at=datetime.now(UTC)
    )
    await session.commit()
    return state.as_dict()


@router.get(
    "/rehearsal",
    summary="ARMED rehearsal — evaluate every pre-submission condition",
)
async def rehearsal(_admin: AdminUser, session: DbSession) -> dict[str, object]:
    """Prove the chain with no transaction existing. It cannot submit or sign."""
    report = await rehearse(session, now=datetime.now(UTC))
    return rehearsal_as_dict(report)


@router.get(
    "/funding-readiness",
    summary="What stands between here and a funded canary",
)
async def funding_readiness(_admin: AdminUser, session: DbSession) -> dict[str, object]:
    """A read-only checklist. It can never enable anything.

    Measures what it can (balance, genesis, kill switch) and reports the rest as
    UNKNOWN rather than as satisfied — an unmeasured precondition has not been
    met, it has merely not been looked at.
    """
    public_key = settings.REAL_WALLET_PUBLIC_KEY.strip()
    balance_sol: Decimal | None = None
    network_verified: bool | None = None
    if public_key and is_valid_wallet_address(public_key):
        rpc = StandardSolanaRPC(rpc_url=settings.REAL_WALLET_RPC_URL)
        try:
            async with rpc:
                network = await verify_wallet_network(
                    rpc, network=settings.REAL_WALLET_NETWORK
                )
                network_verified = network.verified
                if network.verified:
                    balances = ExecutionWalletBalanceService(rpc)
                    balance_sol = Decimal(
                        str((await balances.get_sol_balance(public_key)).sol)
                    )
        except Exception:  # pragma: no cover - an unreadable chain is UNKNOWN
            network_verified = None

    kill_switch_active: bool | None = None
    try:
        kill_switch_active = bool(
            await LiveIntentRepository(session).active_kill_switches()
        )
    except Exception:  # pragma: no cover - unreadable state stays UNKNOWN
        kill_switch_active = None

    readiness = evaluate_funding_readiness(
        wallet_balance_sol=balance_sol,
        network_verified=network_verified,
        kill_switch_active=kill_switch_active,
        # Nothing has been promoted. When the V6 review promotes something this
        # becomes its id, and it is deliberately not derivable from config.
        validated_strategy=None,
    )
    return readiness_as_dict(readiness)


@router.get("/status", summary="Read dedicated execution-wallet status")
async def status(_admin: AdminUser, session: DbSession) -> dict[str, object]:
    """Return public and readiness metadata only; never signer material."""
    now = datetime.now(UTC)
    transport = transport_readiness()
    # Read-only price probe. It cannot trigger an order, a signature or a
    # submission; it exists so the dashboard can distinguish "fee accounting
    # would work" from "a net figure would silently be gross".
    try:
        sol_price = await JupiterSolUsdPriceSource().current(now=now)
    except Exception:  # pragma: no cover - the source already fails closed
        sol_price = None
    public_key = settings.REAL_WALLET_PUBLIC_KEY.strip()
    address_valid = bool(public_key) and is_valid_wallet_address(public_key)
    balance_sol: float | None = None
    token_balances: list[dict[str, object]] = []
    balance_error: str | None = None
    rpc_status: dict[str, object] = {
        "network": settings.REAL_WALLET_NETWORK,
        "verified": False,
        "observed_genesis_hash": None,
        "error": "wallet_not_configured" if not public_key else "invalid_address",
    }
    if address_valid:
        # Never inherit the scanner RPC. The wallet reader verifies this exact
        # endpoint's genesis hash before it displays chain state.
        rpc = StandardSolanaRPC(rpc_url=settings.REAL_WALLET_RPC_URL)
        try:
            async with rpc:
                network = await verify_wallet_network(
                    rpc, network=settings.REAL_WALLET_NETWORK
                )
                rpc_status = {
                    "network": network.network,
                    "verified": network.verified,
                    "observed_genesis_hash": network.observed_genesis_hash,
                    "error": network.error,
                }
                if not network.verified:
                    balance_error = "network_unverified"
                else:
                    balances = ExecutionWalletBalanceService(rpc)
                    sol_balance = await balances.get_sol_balance(public_key)
                    balance_sol = sol_balance.sol
                    spl_balances = await balances.get_spl_balances(public_key)
                    known_tokens = await TokenRepository(session).get_many_by_mints(
                        [row.mint_address for row in spl_balances]
                    )
                    # Repeat the read-free RPC result after the DB lookup so no
                    # token metadata can be mistaken for on-chain balance data.
                    for row in spl_balances:
                        token = known_tokens.get(row.mint_address)
                        token_balances.append(
                            {
                                "token_account": row.token_account,
                                "mint_address": row.mint_address,
                                "raw_amount": row.raw_amount,
                                "quantity": row.quantity,
                                "decimals": row.decimals,
                                "program_id": row.program_id,
                                "symbol": None if token is None else token.symbol,
                                "name": None if token is None else token.name,
                                "image_url": None if token is None else token.image_url,
                            }
                        )
        except Exception:
            balance_error = "unavailable"
    decisions = await RealWalletExecutionRepository(session).latest(limit=30)
    live = LiveIntentRepository(session)
    unresolved = await live.unresolved()
    kill_switches = await live.active_kill_switches()
    kill_switch_history = await live.kill_switch_history(limit=20)
    open_positions = await live.open_positions_count()
    health = await live.health()
    positions = await live.positions(limit=30)
    return {
        "public_key": public_key or None,
        "address_valid": address_valid,
        "network": settings.REAL_WALLET_NETWORK,
        "rpc": rpc_status,
        "sol_balance": balance_sol,
        "token_balances": token_balances,
        "balance_error": balance_error,
        "funding_status": (
            "unknown" if balance_sol is None else "unfunded" if balance_sol == 0 else "funded"
        ),
        "mode": settings.REAL_WALLET_EXECUTION_MODE,
        "execution_enabled": settings.REAL_WALLET_EXECUTION_ENABLED,
        "autotrade_enabled": settings.REAL_WALLET_AUTOTRADE_ENABLED,
        # An API process must never read a keypair merely to light a dashboard
        # badge. A future isolated signer will report health through a narrow
        # authenticated channel; until then this is intentionally unavailable.
        "signer_status": "not_available_to_api",
        "live_submission_transport": (
            "installed" if transport.production_transport_installed else "not_installed"
        ),
        "safety_gate": "read_only_safety_gate_available",
        # --- Pre-mainnet readiness ------------------------------------------
        # Deliberately four separate blocks that each say "architecturally
        # ready" or not. None of them says the system is live, and none of them
        # can make it live: this endpoint is read-only and there is no
        # enable control anywhere in the product.
        "readiness": {
            "config_contract": {
                # Proven by `test_compose_env_contract.py`, not asserted here:
                # every execution setting is in the shared compose anchor, so
                # the API, worker and scheduler cannot hold different values.
                "execution_settings_shared": True,
                "mode": settings.REAL_WALLET_EXECUTION_MODE,
                "execution_enabled": settings.REAL_WALLET_EXECUTION_ENABLED,
                "autotrade_enabled": settings.REAL_WALLET_AUTOTRADE_ENABLED,
                "safety_policy_version": settings.REAL_WALLET_SAFETY_POLICY_VERSION,
            },
            "transport": {
                "envelope": transport.envelope,
                "release_approved": transport.release_approved,
                "production_transport_installed": (transport.production_transport_installed),
                "submission_permitted": transport.submission_permitted,
                "reasons": list(transport.reasons),
                "allowed_hosts": list(transport.allowed_hosts),
                "configured_host": transport.configured_host,
            },
            "order_validation": {
                # The check the signer cannot perform: swap semantics compared
                # against the authorised intent before anything is signed.
                "evidence_recheck_installed": True,
                "checks": [
                    "taker",
                    "input_mint",
                    "output_mint",
                    "in_amount_exact",
                    "minimum_output",
                    "slippage_bps",
                    "request_id",
                    "order_freshness",
                    "price_impact",
                    "route_evidence",
                    "sell_position_binding",
                    "sell_quantity_confirmed",
                ],
            },
            "fee_accounting": _fee_accounting_readiness(sol_price, now=now),
        },
        # The one line that must never be ambiguous on a dashboard. `LOCKED`
        # means no configuration reachable from this process can submit; it is
        # derived from the transport policy rather than restated by hand, so it
        # cannot say unlocked while the policy refuses.
        "lock_state": (
            "LOCKED" if not transport.submission_permitted else "SUBMISSION_PERMITTED"
        ),
        "limits": {
            "entry_size_usd": (
                None
                if configured_entry_size_usd() is None
                else _decimal(settings.REAL_WALLET_ENTRY_SIZE_USD)
            ),
            "entry_size_configured": configured_entry_size_usd() is not None,
            "max_trade_usd": _decimal(settings.REAL_WALLET_MAX_TRADE_USD),
            "max_open_positions": settings.REAL_WALLET_MAX_OPEN_POSITIONS,
            "max_total_exposure_usd": _decimal(settings.REAL_WALLET_MAX_TOTAL_EXPOSURE_USD),
            "max_daily_notional_usd": _decimal(settings.REAL_WALLET_MAX_DAILY_NOTIONAL_USD),
            "max_daily_trades": settings.REAL_WALLET_MAX_DAILY_TRADES,
            "max_daily_loss_usd": _decimal(settings.REAL_WALLET_MAX_DAILY_LOSS_USD),
            "max_balance_sol": _decimal(settings.REAL_WALLET_MAX_BALANCE_SOL),
            "max_balance_lamports": lamports_from_sol(settings.REAL_WALLET_MAX_BALANCE_SOL),
            "min_sol_fee_reserve": _decimal(settings.REAL_WALLET_MIN_SOL_FEE_RESERVE),
        },
        "security_gate": {
            # Named so the dashboard can state it rather than imply it: real
            # entries are gated by the same SEC-2 evaluator and the same pure
            # `entry_policy.decide` that Paper uses.
            "shared_with_paper": True,
            "evaluator": "sec2_entry_policy",
            "mandatory_checks": [
                str(check) for check in entry_policy.MANDATORY_CHECKS
            ],
            "max_evidence_age_seconds": int(
                entry_policy.MAX_EVIDENCE_AGE.total_seconds()
            ),
        },
        "program_allowlist": sorted(_allowed_programs()),
        "dry_run": {
            "feature_enabled": settings.FEATURE_REAL_WALLET_DRY_RUN_ENABLED,
            "decisions": [
                {
                    "mint_address": row.mint_address,
                    "symbol": row.symbol,
                    "radar_rank": row.radar_rank,
                    "status": row.status,
                    "safety": row.safety_decision,
                    "reason_codes": row.reason_codes,
                    "buy_impact_pct": (
                        None if row.buy_impact_pct is None else str(row.buy_impact_pct)
                    ),
                    "sell_impact_pct": (
                        None if row.sell_impact_pct is None else str(row.sell_impact_pct)
                    ),
                    "round_trip_loss_pct": (
                        None
                        if row.round_trip_loss_pct is None
                        else str(row.round_trip_loss_pct)
                    ),
                    "liquidity_usd": (
                        None if row.liquidity_usd is None else str(row.liquidity_usd)
                    ),
                    "buy_order": row.buy_order,
                    "sell_order": row.sell_order,
                    "evaluated_at": row.evaluated_at,
                }
                for row in decisions
            ],
        },
        "live_readiness": {
            "open_real_positions": open_positions,
            "unresolved_intents": [
                {
                    "id": str(intent.id),
                    "mint_address": intent.mint_address,
                    "state": intent.state,
                }
                for intent in unresolved
            ],
            "kill_switches": [
                {
                    "kind": switch.kind,
                    "reason": switch.reason,
                    "activated_at": switch.activated_at,
                    "activated_by": switch.actor,
                }
                for switch in kill_switches
            ],
            "kill_switch_history": [
                {
                    "kind": event.kind,
                    "action": event.action,
                    "actor": event.actor,
                    "reason": event.reason,
                    "at": event.created_at,
                }
                for event in kill_switch_history
            ],
        },
        "confirmed_lifecycle": {
            "consecutive_execution_failures": (
                0 if health is None else health.consecutive_failures
            ),
            "last_failure_reason": None if health is None else health.last_failure_reason,
            "positions": [
                {
                    "id": str(position.id),
                    "mint_address": position.mint_address,
                    "status": position.status,
                    "quantity": _decimal(position.quantity),
                    "entry_actual_input_amount": (
                        None
                        if position.entry_actual_input_amount is None
                        else _decimal(position.entry_actual_input_amount)
                    ),
                    "entry_actual_output_amount": (
                        None
                        if position.entry_actual_output_amount is None
                        else _decimal(position.entry_actual_output_amount)
                    ),
                    "exit_actual_input_amount": (
                        None
                        if position.exit_actual_input_amount is None
                        else _decimal(position.exit_actual_input_amount)
                    ),
                    "exit_actual_output_amount": (
                        None
                        if position.exit_actual_output_amount is None
                        else _decimal(position.exit_actual_output_amount)
                    ),
                    "realised_gross_pnl_usd": (
                        None
                        if position.realised_gross_pnl_usd is None
                        else _decimal(position.realised_gross_pnl_usd)
                    ),
                    "realised_net_pnl_usd": (
                        None
                        if position.realised_net_pnl_usd is None
                        else _decimal(position.realised_net_pnl_usd)
                    ),
                    "opened_at": position.opened_at,
                    "closed_at": position.closed_at,
                }
                for position in positions
            ],
        },
    }


@router.post(
    "/kill-switches/{kind}/clear",
    summary="Clear one armed kill switch, with attribution",
)
async def clear_kill_switch(
    kind: str,
    payload: KillSwitchClearIn,
    admin: AdminUser,
    session: DbSession,
) -> dict[str, object]:
    """Disarm one switch. **This authorises nothing else.**

    Every other barrier is evaluated independently and is untouched here: mode,
    the enable flags, the release constant, the submission guard, SEC-2
    freshness, network verification and the canary limits. Clearing a switch
    returns the system to whatever those already said, which today is still
    "no submission is possible".

    The consecutive-failure counter is deliberately not reset. It armed this
    switch; zeroing it here would let a repeating fault start from a clean
    slate after every clear instead of tripping again immediately.
    """
    live = LiveIntentRepository(session)
    cleared = await live.clear_kill_switch(
        kind=kind,
        actor=admin.email,
        reason=payload.reason,
        at=datetime.now(UTC),
    )
    if not cleared:
        raise NotFoundError("No armed kill switch of that kind.")
    await session.commit()
    remaining = await live.active_kill_switches()
    return {
        "kind": kind,
        "cleared": True,
        "cleared_by": admin.email,
        "active_kill_switches": [switch.kind for switch in remaining],
        # Restated so nobody reads a successful clear as a release.
        "execution_still_blocked": True,
        "mode": settings.REAL_WALLET_EXECUTION_MODE,
        "execution_enabled": settings.REAL_WALLET_EXECUTION_ENABLED,
        "submission_permitted": transport_readiness().submission_permitted,
    }


def _intent_summary(intent: RealWalletDevnetIntent) -> DevnetIntentSummary:
    """Public operator projection: never return unsigned or signed wire bytes."""
    return DevnetIntentSummary(
        id=intent.id,
        state=intent.state,
        action_type=intent.action_type,
        wallet_public_key=intent.wallet_public_key,
        destination_public_key=intent.destination_public_key,
        input_mint=intent.input_mint,
        output_mint=intent.output_mint,
        input_amount_raw=_decimal(intent.input_amount_raw),
        quote_id=intent.quote_id,
        quote_expires_at=intent.quote_expires_at,
        simulation_status=intent.simulation_status,
        approval_status=intent.approval_status,
        approval_expires_at=intent.approval_expires_at,
        signing_status=intent.signing_status,
        transaction_signature=intent.transaction_signature,
        submission_status=intent.submission_status,
        submission_retry_count=intent.submission_retry_count,
        confirmation_status=intent.confirmation_status,
        confirmation_slot=intent.confirmation_slot,
        failure_reason=intent.failure_reason,
        reconciliation=intent.reconciliation,
        created_at=intent.created_at,
        updated_at=intent.updated_at,
    )


def _quote_out(quote: RealWalletDevnetQuote) -> dict[str, object]:
    return {
        "id": quote.id,
        "network": quote.network,
        "wallet_public_key": quote.wallet_public_key,
        "input_mint": quote.input_mint,
        "output_mint": quote.output_mint,
        "input_amount_raw": _decimal(quote.input_amount_raw),
        "expected_output_raw": _decimal(quote.expected_output_raw),
        "minimum_output_raw": _decimal(quote.minimum_output_raw),
        "slippage_bps": quote.slippage_bps,
        "price_impact_pct": None
        if quote.price_impact_pct is None
        else _decimal(quote.price_impact_pct),
        "estimated_fee_lamports": quote.estimated_fee_lamports,
        "provider": quote.provider,
        "provider_reference": quote.provider_reference,
        "route": quote.route,
        "quoted_at": quote.quoted_at,
        "expires_at": quote.expires_at,
        "jupiter_devnet_limitation": "Jupiter devnet swap routing is not used or implied.",
    }


def _workflow_error(exc: Exception) -> None:
    if isinstance(exc, DevnetIntentExpiredError):
        raise ConflictError(
            "The devnet quote or approval has expired.",
            code="devnet_intent_expired",
        ) from exc
    if isinstance(exc, DevnetApprovalRequiredError):
        raise ConflictError(str(exc), code="devnet_manual_approval_required") from exc
    if isinstance(exc, DevnetExecutionBlockedError):
        raise ConflictError(
            "Phase 2 is verified-devnet only.",
            code="phase2_devnet_only",
        ) from exc
    if isinstance(exc, DevnetManualWorkflowError):
        raise ConflictError(str(exc), code="devnet_manual_workflow_rejected") from exc
    if isinstance(exc, DevnetIntentTransitionError):
        raise ConflictError(
            "That lifecycle transition is not permitted.",
            code="devnet_transition_rejected",
        ) from exc
    raise exc


def _manual_workflow(session: DbSession) -> DevnetManualWorkflow:
    """A no-I/O workflow used by quote, intent, and approval handlers."""
    return DevnetManualWorkflow(
        session,
        StandardSolanaRPC(rpc_url=settings.REAL_WALLET_RPC_URL),
    )


@router.post(
    "/devnet/quotes/native-transfer",
    summary="Create a read-only devnet transfer quote",
)
async def create_native_transfer_quote(
    payload: NativeTransferQuoteIn, _admin: AdminUser, session: DbSession
) -> dict[str, object]:
    """The only Phase 2 quote. No signer, transaction, or submission is involved."""
    workflow = _manual_workflow(session)
    try:
        quote = await workflow.quote_native_transfer(
            destination_public_key=payload.destination_public_key, lamports=payload.lamports
        )
    except Exception as exc:
        _workflow_error(exc)
        raise  # pragma: no cover - `_workflow_error` always raises
    return _quote_out(quote)


@router.post(
    "/devnet/intents",
    response_model=DevnetIntentSummary,
    summary="Create a devnet intent",
)
async def create_devnet_intent(
    payload: DevnetIntentIn, _admin: AdminUser, session: DbSession
) -> DevnetIntentSummary:
    workflow = _manual_workflow(session)
    try:
        intent = await workflow.create_intent(
            quote_id=payload.quote_id, idempotency_key=payload.idempotency_key
        )
    except Exception as exc:
        _workflow_error(exc)
        raise  # pragma: no cover
    return _intent_summary(intent)


@router.get(
    "/devnet/intents",
    response_model=list[DevnetIntentSummary],
    summary="List manual devnet intents",
)
async def list_devnet_intents(
    _admin: AdminUser, session: DbSession
) -> list[DevnetIntentSummary]:
    intents = await DevnetIntentRepository(session).intents()
    return [_intent_summary(intent) for intent in intents]


@router.get(
    "/devnet/intents/{intent_id}", summary="Read one manual devnet intent and audit chain"
)
async def read_devnet_intent(
    intent_id: uuid.UUID, _admin: AdminUser, session: DbSession
) -> dict[str, object]:
    repository = DevnetIntentRepository(session)
    intent = await repository.intent_by_id(intent_id)
    if intent is None:
        raise NotFoundError("Devnet intent not found.", code="devnet_intent_not_found")
    quote = await repository.quote_by_id(intent.quote_id) if intent.quote_id else None
    return {
        "intent": _intent_summary(intent).model_dump(mode="json"),
        "quote": None if quote is None else _quote_out(quote),
        "simulation": {
            "status": intent.simulation_status,
            "logs": intent.simulation_logs or [],
            "units_consumed": intent.simulation_units_consumed,
            "context_slot": intent.simulation_context_slot,
            "blockhash": intent.simulation_blockhash,
            "simulated_at": intent.simulated_at,
        },
        "events": [
            {
                "id": event.id,
                "type": event.event_type,
                "detail": event.detail,
                "created_at": event.created_at,
            }
            for event in await repository.events(intent.id)
        ],
    }


@router.post(
    "/devnet/intents/{intent_id}/simulate",
    response_model=DevnetIntentSummary,
    summary="Build, inspect, and simulate an unsigned devnet transfer",
)
async def simulate_devnet_intent(
    intent_id: uuid.UUID, _admin: AdminUser, session: DbSession
) -> DevnetIntentSummary:
    rpc = StandardSolanaRPC(rpc_url=settings.REAL_WALLET_RPC_URL)
    try:
        async with rpc:
            intent = await DevnetManualWorkflow(session, rpc).simulate(intent_id=intent_id)
    except Exception as exc:
        _workflow_error(exc)
        raise  # pragma: no cover
    return _intent_summary(intent)


@router.post(
    "/devnet/intents/{intent_id}/approve",
    response_model=DevnetIntentSummary,
    summary="Explicitly approve one successfully simulated devnet intent",
)
async def approve_devnet_intent(
    intent_id: uuid.UUID,
    payload: ManualApprovalIn,
    admin: AdminUser,
    session: DbSession,
) -> DevnetIntentSummary:
    workflow = _manual_workflow(session)
    try:
        intent = await workflow.approve(
            intent_id=intent_id,
            approved_by_user_id=admin.id,
            confirmation_phrase=payload.confirmation_phrase,
        )
    except Exception as exc:
        _workflow_error(exc)
        raise  # pragma: no cover
    return _intent_summary(intent)


@router.post(
    "/devnet/intents/{intent_id}/sign",
    response_model=DevnetIntentSummary,
    summary="Ask the isolated signer to sign one approved devnet intent",
)
async def sign_devnet_intent(
    intent_id: uuid.UUID, _admin: AdminUser, session: DbSession
) -> DevnetIntentSummary:
    try:
        await UnixDevnetSignerClient().sign(intent_id)
    except DevnetSignerUnavailableError as exc:
        raise ServiceUnavailableError(
            "The isolated devnet signer is unavailable.",
            code="devnet_signer_unavailable",
        ) from exc
    except DevnetSignerRejectedError as exc:
        raise ConflictError(
            "The isolated signer rejected this intent.",
            code="devnet_signer_rejected",
        ) from exc
    intent = await DevnetIntentRepository(session).intent_by_id(intent_id)
    if intent is None:  # pragma: no cover - signer accepted an impossible missing intent
        raise NotFoundError("Devnet intent not found.", code="devnet_intent_not_found")
    return _intent_summary(intent)


@router.post(
    "/devnet/intents/{intent_id}/submit",
    response_model=DevnetIntentSummary,
    summary="Submit one signed devnet transfer exactly once",
)
async def submit_devnet_intent(
    intent_id: uuid.UUID, _admin: AdminUser, session: DbSession
) -> DevnetIntentSummary:
    rpc = StandardSolanaRPC(rpc_url=settings.REAL_WALLET_RPC_URL)
    try:
        async with rpc:
            intent = await DevnetManualWorkflow(session, rpc).submit(intent_id=intent_id)
    except Exception as exc:
        _workflow_error(exc)
        raise  # pragma: no cover
    return _intent_summary(intent)


@router.post(
    "/devnet/intents/{intent_id}/confirm",
    response_model=DevnetIntentSummary,
    summary="Confirm and reconcile one submitted devnet transfer",
)
async def confirm_devnet_intent(
    intent_id: uuid.UUID, _admin: AdminUser, session: DbSession
) -> DevnetIntentSummary:
    rpc = StandardSolanaRPC(rpc_url=settings.REAL_WALLET_RPC_URL)
    try:
        async with rpc:
            intent = await DevnetManualWorkflow(session, rpc).confirm_and_reconcile(
                intent_id=intent_id
            )
    except Exception as exc:
        _workflow_error(exc)
        raise  # pragma: no cover
    return _intent_summary(intent)


@router.post(
    "/devnet/intents/{intent_id}/cancel",
    response_model=DevnetIntentSummary,
    summary="Cancel an unsigned manual devnet intent",
)
async def cancel_devnet_intent(
    intent_id: uuid.UUID, _admin: AdminUser, session: DbSession
) -> DevnetIntentSummary:
    repository = DevnetIntentRepository(session)
    intent = await repository.intent_by_id(intent_id)
    if intent is None:
        raise NotFoundError("Devnet intent not found.", code="devnet_intent_not_found")
    if intent.state == DevnetIntentState.CANCELLED:
        return _intent_summary(intent)
    try:
        await repository.transition(
            intent=intent,
            next_state=DevnetIntentState.CANCELLED,
            at=datetime.now(UTC),
            event_type="cancelled_by_admin",
            detail={},
        )
    except Exception as exc:
        _workflow_error(exc)
        raise  # pragma: no cover
    return _intent_summary(intent)
