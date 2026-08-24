"""Unit tests for the DexScreener provider adapter.

Fixtures mirror real API responses captured from mainnet, including the awkward
ones: `{"pairs": null}` for an unindexed mint, and many pairs per token.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import httpx
import pytest

from app.core.backoff import BackoffPolicy
from app.models.market import TradingStatus
from app.services.market.circuit_breaker import CircuitBreaker, CircuitState
from app.services.market.providers.base import ProviderError, ProviderUnavailableError
from app.services.market.providers.dexscreener import DexScreenerProvider

pytestmark = pytest.mark.unit

MINT = "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263"
OTHER = "HHbRJ9Fw2tPxETGSsaeQhpgdizfVafLvXK7eo5mwpump"

NO_WAIT = BackoffPolicy(initial_seconds=0.0, max_seconds=0.0, multiplier=1.0, jitter=False)


def _pair(
    mint: str = MINT, *, liquidity: float = 133121.32, dex: str = "orca"
) -> dict[str, Any]:
    return {
        "chainId": "solana",
        "dexId": dex,
        "pairAddress": f"pool-{dex}",
        "labels": ["wp"],
        "priceUsd": "0.000003155",
        "priceNative": "0.00000004129",
        "fdv": 280377626,
        "marketCap": 277638943,
        "liquidity": {"usd": liquidity, "base": 27700773850, "quote": 598.3556},
        "volume": {"h24": 463215.88, "h6": 126314.96, "h1": 25228.19, "m5": 948.46},
        "txns": {"h24": {"buys": 7528, "sells": 7299}},
        "baseToken": {"address": mint, "name": "Bonk", "symbol": "Bonk"},
        "quoteToken": {"address": "So111", "name": "Wrapped SOL", "symbol": "SOL"},
    }


def _provider(handler: httpx.MockTransport, **kwargs: Any) -> DexScreenerProvider:
    return DexScreenerProvider(
        base_url="https://api.test",
        client=httpx.AsyncClient(transport=handler),
        backoff=NO_WAIT,
        **kwargs,
    )


def _respond(payload: dict[str, Any]) -> httpx.MockTransport:
    return httpx.MockTransport(lambda request: httpx.Response(200, json=payload))


# --- Happy path --------------------------------------------------------------


async def test_maps_every_required_field() -> None:
    result = await _provider(_respond({"pairs": [_pair()]})).fetch_many([MINT])

    data = result[MINT]
    assert data.price_usd == Decimal("0.000003155")
    assert data.price_native == Decimal("0.00000004129")
    assert data.liquidity_usd == Decimal("133121.32")
    assert data.fully_diluted_valuation == Decimal("280377626")
    assert data.market_cap == Decimal("277638943")
    assert data.volume_24h == Decimal("463215.88")
    assert data.volume_1h == Decimal("25228.19")
    assert data.volume_5m == Decimal("948.46")
    assert data.buy_count_24h == 7528
    assert data.sell_count_24h == 7299
    assert data.dex_name == "orca"
    assert data.trading_pair == "Bonk/SOL"
    assert data.pool_address == "pool-orca"
    assert data.trading_status is TradingStatus.TRADING
    assert data.is_verified is True
    assert data.provider == "dexscreener"
    assert data.provider_latency_ms is not None
    assert data.has_market


async def test_prices_are_decimal_not_float() -> None:
    """Money must never round-trip through binary floating point."""
    result = await _provider(_respond({"pairs": [_pair()]})).fetch_many([MINT])
    assert isinstance(result[MINT].price_usd, Decimal)
    assert isinstance(result[MINT].liquidity_usd, Decimal)


async def test_picks_the_deepest_liquidity_pair() -> None:
    """Thin pools carry noisy prices; the deepest pool is canonical."""
    payload = {
        "pairs": [
            _pair(liquidity=100.0, dex="thin"),
            _pair(liquidity=999_999.0, dex="deep"),
            _pair(liquidity=5000.0, dex="mid"),
        ]
    }
    result = await _provider(_respond(payload)).fetch_many([MINT])
    assert result[MINT].dex_name == "deep"


async def test_batches_several_mints_in_one_request() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, json={"pairs": [_pair(MINT), _pair(OTHER)]})

    result = await _provider(httpx.MockTransport(handler)).fetch_many([MINT, OTHER])
    assert len(seen) == 1, "batching must not fan out into per-mint requests"
    assert set(result) == {MINT, OTHER}


async def test_ignores_pair_when_requested_mint_is_not_the_base_token() -> None:
    """Pair-level info must never be treated as metadata for the wrong mint side."""
    pair = _pair(OTHER)
    pair["quoteToken"] = {"address": MINT, "name": "Requested Token", "symbol": "REQ"}
    pair["info"] = {"imageUrl": "https://cdn.test/pair-or-base-token.png"}

    result = await _provider(_respond({"pairs": [pair]})).fetch_many([MINT])

    assert result == {}


async def test_deduplicates_requested_mints() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, json={"pairs": [_pair()]})

    await _provider(httpx.MockTransport(handler)).fetch_many([MINT, MINT, MINT])
    assert seen[0].count(MINT) == 1


# --- Empty and partial results ----------------------------------------------


async def test_unindexed_mint_returns_empty_not_an_error() -> None:
    """`{"pairs": null}` is normal for a token seconds old."""
    result = await _provider(_respond({"pairs": None})).fetch_many([MINT])
    assert result == {}


async def test_ignores_pairs_for_mints_that_were_not_requested() -> None:
    result = await _provider(_respond({"pairs": [_pair(OTHER)]})).fetch_many([MINT])
    assert result == {}


async def test_partial_pair_does_not_raise() -> None:
    payload = {"pairs": [{"baseToken": {"address": MINT}, "pairAddress": "p1"}]}
    result = await _provider(_respond(payload)).fetch_many([MINT])

    data = result[MINT]
    assert data.price_usd is None
    assert data.volume_24h is None
    assert data.trading_status is TradingStatus.TRADING


async def test_junk_values_are_coerced_to_none() -> None:
    pair = _pair()
    pair["priceUsd"] = "not-a-number"
    pair["fdv"] = None
    pair["txns"] = {"h24": {"buys": "many", "sells": 3}}
    result = await _provider(_respond({"pairs": [pair]})).fetch_many([MINT])

    data = result[MINT]
    assert data.price_usd is None
    assert data.fully_diluted_valuation is None
    assert data.buy_count_24h is None
    assert data.sell_count_24h == 3


async def test_dust_liquidity_is_marked_inactive() -> None:
    result = await _provider(_respond({"pairs": [_pair(liquidity=1.0)]})).fetch_many([MINT])
    assert result[MINT].trading_status is TradingStatus.INACTIVE


async def test_empty_input_short_circuits() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("must not call the provider for an empty mint list")

    assert await _provider(httpx.MockTransport(handler)).fetch_many([]) == {}


async def test_oversized_batch_is_rejected() -> None:
    provider = _provider(_respond({"pairs": []}), batch_size=2)
    with pytest.raises(ValueError, match="exceeds batch_size"):
        await provider.fetch_many(["a", "b", "c"])


# --- Reliability -------------------------------------------------------------


async def test_transient_500_is_retried() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(500)
        return httpx.Response(200, json={"pairs": [_pair()]})

    result = await _provider(httpx.MockTransport(handler), max_attempts=4).fetch_many([MINT])
    assert MINT in result
    assert calls["n"] == 3


async def test_timeout_is_retried_then_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("too slow")

    with pytest.raises(ProviderError, match="failed after 2 attempts"):
        await _provider(httpx.MockTransport(handler), max_attempts=2).fetch_many([MINT])


async def test_repeated_failures_open_the_circuit() -> None:
    breaker = CircuitBreaker(name="t", failure_threshold=2, reset_seconds=60.0)
    provider = _provider(
        httpx.MockTransport(lambda r: httpx.Response(500)), breaker=breaker, max_attempts=1
    )

    for _ in range(2):
        with pytest.raises(ProviderError):
            await provider.fetch_many([MINT])

    assert breaker.state is CircuitState.OPEN
    # Subsequent calls fail fast rather than hammering a struggling provider.
    with pytest.raises(ProviderUnavailableError):
        await provider.fetch_many([MINT])


async def test_client_error_is_not_retried() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(400)

    with pytest.raises(ProviderError, match="rejected request"):
        await _provider(httpx.MockTransport(handler), max_attempts=3).fetch_many([MINT])
    assert calls["n"] == 1


async def test_health_reports_circuit_state() -> None:
    provider = _provider(_respond({"pairs": [_pair()]}))
    await provider.fetch_many([MINT])

    health = await provider.health()
    assert health.name == "dexscreener"
    assert health.available is True
    assert health.circuit_state == "closed"
    assert health.last_latency_ms is not None


async def test_unstarted_provider_raises_clearly() -> None:
    with pytest.raises(ProviderError, match="not started"):
        await DexScreenerProvider(base_url="https://api.test").fetch_many([MINT])


class TestSolanaOnly:
    """This platform trades one chain. A pair from anywhere else is not a
    cheaper venue — it is a different asset, and pricing a position from it
    would be silently wrong in the one direction nobody checks.
    """

    def test_a_non_solana_pair_is_never_selected(self):
        provider = DexScreenerProvider()
        mint = "So11111111111111111111111111111111111111112"
        payload = {
            "pairs": [
                {
                    "chainId": "ethereum",
                    "baseToken": {"address": mint, "symbol": "FAKE"},
                    "quoteToken": {"address": "0xquote", "symbol": "WETH"},
                    "priceUsd": "999.0",
                    "liquidity": {"usd": 99_000_000},
                },
                {
                    "chainId": "solana",
                    "baseToken": {"address": mint, "symbol": "SOL"},
                    "quoteToken": {"address": "usdc", "symbol": "USDC"},
                    "priceUsd": "200.0",
                    "liquidity": {"usd": 1_000},
                },
            ]
        }
        result = provider._parse(payload, requested={mint}, latency_ms=1)
        assert mint in result
        # The Ethereum pair has 99,000x the liquidity and would have won on
        # depth alone. It must lose on chain instead.
        assert result[mint].price_usd == Decimal("200.0")

    def test_an_all_foreign_response_yields_nothing_rather_than_a_wrong_price(self):
        provider = DexScreenerProvider()
        mint = "So11111111111111111111111111111111111111112"
        payload = {
            "pairs": [
                {
                    "chainId": "base",
                    "baseToken": {"address": mint, "symbol": "FAKE"},
                    "quoteToken": {"address": "0xq", "symbol": "WETH"},
                    "priceUsd": "1.0",
                    "liquidity": {"usd": 5_000_000},
                }
            ]
        }
        assert provider._parse(payload, requested={mint}, latency_ms=1) == {}

    def test_a_pair_with_no_chain_stated_is_not_assumed_to_be_solana(self):
        provider = DexScreenerProvider()
        mint = "So11111111111111111111111111111111111111112"
        payload = {
            "pairs": [
                {
                    "baseToken": {"address": mint, "symbol": "SOL"},
                    "quoteToken": {"address": "usdc", "symbol": "USDC"},
                    "priceUsd": "200.0",
                    "liquidity": {"usd": 1_000_000},
                }
            ]
        }
        assert provider._parse(payload, requested={mint}, latency_ms=1) == {}
