"""Admin-only, read-only dedicated execution-wallet status."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from fastapi import APIRouter

from app.api.deps import AdminUser, DbSession
from app.core.config import settings
from app.real_wallet.balance import ExecutionWalletBalanceService
from app.real_wallet.live_repository import LiveIntentRepository
from app.real_wallet.repository import RealWalletExecutionRepository
from app.real_wallet.signer import FileExecutionSigner
from app.real_wallet.sol_price import JupiterSolUsdPriceSource, SolUsdPrice
from app.real_wallet.transport_policy import readiness as transport_readiness
from app.services.rpc.registry import get_rpc

router = APIRouter(prefix="/real-wallet", tags=["real-wallet"])


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
    balance_sol: float | None = None
    balance_error: str | None = None
    if public_key:
        rpc = get_rpc()
        try:
            async with rpc:
                balance = await ExecutionWalletBalanceService(rpc).get_sol_balance(public_key)
                balance_sol = balance.sol
        except Exception:
            balance_error = "unavailable"
    decisions = await RealWalletExecutionRepository(session).latest(limit=30)
    live = LiveIntentRepository(session)
    unresolved = await live.unresolved()
    kill_switches = await live.active_kill_switches()
    open_positions = await live.open_positions_count()
    health = await live.health()
    positions = await live.positions(limit=30)
    signer_ready = False
    if public_key and settings.REAL_WALLET_EXECUTION_SECRET_FILE:
        # Readiness is intentionally a boolean. The secret and its bytes never
        # escape this backend-only check.
        try:
            FileExecutionSigner.load(
                secret_file=Path(settings.REAL_WALLET_EXECUTION_SECRET_FILE),
                expected_public_key=public_key,
            )
            signer_ready = True
        except Exception:
            signer_ready = False
    return {
        "public_key": public_key or None,
        "sol_balance": balance_sol,
        "balance_error": balance_error,
        "funding_status": (
            "unknown" if balance_sol is None else "unfunded" if balance_sol == 0 else "funded"
        ),
        "mode": settings.REAL_WALLET_EXECUTION_MODE,
        "execution_enabled": settings.REAL_WALLET_EXECUTION_ENABLED,
        "autotrade_enabled": settings.REAL_WALLET_AUTOTRADE_ENABLED,
        "signer_ready": signer_ready,
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
        "limits": {
            "max_trade_usd": _decimal(settings.REAL_WALLET_MAX_TRADE_USD),
            "max_open_positions": settings.REAL_WALLET_MAX_OPEN_POSITIONS,
            "max_total_exposure_usd": _decimal(settings.REAL_WALLET_MAX_TOTAL_EXPOSURE_USD),
            "max_daily_notional_usd": _decimal(settings.REAL_WALLET_MAX_DAILY_NOTIONAL_USD),
            "max_daily_loss_usd": _decimal(settings.REAL_WALLET_MAX_DAILY_LOSS_USD),
            "min_sol_fee_reserve": _decimal(settings.REAL_WALLET_MIN_SOL_FEE_RESERVE),
        },
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
                {"kind": switch.kind, "reason": switch.reason} for switch in kill_switches
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
