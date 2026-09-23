"""Watch the pool factory, resolve each new token, record what it is worth.

RECORDS ONLY. There is no book, no arm and no order path in this package, and
nothing else in the platform reads its tables — so this cannot open a position
however it fails.

WHY A RECORDER AND NOT A LAB
────────────────────────────
The graduation lab's numbers (a $500k pool floor, a five-minute hold, drains
landing in the fifth minute) were all measured on pump.fun. A different chain
has different fees, pool sizes and operators, and porting those thresholds
would be assuming the answer rather than measuring it. So this writes down what
happens and decides nothing.

WHY THE FACTORY AND NOT THE LOCKER
─────────────────────────────────
The first version watched the Pons locker, on the reasonable-looking grounds
that it fired ~13 times per 34 minutes. Switched on, it recorded the same TWO
established tokens over and over — pairs 54 and 66 days old — every five
minutes. Re-locks, not launches. Four minutes of real data killed an
assumption that would otherwise have sat under a whole lab.

The factory is the right signal: `PoolCreated` is a token meeting WETH in a
pool for the first time, which is what graduating means here.

THE PAIR IS PINNED BY THE CHAIN
───────────────────────────────
The event carries the pool address it just created, so the pair is not chosen
at all — it is the one the graduation made. That removes the trap entirely: a
token can have many pairs (one had SEVEN, $1,146 to $157,675 of liquidity),
and picking between them per sample is how an unpinned Solana book fabricated
$2,414 of profit while looking like a price move.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.labs.rhood import config
from app.labs.rhood.models import RhoodLock, RhoodSample

logger = get_logger(__name__)

_SYMBOL = "0x95d89b41"
_NAME = "0x06fdde03"
#: noqa below: ruff reads "token" in a URL template as a credential.
DEX_TOKEN_PAIRS = "https://api.dexscreener.com/token-pairs/v1/{chain}/{token}"  # noqa: S105


def _addr(word: str) -> str:
    """The address in a 32-byte word, lower-cased."""
    return "0x" + word[-40:].lower()


def _dec(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _string(result: str | None) -> str | None:
    """An ABI-encoded string, or a bytes32 one, or nothing.

    Both encodings appear on this chain, and a token that answers neither is
    recorded without a name rather than skipped: what it is worth is the
    measurement, what it is called is decoration.
    """
    if not result or result == "0x":
        return None
    body = result[2:]
    try:
        offset = int(body[:64], 16) * 2
        length = int(body[offset:offset + 64], 16) * 2
        text = bytes.fromhex(body[offset + 64:offset + 64 + length]).decode("utf-8", "ignore")
    except (ValueError, IndexError):
        try:
            text = bytes.fromhex(body).decode("utf-8", "ignore")
        except ValueError:
            return None
    return text.replace("\x00", "").strip() or None


class Rpc:
    """The chain, over JSON-RPC. One client, one place errors can come from."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client
        self._id = 0

    async def call(self, method: str, params: list[Any]) -> Any:
        self._id += 1
        response = await self._client.post(
            config.RPC_URL,
            json={"jsonrpc": "2.0", "id": self._id, "method": method, "params": params},
            timeout=config.HTTP_TIMEOUT_S)
        response.raise_for_status()
        body = response.json()
        if "error" in body:
            raise RuntimeError(f"{method}: {body['error']}")
        return body.get("result")

    async def block_number(self) -> int:
        return int(await self.call("eth_blockNumber", []), 16)

    async def logs(self, from_block: int, to_block: int) -> list[dict[str, Any]]:
        return await self.call("eth_getLogs", [{
            "address": config.FACTORY,
            "topics": [config.POOL_CREATED_TOPIC],
            "fromBlock": hex(from_block), "toBlock": hex(to_block)}]) or []

    async def block_time(self, number: int) -> datetime | None:
        block = await self.call("eth_getBlockByNumber", [hex(number), False])
        if not block:
            return None
        return datetime.fromtimestamp(int(block["timestamp"], 16), tz=UTC)

    async def text(self, address: str, selector: str) -> str | None:
        try:
            return _string(await self.call(
                "eth_call", [{"to": address, "data": selector}, "latest"]))
        except (RuntimeError, httpx.HTTPError):
            return None


async def _pairs(client: httpx.AsyncClient, token: str) -> list[dict[str, Any]]:
    url = DEX_TOKEN_PAIRS.format(chain=config.DEX_CHAIN, token=token)
    try:
        response = await client.get(url, timeout=config.HTTP_TIMEOUT_S)
        response.raise_for_status()
        body = response.json()
    except (httpx.HTTPError, json.JSONDecodeError):
        return []
    return body if isinstance(body, list) else (body.get("pairs") or [])


