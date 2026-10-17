"""Market, security, Bitcoin-network and meme data from free public APIs.

Each reader returns plain JSON-able data or raises; the refresher records which
source failed and when it last answered, and the page says so. Nothing here is
estimated or filled in when a source is down.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx

UA = {"User-Agent": "MEMESCOPE-newsroom/1.0 (+https://www.memescope.site)"}
CG = "https://api.coingecko.com/api/v3"


async def _get(client: httpx.AsyncClient, url: str, **params: Any) -> Any:
    r = await client.get(
        url, params=params or None, headers=UA, timeout=20, follow_redirects=True
    )
    r.raise_for_status()
    return r.json()


async def market(client: httpx.AsyncClient) -> dict[str, Any]:
    g = (await _get(client, f"{CG}/global"))["data"]
    coins = await _get(
        client,
        f"{CG}/coins/markets",
        vs_currency="usd",
        order="market_cap_desc",
        per_page=100,
        page=1,
        sparkline="true",
        price_change_percentage="1h,24h,7d",
    )
    slim = [
        {
            "id": c["id"],
            "symbol": c["symbol"].upper(),
            "name": c["name"],
            "image": c.get("image"),
            "price": c.get("current_price"),
            "mcap": c.get("market_cap"),
            "volume": c.get("total_volume"),
            "ch1h": c.get("price_change_percentage_1h_in_currency"),
            "ch24h": c.get("price_change_percentage_24h_in_currency"),
            "ch7d": c.get("price_change_percentage_7d_in_currency"),
            # 7-day hourly closes thinned to 42 points: enough for a sparkline.
            "spark": [
                round(p, 8) for p in (c.get("sparkline_in_7d") or {}).get("price", [])[::4]
            ],
        }
        for c in coins
    ]
    return {
        "total_mcap": g["total_market_cap"].get("usd"),
        # CoinGecko's global volume counts wash-traded venues (it read $189T on
        # 2026-10-17); the top 100 coins' own 24h volumes are the honest figure.
        "top100_volume": sum(c.get("total_volume") or 0 for c in coins),
        "mcap_change_24h": g.get("market_cap_change_percentage_24h_usd"),
        "btc_dominance": g["market_cap_percentage"].get("btc"),
        "eth_dominance": g["market_cap_percentage"].get("eth"),
        "active_coins": g.get("active_cryptocurrencies"),
        "coins": slim,
    }


async def narratives(client: httpx.AsyncClient) -> list[dict[str, Any]]:
    """CoinGecko's sectors, ranked by size; the page measures 'attention' as each
    sector's 24h market-cap change and says so."""
    cats = await _get(client, f"{CG}/coins/categories")
    big = [
        c
        for c in cats
        if (c.get("market_cap") or 0) >= 300_000_000
        and c.get("market_cap_change_24h") is not None
    ]
    big.sort(key=lambda c: c["market_cap"], reverse=True)
    return [
        {
            "id": c["id"],
            "name": c["name"],
            "mcap": c["market_cap"],
            "change_24h": c["market_cap_change_24h"],
            "volume": c.get("volume_24h"),
        }
        for c in big[:40]
    ]


async def fear_greed(client: httpx.AsyncClient) -> dict[str, Any]:
    d = (await _get(client, "https://api.alternative.me/fng/", limit=2))["data"]
    return {
        "value": int(d[0]["value"]),
        "label": d[0]["value_classification"],
        "yesterday": int(d[1]["value"]) if len(d) > 1 else None,
    }


async def hacks(client: httpx.AsyncClient) -> list[dict[str, Any]]:
    """DeFiLlama's hack log: the newest incidents, with what was taken."""
    rows = await _get(client, "https://api.llama.fi/hacks")
    rows = sorted(rows, key=lambda r: r.get("date") or 0, reverse=True)[:12]
    return [
        {
            "name": r.get("name"),
            "date": datetime.fromtimestamp(r["date"], UTC).isoformat(),
            "amount_usd": r.get("amount"),
            "chains": r.get("chain") or [],
            "technique": r.get("technique") or r.get("classification"),
            "source": r.get("source"),
        }
        for r in rows
        if r.get("date")
    ]


async def bitcoin_network(client: httpx.AsyncClient) -> dict[str, Any]:
    adj = await _get(client, "https://mempool.space/api/v1/difficulty-adjustment")
    r = await client.get("https://mempool.space/api/blocks/tip/height", headers=UA, timeout=20)
    r.raise_for_status()
    height = int(r.text)
    next_halving = (height // 210_000 + 1) * 210_000
    return {
        "height": height,
        "difficulty_change_pct": adj.get("difficultyChange"),
        "difficulty_at": datetime.fromtimestamp(
            adj["estimatedRetargetDate"] / 1000, UTC
        ).isoformat(),
        "difficulty_blocks_left": adj.get("remainingBlocks"),
        "halving_height": next_halving,
        "halving_blocks_left": next_halving - height,
        # Ten minutes a block is the protocol's target, so this is an estimate and labelled one.
        "halving_estimate": datetime.fromtimestamp(
            datetime.now(UTC).timestamp() + (next_halving - height) * 600, UTC
        ).isoformat(),
    }


async def boosted_memes(client: httpx.AsyncClient) -> list[dict[str, Any]]:
    """DexScreener's most-boosted tokens with their pools' real numbers."""
    top = await _get(client, "https://api.dexscreener.com/token-boosts/top/v1")
    top = [t for t in top if t.get("chainId") and t.get("tokenAddress")][:24]
    by_chain: dict[str, list[str]] = {}
    for t in top:
        by_chain.setdefault(t["chainId"], []).append(t["tokenAddress"])
    pairs: dict[str, dict[str, Any]] = {}
    for chain, addrs in by_chain.items():
        got = await _get(
            client, f"https://api.dexscreener.com/tokens/v1/{chain}/{','.join(addrs[:30])}"
        )
        for p in got if isinstance(got, list) else []:
            a = (p.get("baseToken") or {}).get("address")
            if a and ((p.get("liquidity") or {}).get("usd") or 0) > (
                pairs.get(a, {}).get("liquidity") or 0
            ):
                pairs[a] = {
                    "liquidity": (p.get("liquidity") or {}).get("usd"),
                    "volume24h": (p.get("volume") or {}).get("h24"),
                    "change24h": (p.get("priceChange") or {}).get("h24"),
                    "fdv": p.get("fdv"),
                    "created": p.get("pairCreatedAt"),
                    "symbol": (p.get("baseToken") or {}).get("symbol"),
                    "name": (p.get("baseToken") or {}).get("name"),
                    "url": p.get("url"),
                }
    out = []
    for t in top:
        p = pairs.get(t["tokenAddress"])
        if not p:
            continue
        out.append(
            {
                "chain": t["chainId"],
                "address": t["tokenAddress"],
                "boost": t.get("totalAmount"),
                **p,
            }
        )
    return out[:12]
