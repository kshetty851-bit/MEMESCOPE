"""Admin-only, read-only dedicated execution-wallet status."""

from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter

from app.api.deps import AdminUser
from app.core.config import settings
from app.real_wallet.balance import ExecutionWalletBalanceService
from app.services.rpc.registry import get_rpc

router = APIRouter(prefix="/real-wallet", tags=["real-wallet"])


def _decimal(value: Decimal) -> str:
    return format(value, "f")


@router.get("/status", summary="Read dedicated execution-wallet status")
async def status(_admin: AdminUser) -> dict[str, object]:
    """Public-address data only. This endpoint cannot load, create, or use a signer."""
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
        "safety_gate": "read_only_safety_gate_available",
        "limits": {
            "max_trade_usd": _decimal(settings.REAL_WALLET_MAX_TRADE_USD),
            "max_open_positions": settings.REAL_WALLET_MAX_OPEN_POSITIONS,
            "max_total_exposure_usd": _decimal(settings.REAL_WALLET_MAX_TOTAL_EXPOSURE_USD),
            "max_daily_notional_usd": _decimal(settings.REAL_WALLET_MAX_DAILY_NOTIONAL_USD),
            "max_daily_loss_usd": _decimal(settings.REAL_WALLET_MAX_DAILY_LOSS_USD),
            "min_sol_fee_reserve": _decimal(settings.REAL_WALLET_MIN_SOL_FEE_RESERVE),
        },
    }
