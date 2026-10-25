"""Read-only, exact-pool identity checks for Pool Sprint. Symbols prove nothing."""

from __future__ import annotations

import asyncio
import base64
from functools import lru_cache

import httpx

from app.labs.graduation import config
from app.security.liquidity import PUMPSWAP_PROGRAM, WSOL_MINT, derive_or_none, parse_pool


@lru_cache(maxsize=50000)
def canonical_sol(mint: str, pair: str) -> bool:
    derived = derive_or_none(mint, pumpfun_program=config.PUMP_PROGRAM_ID)
    return bool(derived and derived[0] == pair)


def account_identity(account: object) -> tuple[str, str, str] | None:
    if not isinstance(account, dict) or account.get("owner") != PUMPSWAP_PROGRAM:
        return None
    try:
        pool = parse_pool(base64.b64decode(account["data"][0], validate=True))
    except (KeyError, TypeError, ValueError, IndexError):
        return None
    return (pool.base_mint, pool.quote_mint, "pumpswap_account") if pool else None


async def verify_pairs(pairs: dict[str, str]) -> dict[str, tuple[str, str, str]]:
    """Return pair -> (base mint, quote mint, evidence). Unknown stays absent.

    Pool mint addresses are immutable identities. Current reserves and prices
    never determine historical admission. No database, cache or wallet writes.
    """
    out = {}
    for pair, mint in pairs.items():
        if await asyncio.to_thread(canonical_sol, mint, pair):
            out[pair] = (mint, WSOL_MINT, "canonical_sol_pda")
    pending = [p for p in pairs if p not in out]
    async with httpx.AsyncClient(timeout=20) as client:
        for start in range(0, len(pending), 100):
            batch = pending[start : start + 100]
            try:
                response = await client.post(
                    config.rpc_url(),
                    json={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "getMultipleAccounts",
                        "params": [batch, {"encoding": "base64", "commitment": "confirmed"}],
                    },
                )
                response.raise_for_status()
                values = response.json()["result"]["value"]
                if len(values) != len(batch):
                    continue
                for pair, account in zip(batch, values, strict=True):
                    if identity := account_identity(account):
                        out[pair] = identity
            except Exception:  # noqa: S110
                # Never expose a keyed RPC URL or provider response in logs.
                pass
        pending = [p for p in pending if p not in out]
        for start in range(0, len(pending), 30):
            batch = pending[start : start + 30]
            try:
                response = await client.get(
                    "https://api.dexscreener.com/latest/dex/pairs/solana/" + ",".join(batch)
                )
                response.raise_for_status()
                for row in response.json().get("pairs") or []:
                    pair = row.get("pairAddress")
                    base = (row.get("baseToken") or {}).get("address")
                    quote = (row.get("quoteToken") or {}).get("address")
                    if row.get("chainId") == "solana" and pair in batch and base and quote:
                        out[pair] = (base, quote, "dexscreener_exact_pool")
            except Exception:  # noqa: S110
                # Verification failure is exposed as an unverified pool count.
                pass
            if start + 30 < len(pending):
                await asyncio.sleep(0.25)
    return out