def _deepest(pairs: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not pairs:
        return None
    return max(pairs, key=lambda p: float((p.get("liquidity") or {}).get("usd") or 0))


def _sample(token: str, pair: dict[str, Any]) -> RhoodSample:
    liquidity = pair.get("liquidity") or {}
    volume = pair.get("volume") or {}
    txns = (pair.get("txns") or {}).get("m5") or {}
    return RhoodSample(
        token=token, pair_address=pair.get("pairAddress"),
        price_usd=_dec(pair.get("priceUsd")), price_native=_dec(pair.get("priceNative")),
        liquidity_usd=_dec(liquidity.get("usd")), fdv=_dec(pair.get("fdv")),
        volume_m5_usd=_dec(volume.get("m5")),
        txns_m5_buys=txns.get("buys"), txns_m5_sells=txns.get("sells"))


async def record(session: AsyncSession) -> dict[str, Any]:
    """One pass: new locks, then a reading for everything still in its window."""
    if not config.ENABLED:
        return {"enabled": False}

    found = new = sampled = 0
    async with httpx.AsyncClient() as client:
        rpc = Rpc(client)
        tip = await rpc.block_number()
        logs = await rpc.logs(max(tip - config.LOOKBACK_BLOCKS, 0), tip)
        found = len(logs)
        times: dict[int, datetime | None] = {}
        for log in logs:
            topics = log.get("topics") or []
            if len(topics) < 3:
                continue
            token0, token1 = _addr(topics[1]), _addr(topics[2])
            # The coin is whichever side is not the quote. A pool of two
            # unknown tokens is not a graduation and is skipped rather than
            # guessed at.
            if token0 == config.WETH:
                token, quote = token1, token0
            elif token1 == config.WETH:
                token, quote = token0, token1
            else:
                continue
            data = (log.get("data") or "0x")[2:]
            # PoolCreated's data is (int24 tickSpacing, address pool).
            pool = _addr(data[64:128]) if len(data) >= 128 else None
            block = int(log["blockNumber"], 16)
            if block not in times:
                times[block] = await rpc.block_time(block)
            pairs = await _pairs(client, token)
            listed = next((p for p in pairs if (p.get("pairAddress") or "").lower() == pool),
                          None)
            row = {
                "block_number": block,
                "block_at": times[block] or datetime.now(UTC),
                "tx_hash": log["transactionHash"],
                "log_index": int(log["logIndex"], 16),
                "token": token,
                "quote": quote,
                "symbol": await rpc.text(token, _SYMBOL),
                "name": await rpc.text(token, _NAME),
                "pairs_seen": len(pairs),
                # The pool the event made, not the deepest one we could find.
                "pair_address": pool,
                # DexScreener may not have indexed a pool this new yet. That is
                # recorded rather than waited for: `priced` false with a pool
                # address says "too new to price", which is itself a finding.
                "priced": listed is not None,
            }
            if listed is not None and listed.get("pairCreatedAt"):
                row["pair_created_at"] = datetime.fromtimestamp(
                    listed["pairCreatedAt"] / 1000, tz=UTC)
            result = await session.execute(
                insert(RhoodLock).values(**row)
                .on_conflict_do_nothing(index_elements=["tx_hash", "log_index"]))
            new += result.rowcount or 0

        # Everything launched inside the window gets one reading, newest first.
        since = datetime.now(UTC) - timedelta(minutes=config.SAMPLE_WINDOW_MINUTES)
        # Not filtered on `priced`: a pool DexScreener had not indexed when it
        # was created is exactly the one worth asking about again a minute
        # later, and dropping it would lose every coin's first minutes.
        watching = (await session.scalars(
            select(RhoodLock).where(RhoodLock.block_at >= since)
            .order_by(RhoodLock.block_at.desc()).limit(config.SAMPLE_PER_PASS))).all()
        for lock in watching:
            pairs = await _pairs(client, lock.token)
            # The PINNED pair, not the deepest one now.
            pair = next((p for p in pairs if p.get("pairAddress") == lock.pair_address), None)
            if pair is None:
                continue
            session.add(_sample(lock.token, pair))
            sampled += 1

    await session.commit()
    logger.info("rhood_recorded", locks_seen=found, locks_new=new, sampled=sampled)
    return {"enabled": True, "locks_seen": found, "locks_new": new, "sampled": sampled}
