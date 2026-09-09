"""GeckoTerminal client: new pools, and minute candles.

Chosen over DexScreener for this because it serves HISTORICAL OHLCV per pool.
The platform's DexScreener client answers "what is this token worth now", which
is what enrichment needs; a study of the minutes after a launch needs the
candles, and needs them for pools that no longer appear in any "new" feed.

Public and unauthenticated, so it is rate limited. Requests are spaced rather
than bursted: a collector that gets itself throttled records nothing, and the
discovery window it is racing is only about seventy minutes wide.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from app.core.logging import get_logger

logger = get_logger(__name__)

BASE_URL = "https://api.geckoterminal.com/api/v2"

#: Free tier is roughly 30 calls a minute. Two seconds between calls keeps a
#: whole collection pass an order of magnitude inside that, leaving headroom
#: for the analysis to fetch candles at the same time.
REQUEST_INTERVAL_SECONDS = 2.0

TIMEOUT = httpx.Timeout(20.0, connect=10.0)


def _dec(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _when(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


class GeckoTerminal:
    """Read-only. Owns no session and writes nothing."""

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client
        self._owns = client is None

    async def __aenter__(self) -> "GeckoTerminal":
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=TIMEOUT, headers={"Accept": "application/json"})
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._owns and self._client is not None:
            await self._client.aclose()

    async def _get(self, path: str) -> dict[str, Any]:
        assert self._client is not None
        r = await self._client.get(f"{BASE_URL}{path}")
        r.raise_for_status()
        return r.json()

    async def new_pools(self, network: str, *, pages: int) -> list[dict[str, Any]]:
        """Recently created pools, newest first, across `pages`.

        Errors on a page are logged and skipped rather than raised: a partial
        pass records most of the window, and a pass that raises records none of
        it — and the window does not wait.
        """
        out: list[dict[str, Any]] = []
        for page in range(1, pages + 1):
            try:
                payload = await self._get(
                    f"/networks/{network}/new_pools?page={page}")
            except Exception as exc:  # noqa: BLE001
                logger.info("evm_new_pools_page_failed", network=network,
                            page=page, error=type(exc).__name__)
                continue
            rows = payload.get("data") or []
            if not rows:
                break
            out.extend(rows)
            await asyncio.sleep(REQUEST_INTERVAL_SECONDS)
        return out

    async def minute_ohlcv(self, network: str, pool: str, *,
                           limit: int = 300) -> list[list[float]]:
        """`[[unix_ts, open, high, low, close, volume], …]`, newest first."""
        payload = await self._get(
            f"/networks/{network}/pools/{pool}/ohlcv/minute"
            f"?aggregate=1&limit={limit}")
        return (payload.get("data", {})
                       .get("attributes", {})
                       .get("ohlcv_list", []) or [])


def parse_pool(row: dict[str, Any], network: str, *,
               now: datetime | None = None) -> dict[str, Any] | None:
    """One `new_pools` row into the columns `evm_launches` stores, or None."""
    attrs = row.get("attributes") or {}
    address = attrs.get("address") or row.get("id")
    if not address:
        return None
    # GeckoTerminal ids are prefixed with the network ("base_0x…"); the pool
    # endpoints want the bare address, so it is stored bare.
    address = str(address).split("_")[-1]
    rel = (row.get("relationships") or {})
    token = (((rel.get("base_token") or {}).get("data") or {}).get("id") or "")
    dex = (((rel.get("dex") or {}).get("data") or {}).get("id") or "") or None
    return {
        "network": network,
        "pool_address": address[:64],
        "base_token_address": (str(token).split("_")[-1][:64] or None),
        "name": (attrs.get("name") or None) and str(attrs["name"])[:128],
        "dex_id": dex and str(dex)[:64],
        "pool_created_at": _when(attrs.get("pool_created_at")),
        "first_seen_at": now or datetime.now(UTC),
        "liquidity_usd_at_sighting": _dec(attrs.get("reserve_in_usd")),
    }
