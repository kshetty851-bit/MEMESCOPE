"""DexScreener market data provider.

The first concrete `MarketDataProvider`. Chosen to start with because it needs
no API key, covers Solana DEXes broadly, and accepts up to 30 mints per request
— batching is what makes refreshing thousands of tokens affordable.

Two behaviours worth knowing, both learned from the live API:

  * A token with no indexed pool returns `{"pairs": null}`. That is an empty
    result, not an error: freshly launched mints are routinely not indexed for
    the first minutes of their life.
  * A token often has many pairs across DEXes. The pair with the deepest USD
    liquidity is treated as canonical, because that is where price is actually
    discovered; thin pools carry noisy prices.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from app.core.backoff import BackoffPolicy
from app.core.config import settings
from app.core.logging import get_logger
from app.models.market import TradingStatus
from app.services.market.circuit_breaker import CircuitBreaker, CircuitOpenError
from app.services.market.providers.base import (
    MarketData,
    MarketDataProvider,
    ProviderError,
    ProviderHealth,
    ProviderRateLimitError,
    ProviderUnavailableError,
)

logger = get_logger(__name__)

#: The only chain this platform trades. DexScreener answers token queries
#: across all indexed chains; everything downstream — Jupiter routing, the
#: scanner's program subscriptions, every execution quote — is Solana, so a
#: pair from anywhere else is not a cheaper venue, it is a different asset.
SOLANA_CHAIN_ID = "solana"

# Below this USD liquidity a pool is treated as effectively untradeable.
MIN_TRADEABLE_LIQUIDITY_USD = Decimal("100")


def _decimal(value: Any) -> Decimal | None:
    """Coerce provider JSON to Decimal, tolerating strings, nulls and junk."""
    if value is None or isinstance(value, bool):
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    # NaN/Infinity would poison any later aggregate.
    return result if result.is_finite() else None


def _as_dict(value: Any) -> dict[str, Any]:
    """Coerce an untrusted nested value to a dict, so `.get()` chains are safe."""
    return value if isinstance(value, dict) else {}


def _int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


class DexScreenerProvider(MarketDataProvider):
    name = "dexscreener"

    def __init__(
        self,
        *,
        base_url: str | None = None,
        client: httpx.AsyncClient | None = None,
        breaker: CircuitBreaker | None = None,
        backoff: BackoffPolicy | None = None,
        batch_size: int | None = None,
        max_attempts: int | None = None,
    ) -> None:
        self._base_url = (base_url or settings.MARKET_PROVIDER_BASE_URL).rstrip("/")
        self._client = client
        self._owns_client = client is None
        self.batch_size = batch_size or settings.MARKET_PROVIDER_BATCH_SIZE
        self._max_attempts = max_attempts or settings.MARKET_PROVIDER_MAX_ATTEMPTS
        self._backoff = backoff or BackoffPolicy.from_settings()
        self._breaker = breaker or CircuitBreaker(
            name="dexscreener",
            failure_threshold=settings.MARKET_BREAKER_FAILURE_THRESHOLD,
            reset_seconds=settings.MARKET_BREAKER_RESET_SECONDS,
            half_open_successes=settings.MARKET_BREAKER_HALF_OPEN_SUCCESSES,
        )
        self._last_latency_ms: int | None = None

    async def start(self) -> None:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(settings.MARKET_PROVIDER_TIMEOUT_SECONDS),
                limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
                headers={"accept": "application/json"},
            )
            self._owns_client = True

    async def close(self) -> None:
        if self._client is not None and self._owns_client:
            await self._client.aclose()
            self._client = None

    @property
    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            raise ProviderError("DexScreenerProvider is not started; call start().")
        return self._client

    async def fetch_many(self, mint_addresses: Sequence[str]) -> dict[str, MarketData]:
        mints = [mint for mint in dict.fromkeys(mint_addresses) if mint]
        if not mints:
            return {}
        if len(mints) > self.batch_size:
            raise ValueError(
                f"{len(mints)} mints exceeds batch_size {self.batch_size}; chunk upstream"
            )

        try:
            self._breaker.ensure_closed()
        except CircuitOpenError as exc:
            # The cooldown travels with the error so the caller can defer the
            # batch by exactly that long rather than re-claiming immediately.
            raise ProviderUnavailableError(
                str(exc), retry_after_seconds=exc.retry_after_seconds
            ) from exc

        url = f"{self._base_url}/latest/dex/tokens/{','.join(mints)}"
        started = time.perf_counter()
        payload = await self._get_with_retry(url)
        latency_ms = int((time.perf_counter() - started) * 1000)
        self._last_latency_ms = latency_ms

        logger.debug(
            "provider_latency", provider=self.name, latency_ms=latency_ms, mints=len(mints)
        )

        return self._parse(payload, requested=set(mints), latency_ms=latency_ms)

    async def _get_with_retry(self, url: str) -> dict[str, Any]:
        last_error: Exception | None = None

        for attempt in range(1, self._max_attempts + 1):
            try:
                response = await self._http.get(url)

                if response.status_code == 429:
                    last_error = ProviderRateLimitError("dexscreener rate limited")
                elif response.status_code >= 500:
                    last_error = ProviderError(f"dexscreener returned {response.status_code}")
                elif response.status_code >= 400:
                    # A 4xx other than 429 is our fault and will not improve.
                    self._breaker.record_failure()
                    raise ProviderError(
                        f"dexscreener rejected request: {response.status_code}"
                    )
                else:
                    body = response.json()
                    self._breaker.record_success()
                    return body if isinstance(body, dict) else {}

            except httpx.TimeoutException as exc:
                last_error = ProviderError(f"dexscreener timed out: {exc}")
            except httpx.TransportError as exc:
                last_error = ProviderError(f"dexscreener transport error: {exc}")
            except ValueError as exc:
                last_error = ProviderError(f"dexscreener returned invalid JSON: {exc}")

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
            f"dexscreener failed after {self._max_attempts} attempts: {last_error}"
        )

    def _parse(
        self, payload: dict[str, Any], *, requested: set[str], latency_ms: int
    ) -> dict[str, MarketData]:
        pairs = payload.get("pairs")
        if not isinstance(pairs, list):
            # `{"pairs": null}` — nothing indexed for any requested mint.
            return {}

        # Keep the deepest-liquidity pair per mint.
        best: dict[str, dict[str, Any]] = {}
        for pair in pairs:
            if not isinstance(pair, dict):
                continue
            # SOLANA ONLY. `/latest/dex/tokens/{addresses}` answers across every
            # chain DexScreener indexes, and this parser previously selected a
            # pair on address alone — so a same-address or provider-side
            # mismatch on another chain could price a different asset entirely.
            # This platform is Solana-only end to end (Jupiter routes, the
            # scanner's programs, every execution quote), so a non-Solana pair
            # is never the right answer and is dropped before selection rather
            # than out-competed on liquidity.
            if pair.get("chainId") != SOLANA_CHAIN_ID:
                continue
            # BASE SIDE ONLY. Every field on a pair — `priceUsd`, `fdv`,
            # `marketCap`, `volume`, `txns` — describes the BASE token. A pair
            # where the requested mint is the QUOTE side therefore answers a
            # question about a different asset, and accepting it priced that
            # other asset as if it were this one: JUP, quoted in hundreds of
            # pools, read back at $1,095.89 against a real price near $0.50.
            #
            # The damage scales with how established a token is, because deep
            # tokens are the ones other pairs quote in — so the market universe
            # is the population most exposed to it, not the least.
            base = pair.get("baseToken")
            if not isinstance(base, dict):
                continue
            base_address = base.get("address")
            if not isinstance(base_address, str) or base_address not in requested:
                continue
            mint = base_address

            incumbent = best.get(mint)
            if incumbent is None or self._liquidity(pair) > self._liquidity(incumbent):
                best[mint] = pair

        observed_at = datetime.now(UTC)
        return {
            mint: self._to_market_data(mint, pair, latency_ms, observed_at)
            for mint, pair in best.items()
        }

    @staticmethod
    def _liquidity(pair: dict[str, Any]) -> Decimal:
        return _decimal(_as_dict(pair.get("liquidity")).get("usd")) or Decimal(0)

    def _to_market_data(
        self, mint: str, pair: dict[str, Any], latency_ms: int, observed_at: datetime
    ) -> MarketData:
        liquidity = _as_dict(pair.get("liquidity"))
        volume = _as_dict(pair.get("volume"))
        txns_24h = _as_dict(_as_dict(pair.get("txns")).get("h24"))

        base_symbol = _as_dict(pair.get("baseToken")).get("symbol")
        quote_symbol = _as_dict(pair.get("quoteToken")).get("symbol")
        trading_pair = (
            f"{base_symbol}/{quote_symbol}" if base_symbol and quote_symbol else None
        )

        liquidity_usd = _decimal(liquidity.get("usd"))
        pool_address = pair.get("pairAddress")

        if pool_address and liquidity_usd is not None:
            status = (
                TradingStatus.TRADING
                if liquidity_usd >= MIN_TRADEABLE_LIQUIDITY_USD
                else TradingStatus.INACTIVE
            )
        elif pool_address:
            status = TradingStatus.TRADING
        else:
            status = TradingStatus.UNKNOWN

        # DexScreener marks paid/enhanced profiles via `labels`; treat the
        # presence of a profile or boost as the closest available "verified".
        labels = pair.get("labels")
        is_verified = bool(pair.get("info")) or (isinstance(labels, list) and bool(labels))

        return MarketData(
            mint_address=mint,
            price_usd=_decimal(pair.get("priceUsd")),
            price_native=_decimal(pair.get("priceNative")),
            liquidity_usd=liquidity_usd,
            fully_diluted_valuation=_decimal(pair.get("fdv")),
            market_cap=_decimal(pair.get("marketCap")),
            volume_24h=_decimal(volume.get("h24")),
            volume_1h=_decimal(volume.get("h1")),
            volume_5m=_decimal(volume.get("m5")),
            buy_count_24h=_int(txns_24h.get("buys")),
            sell_count_24h=_int(txns_24h.get("sells")),
            dex_name=pair.get("dexId") if isinstance(pair.get("dexId"), str) else None,
            trading_pair=trading_pair[:96] if trading_pair else None,
            pool_address=pool_address if isinstance(pool_address, str) else None,
            trading_status=status,
            is_verified=is_verified,
            provider=self.name,
            provider_latency_ms=latency_ms,
            observed_at=observed_at,
        )

    async def health(self) -> ProviderHealth:
        return ProviderHealth(
            name=self.name,
            available=self._breaker.allows_request(),
            circuit_state=str(self._breaker.state),
            consecutive_failures=self._breaker.consecutive_failures,
            last_latency_ms=self._last_latency_ms,
        )
