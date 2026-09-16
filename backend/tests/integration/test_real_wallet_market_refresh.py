"""A current reading before the safety gate, fetched only when there is none.

For the graduation arm the platform's first snapshot landed a median 82s after
the lab decided, so the gate refused 181 of 233 trades for having no reading.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.models.market import TradingStatus
from app.models.token import DiscoveredToken
from app.real_wallet.market_refresh import FRESH_S, ensure_fresh
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

    def __init__(self, *, fails: bool = False, at: datetime = NOW) -> None:
        self.calls: list[list[str]] = []
        self.fails = fails
        self.at = at

    async def fetch_many(self, mint_addresses: Sequence[str]) -> dict[str, MarketData]:
        self.calls.append(list(mint_addresses))
        if self.fails:
            raise ProviderError("down")
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
