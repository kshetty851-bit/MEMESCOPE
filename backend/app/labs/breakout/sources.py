"""The two keyless sources: GeckoTerminal (pools and OHLCV) and DexScreener
(boosted and newly-profiled tokens). One client, TWO budgets, one backoff.

The two hosts limit at very different rates, so one bucket would either
throttle DexScreener to GeckoTerminal's tier or let GeckoTerminal spend
DexScreener's. They get a `CallBudget` each. Both are the platform's token
bucket; the backoff is the platform's `BackoffPolicy`. Neither is new.

**This lab keeps its own thin client on purpose.** The platform already
speaks to both hosts — `app/services/market/providers/dexscreener.py` is the
primary market provider and `.../geckoterminal.py` is the bonding-curve
liquidity fill — and neither is imported here. Those answer "what is the
market for this mint?" against the pump.fun feed, with a circuit breaker and
a snapshot contract this lab has no use for; the two endpoints it wants
(ranked pools and OHLCV) are not in either. Reusing them would couple a lab
to the platform's feed, which is the thing labs exist not to do.

What is shared is the budget accounting: see `config.py` for how much of
each host's allowance the platform is already spending and why the lab's
numbers sit under the remainder.

A 429 honours `Retry-After` when the host sends it and backs off otherwise.
Nothing here retries forever: after `MAX_ATTEMPTS` the call raises, the
caller records the error against that token, and the next tick tries again.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from types import TracebackType
from typing import Any, Self

import httpx

from app.core.backoff import BackoffPolicy
from app.core.logging import get_logger
from app.labs.breakout import config
from app.services.market.providers.rate_budget import CallBudget

logger = get_logger(__name__)

_RETRY_STATUSES = frozenset({429})
GECKO = "geckoterminal"
DEX = "dexscreener"


def _retry_after(response: httpx.Response) -> float:
    """The header's value in seconds, or 0 when it is absent or unparseable.
    Never negative — a malformed header must not shorten a backoff."""
    raw = response.headers.get("Retry-After")
    if not raw:
        return 0.0
    try:
        return max(0.0, float(raw))
    except ValueError:
        return 0.0


class BudgetExhaustedError(RuntimeError):
    """The tick's call allowance is spent. Raised instead of sending, so the
    caller stops cleanly and carries the rest of its queue to the next tick."""


class BreakoutSource:
    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        gecko_budget: CallBudget | None = None,
        dex_budget: CallBudget | None = None,
        backoff: BackoffPolicy | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        max_calls: int = config.MAX_CALLS_PER_TICK,
    ) -> None:
        self._client = client
        self._owns_client = client is None
        # Capacity ONE, window `60 / rate`: the platform's token bucket used as
        # a minimum SPACING between calls rather than a per-minute allowance.
        # See `config.call_spacing_seconds` for the measurement behind it.
        self._budgets = {
            GECKO: gecko_budget or CallBudget(
                1, window_seconds=config.call_spacing_seconds(
                    config.GECKOTERMINAL_CALLS_PER_MINUTE)),
            DEX: dex_budget or CallBudget(
                1, window_seconds=config.call_spacing_seconds(
                    config.DEXSCREENER_CALLS_PER_MINUTE)),
        }
        self._backoff = backoff or BackoffPolicy(
            initial_seconds=config.BACKOFF_INITIAL_SECONDS,
            max_seconds=config.BACKOFF_MAX_SECONDS)
        self._sleep = sleep
        self._max_calls = max_calls
        #: Every request actually sent, retries included, per host. Reported
        #: per tick.
        self.requests: dict[str, int] = {GECKO: 0, DEX: 0}

    @property
    def total_requests(self) -> int:
        return sum(self.requests.values())

    async def __aenter__(self) -> Self:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(config.HTTP_TIMEOUT_SECONDS),
                headers={"accept": "application/json",
                         "user-agent": config.HTTP_USER_AGENT},
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

    async def _get(self, url: str, params: dict[str, Any] | None, *, host: str) -> Any:
        if self._client is None:
            raise RuntimeError("BreakoutSource used outside `async with`")
        if self.total_requests >= self._max_calls:
            raise BudgetExhaustedError(f"breakout: {self._max_calls} calls spent this tick")
        bucket = self._budgets[host]
        for attempt in range(1, config.MAX_ATTEMPTS + 1):
            # ponytail: poll the bucket rather than compute the exact wait. A
            # tick spends at most MAX_CALLS_PER_TICK, and the deadline in
            # `candles.py` is what bounds the wall clock.
            while not bucket.try_acquire(1):
                await self._sleep(0.5)
            response = await self._client.get(url, params=params)
            self.requests[host] += 1
            if response.status_code in _RETRY_STATUSES or response.status_code >= 500:
                # `Retry-After` is a FLOOR, never a ceiling. GeckoTerminal
                # answers a 429 with `Retry-After: 0` and then refuses for
                # about 35 seconds — honouring that header literally retried
                # four times inside a millisecond and gave up while the host
                # was still angry. Measured, on the first live tick.
                delay = max(_retry_after(response), self._backoff.delay_for(attempt))
                logger.warning("breakout_http_retry", host=host, url=url,
                               status=response.status_code, attempt=attempt,
                               delay_seconds=delay)
                await self._sleep(min(delay, 60.0))
                continue
            response.raise_for_status()
            return response.json()
        raise RuntimeError(f"breakout: gave up on {url} after {config.MAX_ATTEMPTS} attempts")

    # --- GeckoTerminal ------------------------------------------------------

    async def gecko_pools(self, page: int) -> dict[str, Any]:
        """One page of Solana pools by 24h volume, newest data, with the base
        token included so a symbol and a name come back in the same call.

        Twenty pools a page, and page 11 answers 401 — measured. That is why
        `UNIVERSE_PAGES` defaults to the API's own ceiling rather than to a
        number someone liked.
        """
        return await self._get(
            f"{config.GECKOTERMINAL_URL}/networks/{config.NETWORK}/pools",
            {"page": page, "sort": "h24_volume_usd_desc", "include": "base_token"},
            host=GECKO,
        )

    async def gecko_trending(self) -> dict[str, Any]:
        """Trending Solana pools over 24h. A second view of the same universe:
        a pool can trend on volume growth without being in the top 200 by
        absolute volume."""
        return await self._get(
            f"{config.GECKOTERMINAL_URL}/networks/{config.NETWORK}/trending_pools",
            {"include": "base_token", "duration": "24h"},
            host=GECKO,
        )

    async def gecko_ohlcv(
        self, pool: str, timeframe: str, *, limit: int = config.OHLCV_LIMIT,
        before: int | None = None,
    ) -> list[list[Any]]:
        """`[[open_ts_seconds, o, h, l, c, volume_usd], ...]`, NEWEST FIRST.

        `limit` is capped at 100 by the API. `before_timestamp` is INCLUSIVE —
        a page asked for `before=t` comes back with the bar at `t` as its
        first row — so the caller pages on the oldest open time it holds and
        lets the upsert absorb the overlap.
        """
        params: dict[str, Any] = {
            "aggregate": 1, "limit": min(limit, config.OHLCV_LIMIT), "currency": "usd",
        }
        if before is not None:
            params["before_timestamp"] = before
        body = await self._get(
            f"{config.GECKOTERMINAL_URL}/networks/{config.NETWORK}"
            f"/pools/{pool}/ohlcv/{timeframe}",
            params, host=GECKO,
        )
        attributes = (body.get("data") or {}).get("attributes") or {}
        return list(attributes.get("ohlcv_list") or ())

    # --- DexScreener --------------------------------------------------------

    async def dex_boosts(self) -> list[dict[str, Any]]:
        """Tokens with the most active boosts. Returns `{chainId, tokenAddress}`
        and no market data at all — `dex_pairs` is what turns these into pools."""
        body = await self._get(f"{config.DEXSCREENER_URL}/token-boosts/top/v1",
                               None, host=DEX)
        return body if isinstance(body, list) else []

    async def dex_profiles(self) -> list[dict[str, Any]]:
        """The newest token profiles, same shape as the boosts."""
        body = await self._get(f"{config.DEXSCREENER_URL}/token-profiles/latest/v1",
                               None, host=DEX)
        return body if isinstance(body, list) else []

    async def dex_pairs(self, mints: Sequence[str]) -> list[dict[str, Any]]:
        """The best pair for each of up to 30 mints, with `pairCreatedAt`,
        `liquidity.usd`, `volume.h24` and `dexId` — the fields the filters
        need and the boost and profile lists do not carry.

        Tokens with no indexed pool are simply absent from the answer.
        """
        if not mints:
            return []
        body = await self._get(
            f"{config.DEXSCREENER_URL}/tokens/v1/{config.NETWORK}/{','.join(mints[:30])}",
            None, host=DEX,
        )
        return body if isinstance(body, list) else []
