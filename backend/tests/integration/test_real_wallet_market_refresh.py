"""A current reading before the safety gate, fetched only when there is none.

For the graduation arm the platform's first snapshot landed a median 82s after
the lab decided, so the gate refused 181 of 233 trades for having no reading.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.labs.graduation.models import GradPostgradSample
from app.models.market import TradingStatus
from app.models.token import DiscoveredToken
from app.real_wallet.market_refresh import FRESH_S, LAB_PROVIDER, ensure_fresh
from app.repositories.market import MarketSnapshotRepository
from app.services.market.providers.base import (
    MarketData,
    MarketDataProvider,
    ProviderError,
    ProviderHealth,
)

pytestmark = pytest.mark.integration

MINT = "Awa4V1xpYjvVtzjhqXAB6tfxvDdQv8jQ62JXTjspump"
NOW = datetime(2026, 9, 16, 14, 7, 50, tzinfo=UTC)


class Provider(MarketDataProvider):
    name = "fake"
    batch_size = 30

    def __init__(self, *, fails: bool = False, listed: bool = True,
                 at: datetime = NOW) -> None:
        self.calls: list[list[str]] = []
        self.fails = fails
        self.listed = listed
        self.at = at

    async def fetch_many(self, mint_addresses: Sequence[str]) -> dict[str, MarketData]:
        self.calls.append(list(mint_addresses))
        if self.fails:
            raise ProviderError("down")
        if not self.listed:  # DexScreener answers, with no pair for a pool this new
            return {}
        return {m: MarketData(
            mint_address=m, price_usd=Decimal("0.007655"),
            price_native=Decimal("0.00007898"), liquidity_usd=Decimal("226957.33"),
            dex_name="pumpswap", pool_address="3AUWJB3UckEypW9QFn8gaFtiLpr5FPhBpb4Yc8jnF9dw",
            trading_status=TradingStatus.TRADING, provider=self.name,
            observed_at=self.at) for m in mint_addresses}

    async def health(self) -> ProviderHealth:
        return ProviderHealth(name=self.name, available=True, circuit_state="closed")


async def _token(session) -> DiscoveredToken:
    token = DiscoveredToken(mint_address=MINT, signature=f"sig-{MINT}", slot=1,
                            discovered_at=NOW - timedelta(minutes=1))
    session.add(token)
    await session.flush()
    return token


async def test_a_token_with_no_reading_gets_one_before_the_gate(db_session):
    await _token(db_session)
    provider = Provider()
    reading = await ensure_fresh(db_session, MINT, now=NOW, provider=provider)
    assert reading.status == "refreshed"
    assert provider.calls == [[MINT]]
    snapshot = await MarketSnapshotRepository(db_session).latest_for_mint(MINT)
    assert snapshot is not None
    assert snapshot.price_usd == Decimal("0.007655")
    assert snapshot.dex_name == "pumpswap"


async def test_a_current_reading_is_not_fetched_again(db_session):
    await _token(db_session)
    first = Provider()
    await ensure_fresh(db_session, MINT, now=NOW, provider=first)
    snapshot = await MarketSnapshotRepository(db_session).latest_for_mint(MINT)
    assert snapshot is not None
    soon = snapshot.captured_at + timedelta(seconds=FRESH_S - 1)
    late = snapshot.captured_at + timedelta(seconds=FRESH_S + 1)
    again = Provider(at=late + timedelta(milliseconds=150))
    assert (await ensure_fresh(db_session, MINT, now=soon, provider=again)).status == "fresh"
    assert again.calls == []
    # Past the window it is asked for again, and says when the new one was taken.
    reading = await ensure_fresh(db_session, MINT, now=late, provider=again)
    assert reading == ("refreshed", late + timedelta(milliseconds=150))
    assert again.calls == [[MINT]]


async def test_a_failed_fetch_leaves_the_refusal_to_the_gate(db_session):
    """Never raises, never invents a reading: the gate then finds none."""
    await _token(db_session)
    assert (await ensure_fresh(db_session, MINT, now=NOW,
                               provider=Provider(fails=True))).status == "no_reading"
    assert await MarketSnapshotRepository(db_session).latest_for_mint(MINT) is None


async def test_a_token_the_platform_never_discovered_is_left_alone(db_session):
    provider = Provider()
    assert (await ensure_fresh(db_session, MINT, now=NOW, provider=provider)).status == "token_unknown"
    assert provider.calls == []


async def test_the_gate_judges_a_new_reading_from_when_it_was_taken(db_session, monkeypatch):
    """A fetch finishes after the moment the executor started from. Judged
    from that earlier moment the reading sits in the future, and the gate
    refuses a reading from the future as stale — the refresh would have
    refused the very buy it exists to allow."""
    from types import SimpleNamespace

    from app.real_wallet import executor as ex
    from app.real_wallet.market_refresh import Reading

    taken = NOW + timedelta(milliseconds=200)
    seen: list[datetime] = []

    async def _fresh(session, mint, *, now):
        return Reading("refreshed", taken)

    class _Gate:
        def __init__(self, session):
            pass

        async def evaluate(self, *, mint_address, trade_size_usd, now):
            seen.append(now)
            return SimpleNamespace(decision="REJECT", reason_codes=("TEST",),
                                   policy_version="t", evaluation_id=None)

    class _Repo:
        async def transition(self, **kw):
            return None

    monkeypatch.setattr(ex.market_refresh, "ensure_fresh", _fresh)
    monkeypatch.setattr(ex, "RealWalletSafetyGate", _Gate)
    executor = ex.RealWalletExecutor(db_session)
    executor._repository = _Repo()
    intent = SimpleNamespace(id="i1", mint_address=MINT, side="BUY",
                             requested_usd=Decimal("100"), state="created")
    await executor._run_safety(intent, NOW)
    assert seen == [taken]


# --- the graduation lab's own poll, when the provider has not listed the pool --

LAB_PAIR = "8xQ3uUoLabPairPumpSwap1111111111111111111111"


async def _lab_poll(session, *, age_s: float, liquidity: str = "91799.00",
                    source: str = "dexscreener") -> datetime:
    """The lab's DexScreener sample of the pool its paper book just bought."""
    ts = NOW - timedelta(seconds=age_s)
    session.add(GradPostgradSample(
        ts=ts, mint=MINT, source=source, pair_address=LAB_PAIR, dex_id="pumpswap",
        price_usd=Decimal("0.001227"), price_native=Decimal("0.00001211"),
        liquidity_usd=Decimal(liquidity)))
    await session.flush()
    return ts


