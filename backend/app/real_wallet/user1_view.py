"""USER 1's real trades beside the Pump Catcher Lab (Karthik, 2026-10-27: "bring
user 1 trades to lab with balance, so i can check from mobile or other laptop").

Read only, behind the site's sign-in like every lab page: the balance read from
chain, and each trade since USER 1 started following the lab, beside the lab's
own result for the same coin. No address, no switch, no withdrawal here; those
stay in the device-locked JUPITER box on /real-wallet.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter
from sqlalchemy import text

from app.api.deps import DbSession

router = APIRouter(prefix="/labs/graduation/karthik/pump-catcher/user1", tags=["graduation-lab"])

#: USER 1 switched to the Pump Catcher's coins (G-PUMP) at 20:00 Dubai, 26 Oct.
SINCE = datetime(2026, 10, 26, 16, tzinfo=UTC)
_CACHE: tuple[float, dict[str, Any]] | None = None
_TRADES = text("""
    select p.mint_address, t.symbol, p.opened_at, p.closed_at, p.status, p.exit_reason,
           p.realised_net_pnl_usd, p.entry_actual_input_amount * p.entry_sol_price_usd
    from real_wallet_positions p left join grad_tokens t on t.mint = p.mint_address
    where p.wallet_public_key = :w and p.opened_at >= :s
    order by p.opened_at desc""")


def _why(reason: str | None) -> str | None:
    if not reason:
        return None
    if reason.startswith("target_"):
        return "hit the target"
    if reason == "down_at_5m":
        return "down at 5 min"
    if reason.startswith("time_"):
        return "10 minutes"
    return reason.replace("_", " ")


@router.get("", summary="USER 1's balance and real trades beside the Pump Catcher Lab")
async def user1(session: DbSession) -> dict[str, Any]:
    from app.labs.graduation import api as grad_api
    from app.real_wallet import family_api, family_wallets

    global _CACHE
    if _CACHE and time.monotonic() - _CACHE[0] < 30:
        return _CACHE[1]
    wallet = family_wallets.address("USER1")
    own = await family_api._own_wallet("USER1") if wallet else {}
    lab = {t["mint"]: t for t in (await grad_api.pump_catcher_book_cached(session))["trades_list"]}
    rows = (await session.execute(_TRADES, {"w": wallet, "s": SINCE})).all() if wallet else []
    trades = []
    for mint, symbol, opened, closed, status, reason, net, stake in rows:
        t = lab.get(mint)
        trades.append({
            "mint": mint, "symbol": symbol, "opened_at": opened, "closed_at": closed,
            "open": status == "OPEN", "stake_usd": round(float(stake), 2) if stake else None,
            "pnl_usd": round(float(net), 2) if net is not None else None,
            "pct": round(100 * float(net) / float(stake), 1) if net is not None and stake else None,
            "how": _why(reason), "lab_pct": float(t["pct"]) if t else None})
    closed = [t for t in trades if t["pnl_usd"] is not None]
    pnl = sum(t["pnl_usd"] for t in closed)
    out = {
        "since": SINCE, "balance_usd": own.get("balance_usd"), "balance_sol": own.get("balance_sol"),
        "balance_error": own.get("balance_error"), "trades": len(closed),
        "open": sum(t["open"] for t in trades), "wins": sum(t["pnl_usd"] > 0 for t in closed),
        "pnl_usd": round(pnl, 2),
        "lab_pnl_same_coins_usd": round(sum(
            (t["lab_pct"] or 0) / 100 * (t["stake_usd"] or 0) for t in closed if t["lab_pct"] is not None), 2),
        "trades_list": trades[:100], "as_of": datetime.now(UTC),
    }
    _CACHE = (time.monotonic(), out)
    return out

