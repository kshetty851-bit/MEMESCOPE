"""SOL/USD falls back to DexScreener when Jupiter refuses (2026-10-10)."""

from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest

from app.core.config import settings
from app.real_wallet import sol_price

NOW = datetime(2026, 10, 10, 11, 0, tzinfo=UTC)
SOL = settings.EXECUTION_SOL_MINT


def _pair(quote: str, liq: float, price: str, base: str = SOL) -> dict:
    return {"baseToken": {"address": base}, "quoteToken": {"symbol": quote},
            "liquidity": {"usd": liq}, "priceUsd": price}


def _client(pairs: list) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json=pairs)))


async def test_dexscreener_takes_the_deepest_usd_pool() -> None:
    src = sol_price.DexScreenerSolUsdPriceSource(client=_client([
        _pair("USDC", 2_000_000, "150.10"),
        _pair("USDC", 9_000_000, "150.40"),
        _pair("USDT", 500_000, "999"), _pair("BONK", 50_000_000, "1"),
        _pair("USDC", 90_000_000, "7", base="OTHER")]))
    got = await src.current(now=NOW)
    assert got is not None and got.usd == Decimal("150.40")
    assert got.source == "dexscreener_pair"


async def test_dexscreener_with_no_usable_pool_is_none() -> None:
    src = sol_price.DexScreenerSolUsdPriceSource(client=_client([_pair("USDC", 10, "150")]))
    assert await src.current(now=NOW) is None


async def test_current_falls_back_when_jupiter_has_nothing(
        monkeypatch: pytest.MonkeyPatch) -> None:
    async def none(self, *, now):  # Jupiter refusing
        return None

    async def dex(self, *, now):
        return sol_price.SolUsdPrice(usd=Decimal("150"), observed_at=now,
                                     source="dexscreener_pair")

    monkeypatch.setattr(sol_price.JupiterSolUsdPriceSource, "current", none)
    monkeypatch.setattr(sol_price.DexScreenerSolUsdPriceSource, "current", dex)
    got = await sol_price.current(NOW)
    assert got is not None and got.source == "dexscreener_pair"
