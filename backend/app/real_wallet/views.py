"""What a wallet's page shows, in one shape for the main wallet and for every
user wallet (Karthik, 2026-09-30: "user 1 dashboard should be same as real
wallet with open closed trades then daily profit box")."""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.real_wallet_execution import RealWalletLiveIntent, RealWalletPosition
from app.repositories.token import TokenRepository

DUBAI = timedelta(hours=4)


def decimal_str(value: Decimal) -> str:
    return format(value, "f")


def _amount(value: Decimal | None) -> str | None:
    return None if value is None else decimal_str(value)


def open_trade_value(positions, owner: str) -> Decimal:
    """The owner's open trades at what they would sell for now.

    Karthik, 2026-09-29: "if there is open trade, make sure the main balance
    shows including the value of open trade". The exit driver's executable
    multiple, or cost until the first mark; a NULL wallet is the owner's.
    ponytail: ignores a partial sell's banked proceeds; this strategy never
    sells in parts.
    """
    return sum(
        (p.entry_price_usd * p.quantity * (p.last_exec_multiple or Decimal(1))
         for p in positions
         if p.status == "OPEN" and p.wallet_public_key in (None, owner)),
        Decimal(0))


async def positions_payload(session: AsyncSession, positions) -> list[dict[str, Any]]:
    """Every trade as the trades table reads it: token, amounts, results, the
    sell's state while open, and both transactions."""
    exit_states: dict[uuid.UUID, str] = {
        row.id: row.state for row in (await session.execute(
            select(RealWalletLiveIntent.id, RealWalletLiveIntent.state).where(
                RealWalletLiveIntent.id.in_(
                    [p.exit_intent_id for p in positions if p.exit_intent_id])))).all()
    }
    symbols = await TokenRepository(session).get_many_by_mints(
        list({p.mint_address for p in positions}))
    return [
        {
            "id": str(p.id),
            "mint_address": p.mint_address,
            "symbol": symbols[p.mint_address].symbol if p.mint_address in symbols else None,
            "status": p.status,
            "strategy_id": p.strategy_id,
            "quantity": decimal_str(p.quantity),
            "cost_usd": decimal_str(p.entry_price_usd * p.quantity),
            "spent": _amount(p.entry_actual_input_amount),
            "received": _amount(p.exit_actual_output_amount),
            "realised_gross_pnl_usd": _amount(p.realised_gross_pnl_usd),
            "realised_net_pnl_usd": _amount(p.realised_net_pnl_usd),
            "exit_reason": p.exit_reason,
            # What the sell is doing right now, for an open position.
            "exit_state": exit_states.get(p.exit_intent_id) if p.exit_intent_id else None,
            "opened_at": p.opened_at,
            "closed_at": p.closed_at,
            "entry_signature": p.entry_transaction_signature,
            "exit_signature": p.exit_transaction_signature,
        }
        for p in positions
    ]


def since_payload(since: dict[str, Any] | None) -> dict[str, Any] | None:
    """The "since the first trade" card; None until there is a first trade."""
    if since is None:
        return None
    return {
        "first_trade_at": since["first_trade_at"],
        "trades": since["trades"], "won": since["won"], "lost": since["lost"],
        "open": since["open"],
        **{key: None if since[key] is None
           else decimal_str(since[key].quantize(Decimal(places)))
           for key, places in (("net_pnl_usd", "0.0001"),
                               ("traded_usd", "0.01"),
                               ("average_return_pct", "0.01"),
                               ("start_balance_sol", "0.000000001"),
                               ("start_value_usd", "0.01"),
                               ("return_pct", "0.01"))},
    }


def days_payload(positions, now: datetime) -> list[dict[str, Any]]:
    """Closed trades' profit per Dubai calendar day, newest first, today always
    first (dollars only, as on Karthik's Lab). Net where measured, gross else."""
    by_day: dict[str, list[Decimal]] = defaultdict(list)
    for p in positions:
        pnl = p.realised_net_pnl_usd if p.realised_net_pnl_usd is not None \
            else p.realised_gross_pnl_usd
        if p.status == "CLOSED" and p.closed_at is not None and pnl is not None:
            by_day[(p.closed_at + DUBAI).date().isoformat()].append(Decimal(pnl))
    today = (now + DUBAI).date().isoformat()
    by_day.setdefault(today, [])
    return [{"day": day, "running": day == today,
             "pnl_usd": decimal_str(sum(v, Decimal(0)).quantize(Decimal("0.01"))),
             "trades": len(v), "won": sum(1 for x in v if x > 0)}
            for day, v in sorted(by_day.items(), reverse=True)]


async def wallet_results(session: AsyncSession, wallets: list[tuple[str, str]],
                         now: datetime, since: datetime | None = None) -> list[dict[str, Any]]:
    """Each wallet's closed trades side by side (Karthik, 2026-10-01: "show
    each wallet side by side in jupiter"): today (Dubai) and since it began.
    `wallets` is [(label, address)], in the order to show them. Net where
    measured, gross else. With `since`, "all" counts only trades opened from
    then on."""
    if not wallets:
        return []
    pnl = func.coalesce(RealWalletPosition.realised_net_pnl_usd,
                        RealWalletPosition.realised_gross_pnl_usd)
    cost = RealWalletPosition.entry_price_usd * RealWalletPosition.quantity
    start = datetime.combine((now + DUBAI).date(), datetime.min.time(), now.tzinfo) - DUBAI
    today = RealWalletPosition.opened_at >= start
    rows = {r.w: r for r in (await session.execute(
        select(RealWalletPosition.wallet_public_key.label("w"),
               func.count().filter(today).label("t_trades"),
               func.count().filter(today, pnl > 0).label("t_won"),
               func.coalesce(func.sum(pnl).filter(today), 0).label("t_pnl"),
               func.coalesce(func.sum(cost).filter(today), 0).label("t_cost"),
               func.count().label("a_trades"),
               func.coalesce(func.sum(pnl), 0).label("a_pnl"),
               func.coalesce(func.sum(cost), 0).label("a_cost"))
        .where(RealWalletPosition.status == "CLOSED", pnl.is_not(None),
               RealWalletPosition.wallet_public_key.in_([a for _, a in wallets]),
               RealWalletPosition.opened_at >= since if since else true())
        .group_by(RealWalletPosition.wallet_public_key))).all()}

    def pct(made: Decimal, spent: Decimal) -> str | None:
        return None if not spent else decimal_str((Decimal(made) / Decimal(spent) * 100)
                                                  .quantize(Decimal("0.01")))
    out = []
    for label, address in wallets:
        r = rows.get(address)
        out.append({
            "label": label,
            "today_trades": int(r.t_trades) if r else 0,
            "today_won": int(r.t_won) if r else 0,
            "today_pnl_usd": decimal_str(
                Decimal(r.t_pnl if r else 0).quantize(Decimal("0.01"))),
            "today_avg_pct": pct(r.t_pnl, r.t_cost) if r else None,
            "all_trades": int(r.a_trades) if r else 0,
            "all_pnl_usd": decimal_str(Decimal(r.a_pnl if r else 0).quantize(Decimal("0.01"))),
            "all_avg_pct": pct(r.a_pnl, r.a_cost) if r else None,
        })
    return out
