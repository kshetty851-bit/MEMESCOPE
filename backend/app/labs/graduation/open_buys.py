"""Was a coin's pool bought when it opened? (Karthik, 2026-10-17.)

Read from Helius first (one getTransactionsForAddress call, oldest first; the
free node could not read about half the pools, Rockstar among them, 18 Oct),
then the public Solana node: the pool's oldest signatures, then the
transactions of its first `OPEN_WINDOW_S`, oldest first, stopping at the first
fee payer who spent more than `MIN_BUY_SOL`. In 98% of coins that buy lands at
second 0, so the answer is known before the book's 19-46 s entry.
"""
from __future__ import annotations

import asyncio
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.labs.graduation.models import GradOpenBuy, GradPaperPosition
from app.labs.graduation.sources import PUBLIC_RPC_URL

logger = get_logger(__name__)

BOOKS = ("KARTHIK_QUIET_5M", "KARTHIK_Q50_5M")
OPEN_WINDOW_S = 60
MIN_BUY_SOL = Decimal("0.5")
MAX_TXS = 30
SIG_PAGES = 3          # a young pool has one page; an old one is left unread
PER_PASS = 15
LOOKBACK = timedelta(hours=6)


def biggest_open_spend(txs: Sequence[dict[str, Any] | None], t0: int) -> Decimal:
    """Largest fee-payer SOL spend among `txs` inside the open window; 0 for none
    over `MIN_BUY_SOL`. A missing transaction is skipped, never a buy."""
    best = Decimal(0)
    for tx in txs:
        if not isinstance(tx, dict) or (tx.get("blockTime") or 0) > t0 + OPEN_WINDOW_S:
            continue
        meta = tx.get("meta") or {}
        pre, post = meta.get("preBalances") or [0], meta.get("postBalances") or [0]
        spent = Decimal(pre[0] - post[0]) / Decimal(1_000_000_000)
        if spent > MIN_BUY_SOL:
            best = max(best, spent)
    return best


def no_buy_at_open(row: GradOpenBuy | None) -> bool:
    """Skip only a read pool with no buy: unread or unchecked is bought."""
    return row is not None and row.read and (row.open_buy_sol or 0) <= MIN_BUY_SOL


async def _rpc(client: httpx.AsyncClient, method: str, params: list[Any]) -> Any:
    for attempt in range(3):
        try:
            got = (await client.post(PUBLIC_RPC_URL, json={
                "jsonrpc": "2.0", "id": 1, "method": method, "params": params})).json()
            if isinstance(got, dict) and "result" in got:
                return got["result"]
        except (httpx.HTTPError, ValueError):
            pass
        await asyncio.sleep(1 + attempt)
    raise LookupError(method)


HELIUS_TXS = 50


async def _read_helius(client: httpx.AsyncClient, pool: str) -> Decimal | None:
    """The pool's first `HELIUS_TXS` landed transactions in one call, or None."""
    if not settings.helius_configured:
        return None
    try:
        got = (await client.post(settings.HELIUS_RPC_URL, json={
            "jsonrpc": "2.0", "id": 1, "method": "getTransactionsForAddress",
            "params": [pool, {"transactionDetails": "full", "sortOrder": "asc",
                              "limit": HELIUS_TXS, "encoding": "json",
                              "maxSupportedTransactionVersion": 1}]})).json()
        txs = [t for t in got["result"]["data"] if not (t.get("meta") or {}).get("err")]
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        return None       # never logged: the URL carries the key
    if not txs:
        return None
    return biggest_open_spend(txs, txs[0].get("blockTime") or 0)


async def read_pool(client: httpx.AsyncClient, pool: str) -> Decimal | None:
    """The biggest open spend on `pool`, or None when it cannot be read."""
    spent = await _read_helius(client, pool)
    if spent is not None:
        return spent
    try:
        before, page = None, []
        for _ in range(SIG_PAGES):
            opts: dict[str, Any] = {"limit": 1000}
            if before:
                opts["before"] = before
            got = await _rpc(client, "getSignaturesForAddress", [pool, opts])
            if got:
                page, before = got, got[-1]["signature"]
            if len(got) < 1000:
                break
        else:
            return None
        ok = [s for s in reversed(page) if s.get("err") is None][:MAX_TXS]
        if not ok:
            return None
        t0 = ok[0].get("blockTime") or 0
        missed = False
        for s in ok:
            if (s.get("blockTime") or 0) > t0 + OPEN_WINDOW_S:
                break
            try:
                tx = await _rpc(client, "getTransaction", [s["signature"], {
                    "encoding": "json", "maxSupportedTransactionVersion": 1}])
            except LookupError:
                missed = True     # one unread transaction must not end the read
                continue
            if isinstance(tx, dict):
                tx.setdefault("blockTime", s.get("blockTime"))
            else:
                missed = True
            spent = biggest_open_spend([tx], t0)
            if spent:
                return spent      # one buy over the floor answers the question
        # "No buy" only when every transaction of the window was read.
        return None if missed else Decimal(0)
    except LookupError:
        return None


async def open_buys_pass(session: AsyncSession, *, now: datetime) -> dict[str, Any]:
    """Check the newest unchecked Karthik Lab coins, at most `PER_PASS`."""
    from app.labs.graduation.tournament import graduation_pool

    todo = (await session.scalars(
        select(GradPaperPosition.mint).where(
            GradPaperPosition.book.in_(BOOKS),
            GradPaperPosition.opened_at >= now - LOOKBACK,
            # The pool's first minute must be over, so a late open buy is seen.
            GradPaperPosition.opened_at <= now - timedelta(seconds=OPEN_WINDOW_S),
            GradPaperPosition.mint.not_in(select(GradOpenBuy.mint)))
        .distinct().limit(PER_PASS))).all()
    read = 0
    async with httpx.AsyncClient(timeout=15) as client:
        for mint in todo:
            pool = graduation_pool(mint)
            spent = await read_pool(client, pool) if pool else None
            session.add(GradOpenBuy(mint=mint, read=spent is not None, open_buy_sol=spent,
                                    checked_at=datetime.now(UTC)))
            read += spent is not None
    await session.commit()
    logger.info("graduation_open_buys_read", read=read, of=len(todo))
    return {"read": read, "of": len(todo)}


#: The real wallet's answers, per mint, for this process: a coin is judged once.
_AT_BUY: dict[str, bool | None] = {}
AT_BUY_TIMEOUT_S = 6


async def bought_at_open(mint: str) -> bool | None:
    """For a real-wallet buy: has anyone spent > `MIN_BUY_SOL` on this coin's
    pool since it opened? True/False, or None when the chain cannot answer in
    `AT_BUY_TIMEOUT_S` (then the coin is bought, as the lab keeps unread coins).
    The opening buy lands at second 0 in 98% of coins, so at the wallet's
    19-46 s entry it has normally happened already."""
    from app.labs.graduation.tournament import graduation_pool

    if mint in _AT_BUY:
        return _AT_BUY[mint]
    pool = graduation_pool(mint)
    if not pool:
        return None
    try:
        async with httpx.AsyncClient(timeout=4) as client:
            spent = await asyncio.wait_for(read_pool(client, pool), AT_BUY_TIMEOUT_S)
    except TimeoutError:
        spent = None
    answer = None if spent is None else spent > MIN_BUY_SOL
    if answer is not None:
        if len(_AT_BUY) > 5000:
            _AT_BUY.clear()
        _AT_BUY[mint] = answer
    return answer