async def test_a_pool_the_provider_has_not_listed_is_read_from_the_lab(db_session):
    """ChatGPT, 2026-09-17 20:30: the lab's poll had the pool three seconds
    before the wallet refused it for having no reading at all."""
    await _token(db_session)
    taken = await _lab_poll(db_session, age_s=3)
    reading = await ensure_fresh(db_session, MINT, now=NOW, provider=Provider(listed=False))
    assert reading == ("refreshed_from_lab", taken)
    snapshot = await MarketSnapshotRepository(db_session).latest_for_mint(MINT)
    assert snapshot is not None
    # Its own source and its own time: the gate ages it from when it was polled.
    assert (snapshot.provider, snapshot.captured_at) == (LAB_PROVIDER, taken)
    assert (snapshot.price_usd, snapshot.liquidity_usd) == (
        Decimal("0.001227"), Decimal("91799.00"))
    assert (snapshot.dex_name, snapshot.pool_address) == ("pumpswap", LAB_PAIR)
    assert snapshot.trading_status is TradingStatus.TRADING


async def test_the_providers_own_reading_wins_when_it_has_one(db_session):
    await _token(db_session)
    await _lab_poll(db_session, age_s=3)
    reading = await ensure_fresh(db_session, MINT, now=NOW, provider=Provider())
    assert reading.status == "refreshed"
    snapshot = await MarketSnapshotRepository(db_session).latest_for_mint(MINT)
    assert snapshot is not None and snapshot.provider == "fake"


@pytest.mark.parametrize("age_s, source", [
    (FRESH_S + 1, "dexscreener"),   # older than a reading this module would reuse
    (3, "geckoterminal"),           # a candle backfilled later, not a live poll
])
async def test_only_a_current_live_poll_stands_in(db_session, age_s, source):
    await _token(db_session)
    await _lab_poll(db_session, age_s=age_s, source=source)
    reading = await ensure_fresh(db_session, MINT, now=NOW, provider=Provider(listed=False))
    assert reading.status == "no_reading"
    assert await MarketSnapshotRepository(db_session).latest_for_mint(MINT) is None


async def test_a_lab_reading_is_judged_by_the_providers_own_rule(db_session):
    """Shallower than DexScreener calls tradeable: written as INACTIVE, which
    the gate refuses exactly as it would refuse the provider's own print."""
    await _token(db_session)
    await _lab_poll(db_session, age_s=3, liquidity="42.00")
    await ensure_fresh(db_session, MINT, now=NOW, provider=Provider(listed=False))
    snapshot = await MarketSnapshotRepository(db_session).latest_for_mint(MINT)
    assert snapshot is not None
    assert snapshot.trading_status is TradingStatus.INACTIVE
