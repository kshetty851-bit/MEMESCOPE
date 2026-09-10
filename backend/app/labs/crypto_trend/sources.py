"""The two keyless sources: CoinGecko (ranking, once a day) and Binance
Futures (candles and funding, every tick). One client, one weight budget,
one backoff.

Binance limits by REQUEST WEIGHT per IP per minute, not by request count, so
the budget is spent in weight units and each call declares its own. The
budget is the platform's `CallBudget` token bucket; the backoff is the
platform's `BackoffPolicy`. Neither is new.

A 429 or 418 (the IP-ban code) honours `Retry-After` when Binance sends it
and backs off otherwise. Nothing here ever retries forever: after
`MAX_ATTEMPTS` the call raises, the service records the error against that
symbol, and the next tick tries again.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from types import TracebackType
from typing import Any, Self

import httpx

from app.core.backoff import BackoffPolicy
from app.core.logging import get_logger
from app.labs.crypto_trend import config
from app.services.market.providers.rate_budget import CallBudget

logger = get_logger(__name__)

_RETRY_STATUSES = frozenset({418, 429})


def klines_weight(limit: int) -> int:
    """Binance's published weight tiers for `/fapi/v1/klines`."""
    return 1 if limit < 100 else 2 if limit < 500 else 5 if limit < 1000 else 10


class MarketSource:
    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        budget: CallBudget | None = None,
        backoff: BackoffPolicy | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._client = client
        self._owns_client = client is None
        self._budget = budget or CallBudget(config.WEIGHT_PER_MINUTE, window_seconds=60.0)
        self._backoff = backoff or BackoffPolicy(initial_seconds=1.0, max_seconds=30.0)
        self._sleep = sleep
        #: Every request actually sent, retries included. Reported per tick.
        self.requests = 0

    async def __aenter__(self) -> Self:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(config.HTTP_TIMEOUT_SECONDS),
                headers={"accept": "application/json"},
            )
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _get(self, url: str, params: dict[str, Any] | None, *, weight: int) -> Any:
        if self._client is None:
            raise RuntimeError("MarketSource used outside `async with`")
        for attempt in range(1, config.MAX_ATTEMPTS + 1):
            # ponytail: poll the bucket rather than compute the exact wait;
            # a tick spends ~200 weight an hour against a 1,200/min budget.
            while not self._budget.try_acquire(weight):
                await self._sleep(0.5)
            response = await self._client.get(url, params=params)
            self.requests += 1
            if response.status_code in _RETRY_STATUSES or response.status_code >= 500:
                retry_after = response.headers.get("Retry-After")
                delay = float(retry_after) if retry_after else self._backoff.delay_for(attempt)
                logger.warning("crypto_trend_http_retry", url=url, status=response.status_code,
                               attempt=attempt, delay_seconds=delay)
                await self._sleep(min(delay, 60.0))
                continue
            response.raise_for_status()
            return response.json()
        raise RuntimeError(
            f"crypto_trend: gave up on {url} after {config.MAX_ATTEMPTS} attempts")

    # --- CoinGecko ----------------------------------------------------------

    async def coingecko_markets(self) -> list[dict[str, Any]]:
        """Top `UNIVERSE_FETCH` by market cap. Once a day; no weight budget applies."""
        return await self._get(config.COINGECKO_MARKETS_URL, {
            "vs_currency": "usd", "order": "market_cap_desc",
            "per_page": config.UNIVERSE_FETCH, "page": 1,
        }, weight=0)

    # --- Binance Futures ----------------------------------------------------

    async def binance_perps(self) -> set[str]:
        """Every USDT-margined perpetual currently trading."""
        info = await self._get(f"{config.BINANCE_FAPI_URL}/fapi/v1/exchangeInfo", None,
                               weight=1)
        return {
            s["symbol"] for s in info.get("symbols", ())
            if s.get("contractType") == "PERPETUAL"
            and s.get("quoteAsset") == "USDT"
            and s.get("status") == "TRADING"
        }

    async def klines(
        self, symbol: str, interval: str, *, start_ms: int | None = None,
        limit: int = config.CANDLE_WINDOW,
    ) -> list[list[Any]]:
        params: dict[str, Any] = {"symbol": symbol, "interval": interval, "limit": limit}
        if start_ms is not None:
            params["startTime"] = start_ms
        return await self._get(f"{config.BINANCE_FAPI_URL}/fapi/v1/klines", params,
                               weight=klines_weight(limit))

    async def premium_index(self) -> list[dict[str, Any]]:
        """Mark price and current funding rate for EVERY symbol, in one call
        of weight 10 — cheaper than twenty calls of weight 1."""
        return await self._get(f"{config.BINANCE_FAPI_URL}/fapi/v1/premiumIndex", None,
                               weight=10)
