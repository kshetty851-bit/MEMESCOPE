"""Fresh Catch on-chain trial: buys vs sells in a new pool's first seconds, from
Helius (Karthik, 2026-10-27: "yes do both"). One week of RECORDING only.

Fresh Catch needs "65%+ of trades are buys", which only DexScreener gives, ~50 s
after graduation. The first-minute recorder sees the pool in ~2-5 s; this reads
the pool's own swaps once, ~1 minute after graduation, and counts what had
happened by 10, 20 and 30 s (by block time), so a rule deciding at 10 s can be
tested later against the same coins. Only pools of $10k-$30k at 10 s (the lab's
band), one Helius call each (~500 a day). Nothing here buys anything.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import text

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

KEY = "freshcatch:helius:v1"
WINDOWS_S = (10, 20, 30)
POOL = (10_000, 30_000)
#: Ended early (Karthik, 2026-10-31: "change the due date, and proceed now to
#: analyze"): 1,463 pools by then; every 10 s buy-share rule lost after costs.
STOP_AT = datetime(2026, 10, 31, 14, tzinfo=UTC)       # 31 Oct 18:00 Dubai

#: Each new pool's readings in its first 10 s; the last one is its size at 10 s.
_DUE = text("""
    select mint, pool, migrated_at, quote_reserve from grad_first_minute
    where migrated_at between :a and :b and sol_quoted
      and ts <= migrated_at + interval '10 seconds'
    order by mint, ts""")
_SOL = text("""
    select price_usd / price_native from grad_postgrad_samples
    where source = 'dexscreener' and price_native > 0
      and price_usd / price_native between 50 and 1000
    order by ts desc limit 1""")


def swaps(txs: list[dict[str, Any]], mint: str) -> list[tuple[int, str, float]]:
    """(block time, "buy"/"sell", SOL) per landed swap, by the fee payer's own
    balances: tokens up and SOL down is a buy, tokens down and SOL up a sell."""
    out = []
    for tx in txs:
        meta = tx.get("meta") or {}
        if meta.get("err") or not tx.get("blockTime"):
            continue
        keys = ((tx.get("transaction") or {}).get("message") or {}).get("accountKeys") or []
        if not keys:
            continue
        payer = keys[0] if isinstance(keys[0], str) else keys[0].get("pubkey")
        sol = (meta["preBalances"][0] - meta["postBalances"][0]) / 1e9

        def held(bals: Any) -> float:
            return sum(float(b["uiTokenAmount"]["uiAmount"] or 0) for b in bals or []
                       if b.get("mint") == mint and b.get("owner") == payer)
        tokens = held(meta.get("postTokenBalances")) - held(meta.get("preTokenBalances"))
        if tokens > 0 and sol > 0.001:
            out.append((tx["blockTime"], "buy", sol))
        elif tokens < 0 and sol < -0.001:
            out.append((tx["blockTime"], "sell", -sol))
    return out


def counts(found: list[tuple[int, str, float]], graduated: datetime) -> dict[str, list[float]]:
    """Per window: [buys, sells, SOL bought, SOL sold] by `graduated` + window."""
    start = graduated.timestamp()
    out = {}
    for w in WINDOWS_S:
        inside = [f for f in found if f[0] <= start + w]
        out[str(w)] = [sum(f[1] == "buy" for f in inside), sum(f[1] == "sell" for f in inside),
                       round(sum(f[2] for f in inside if f[1] == "buy"), 3),
                       round(sum(f[2] for f in inside if f[1] == "sell"), 3)]
    return out


async def refresh(session, redis, now: datetime | None = None) -> dict[str, int]:
    now = now or datetime.now(UTC)
    if now >= STOP_AT or not settings.helius_configured:
        return {"skipped": 1}
    sol = float(await session.scalar(_SOL) or 0)
    last: dict[str, tuple[str, datetime, Any]] = {}
    for mint, pool, graduated, quote in (await session.execute(
            _DUE, {"a": now - timedelta(minutes=10), "b": now - timedelta(seconds=45)})).all():
        last[mint] = (pool, graduated, quote)
    rows = [(m, *v) for m, v in last.items()]
    done = {k.decode() if isinstance(k, bytes) else k for k in await redis.hkeys(KEY)}
    read = 0
    async with httpx.AsyncClient(timeout=20) as client:
        for mint, pool, graduated, q10 in rows:
            if mint in done or q10 is None or not sol:
                continue
            pool_usd = 2 * float(q10) * sol
            rec: dict[str, Any] = {"pool_usd": round(pool_usd), "graduated_at": graduated.isoformat()}
            if POOL[0] <= pool_usd < POOL[1]:
                try:
                    got = (await client.post(settings.HELIUS_RPC_URL, json={
                        "jsonrpc": "2.0", "id": 1, "method": "getTransactionsForAddress",
                        "params": [pool, {"transactionDetails": "full", "sortOrder": "asc",
                                          "limit": 100, "encoding": "json",
                                          "maxSupportedTransactionVersion": 1}]})).json()
                    txs = got["result"]["data"]
                except Exception:   # never logged: the URL carries the key
                    continue        # asked again next minute
                rec["windows"] = counts(swaps(txs, mint), graduated)
                rec["txs"] = len(txs)
                # One call (the free plan's budget): the first 100 transactions.
                # A busy pool reaches 100 inside its first seconds, so its later
                # windows stop growing; the buy share of those 100 still stands.
                rec["capped"] = len(txs) >= 100
                read += 1
            await redis.hset(KEY, mint, json.dumps(rec))
    return {"read": read, "seen": len(rows)}
