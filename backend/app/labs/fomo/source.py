"""FOMO 24h roster and Solana swap observations from a plain RPC node; both fail closed."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation

import httpx

from app.pumpfun.follower import WSOL, LeaderTrade

FOMO_URL = "https://api.fomoapi.io/v2/leaderboard/24h"
ADDRESS = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")


@dataclass(frozen=True)
class Leader:
    user_id: str
    handle: str
    wallet: str
    rank: int
    pnl_usd: Decimal | None


def parse_roster(payload: object, *, now: datetime) -> list[Leader]:
    """Keep exactly the source's top 20; missing Solana wallets stay absent."""
    if not isinstance(payload, dict) or payload.get("window") != "24h":
        raise ValueError("unexpected leaderboard window")
    captured = payload.get("capturedAt")
    if not isinstance(captured, str):
        raise ValueError("leaderboard capture time missing")
    try:
        captured_at = datetime.fromisoformat(captured.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("invalid leaderboard capture time") from exc
    if (
        captured_at.tzinfo is None
        or captured_at > now + timedelta(minutes=1)
        or now - captured_at > timedelta(hours=2)
    ):
        raise ValueError("leaderboard snapshot is stale")
    rows = payload.get("traders")
    if not isinstance(rows, list) or len(rows) < 20:
        raise ValueError("leaderboard has fewer than 20 rows")
    leaders: list[Leader] = []
    seen: set[str] = set()
    for row in rows[:20]:
        if not isinstance(row, dict):
            continue
        wallets = row.get("wallets")
        wallet = wallets.get("solana") if isinstance(wallets, dict) else None
        user_id = row.get("userId")
        rank = row.get("rank")
        if (
            not isinstance(wallet, str)
            or not ADDRESS.fullmatch(wallet)
            or not isinstance(user_id, str)
            or not user_id
            or user_id in seen
            or not isinstance(rank, int)
            or isinstance(rank, bool)
            or rank < 1
        ):
            continue
        seen.add(user_id)
        try:
            pnl = Decimal(str(row["pnlUsd"])) if row.get("pnlUsd") is not None else None
        except (InvalidOperation, ValueError):
            pnl = None
        if pnl is not None and not pnl.is_finite():
            pnl = None
        leaders.append(Leader(user_id, str(row.get("handle") or user_id), wallet, rank, pnl))
    if not leaders:
        raise ValueError("top 20 have no valid Solana wallets")
    return leaders


async def fetch_roster(client: httpx.AsyncClient, key: str) -> tuple[list[Leader], datetime]:
    if not key:
        raise ValueError("FOMO_API_KEY is not configured")
    response = await client.get(
        FOMO_URL, headers={"Authorization": f"Bearer {key}"}, params={"limit": 20}
    )
    response.raise_for_status()
    payload = response.json()
    leaders = parse_roster(payload, now=datetime.now(UTC))
    captured_at = datetime.fromisoformat(payload["capturedAt"].replace("Z", "+00:00"))
    return leaders, captured_at


#: Below this the SOL leg is only fees and dust, not a payment.
MIN_SOL_LEG_LAMPORTS = 100_000
FIRST_LOOK = timedelta(minutes=10)      # a wallet's first poll reads back no further
PAGE = 100
MAX_READS = 15          # transactions read per wallet per pass; the rest wait
READ_PAUSE_S = 0.2
WALLET_PAUSE_S = 0.5    # one wallet at a time, half a second apart (18 Oct: 429s)


def _token_deltas(meta: dict, wallet: str) -> dict[str, int]:
    """Raw token balance changes owned by `wallet`, by mint (post - pre)."""
    out: dict[str, int] = {}
    for sign, key in ((-1, "preTokenBalances"), (1, "postTokenBalances")):
        for tb in meta.get(key) or []:
            if not isinstance(tb, dict) or tb.get("owner") != wallet or not tb.get("mint"):
                continue
            raw = (tb.get("uiTokenAmount") or {}).get("amount")
            try:
                out[tb["mint"]] = out.get(tb["mint"], 0) + sign * int(raw)
            except (TypeError, ValueError):
                continue
    return {m: a for m, a in out.items() if a}


def parse_transaction(tx: object, wallet: str, signature: str) -> LeaderTrade | None:
    """One raw `getTransaction` (jsonParsed) as this wallet's swap, or None.

    The same reading as the Helius parser (`follower._traded`): the side is the
    sign of the wallet's own largest non-SOL token change. A swap also needs
    value going the other way -- SOL (native, fee added back, or wrapped) or
    another token -- so a plain transfer or airdrop is not read as a trade.
    """
    if not isinstance(tx, dict):
        return None
    meta = tx.get("meta") or {}
    if meta.get("err") is not None or not tx.get("blockTime"):
        return None
    deltas = _token_deltas(meta, wallet)
    wsol = deltas.pop(WSOL, 0)
    if not deltas:
        return None
    mint, amount = max(deltas.items(), key=lambda kv: abs(kv[1]))
    keys = ((tx.get("transaction") or {}).get("message") or {}).get("accountKeys") or []
    addrs = [k.get("pubkey") if isinstance(k, dict) else k for k in keys]
    native = 0
    if wallet in addrs:
        i = addrs.index(wallet)
        pre, post = meta.get("preBalances") or [], meta.get("postBalances") or []
        if i < len(pre) and i < len(post):
            native = post[i] - pre[i] + (int(meta.get("fee") or 0) if i == 0 else 0)
    sol = native + wsol
    paid = (amount > 0 and sol <= -MIN_SOL_LEG_LAMPORTS) or (
        amount < 0 and sol >= MIN_SOL_LEG_LAMPORTS)
    other = any((a < 0) != (amount < 0) for m, a in deltas.items() if m != mint)
    if not (paid or other):
        return None
    return LeaderTrade(
        signature=signature,
        slot=int(tx.get("slot") or 0),
        mint=mint,
        side="buy" if amount > 0 else "sell",
        sol_amount=(round(abs(sol) / 1_000_000_000, 6)
                    if abs(sol) >= MIN_SOL_LEG_LAMPORTS else None),
        at=datetime.fromtimestamp(int(tx["blockTime"]), tz=UTC),
    )


async def _rpc(client: httpx.AsyncClient, url: str, method: str, params: list) -> object:
    for attempt in range(4):
        try:
            response = await client.post(
                url, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
            if response.status_code == 429:
                # The node's own hint when it gives one, else 2, 4, 8, 16 s.
                try:
                    wait = float(response.headers.get("retry-after") or 0)
                except ValueError:
                    wait = 0.0
                await asyncio.sleep(min(max(wait, 2.0 * 2**attempt), 30.0))
                continue
            response.raise_for_status()
            body = response.json()
            if isinstance(body, dict) and "result" in body:
                return body["result"]
        except (httpx.HTTPError, ValueError):
            pass
        await asyncio.sleep(0.5 + attempt)
    raise LookupError(method)


async def fetch_swaps(
    client: httpx.AsyncClient,
    rpc_url: str,
    wallets: list[str],
    cursors: dict[str, str | None],
    *,
    now: datetime,
) -> tuple[list[tuple[str, LeaderTrade]], dict[str, str], dict[str, str]]:
    """Each wallet's swaps since its bookmark, from a plain Solana RPC node.

    Returns (trades oldest first, errors by wallet, new bookmarks). Reads go
    oldest first and a wallet's bookmark moves to the last one read, so a failed
    read, or one past `MAX_READS`, is asked for again next pass (`apply` drops
    what it has already seen).
    A wallet with no bookmark reads back `FIRST_LOOK` only: a newly followed
    trader's older buys could never be copied anyway.
    """
    # Gentle on purpose: the lab's quiet-pool check asks this same node from the
    # same server before every buy, and a throttled node would make it skip.
    semaphore = asyncio.Semaphore(1)

    async def one(wallet: str) -> tuple[str, list[LeaderTrade], str | None, str | None]:
        async with semaphore:
            trades: list[LeaderTrade] = []
            mark = None
            await asyncio.sleep(WALLET_PAUSE_S)
            try:
                opts: dict = {"limit": PAGE}
                if cursors.get(wallet):
                    opts["until"] = cursors[wallet]
                sigs = await _rpc(client, rpc_url, "getSignaturesForAddress", [wallet, opts])
                if not isinstance(sigs, list):
                    raise ValueError("unexpected signatures payload")
                if not cursors.get(wallet):
                    floor = (now - FIRST_LOOK).timestamp()
                    sigs = [x for x in sigs if (x.get("blockTime") or 0) >= floor]
                gap = "history_capped" if len(sigs) >= PAGE and cursors.get(wallet) else None
                reads = 0
                # Oldest first, and the bookmark follows each one read: a failure
                # or the per-pass cap leaves the rest for the next pass.
                for entry in reversed(sigs):
                    if entry.get("err") is None:
                        if reads >= MAX_READS:
                            return wallet, trades, gap, mark
                        reads += 1
                        await asyncio.sleep(READ_PAUSE_S)
                        tx = await _rpc(client, rpc_url, "getTransaction", [
                            entry["signature"],
                            {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 1}])
                        trade = parse_transaction(tx, wallet, entry["signature"])
                        if trade is not None:
                            trades.append(trade)
                    mark = entry["signature"]
                return wallet, trades, gap, mark
            except (LookupError, ValueError, TypeError, KeyError, AttributeError) as exc:
                return wallet, trades, type(exc).__name__, mark

    results = await asyncio.gather(*(one(wallet) for wallet in wallets))
    trades = [(wallet, trade) for wallet, items, _, _ in results for trade in items]
    errors = {wallet: error for wallet, _, error, _ in results if error}
    marks = {wallet: mark for wallet, _, _, mark in results if mark}
    trades.sort(key=lambda pair: (pair[1].at, pair[1].signature, pair[0]))
    return trades, errors, marks
