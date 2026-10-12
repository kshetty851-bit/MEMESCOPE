"""The $10k book's sells rule (Karthik, 2026-10-12): how many times the coin was
sold before the book bought it, read from chain once per position.

A coin in a pool under $100k with fewer than 22 sells by the moment of the buy
is skipped by the page (`pool_lab.too_few_sells`): a bundled launch, everyone
buying and nobody selling. On the book's 5-11 Oct trades it halved the rugs
(13 -> 6) and added about $149; chosen after testing ~360 rules on those days,
so judged forward from 12 Oct.

A sell = a transaction whose signer ends it holding less of the coin than it
started with (bonding curve or pool, before the buy). Reading stops at 22: the
rule only asks "22 or more?".
"""

from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.labs.graduation import pool_lab as pl
from app.labs.graduation.models import GradPaperPosition

logger = get_logger(__name__)

#: Positions read per worker tick, and the time one read may take.
PER_TICK = 6
READ_TIMEOUT_S = 30


def is_sell(tx: dict[str, Any], mint: str) -> bool:
    """Did this transaction's signer end it holding less of `mint`?"""
    keys = ((tx.get("transaction") or {}).get("message") or {}).get("accountKeys") or []
    if not keys:
        return False
    who = keys[0] if isinstance(keys[0], str) else keys[0].get("pubkey")
    meta = tx.get("meta") or {}

    def held(side: str) -> int:
        return sum(int(b["uiTokenAmount"]["amount"]) for b in meta.get(side) or []
                   if b.get("mint") == mint and b.get("owner") == who)

    return held("postTokenBalances") < held("preTokenBalances")


async def count_sells(history: Any, mint: str, at: int, cap: int = pl.MIN_CHAIN_SELLS) -> int:
    """Sells of `mint` up to second `at`, oldest first, stopping at `cap`.
    `history` is `chain.Helius.history` (or a stand-in for tests)."""
    n = 0
    async for tx in history(mint, t_to=at, cap=6000, limit=100):
        if is_sell(tx, mint):
            n += 1
            if n >= cap:
                break
    return n


async def fill(session: AsyncSession, limit: int = PER_TICK) -> int:
    """Read the newest unread $10k positions in pools under the rule's cap.
    An unreadable history is stored as -1 (the page keeps such a coin)."""
    from app.labs.tape import chain

    rows = (await session.execute(
        select(GradPaperPosition.id, GradPaperPosition.mint, GradPaperPosition.opened_at)
        .where(GradPaperPosition.book == pl.TEN_K_BOOK,
               GradPaperPosition.chain_sells_before.is_(None),
               GradPaperPosition.opened_at >= pl.START,
               GradPaperPosition.liq_open_usd >= 10_000,
               GradPaperPosition.liq_open_usd < pl.SELLS_RULE_POOL_CAP)
        .order_by(GradPaperPosition.opened_at.desc()).limit(limit))).all()
    if not rows:
        return 0
    async with chain.Helius(settings.HELIUS_RPC_URL, rps=5, concurrency=5) as h:
        for pid, mint, opened_at in rows:
            try:
                n = await asyncio.wait_for(
                    count_sells(h.history, mint, int(opened_at.timestamp())), READ_TIMEOUT_S)
            except Exception as exc:  # one coin's history must never stop the lab
                logger.warning("ten_k_sells_read_failed", mint=mint, error=str(exc)[:200])
                n = -1
            await session.execute(update(GradPaperPosition)
                                  .where(GradPaperPosition.id == pid)
                                  .values(chain_sells_before=n))
    await session.commit()
    return len(rows)
