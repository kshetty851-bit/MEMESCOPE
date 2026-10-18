"""FOMO 24h roster and Helius swap observations; both fail closed."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation

import httpx

from app.pumpfun.follower import LeaderTrade, _is_swap, _leader_sol, _traded

FOMO_URL = "https://api.fomoapi.io/v2/leaderboard/24h"
HELIUS_URL = "https://api.helius.xyz/v0/addresses"
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


def parse_swaps(payload: object, wallet: str) -> list[LeaderTrade]:
    if not isinstance(payload, list):
        raise ValueError("unexpected Helius swap payload")
    trades: list[LeaderTrade] = []
    for tx in payload:
        if not isinstance(tx, dict) or not _is_swap(tx):
            continue
        traded = _traded(tx, wallet)
        signature, ts = tx.get("signature"), tx.get("timestamp")
        if traded is None or not isinstance(signature, str) or not ts:
            continue
        mint, side = traded
        trades.append(
            LeaderTrade(
                signature=signature,
                slot=int(tx.get("slot") or 0),
                mint=mint,
                side=side,
                sol_amount=_leader_sol(tx, wallet),
                at=datetime.fromtimestamp(int(ts), tz=UTC),
            )
        )
    return trades


async def fetch_swaps(
    client: httpx.AsyncClient,
    key: str,
    wallets: list[str],
) -> tuple[list[tuple[str, LeaderTrade]], dict[str, str]]:
    """One bounded request per wallet; a failed wallet cannot erase its history."""
    if not key:
        raise ValueError("HELIUS_API_KEY is not configured")
    semaphore = asyncio.Semaphore(5)

    async def one(wallet: str) -> tuple[str, list[LeaderTrade], str | None]:
        async with semaphore:
            try:
                response = await client.get(
                    f"{HELIUS_URL}/{wallet}/transactions",
                    params={"api-key": key, "limit": 100, "type": "SWAP"},
                )
                response.raise_for_status()
                payload = response.json()
                trades = parse_swaps(payload, wallet)
                # Helius caps this read at 100. A saturated page may have
                # hidden swaps older than the last row, so expose the gap.
                return wallet, trades, "history_capped" if len(payload) >= 100 else None
            except (
                httpx.HTTPError,
                ValueError,
                TypeError,
                AttributeError,
                KeyError,
                OverflowError,
            ) as exc:
                return wallet, [], type(exc).__name__

    results = await asyncio.gather(*(one(wallet) for wallet in wallets))
    trades = [(wallet, trade) for wallet, items, _ in results for trade in items]
    errors = {wallet: error for wallet, _, error in results if error}
    trades.sort(key=lambda pair: (pair[1].at, pair[1].signature, pair[0]))
    return trades, errors
