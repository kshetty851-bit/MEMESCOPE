"""The execution wallet's page: status, start/stop, withdraw.

Who may do what, decided by the operator on 2026-09-16:

* Reading the wallet, pressing STOP and withdrawing need only the site code
  (`AlphaAccessMiddleware`). None of them can spend the money on anything:
  STOP only ends buying, and a withdrawal can only reach the one nominated
  address, which the signer re-checks against its own copy.
* START and clearing a kill switch need the administrator account, because
  they are the two controls a stranger could use to put the money at risk.

Account emails are shown only to the administrator; the site code is shared.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import ROUND_UP, Decimal
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.api.deps import AdminUser, DbSession, OptionalUser
from app.core.config import settings
from app.core.exceptions import ConflictError, NotFoundError, ServiceUnavailableError
from app.models.lab import LabDecision
from app.models.real_wallet_execution import (
    RealWalletDevnetIntent,
    RealWalletDevnetQuote,
    RealWalletLiveIntent,
    RealWalletPosition,
)
from app.models.user import User, UserRole
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
from app.real_wallet.driver import RealWalletDriver
from app.real_wallet.live_repository import LiveIntentRepository
from app.real_wallet import withdraw_service, withdrawal
from app.real_wallet.mainnet_signer_client import (
    MainnetSignerRejectedError,
    MainnetSignerUnavailableError,
    UnixMainnetSignerClient,
)
from app.real_wallet.network import (
    DevnetExecutionBlockedError,
    is_valid_wallet_address,
    verify_wallet_network,
)
from app.real_wallet.funding_readiness import as_dict as readiness_as_dict
from app.real_wallet.funding_readiness import evaluate as evaluate_funding_readiness
from app.real_wallet.autotrade import (
    AutotradeSwitchService,
    InvalidTicketError,
    UnknownStrategyError,
    ticket_choices,
    ticket_for,
)
from app.real_wallet.rehearsal import as_dict as rehearsal_as_dict
from app.real_wallet.rehearsal import rehearse
from app.real_wallet.policy import configured_entry_size_usd
from app.real_wallet.sol_price import JupiterSolUsdPriceSource
from app.real_wallet.sol_price import current_usd as sol_usd_now
from app.real_wallet.transport_policy import readiness as transport_readiness
from app.real_wallet.tx_inspect import lamports_from_sol
from app.repositories.token import TokenRepository
from app.services.rpc.standard import StandardSolanaRPC

from app.core.logging import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/real-wallet", tags=["real-wallet"])


def _is_owner(viewer: User | None) -> bool:
    return viewer is not None and viewer.role == UserRole.ADMIN


def _who(actor: str | None, owner: bool) -> str | None:
    """An account email is the owner's to see; the site code is shared."""
    if owner or not actor or "@" not in actor:
        return actor
    return "signed-in user"


def _usd(value: Decimal) -> str:
    """A dollar amount without trailing zeros: 100, 25, 12.5."""
    return format(value.normalize(), "f")


def _wallet_strategies(ticket: Decimal) -> list[dict[str, object]]:
    """The strategies START can nominate, each stated from its own spec and
    sized at `ticket`."""
    from app.labs.graduation import config as grad
    from app.labs.graduation import live_spec

    return [{
        "id": s.id,
        "name": s.name,
        "paper_book": live_spec.PAPER_BOOKS[s.id],
        "idea": s.hypothesis,
        "pool_floor_usd": live_spec.POOL_FLOOR_USD,
        "hold_minutes": live_spec.hold_minutes(s),
        "take_profit": s.exits.take_profit is not None,
        "stop_loss": s.exits.stop_loss is not None,
        "max_signal_age_seconds": live_spec.MAX_DECISION_AGE_SECONDS,
        "ticket_usd": _usd(ticket),
        "min_ticket_usd": _usd(grad.wallet_floor(ticket)),
    } for s in live_spec.STRATEGIES]


def _wallet_strategy(nominated: str | None, ticket: Decimal) -> dict[str, object]:
    """The strategy the page describes: the nominated one, else the first."""
    strategies = _wallet_strategies(ticket)
    return next((s for s in strategies if s["id"] == (nominated or "").upper()),
                strategies[0])


def _sol_for(usd: Decimal, price: Decimal) -> Decimal:
    """SOL a balance needs to spend `usd` and still keep the fee reserve."""
    return (settings.REAL_WALLET_MIN_SOL_FEE_RESERVE + usd / price).quantize(
        Decimal("0.001"), rounding=ROUND_UP)


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


