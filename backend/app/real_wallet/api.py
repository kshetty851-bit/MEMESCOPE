"""Admin-only, read-only dedicated execution-wallet status."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from fastapi import APIRouter

from app.api.deps import AdminUser, DbSession
from app.core.config import settings
from app.real_wallet.balance import ExecutionWalletBalanceService
from app.real_wallet.live_repository import LiveIntentRepository
from app.real_wallet.repository import RealWalletExecutionRepository
from app.real_wallet.signer import FileExecutionSigner
from app.services.rpc.registry import get_rpc

router = APIRouter(prefix="/real-wallet", tags=["real-wallet"])


def _decimal(value: Decimal) -> str:
    return format(value, "f")


@router.get("/status", summary="Read dedicated execution-wallet status")
async def status(_admin: AdminUser, session: DbSession) -> dict[str, object]:
    """Return public and readiness metadata only; never signer material."""
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
        "live_submission_transport": "not_installed",
        "safety_gate": "read_only_safety_gate_available",
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
