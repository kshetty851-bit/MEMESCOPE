"""Unit tests for the GeckoTerminal pool-liquidity adapter.

Fixtures mirror real `pools/multi` responses captured from mainnet, including
the two awkward cases seen live: a pool that is indexed but reports no reserve
yet, and a requested pool the vendor has never heard of.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import httpx
import pytest

from app.core.backoff import BackoffPolicy
from app.services.market.circuit_breaker import CircuitBreaker, CircuitState
from app.services.market.providers.base import (
    ProviderError,
    ProviderRateLimitError,
    ProviderUnavailableError,
)
from app.services.market.providers.geckoterminal import GeckoTerminalPoolLiquidity
from app.services.market.providers.rate_budget import CallBudget

pytestmark = pytest.mark.unit

POOL = "9pDuF4dvUNSdGiJqQnJTrwWyBnHnUvpVfXpNvbwCvXyz"
OTHER = "7RrnoB1JJZQpxVQ8cKcCLmZgHFEHkPfmXaXhqTgvNa11"

NO_WAIT = BackoffPolicy(initial_seconds=0.0, max_seconds=0.0, multiplier=1.0, jitter=False)


def _pool(address: str = POOL, reserve: Any = "1631.1462") -> dict[str, Any]:
    return {
        "id": f"solana_{address}",
        "type": "pool",
        "attributes": {
            "address": address,
            "name": "MEOW / SOL",
            "reserve_in_usd": reserve,
            "base_token_price_usd": "0.00000206749829802420810840463968",
        },
        "relationships": {"dex": {"data": {"id": "pump-fun"}}},
    }


def _provider(handler: httpx.MockTransport, **kwargs: Any) -> GeckoTerminalPoolLiquidity:
    kwargs.setdefault("budget", CallBudget(100))
    return GeckoTerminalPoolLiquidity(
        base_url="https://gt.test/api/v2",
        client=httpx.AsyncClient(transport=handler),
        backoff=NO_WAIT,
        **kwargs,
    )


def _ok(payload: dict[str, Any]) -> httpx.MockTransport:
    return httpx.MockTransport(lambda request: httpx.Response(200, json=payload))


# --- Parsing -----------------------------------------------------------------


async def test_reads_pool_level_reserve() -> None:
    provider = _provider(_ok({"data": [_pool()]}))
    assert await provider.fetch_pool_reserves([POOL]) == {POOL: Decimal("1631.1462")}


async def test_keys_by_pool_address_not_mint() -> None:
    """The whole point of this adapter: `reserve_in_usd` is a pool fact.

    See the module docstring — the mint-keyed endpoint carries a field of the
    same name and different meaning, measured at 0.49x-0.97x of this one.
    """
    provider = _provider(_ok({"data": [_pool(), _pool(OTHER, "42.5")]}))
    result = await provider.fetch_pool_reserves([POOL, OTHER])
    assert set(result) == {POOL, OTHER}
    assert result[OTHER] == Decimal("42.5")


async def test_pool_requested_but_not_returned_is_simply_absent() -> None:
    """A pool minutes old is routinely unindexed. That is not an error."""
    provider = _provider(_ok({"data": [_pool()]}))
    result = await provider.fetch_pool_reserves([POOL, OTHER])
    assert POOL in result
    assert OTHER not in result


async def test_unrequested_pools_are_ignored() -> None:
    provider = _provider(_ok({"data": [_pool("some-other-pool")]}))
    assert await provider.fetch_pool_reserves([POOL]) == {}


async def test_indexed_pool_with_no_reserve_is_absent_not_zero() -> None:
    """An unindexed pool and a drained one are different claims about a market."""
    provider = _provider(_ok({"data": [_pool(reserve=None)]}))
    assert await provider.fetch_pool_reserves([POOL]) == {}


@pytest.mark.parametrize("junk", ["", "abc", "NaN", "Infinity", True, {}, [], "-5"])
async def test_junk_and_negative_reserves_are_rejected(junk: Any) -> None:
    provider = _provider(_ok({"data": [_pool(reserve=junk)]}))
    assert await provider.fetch_pool_reserves([POOL]) == {}


@pytest.mark.parametrize("payload", [{}, {"data": None}, {"data": {}}, {"data": [None, 7]}])
async def test_malformed_payloads_yield_nothing_rather_than_raising(
    payload: dict[str, Any],
) -> None:
    provider = _provider(_ok(payload))
    assert await provider.fetch_pool_reserves([POOL]) == {}


async def test_empty_request_makes_no_call() -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("no HTTP call should be made")

    provider = _provider(httpx.MockTransport(handler))
    assert await provider.fetch_pool_reserves([]) == {}


async def test_duplicate_pools_are_collapsed() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, json={"data": [_pool()]})

    provider = _provider(httpx.MockTransport(handler))
    await provider.fetch_pool_reserves([POOL, POOL, POOL])
    assert seen[0].count(POOL) == 1


async def test_batch_overflow_is_a_programming_error() -> None:
    provider = _provider(_ok({"data": []}), batch_size=2)
    with pytest.raises(ValueError, match="exceeds batch_size"):
        await provider.fetch_pool_reserves(["a", "b", "c"])


# --- Budget ------------------------------------------------------------------


async def test_exhausted_budget_raises_rate_limit_rather_than_calling() -> None:
    """The composite turns this into a skipped fill, never a lost batch."""
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"data": [_pool()]})

    provider = _provider(httpx.MockTransport(handler), budget=CallBudget(1))
    await provider.fetch_pool_reserves([POOL])
    with pytest.raises(ProviderRateLimitError, match="budget exhausted"):
        await provider.fetch_pool_reserves([OTHER])
    assert calls == 1


async def test_budget_state_is_reported_in_health() -> None:
    provider = _provider(_ok({"data": []}), budget=CallBudget(4))
    health = await provider.health()
    assert health.details["budget_capacity_per_min"] == "4"
    assert health.details["budget_available"] == "4"


# --- Failure handling --------------------------------------------------------


async def test_open_circuit_fails_fast_without_calling() -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("breaker should have short-circuited the call")

    breaker = CircuitBreaker(name="gt", failure_threshold=1)
    breaker.record_failure()
    assert breaker.state is CircuitState.OPEN

    provider = _provider(httpx.MockTransport(handler), breaker=breaker)
    with pytest.raises(ProviderUnavailableError):
        await provider.fetch_pool_reserves([POOL])


async def test_retries_then_fails_after_max_attempts() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(503)

    provider = _provider(httpx.MockTransport(handler), max_attempts=3)
    with pytest.raises(ProviderError, match="after 3 attempts"):
        await provider.fetch_pool_reserves([POOL])
    assert attempts == 3


async def test_a_retry_that_succeeds_returns_data() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(429)
        return httpx.Response(200, json={"data": [_pool()]})

    provider = _provider(httpx.MockTransport(handler), max_attempts=3)
    assert await provider.fetch_pool_reserves([POOL]) == {POOL: Decimal("1631.1462")}


async def test_client_error_is_not_retried() -> None:
    """A 400 is our bug and will not improve; retrying just adds load."""
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(400)

    provider = _provider(httpx.MockTransport(handler), max_attempts=3)
    with pytest.raises(ProviderError, match="rejected request"):
        await provider.fetch_pool_reserves([POOL])
    assert attempts == 1


async def test_invalid_json_is_a_provider_error() -> None:
    handler = httpx.MockTransport(
        lambda request: httpx.Response(200, content=b"<html>nope</html>")
    )
    provider = _provider(handler, max_attempts=1)
    with pytest.raises(ProviderError):
        await provider.fetch_pool_reserves([POOL])


async def test_unstarted_provider_raises_rather_than_crashing() -> None:
    provider = GeckoTerminalPoolLiquidity(base_url="https://gt.test/api/v2")
    with pytest.raises(ProviderError, match="not started"):
        await provider.fetch_pool_reserves([POOL])


async def test_close_is_idempotent() -> None:
    provider = GeckoTerminalPoolLiquidity(base_url="https://gt.test/api/v2")
    await provider.start()
    await provider.close()
    await provider.close()


async def test_request_targets_the_configured_network() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, json={"data": []})

    provider = _provider(httpx.MockTransport(handler))
    await provider.fetch_pool_reserves([POOL])
    assert "/networks/solana/pools/multi/" in seen[0]
