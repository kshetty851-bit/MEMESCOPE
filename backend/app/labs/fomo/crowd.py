"""FOMO Crowd book (Karthik, 2026-10-20): fresh pump.fun graduations fomo piles into.

fomo.family's graduated list shows coins after their move. This book asks the
forward question instead: when a SECOND different fomo trader buys a coin
within `GRAD_WINDOW` of it graduating, does buying then and selling `HOLD`
later pay? The feed is FOMO API's app stream (`/ws/alerts`), which carries only
large trades (about $3k+ positions), so "the crowd" is fomo's bigger traders.

Every Solana buy of a fresh graduation is kept as a `FomoSignal`, opened or
not, so the coins fomo bought can later be set against every graduation's
outcome. Same ledger, prices and fills as the FOMO Lab's other books.
"""

from __future__ import annotations

import asyncio
import json
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select

from app.lab import execution
from app.labs.fomo.models import FomoBook, FomoPosition, FomoSignal
from app.labs.fomo.service import MAX_SIGNAL_AGE_SECONDS, STARTING_USD, FomoService
from app.labs.fomo.source import FOMO_URL
from app.pumpfun.follower import LeaderTrade

KIND = "crowd"
CROWD_MIN = 2                       # the second different trader's buy opens
GRAD_WINDOW = timedelta(minutes=30)
HOLD = timedelta(minutes=5)         # Karthik Lab's own exit
WS_URL = FOMO_URL.replace("https://", "wss://").split("/v2/")[0] + "/ws/alerts"
LISTEN_SECONDS = 90


async def read_alerts(key: str, seconds: float = LISTEN_SECONDS) -> list[dict[str, Any]]:
    """Solana buy/sell alerts heard in `seconds`, the connect-time replay included.
    The stream is not metered in credits; only REST calls are."""
    import websockets

    out: list[dict[str, Any]] = []
    loop = asyncio.get_running_loop()
    end = loop.time() + seconds
    async with websockets.connect(WS_URL, additional_headers={"authorization": f"Bearer {key}"},
                                  open_timeout=20) as ws:
        while (left := end - loop.time()) > 0:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=left)
            except TimeoutError:
                break
            try:
                m = json.loads(raw)
            except ValueError:
                continue
            if (m.get("type") == "alert" and m.get("chain") == "solana"
                    and m.get("alertType") in ("buy", "sell")
                    and m.get("tokenAddress") and m.get("eventId") and m.get("ts")):
                out.append(m)
    return out


async def book(service: FomoService, now: datetime) -> FomoBook:
    b = await service.book(KIND)
    if b is None:
        b = FomoBook(started_at=now, kind=KIND, cash_usd=STARTING_USD)
        service.session.add(b)
        await service.session.flush()
    return b


async def _graduated_at(service: FomoService, mint: str) -> datetime | None:
    from app.labs.graduation.models import GradMigration

    return await service.session.scalar(
        select(func.max(GradMigration.ts)).where(GradMigration.mint == mint))


async def apply(service: FomoService, b: FomoBook, alerts: list[dict[str, Any]],
                now: datetime) -> Counter[str]:
    """Record each fresh-graduation buy once; the second trader's buy opens a lot."""
    counts: Counter[str] = Counter()
    s = service.session
    for a in sorted(alerts, key=lambda a: a["ts"]):
        if a["alertType"] != "buy":
            continue
        mint, who = a["tokenAddress"], str(a.get("userId") or a.get("trader"))
        at = datetime.fromtimestamp(a["ts"] / 1000, tz=UTC)
        grad = await _graduated_at(service, mint)
        if grad is None or not grad <= at <= grad + GRAD_WINDOW:
            counts["not_fresh_graduation"] += 1         # most of the feed: not stored
            continue
        if await s.scalar(select(FomoSignal.id).where(
                FomoSignal.book_id == b.id, FomoSignal.signature == a["eventId"],
                FomoSignal.mint == mint).limit(1)):
            continue                                    # the replay repeats recent alerts
        buyers = set((await s.execute(select(FomoSignal.leader_wallet).where(
            FomoSignal.book_id == b.id, FomoSignal.mint == mint, FomoSignal.side == "buy",
            FomoSignal.traded_at >= grad))).scalars().all())
        pos = None
        if (now - at).total_seconds() > MAX_SIGNAL_AGE_SECONDS:
            outcome = "stale_signal"
        elif who in buyers:
            outcome = "same_trader_again"
        elif len(buyers) + 1 < CROWD_MIN:
            outcome = "first_buyer"
        else:
            outcome, pos = await service._open(
                b, who, LeaderTrade(signature=a["eventId"], slot=0, mint=mint, side="buy",
                                    sol_amount=None, at=at), now)
        s.add(FomoSignal(book_id=b.id, leader_wallet=who[:64], signature=a["eventId"][:96],
                         mint=mint, side="buy", traded_at=at, seen_at=now, outcome=outcome,
                         position_id=pos.id if pos else None))
        await s.flush()
        counts[outcome] += 1
    return counts


async def close_due(service: FomoService, b: FomoBook, now: datetime) -> int:
    """Sell every lot held `HOLD` or longer at the price now; an unpriced one waits."""
    due = (await service.session.execute(select(FomoPosition).where(
        FomoPosition.book_id == b.id, FomoPosition.status == "open",
        FomoPosition.opened_at <= now - HOLD))).scalars().all()
    closed = 0
    for pos in due:
        snap = await service.price(pos.mint, now)
        if snap is None:
            snap, _ = await service.quote_now(LeaderTrade(
                signature=pos.buy_signature, slot=0, mint=pos.mint, side="sell",
                sol_amount=None, at=now), now)
        if snap is None:
            continue
        proceeds = execution.sell_proceeds(pos.quantity, snap.price_usd, snap.liquidity_usd)
        pos.status, pos.closed_at = "closed", now
        pos.exit_price_usd, pos.proceeds_usd = snap.price_usd, proceeds
        pos.last_value_usd, pos.last_mark_at = proceeds, now
        b.cash_usd += proceeds
        await service.session.flush()
        closed += 1
    return closed
