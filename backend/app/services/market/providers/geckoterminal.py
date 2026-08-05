"""GeckoTerminal pool liquidity — the fill for the bonding-curve gap.

## Why this exists

DexScreener reports no liquidity at all for pump.fun bonding-curve pools. That
is not a rare edge: measured on the live database, `pumpfun` accounted for
29,477 of 30,339 snapshots in a two-hour window and **100% of them had a null
`liquidity_usd`**. Since `liquidity_depth` carries 0.20 of the scoring model's
weight, this single gap is why ~90% of the feed scores at 45% coverage instead
of the model's 65% ceiling (MEMESCOPE_MASTER_CONTEXT §11). ADR 0001 predicted
this exact shortfall on day 3 and is the reason the provider layer is an
interface rather than a direct call.

## Why this is not a `MarketDataProvider`

It cannot answer "what is the market for this mint?". It answers a narrower
question — "what is the USD reserve of this pool?" — and it is keyed by **pool
address, not mint address**. Dressing it up as a full provider would mean
implementing `fetch_many(mints)` with a semantically wrong field; see below.

## The field that looks right and is not

GeckoTerminal exposes reserves in two places, and only one of them is
comparable with DexScreener's `liquidity.usd`:

  * `/tokens/multi/{mints}` -> `attributes.total_reserve_in_usd`. **Wrong.** It
    is mint-keyed, so it looks like the obvious batched endpoint to reach for.
    Measured against DexScreener on the same pools it ranges from **0.49x to
    0.97x** — roughly single-sided on thin pools, roughly both sides on deep
    ones.
  * `/pools/multi/{pools}` -> `attributes.reserve_in_usd`. **Right.** Measured
    across 12 pools spanning $50 to $7,600 of liquidity: median **1.005x**,
    range 0.984x-1.046x.

Writing the first into `token_market_snapshots.liquidity_usd` would put values
of two different meanings in one column. The damage is not merely a wrong
number: the Radar's momentum dimension compares liquidity *across time*
(`LIQUIDITY_GROWING` / `LIQUIDITY_SHRINKING`), so a provider changing between
two observations of the same token would manufacture a halving or a doubling
that never happened. Hence pool-keyed, and hence this docstring.

DexScreener supplies `pool_address` for 100% of the rows it leaves without
liquidity, which is what makes the pool-keyed lookup possible at all.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Sequence
from decimal import Decimal, InvalidOperation
from types import TracebackType
from typing import Any, Self

import httpx

from app.core.backoff import BackoffPolicy
from app.core.config import settings
from app.core.logging import get_logger
from app.services.market.circuit_breaker import CircuitBreaker, CircuitOpenError
from app.services.market.providers.base import (
    ProviderError,
    ProviderHealth,
    ProviderRateLimitError,
    ProviderUnavailableError,
)
from app.services.market.providers.rate_budget import CallBudget

logger = get_logger(__name__)


def _reserve(value: Any) -> Decimal | None:
    """Coerce a reserve figure to Decimal, rejecting junk and negatives."""
    if value is None or isinstance(value, bool):
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    if not result.is_finite() or result < 0:
        return None
    return result


class GeckoTerminalPoolLiquidity:
    """Batched pool-reserve lookups, bounded by a call budget.

    Not a `MarketDataProvider` — see the module docstring. `CompositeProvider`
    is the only intended caller.
    """

    name = "geckoterminal"

    def __init__(
        self,
        *,
        base_url: str | None = None,
        client: httpx.AsyncClient | None = None,
        breaker: CircuitBreaker | None = None,
        backoff: BackoffPolicy | None = None,
        batch_size: int | None = None,
        max_attempts: int | None = None,
        budget: CallBudget | None = None,
    ) -> None:
        self._base_url = (base_url or settings.MARKET_SECONDARY_BASE_URL).rstrip("/")
        self._network = settings.MARKET_SECONDARY_NETWORK
        self._client = client
        self._owns_client = client is None
        self.batch_size = batch_size or settings.MARKET_SECONDARY_BATCH_SIZE
        self._max_attempts = max_attempts or settings.MARKET_SECONDARY_MAX_ATTEMPTS
        self._backoff = backoff or BackoffPolicy.from_settings()
        self._budget = budget or CallBudget(
            settings.MARKET_SECONDARY_CALLS_PER_MINUTE, window_seconds=60.0
        )
        self._breaker = breaker or CircuitBreaker(
            name="geckoterminal",
            failure_threshold=settings.MARKET_BREAKER_FAILURE_THRESHOLD,
            reset_seconds=settings.MARKET_BREAKER_RESET_SECONDS,
            half_open_successes=settings.MARKET_BREAKER_HALF_OPEN_SUCCESSES,
        )
        self._last_latency_ms: int | None = None

    async def __aenter__(self) -> Self:
        await self.start()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.close()

    async def start(self) -> None:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(settings.MARKET_SECONDARY_TIMEOUT_SECONDS),
                limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
                headers={"accept": "application/json"},
            )
            self._owns_client = True

    async def close(self) -> None:
        if self._client is not None and self._owns_client:
            await self._client.aclose()
            self._client = None

    @property
    def budget(self) -> CallBudget:
        return self._budget

    @property
    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            raise ProviderError("GeckoTerminalPoolLiquidity is not started; call start().")
        return self._client

    async def fetch_pool_reserves(self, pool_addresses: Sequence[str]) -> dict[str, Decimal]:
        """USD reserve per pool, for the pools the vendor knew about.

        Absent keys mean "not indexed" — routine for a pool seconds old — and
        are never an error. Raises `ProviderError` only when the call failed.

        Spends one budget token per request and refuses rather than waits when
        the budget is empty, so a slow secondary can never stall enrichment.
        """
        pools = [pool for pool in dict.fromkeys(pool_addresses) if pool]
        if not pools:
            return {}
        if len(pools) > self.batch_size:
            raise ValueError(
                f"{len(pools)} pools exceeds batch_size {self.batch_size}; chunk upstream"
            )

        try:
            self._breaker.ensure_closed()
        except CircuitOpenError as exc:
            # The cooldown travels with the error so the caller can defer the
            # batch by exactly that long rather than re-claiming immediately.
            raise ProviderUnavailableError(
                str(exc), retry_after_seconds=exc.retry_after_seconds
            ) from exc

        if not self._budget.try_acquire():
            raise ProviderRateLimitError(
                f"geckoterminal call budget exhausted "
                f"({self._budget.capacity}/min); skipping fill for {len(pools)} pools"
            )

        url = f"{self._base_url}/networks/{self._network}/pools/multi/{','.join(pools)}"
        started = time.perf_counter()
        payload = await self._get_with_retry(url)
        self._last_latency_ms = int((time.perf_counter() - started) * 1000)

        return self._parse(payload, requested=set(pools))

    async def _get_with_retry(self, url: str) -> dict[str, Any]:
        last_error: Exception | None = None

        for attempt in range(1, self._max_attempts + 1):
            try:
                response = await self._http.get(url)

                if response.status_code == 429:
                    last_error = ProviderRateLimitError("geckoterminal rate limited")
                elif response.status_code >= 500:
                    last_error = ProviderError(
                        f"geckoterminal returned {response.status_code}"
                    )
                elif response.status_code >= 400:
                    # 4xx other than 429 is our fault and will not improve.
                    self._breaker.record_failure()
                    raise ProviderError(
                        f"geckoterminal rejected request: {response.status_code}"
                    )
                else:
                    body = response.json()
                    self._breaker.record_success()
                    return body if isinstance(body, dict) else {}

            except httpx.TimeoutException as exc:
                last_error = ProviderError(f"geckoterminal timed out: {exc}")
            except httpx.TransportError as exc:
                last_error = ProviderError(f"geckoterminal transport error: {exc}")
            except ValueError as exc:
                last_error = ProviderError(f"geckoterminal returned invalid JSON: {exc}")

            if attempt < self._max_attempts:
                delay = self._backoff.delay_for(attempt)
                logger.warning(
                    "provider_retry",
                    provider=self.name,
                    attempt=attempt,
                    delay_seconds=round(delay, 2),
                    error=str(last_error),
                )
                await asyncio.sleep(delay)

        self._breaker.record_failure()
        raise ProviderError(
            f"geckoterminal failed after {self._max_attempts} attempts: {last_error}"
        )

    def _parse(self, payload: dict[str, Any], *, requested: set[str]) -> dict[str, Decimal]:
        data = payload.get("data")
        if not isinstance(data, list):
            # `{"data": []}` or an unexpected shape: nothing indexed.
            return {}

        reserves: dict[str, Decimal] = {}
        for pool in data:
            if not isinstance(pool, dict):
                continue
            attributes = pool.get("attributes")
            if not isinstance(attributes, dict):
                continue
            address = attributes.get("address")
            if not isinstance(address, str) or address not in requested:
                continue
            reserve = _reserve(attributes.get("reserve_in_usd"))
            # A pool that exists but reports no reserve stays absent rather than
            # being recorded as zero: "not indexed yet" and "drained" are
            # different claims, and only the second is a fact about the market.
            if reserve is None:
                continue
            reserves[address] = reserve

        return reserves

    async def health(self) -> ProviderHealth:
        return ProviderHealth(
            name=self.name,
            available=self._breaker.allows_request(),
            circuit_state=str(self._breaker.state),
            consecutive_failures=self._breaker.consecutive_failures,
            last_latency_ms=self._last_latency_ms,
            details={
                "budget_capacity_per_min": str(self._budget.capacity),
                "budget_available": str(self._budget.available()),
                "budget_denied": str(self._budget.denied),
            },
        )
