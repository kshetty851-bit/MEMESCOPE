"""The price a buy's quote is judged against: the pool's own, from the
graduation lab's live read of its vaults, when that read is recent."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.labs.graduation.models import SOURCE_HELD_WS, GradPostgradSample
from app.real_wallet_safety.service import POOL_PRICE_TRUST_S, RealWalletSafetyGate

pytestmark = pytest.mark.integration

MINT = "ZR3PxkevGitHubPoolPriceTest111111111111pump"
AT = datetime(2026, 9, 18, 18, 14, 5, tzinfo=UTC)
#: The feed's stale print: its dollar price is wrong, its SOL rate (112.34) is not.
FEED = SimpleNamespace(price_usd=Decimal("0.005498"), price_native=Decimal("0.00004894"))


async def _sample(session, *, age_s: float, source: str = SOURCE_HELD_WS,
                  native: str = "0.000005651772868270") -> None:
    session.add(GradPostgradSample(
        ts=AT - timedelta(seconds=age_s), mint=MINT, source=source,
        pair_address="Eo66ZRXuPool", dex_id="pumpswap",
        price_native=Decimal(native), liquidity_usd=Decimal("67084")))
    await session.flush()


async def test_a_recent_vault_read_prices_the_quote(db_session) -> None:
    await _sample(db_session, age_s=3)
    got = await RealWalletSafetyGate(db_session)._pool_price(MINT, FEED, AT)
    assert got is not None
    assert abs(got / Decimal("0.000635") - 1) < Decimal("0.01")


@pytest.mark.parametrize("age_s, source", [
    (POOL_PRICE_TRUST_S + 1, SOURCE_HELD_WS),   # too old to stand for the pool now
    (-2, SOURCE_HELD_WS),                         # after the moment being judged
    (3, "dexscreener"),                           # the feed itself, not the vaults
])
async def test_only_a_recent_vault_read_stands_in(db_session, age_s, source) -> None:
    await _sample(db_session, age_s=age_s, source=source)
    assert await RealWalletSafetyGate(db_session)._pool_price(MINT, FEED, AT) is None


async def test_without_the_feeds_sol_rate_there_is_no_dollar_price(db_session) -> None:
    await _sample(db_session, age_s=3)
    no_rate = SimpleNamespace(price_usd=Decimal("0.005498"), price_native=None)
    assert await RealWalletSafetyGate(db_session)._pool_price(MINT, no_rate, AT) is None