class AutotradeStartIn(BaseModel):
    """Starting requires naming a strategy and a reason. Both are recorded."""

    strategy_id: str = Field(min_length=2, max_length=16)
    reason: str = Field(min_length=3, max_length=256)
    #: One of `ticket_choices`; omitted trades `REAL_WALLET_ENTRY_SIZE_USD`.
    ticket_usd: Decimal | None = Field(default=None, gt=0)


class AutotradeStopIn(BaseModel):
    reason: str = Field(min_length=3, max_length=256)


@router.get("/autotrade", summary="Read the operator start/stop control")
async def read_autotrade(viewer: OptionalUser, session: DbSession) -> dict[str, object]:
    owner = _is_owner(viewer)
    from app.labs.graduation.config import wallet_floor

    service = AutotradeSwitchService(session)
    current = await service.state()
    ticket = ticket_for(current, settings.REAL_WALLET_ENTRY_SIZE_USD)
    state = current.as_dict()
    for key in ("started_by", "stopped_by"):
        state[key] = _who(state[key], owner)
    return {
        **state,
        "strategy": _wallet_strategy(current.nominated_strategy, ticket),
        # Every arm START can nominate, and the trade sizes it accepts — each
        # arm is described at the size the wallet would trade it now.
        "strategies": _wallet_strategies(ticket),
        "ticket_choices": [{"ticket_usd": _usd(t), "min_usd": _usd(wallet_floor(t))}
                           for t in ticket_choices()],
        # START needs the administrator account; everything else here does not.
        "can_start": owner,
        "history": [
            {"action": e.action, "actor": _who(e.actor, owner), "reason": e.reason,
             "nominated_strategy": e.nominated_strategy,
             "ticket_usd": None if e.ticket_usd is None else _usd(e.ticket_usd),
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
            ticket_usd=payload.ticket_usd,
        )
    except UnknownStrategyError as exc:
        raise HTTPException(
            status_code=422, detail=f"unknown strategy: {exc}"
        ) from exc
    except InvalidTicketError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await session.commit()
    return state.as_dict()


@router.post("/autotrade/stop", summary="Stop autonomous trading, unconditionally")
async def stop_autotrade(
    payload: AutotradeStopIn, viewer: OptionalUser, session: DbSession
) -> dict[str, object]:
    """Stop. This can never be refused and needs no other condition to be true.

    A control an operator cannot trust to stop is a control they will be afraid
    to start, so this path has no barrier of its own — not even an account — and
    takes effect on the next guard evaluation. Open positions still sell on time.
    """
    service = AutotradeSwitchService(session)
    state = await service.stop(
        actor=viewer.email if viewer else "site visitor",
        reason=payload.reason, at=datetime.now(UTC),
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
async def funding_readiness(session: DbSession) -> dict[str, object]:
    """A read-only checklist. It can never enable anything.

    Measures what it can (balance, genesis, kill switch, signals, settled
    trades) and reports the rest as UNKNOWN rather than as satisfied — an
    unmeasured precondition has not been met, it has merely not been looked at.
    """
    now = datetime.now(UTC)
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

    live = LiveIntentRepository(session)
    kill_switch_active: bool | None = None
    try:
        kill_switch_active = bool(await live.active_kill_switches())
    except Exception:  # pragma: no cover - unreadable state stays UNKNOWN
        kill_switch_active = None

    # What the next entry would spend, by the driver's own rule.
    switch = await AutotradeSwitchService(session).state()
    ticket = ticket_for(switch, settings.REAL_WALLET_ENTRY_SIZE_USD)
    strategy = _wallet_strategy(switch.nominated_strategy, ticket)
    strategy_id = switch.nominated_strategy or str(strategy["id"])
    price = await sol_usd_now(now)
    next_trade: Decimal | None = None
    min_trade_sol = full_trade_sol = None
    if price is not None:
        min_trade_sol = _sol_for(Decimal(str(strategy["min_ticket_usd"])), price)
        full_trade_sol = _sol_for(ticket, price)
        if balance_sol is not None:
            open_positions = await live.open_positions_count()
            configured = configured_entry_size_usd(
                balance_sol * price + await live.open_exposure_usd())
            if configured is not None:
                next_trade = RealWalletDriver._fundable(
                    strategy_id, ticket_for(switch, configured),
                    balance_lamports=lamports_from_sol(balance_sol),
                    sol_price=price, open_positions=open_positions)

    last_signal = await session.scalar(
        select(func.max(LabDecision.checkpoint_at)).where(
            LabDecision.strategy_id == strategy_id.upper(),
            LabDecision.eligible.is_(True)))
    round_trips = await session.scalar(
        select(func.count()).select_from(RealWalletPosition).where(
            RealWalletPosition.status == "CLOSED",
            RealWalletPosition.exit_transaction_signature.is_not(None)))

    # Asked over the socket. This container cannot answer it from its own
    # environment — it is deliberately denied any key path — so an unreachable
    # signer is UNKNOWN rather than a failure to configure something here.
    signer_holds_pinned_key: bool | None = None
    try:
        signer_holds_pinned_key = bool(
            (await UnixMainnetSignerClient().identity()).get("matches_pinned_key")
        )
    except MainnetSignerUnavailableError:
        signer_holds_pinned_key = None
    except MainnetSignerRejectedError:
        signer_holds_pinned_key = False

    readiness = evaluate_funding_readiness(
        wallet_balance_sol=balance_sol,
        network_verified=network_verified,
        kill_switch_active=kill_switch_active,
        signer_holds_pinned_key=signer_holds_pinned_key,
        # Nothing has been promoted. When the lab's review promotes something
        # this becomes its id, and it is deliberately not derivable from config.
        validated_strategy=None,
        next_trade_usd=next_trade,
        min_trade_sol=min_trade_sol,
        full_trade_sol=full_trade_sol,
        last_signal_minutes=(None if last_signal is None
                             else (now - last_signal).total_seconds() / 60),
        signals_measured=True,
        round_trips=int(round_trips or 0),
    )
    return {**readiness_as_dict(readiness), "strategy_id": strategy_id,
            "min_trade_sol": None if min_trade_sol is None else _decimal(min_trade_sol),
            "full_trade_sol": None if full_trade_sol is None else _decimal(full_trade_sol)}


class WithdrawIn(BaseModel):
    """Amount only. The destination is not a parameter and cannot be one."""

    sol_amount: Decimal = Field(gt=0)
    confirmation_phrase: Literal["WITHDRAW_TO_MY_ADDRESS"]


@router.post("/withdraw", summary="Send SOL to the one nominated address")
async def withdraw(
    payload: WithdrawIn, viewer: OptionalUser, session: DbSession
) -> dict[str, object]:
    """The only path here that moves money without a trade.

    It cannot choose a recipient. The destination comes from configuration, is
    checked in the service, and is checked AGAIN inside the isolated signer
    against that process's own copy of the setting — so the worst a compromised
    caller achieves is sending the operator their own money.

    Never retried. A submitted transfer whose response was lost is UNCERTAIN,
    and asking again is how one withdrawal becomes two.
    """
    del session
    rpc = StandardSolanaRPC(rpc_url=settings.REAL_WALLET_RPC_URL)
    try:
        async with rpc:
            balances = ExecutionWalletBalanceService(rpc)
            sol = (await balances.get_sol_balance(
                settings.REAL_WALLET_PUBLIC_KEY.strip()
            )).sol
            prepared = await withdraw_service.prepare(
                rpc,
                sol_amount=payload.sol_amount,
                balance_lamports=lamports_from_sol(Decimal(str(sol))),
            )
            signed = await UnixMainnetSignerClient().sign_withdrawal(
                prepared.unsigned_transaction
            )
            signature = await withdraw_service.submit(
                rpc, signed_transaction=signed["signed_transaction"]
            )
    except withdraw_service.WithdrawError as exc:
        raise ConflictError(str(exc)) from exc
    except (MainnetSignerUnavailableError, MainnetSignerRejectedError) as exc:
        raise ServiceUnavailableError(f"signer: {exc}") from exc

    logger.warning("real_wallet_withdrawal_submitted",
                   actor=str(viewer.id) if viewer else "site visitor",
                   signature=signature, lamports=prepared.lamports)
    return {
        "submitted": True,
        "signature": signature,
        "destination": prepared.destination,
        "sol": str(prepared.sol),
        "explorer": f"https://solscan.io/tx/{signature}",
        "note": ("Submitted once and never retried. If this response was lost, "
                 "check the signature on chain rather than sending again."),
    }


@router.get("/status", summary="Read dedicated execution-wallet status")
async def status(viewer: OptionalUser, session: DbSession) -> dict[str, object]:
    """Return public metadata only; never signer material."""
    now = datetime.now(UTC)
    owner = _is_owner(viewer)
    # Read-only price probe. It cannot trigger an order, a signature or a
    # submission; it prices the balance in the unit every limit is written in.
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
    live = LiveIntentRepository(session)
    kill_switches = await live.active_kill_switches()
    kill_switch_history = await live.kill_switch_history(limit=20)
    open_positions = await live.open_positions_count()
    health = await live.health()
    positions = await live.positions(limit=50)
    exit_states: dict[uuid.UUID, str] = {
        row.id: row.state for row in (await session.execute(
            select(RealWalletLiveIntent.id, RealWalletLiveIntent.state).where(
                RealWalletLiveIntent.id.in_(
                    [p.exit_intent_id for p in positions if p.exit_intent_id])))).all()
    }
    symbols = await TokenRepository(session).get_many_by_mints(
        list({p.mint_address for p in positions}))
    pnl_today = await live.realised_pnl_today(now)
    tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)

    def amount(value: Decimal | None) -> str | None:
        return None if value is None else _decimal(value)

    return {
        "public_key": public_key or None,
        "address_valid": address_valid,
        "network": settings.REAL_WALLET_NETWORK,
        "rpc": rpc_status,
        "sol_balance": balance_sol,
        # The balance in the unit every limit on this page is written in.
        # `None` when the price is unreadable — never a stale or guessed rate.
        "sol_price_usd": (float(sol_price.usd) if sol_price is not None else None),
        "sol_price_fresh": (
            sol_price.is_fresh(
                now, max_age_seconds=settings.EXECUTION_SOL_PRICE_MAX_AGE_SECONDS
            )
            if sol_price is not None else False
        ),
        "balance_usd": (
            float(Decimal(str(balance_sol)) * sol_price.usd)
            if balance_sol is not None and sol_price is not None else None
        ),
        "token_balances": token_balances,
        "balance_error": balance_error,
        "mode": settings.REAL_WALLET_EXECUTION_MODE,
        "execution_enabled": settings.REAL_WALLET_EXECUTION_ENABLED,
        "autotrade_enabled": settings.REAL_WALLET_AUTOTRADE_ENABLED,
        # Asymmetric on purpose: anyone may deposit to a public address, and the
        # money may leave for exactly one nominated destination.
        "withdrawal": {
            "locked_to": withdrawal.policy().destination or None,
            "configured": withdrawal.policy().usable,
            "reason": withdrawal.policy().reason or None,
        },
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
            "balance_ceiling_enabled": settings.REAL_WALLET_BALANCE_CEILING_ENABLED,
            "max_balance_sol": _decimal(settings.REAL_WALLET_MAX_BALANCE_SOL),
            "min_sol_fee_reserve": _decimal(settings.REAL_WALLET_MIN_SOL_FEE_RESERVE),
            "exit_max_price_impact_pct": _decimal(
                settings.REAL_WALLET_EXIT_MAX_PRICE_IMPACT_PCT),
            "max_slippage_bps": settings.REAL_WALLET_EXIT_MAX_SLIPPAGE_BPS,
        },
        # The two daily limits, as they stand. Both reset at 00:00 UTC.
        "today": {
            "realised_pnl_usd": _decimal(pnl_today),
            "loss_limit_usd": _decimal(settings.REAL_WALLET_MAX_DAILY_LOSS_USD),
            "loss_limit_hit": -pnl_today >= settings.REAL_WALLET_MAX_DAILY_LOSS_USD,
            "buys": await RealWalletDriver(session)._trades_today(now),
            "buys_limit": settings.REAL_WALLET_MAX_DAILY_TRADES,
            "resets_at": tomorrow.isoformat(),
        },
        "open_positions": open_positions,
        "kill_switches": [
            {
                "kind": switch.kind,
                "reason": switch.reason,
                "activated_at": switch.activated_at,
                "activated_by": _who(switch.actor, owner),
            }
            for switch in kill_switches
        ],
        "kill_switch_history": [
            {
                "kind": event.kind,
                "action": event.action,
                "actor": _who(event.actor, owner),
                "reason": event.reason,
                "at": event.created_at,
            }
            for event in kill_switch_history
        ],
        "consecutive_execution_failures": (
            0 if health is None else health.consecutive_failures
        ),
        "failures_before_kill_switch": settings.REAL_WALLET_MAX_CONSECUTIVE_EXECUTION_FAILURES,
        "last_failure_reason": None if health is None else health.last_failure_reason,
        "positions": [
            {
                "id": str(position.id),
                "mint_address": position.mint_address,
                "symbol": (symbols[position.mint_address].symbol
                           if position.mint_address in symbols else None),
                "status": position.status,
                "strategy_id": position.strategy_id,
                "quantity": _decimal(position.quantity),
                "cost_usd": _decimal(position.entry_price_usd * position.quantity),
                "spent": amount(position.entry_actual_input_amount),
                "received": amount(position.exit_actual_output_amount),
                "realised_gross_pnl_usd": amount(position.realised_gross_pnl_usd),
                "realised_net_pnl_usd": amount(position.realised_net_pnl_usd),
                "exit_reason": position.exit_reason,
                # What the sell is doing right now, for an open position.
                "exit_state": (exit_states.get(position.exit_intent_id)
                               if position.exit_intent_id else None),
                "opened_at": position.opened_at,
                "closed_at": position.closed_at,
                "entry_signature": position.entry_transaction_signature,
                "exit_signature": position.exit_transaction_signature,
            }
            for position in positions
        ],
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
