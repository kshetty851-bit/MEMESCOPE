"""USER 1's real trades beside the Pump Catcher Lab (Karthik, 2026-10-27: "bring
user 1 trades to lab with balance, so i can check from mobile or other laptop").

Read only, behind the site's sign-in like every lab page: the balance read from
chain, and each trade since USER 1 started following the lab, beside the lab's
own result for the same coin. No address, no switch, no withdrawal here; those
stay in the device-locked JUPITER box on /real-wallet.
"""

from __future__ import annotations

import statistics
import time
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter
from sqlalchemy import text

from app.api.deps import DbSession

router = APIRouter(prefix="/labs/graduation/karthik/pump-catcher/user1", tags=["graduation-lab"])

#: USER 1 switched to the Pump Catcher's coins (G-PUMP) at 20:00 Dubai, 26 Oct.
SINCE = datetime(2026, 10, 26, 16, tzinfo=UTC)
#: Restarted at $2 after the lab's honest re-pricing (Karthik, 2026-10-27).
RESTART = datetime(2026, 10, 27, 19, 3, tzinfo=UTC)
#: The lab's rules were chosen on 24 Oct (Dubai); later days are new to them.
RULES_SET = datetime(2026, 10, 23, 20, tzinfo=UTC)
#: Ready-check (Karthik, 2026-10-28: "yes add the ready-check panel"): what the
#: data should show before more money goes in. Thresholds are fixed here so the
#: panel cannot move its own goalposts.
READY_TRADES, READY_GAP_PTS, READY_DAYS = 100, -1.0, 14
READY_MID_STAKE, READY_MID_TRADES = 15.0, 30
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
    book = (await grad_api.pump_catcher_book_cached(session))["trades_list"]
    lab = {t["mint"]: t for t in book}
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
        "ready": ready(trades, book, datetime.now(UTC)),
    }
    _CACHE = (time.monotonic(), out)
    return out



def ready(trades: list[dict[str, Any]], book: list[dict[str, Any]], now: datetime) -> list[dict[str, Any]]:
    """The ready-check: three tests, each met or not, with how far along it is.
    Data only; whether to add money stays Karthik's call."""
    def gap(xs: list[dict[str, Any]]) -> float | None:
        g = [t["pct"] - t["lab_pct"] for t in xs if t["pct"] is not None and t["lab_pct"] is not None]
        return round(statistics.median(g), 2) if g else None

    real = [t for t in trades if t["pnl_usd"] is not None and t["opened_at"] >= RESTART]
    mid = [t for t in real if (t["stake_usd"] or 0) >= READY_MID_STAKE]
    g_all, g_mid = gap(real), gap(mid)
    days = (now - RESTART).total_seconds() / 86400
    lab_new = sum(float(t["pnl_usd"]) for t in book if t["opened_at"] >= RESTART)
    lab_fwd = sum(float(t["pnl_usd"]) for t in book if t["opened_at"] >= RULES_SET)

    def usd(x: float) -> str:
        return f"{'+' if x >= 0 else '-'}${abs(x):,.0f}"
    return [
        {"title": f"{READY_TRADES}+ real trades, close to the lab",
         "met": len(real) >= READY_TRADES and g_all is not None and g_all >= READY_GAP_PTS,
         "now": f"{len(real)} of {READY_TRADES} trades; USER 1 vs lab "
                + (f"{g_all:+.1f} points a trade (median)" if g_all is not None else "not measured yet")},
        {"title": f"Lab still in profit on new days, {READY_DAYS}+ days",
         "met": days >= READY_DAYS and lab_new > 0,
         "now": f"day {days:.0f} of {READY_DAYS}; lab {usd(lab_new)} since USER 1 restarted "
                f"({usd(lab_fwd)} since its rules were set on 24 Oct)"},
        {"title": f"Bigger real trades (${READY_MID_STAKE:.0f}+) still match",
         "met": len(mid) >= READY_MID_TRADES and g_mid is not None and g_mid >= READY_GAP_PTS,
         "now": f"{len(mid)} of {READY_MID_TRADES} trades at ${READY_MID_STAKE:.0f}+"
                + (f"; {g_mid:+.1f} points vs lab" if g_mid is not None else "; USER 1 trades $2 now")},
    ]
