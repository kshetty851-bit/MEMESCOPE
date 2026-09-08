"""Copying one wallet forward — and never backwards.

The rule these exist for: **his history is not our history.** The follower
always returns his last hundred swaps, which can span days, so without a hard
cutoff the first tick would open the entire book on trades that are already
finished — at prices his own buying moved hours ago. Half of this file is that
one rule, from several directions.

The rest is the ledger. Every leader trade gets a row whether or not we acted,
because the refusals ARE the finding: "we could copy 40 of his 300 trades" is
the number that decides whether copying works, and a record of only our own
fills cannot produce it.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D
from typing import Any

import pytest
from sqlalchemy import select

from app.models.lab import LabPosition, LabStrategy
from app.models.market import TradingStatus
from app.models.pumpfun import PumpfunSignal
from app.models.token import DiscoveredToken
from app.services.market.providers.base import (
    MarketData,
    MarketDataProvider,
    ProviderHealth,
)
from app.pumpfun import service as svc_mod
from app.pumpfun import spec
from app.pumpfun.follower import LeaderTrade
from app.pumpfun.service import PumpfunService

from tests.integration.test_lab_accounting import _radar_token

pytestmark = pytest.mark.integration

NOW = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)
MINT = "K" + "1" * 20
#: One unit of the book. Read from the registry so a resize cannot leave these
#: assertions quietly asserting the old one.
UNIT = spec.STRATEGIES[0].size_usd


def _trade(side, at, mint=MINT, sig=None, slot=1):
    return LeaderTrade(signature=sig or f"sig-{side}-{at.timestamp()}",
                       slot=slot, mint=mint, side=side, sol_amount=1.0, at=at)


class _Provider(MarketDataProvider):
    """A market that knows about exactly the mints it was handed.

    The default is EMPTY on purpose: on-demand pricing must not turn "we have
    never heard of this token" into a fill just because a test forgot to say
    what the market looks like.
    """

    name = "fake"
    batch_size = 30

    def __init__(self, data=None, raises=None) -> None:
        self.data = data or {}
        self.raises = raises
        self.calls: list[list[str]] = []

    async def fetch_many(self, mint_addresses):
        self.calls.append(list(mint_addresses))
        if self.raises is not None:
            raise self.raises
        return {m: self.data[m] for m in mint_addresses if m in self.data}

    async def health(self):
        return ProviderHealth(name=self.name, available=True, circuit_state="closed")


def _market(mint):
    return MarketData(
        mint_address=mint, price_usd=D("0.001"), liquidity_usd=D("600000"),
        pool_address=f"pool-{mint[:6]}", trading_status=TradingStatus.TRADING,
        provider="fake", observed_at=NOW,
    )


@pytest.fixture
def leader(monkeypatch):
    """Replace the chain with a list we control, and the market with a stub.

    `get_provider` is patched rather than left alone so that a test which
    reaches the on-demand path cannot silently make a real DexScreener call.
    """
    box: dict[str, Any] = {"trades": [], "market": {}, "raises": None}

    async def fake(**_kw):
        return list(box["trades"])

    monkeypatch.setattr(svc_mod, "recent_trades", fake)
    monkeypatch.setattr(svc_mod, "get_provider",
                        lambda *a, **k: _Provider(box["market"], box.get("raises")))
    return box


async def _priced(db_session, mint=MINT, at=None):
    """A token whose LAST snapshot lands on NOW.

    `_radar_token` writes 70 minutes of snapshots from `detected`, so backdating
    it two hours leaves the freshest print 50 minutes old — past the 900-second
    stale guard, and correctly refused as unpriceable. The guard is right; the
    fixture has to produce a market that still exists.
    """
    await _radar_token(db_session, mint=mint,
                       detected=(at or NOW) - timedelta(minutes=69),
                       liq=D("600000"), price=D("0.001"), pool=f"P{mint[:4]}")


async def _row(db_session):
    return (await db_session.execute(
        select(LabStrategy).where(LabStrategy.spec_hash == spec.SPEC_HASH)
    )).scalars().first()


# --------------------------------------------------------------------------
# the watermark
# --------------------------------------------------------------------------


async def test_it_never_copies_a_trade_from_before_it_started(db_session, leader):
    """The rule the owner asked for in one sentence: not the history."""
    await _priced(db_session)
    leader["trades"] = [
        _trade("buy", NOW - timedelta(days=3), sig="old-1"),
        _trade("buy", NOW - timedelta(hours=6), mint="K" + "2" * 20, sig="old-2"),
    ]
    out = await PumpfunService(db_session).tick(now=NOW)

    row = await _row(db_session)
    opens = (await db_session.execute(
        select(LabPosition).where(LabPosition.strategy_row_id == row.id)
    )).scalars().all()
    assert opens == [], "his past must never become our book"
    assert out["signals"].get("before_watch_start") == 2
    assert row.cash == spec.STARTING_EQUITY


async def test_the_refusal_is_recorded_not_silently_dropped(db_session, leader):
    """A skip nobody can count is a skip nobody can learn from."""
    leader["trades"] = [_trade("buy", NOW - timedelta(days=2), sig="old-x")]
    await PumpfunService(db_session).tick(now=NOW)
    sig = (await db_session.execute(select(PumpfunSignal))).scalars().first()
    assert sig.outcome == "before_watch_start"
    assert sig.acted is False


async def test_a_trade_after_the_start_IS_copied(db_session, leader):
    """The other half of the rule — forward trades must actually land."""
    await _priced(db_session)
    await PumpfunService(db_session).tick(now=NOW)          # activates, watermark = NOW
    leader["trades"] = [_trade("buy", NOW + timedelta(seconds=30), sig="new-1")]
    await PumpfunService(db_session).tick(now=NOW + timedelta(seconds=60))

    row = await _row(db_session)
    pos = (await db_session.execute(
        select(LabPosition).where(LabPosition.strategy_row_id == row.id)
    )).scalars().all()
    assert len(pos) == 1
    assert pos[0].mint_address == MINT
    assert pos[0].size_usd == UNIT, "our size, not his"
    assert row.cash == spec.STARTING_EQUITY - UNIT


async def test_a_signal_older_than_the_age_limit_is_refused(db_session, leader):
    """He holds 8.5 minutes. Copying an hour-late trade is a different trade."""
    await _priced(db_session)
    await PumpfunService(db_session).tick(now=NOW)
    stale = NOW + timedelta(seconds=30)
    leader["trades"] = [_trade("buy", stale, sig="stale-1")]
    out = await PumpfunService(db_session).tick(
        now=stale + timedelta(seconds=spec.MAX_SIGNAL_AGE_SECONDS + 60))
    assert out["signals"].get("stale_signal") == 1


# --------------------------------------------------------------------------
# mirroring
# --------------------------------------------------------------------------


async def test_when_he_sells_we_sell(db_session, leader):
    await _priced(db_session)
    await PumpfunService(db_session).tick(now=NOW)
    leader["trades"] = [_trade("buy", NOW + timedelta(seconds=10), sig="b1")]
    await PumpfunService(db_session).tick(now=NOW + timedelta(seconds=20))

    leader["trades"] = [_trade("sell", NOW + timedelta(minutes=5), sig="s1")]
    await PumpfunService(db_session).tick(now=NOW + timedelta(minutes=5, seconds=10))

    row = await _row(db_session)
    pos = (await db_session.execute(
        select(LabPosition).where(LabPosition.strategy_row_id == row.id)
    )).scalars().first()
    assert pos.status == "closed"
    assert pos.exit_reason == "leader_sold"
    assert row.cash > spec.STARTING_EQUITY - UNIT


async def test_one_leader_trade_is_never_copied_twice(db_session, leader):
    """Polls overlap. The same transaction stays in view for many ticks."""
    await _priced(db_session)
    await PumpfunService(db_session).tick(now=NOW)
    leader["trades"] = [_trade("buy", NOW + timedelta(seconds=10), sig="dup")]
    for i in range(4):
        await PumpfunService(db_session).tick(now=NOW + timedelta(seconds=20 + i))

    row = await _row(db_session)
    pos = (await db_session.execute(
        select(LabPosition).where(LabPosition.strategy_row_id == row.id)
    )).scalars().all()
    assert len(pos) == 1
    assert row.cash == spec.STARTING_EQUITY - UNIT


async def test_a_token_no_market_knows_is_refused_not_guessed(db_session, leader):
    """A mint with no indexed pool anywhere stays refused, and says so.

    On-demand pricing removes our own blind spot, not the market's absence:
    when the provider comes back empty there is still no price, and inventing
    one would make the whole book fiction. `no_market` and not `unpriceable`,
    because this one is a fact about the token.
    """
    await PumpfunService(db_session).tick(now=NOW)
    leader["trades"] = [_trade("buy", NOW + timedelta(seconds=10),
                               mint="Z" + "9" * 20, sig="nop")]
    out = await PumpfunService(db_session).tick(now=NOW + timedelta(seconds=20))
    assert out["signals"].get("no_market") == 1
    row = await _row(db_session)
    assert row.cash == spec.STARTING_EQUITY


# --------------------------------------------------------------------------
# on-demand pricing — the v1.0.0 coverage fix
# --------------------------------------------------------------------------


async def test_a_mint_the_scanner_never_saw_is_fetched_and_copied(db_session, leader):
    """v1.0.0 copied 7 of 102 because his names were not in our pipeline.

    The refusal was about our coverage, not his trade. Asked at signal time,
    the provider knows the token, and the position opens.
    """
    unknown = "N" + "7" * 20
    await PumpfunService(db_session).tick(now=NOW)
    leader["market"] = {unknown: _market(unknown)}
    leader["trades"] = [_trade("buy", NOW + timedelta(seconds=10),
                               mint=unknown, sig="od1", slot=999)]
    out = await PumpfunService(db_session).tick(now=NOW + timedelta(seconds=20))
    assert out["signals"].get("opened") == 1

    pos = (await db_session.execute(
        select(LabPosition).where(LabPosition.mint_address == unknown)
    )).scalars().first()
    assert pos is not None and pos.entry_price == D("0.001")


async def test_the_registration_carries_his_real_transaction(db_session, leader):
    """Provenance is a chain observation. His swap IS one, so it is recorded
    rather than synthesised — and never as the pump.fun program, which
    `_is_pumpfun` and the real-wallet safety gate both read."""
    unknown = "N" + "6" * 20
    await PumpfunService(db_session).tick(now=NOW)
    leader["market"] = {unknown: _market(unknown)}
    leader["trades"] = [_trade("buy", NOW + timedelta(seconds=10),
                               mint=unknown, sig="realsig", slot=31415)]
    await PumpfunService(db_session).tick(now=NOW + timedelta(seconds=20))

    token = (await db_session.execute(
        select(DiscoveredToken).where(DiscoveredToken.mint_address == unknown)
    )).scalars().first()
    assert token is not None
    assert token.signature == "realsig" and token.slot == 31415
    assert token.source_program == svc_mod.SOURCE_PROGRAM != spec.LEADER_ADDRESS


async def test_the_fill_is_marked_as_having_needed_a_fetch(db_session, leader):
    """v1.0.0 could not have opened it, so the two runs stay comparable."""
    from app.models.lab import LabDecision

    unknown = "N" + "5" * 20
    await PumpfunService(db_session).tick(now=NOW)
    leader["market"] = {unknown: _market(unknown)}
    leader["trades"] = [_trade("buy", NOW + timedelta(seconds=10),
                               mint=unknown, sig="od3")]
    await PumpfunService(db_session).tick(now=NOW + timedelta(seconds=20))

    decision = (await db_session.execute(
        select(LabDecision).where(LabDecision.mint_address == unknown)
    )).scalars().first()
    assert decision.features["priced_on_demand"] is True


async def test_a_token_we_already_price_costs_no_provider_call(
    db_session, leader, monkeypatch
):
    """The fetch is a fallback, not a step. Calling out for a mint the scanner
    is already refreshing would add a round trip to every single fill."""
    seen: list[list[str]] = []

    class _Counting(_Provider):
        async def fetch_many(self, mints):
            seen.append(list(mints))
            return await super().fetch_many(mints)

    monkeypatch.setattr(svc_mod, "get_provider",
                        lambda *a, **k: _Counting(leader["market"]))

    await _priced(db_session)
    await PumpfunService(db_session).tick(now=NOW)
    leader["trades"] = [_trade("buy", NOW + timedelta(seconds=10), sig="cheap")]
    out = await PumpfunService(db_session).tick(now=NOW + timedelta(seconds=20))
    assert out["signals"].get("opened") == 1
    assert seen == []


async def test_a_provider_outage_is_not_a_finding_about_his_token(db_session, leader):
    """The distinction the whole split exists for.

    `_defer` in the enrichment service records the lesson: a token cannot be
    judged by a call that never left the process. If a DexScreener outage were
    counted as `no_market`, our bad afternoon would be read off the coverage
    panel as evidence that his coins have no liquidity.
    """
    from app.services.market.providers.base import ProviderError

    await PumpfunService(db_session).tick(now=NOW)
    leader["raises"] = ProviderError("dexscreener is down")
    leader["trades"] = [_trade("buy", NOW + timedelta(seconds=10),
                               mint="Q" + "4" * 20, sig="down")]
    out = await PumpfunService(db_session).tick(now=NOW + timedelta(seconds=20))
    assert out["signals"].get("quote_unavailable") == 1
    assert out["signals"].get("no_market") is None

    signal = (await db_session.execute(
        select(PumpfunSignal).where(PumpfunSignal.signature == "down")
    )).scalars().first()
    assert signal.outcome == "quote_unavailable" and signal.acted is False


async def test_a_print_we_may_not_act_on_is_not_an_absent_market(db_session, leader):
    """A pool that exists but is not trading is a third answer again.

    The provider knows the token — so it is not `no_market` — but the firewall
    refuses the print, so the book must not open on it either.
    """
    dead = "Q" + "3" * 20
    await PumpfunService(db_session).tick(now=NOW)
    leader["market"] = {dead: MarketData(
        mint_address=dead, pool_address="pool-dead",
        trading_status=TradingStatus.INACTIVE, provider="fake", observed_at=NOW,
    )}
    leader["trades"] = [_trade("buy", NOW + timedelta(seconds=10),
                               mint=dead, sig="halted")]
    out = await PumpfunService(db_session).tick(now=NOW + timedelta(seconds=20))
    assert out["signals"].get("unpriceable") == 1
    row = await _row(db_session)
    assert row.cash == spec.STARTING_EQUITY


async def test_the_book_stops_at_ten_units(db_session, leader):
    await PumpfunService(db_session).tick(now=NOW)
    mints = []
    for i in range(12):
        m = f"M{i}" + "8" * 19
        await _priced(db_session, mint=m)
        mints.append(m)
    leader["trades"] = [
        _trade("buy", NOW + timedelta(seconds=10 + i), mint=m, sig=f"c{i}")
        for i, m in enumerate(mints)
    ]
    out = await PumpfunService(db_session).tick(now=NOW + timedelta(seconds=30))
    assert out["signals"].get("opened") == 10
    assert out["signals"].get("max_concurrent") == 2


# --------------------------------------------------------------------------
# tranches — v1.2.0 mirrors the SHAPE of his sizing
# --------------------------------------------------------------------------


async def test_his_second_buy_adds_a_unit_instead_of_being_refused(db_session, leader):
    """He averages 1.9 buys a name. v1.1.0 threw the second one away."""
    await _priced(db_session)
    await PumpfunService(db_session).tick(now=NOW)
    leader["trades"] = [_trade("buy", NOW + timedelta(seconds=10), sig="d1")]
    await PumpfunService(db_session).tick(now=NOW + timedelta(seconds=20))
    leader["trades"] = [_trade("buy", NOW + timedelta(seconds=40), sig="d2")]
    out = await PumpfunService(db_session).tick(now=NOW + timedelta(seconds=50))
    assert out["signals"].get("added") == 1

    pos = (await db_session.execute(
        select(LabPosition).where(LabPosition.mint_address == MINT)
    )).scalars().all()
    # ONE row, not two: `uq_lab_position_once` allows only one per (strategy,
    # mint) and every other lab depends on that.
    assert len(pos) == 1
    assert pos[0].size_usd == UNIT * 2
    row = await _row(db_session)
    assert row.cash == spec.STARTING_EQUITY - UNIT * 2


async def test_a_name_cannot_swallow_the_book(db_session, leader):
    await _priced(db_session)
    await PumpfunService(db_session).tick(now=NOW)
    for i in range(spec.MAX_UNITS_PER_MINT):
        leader["trades"] = [_trade("buy", NOW + timedelta(seconds=10 + i),
                                   sig=f"u{i}")]
        await PumpfunService(db_session).tick(now=NOW + timedelta(seconds=20 + i))
    leader["trades"] = [_trade("buy", NOW + timedelta(seconds=100), sig="over")]
    out = await PumpfunService(db_session).tick(now=NOW + timedelta(seconds=110))
    assert out["signals"].get("max_units_per_mint") == 1

    pos = (await db_session.execute(
        select(LabPosition).where(LabPosition.mint_address == MINT)
    )).scalars().first()
    assert pos.size_usd == D("10") * spec.MAX_UNITS_PER_MINT


async def test_his_sell_releases_one_unit_not_the_whole_position(db_session, leader):
    """The other half of the asymmetry. He sells in ~1.9 tranches; closing the
    lot on the first one exits while he is still holding."""
    await _priced(db_session)
    await PumpfunService(db_session).tick(now=NOW)
    for i in range(2):
        leader["trades"] = [_trade("buy", NOW + timedelta(seconds=10 + i),
                                   sig=f"b{i}")]
        await PumpfunService(db_session).tick(now=NOW + timedelta(seconds=20 + i))

    pos = (await db_session.execute(
        select(LabPosition).where(LabPosition.mint_address == MINT)
    )).scalars().first()
    whole = pos.quantity

    leader["trades"] = [_trade("sell", NOW + timedelta(seconds=60), sig="s1")]
    out = await PumpfunService(db_session).tick(now=NOW + timedelta(seconds=70))
    assert out["signals"].get("trimmed") == 1

    await db_session.refresh(pos)
    assert pos.status == "open"
    assert pos.quantity_remaining == whole / 2
    assert pos.banked_proceeds_usd > 0
    # The frozen multiple is defined on the ORIGINAL stake and quantity, so a
    # trim must leave both alone — see `_units_held`.
    assert pos.size_usd == D("20") and pos.quantity == whole
    # A hand trim is not the registry's PARTIAL rule and must never claim to be.
    assert pos.partial_done is False and pos.partial_at is None

    leader["trades"] = [_trade("sell", NOW + timedelta(seconds=90), sig="s2")]
    out = await PumpfunService(db_session).tick(now=NOW + timedelta(seconds=100))
    assert out["signals"].get("closed") == 1
    await db_session.refresh(pos)
    assert pos.status == "closed"


async def test_trimming_does_not_inflate_the_executable_multiple(db_session, leader):
    """The bug this design nearly shipped: decrementing `size_usd` on a trim
    would divide the whole position's proceeds by a reduced cost."""
    await _priced(db_session)
    await PumpfunService(db_session).tick(now=NOW)
    for i in range(2):
        leader["trades"] = [_trade("buy", NOW + timedelta(seconds=10 + i),
                                   sig=f"m{i}")]
        await PumpfunService(db_session).tick(now=NOW + timedelta(seconds=20 + i))
    leader["trades"] = [_trade("sell", NOW + timedelta(seconds=60), sig="ms")]
    await PumpfunService(db_session).tick(now=NOW + timedelta(seconds=70))

    pos = (await db_session.execute(
        select(LabPosition).where(LabPosition.mint_address == MINT)
    )).scalars().first()
    # Flat market, two $10 units in: a fill that cost $20 is worth about $20.
    assert pos.last_exec_multiple < D("1.05")


async def test_we_never_hold_the_same_token_twice(db_session, leader):
    """Superseded by tranches, kept as the constraint it protects: one ROW per
    (strategy, mint), whatever the unit count."""
    await _priced(db_session)
    await PumpfunService(db_session).tick(now=NOW)
    leader["trades"] = [_trade("buy", NOW + timedelta(seconds=10), sig="d1")]
    await PumpfunService(db_session).tick(now=NOW + timedelta(seconds=20))
    leader["trades"] = [_trade("buy", NOW + timedelta(seconds=40), sig="d2")]
    out = await PumpfunService(db_session).tick(now=NOW + timedelta(seconds=50))
    assert out["signals"].get("added") == 1


async def test_a_sell_of_something_we_never_bought_is_recorded(db_session, leader):
    """He sells names we could not price on the way in. That gap is the finding,
    so it is counted rather than ignored."""
    await PumpfunService(db_session).tick(now=NOW)
    leader["trades"] = [_trade("sell", NOW + timedelta(seconds=10), sig="orphan")]
    out = await PumpfunService(db_session).tick(now=NOW + timedelta(seconds=20))
    assert out["signals"].get("not_held") == 1


async def test_the_board_counts_a_tranche_as_copied_not_as_a_miss(db_session, leader):
    """`copied` reads the `acted` flag, not a list of outcome names.

    The tranche rules added `added` and `trimmed`; a hardcoded
    ("opened", "closed") would have counted both as misses and printed them
    under "why we missed" on the page.
    """
    from app.pumpfun.api import board

    await _priced(db_session)
    await PumpfunService(db_session).tick(now=NOW)
    for i in range(2):
        leader["trades"] = [_trade("buy", NOW + timedelta(seconds=10 + i),
                                   sig=f"bd{i}")]
        await PumpfunService(db_session).tick(now=NOW + timedelta(seconds=20 + i))
    leader["trades"] = [_trade("sell", NOW + timedelta(seconds=60), sig="bds")]
    await PumpfunService(db_session).tick(now=NOW + timedelta(seconds=70))

    cov = (await board(db_session))["coverage"]
    assert cov["by_outcome"].get("added") == 1
    assert cov["by_outcome"].get("trimmed") == 1
    assert cov["copied"] == 3                      # opened + added + trimmed
    assert "added" not in cov["refusals"]
    assert "trimmed" not in cov["refusals"]
    assert "opened" not in cov["refusals"]


def test_the_registry_is_distinct_from_the_other_tournaments():
    from app.compound import spec as cspec
    from app.lab import spec as v7

    assert len({spec.SPEC_HASH, cspec.SPEC_HASH, v7.SPEC_HASH}) == 3
    assert spec.STRATEGIES[0].size_usd * spec.STRATEGIES[0].max_concurrent \
        <= spec.STARTING_EQUITY


# --------------------------------------------------------------------------
# the request itself
# --------------------------------------------------------------------------


async def test_the_follower_asks_helius_for_swaps_only(monkeypatch):
    """Not an optimisation — the difference between working and silently
    never trading.

    This wallet receives ~25 airdrop dust transfers an hour. Measured on
    2026-09-04 its most recent 100 transactions were 95 TRANSFERs and 5 account
    initialisations, spanning four hours and containing ZERO swaps; the same
    request with `type=SWAP` returned 21 swaps over three days. The lab shipped
    without this and ticked green while seeing nothing.

    Asserted on the request that is actually made, because the bug was
    invisible in every other signal: the task succeeded, the book was empty,
    and nothing was wrong anywhere a test was looking.
    """
    from app.pumpfun import follower as f

    seen: dict[str, object] = {}

    class _Resp:
        status_code = 200

        @staticmethod
        def json():
            return []

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, params=None):
            seen["params"] = params or {}
            return _Resp()

    monkeypatch.setattr(f.httpx, "AsyncClient", lambda **_kw: _Client())
    monkeypatch.setattr(f.settings, "HELIUS_API_KEY",
                        type("S", (), {"get_secret_value": staticmethod(lambda: "k")})())
    await f.recent_trades()
    assert seen["params"].get("type") == "SWAP"


def test_a_trade_is_read_from_his_own_balance_change_not_the_route():
    """How he routed the swap must not decide whether we can copy it.

    Measured on prod over his last 21 swaps: naming him in `tokenTransfers`
    missed 4 (he routes through aggregator accounts), requiring a native SOL
    leg missed 13 (he trades wrapped), and `events.swap` was present on 13 and
    sometimes described a different account entirely. Reading his own token
    balance change resolves 17 of 21.

    Side is the SIGN of that change. The SOL amount is deliberately optional —
    we size from our own book, so a trade whose SOL leg cannot be attributed is
    still perfectly copyable, and demanding a number we never use would discard
    most of the feed.
    """
    from app.pumpfun.follower import _leader_sol, _traded

    addr = "LEADER"
    wrapped_buy = {
        "accountData": [
            {"account": addr, "nativeBalanceChange": 0, "tokenBalanceChanges": [
                {"userAccount": addr, "mint": "TOKEN",
                 "rawTokenAmount": {"tokenAmount": "5000", "decimals": 6}},
                {"userAccount": addr,
                 "mint": "So11111111111111111111111111111111111111112",
                 "rawTokenAmount": {"tokenAmount": "-2000000000", "decimals": 9}},
            ]},
            # somebody else's leg in the same transaction
            {"account": "OTHER", "nativeBalanceChange": -99, "tokenBalanceChanges": [
                {"userAccount": "OTHER", "mint": "NOISE",
                 "rawTokenAmount": {"tokenAmount": "999999", "decimals": 6}}]},
        ]
    }
    assert _traded(wrapped_buy, addr) == ("TOKEN", "buy")
    assert _leader_sol(wrapped_buy, addr) == 2.0

    sell = {"accountData": [{"account": addr, "nativeBalanceChange": 0,
        "tokenBalanceChanges": [{"userAccount": addr, "mint": "TOKEN",
            "rawTokenAmount": {"tokenAmount": "-5000", "decimals": 6}}]}]}
    assert _traded(sell, addr) == ("TOKEN", "sell")
    # No attributable SOL leg, and it is still a copyable trade.
    assert _leader_sol(sell, addr) is None

    # A route that leaves a residue of an intermediate token: the LARGEST
    # absolute move is the one he was actually trading.
    residue = {"accountData": [{"account": addr, "nativeBalanceChange": 0,
        "tokenBalanceChanges": [
            {"userAccount": addr, "mint": "DUST",
             "rawTokenAmount": {"tokenAmount": "3", "decimals": 6}},
            {"userAccount": addr, "mint": "REAL",
             "rawTokenAmount": {"tokenAmount": "900000", "decimals": 6}}]}]}
    assert _traded(residue, addr) == ("REAL", "buy")

    # Nothing of ours moved — not our trade.
    assert _traded({"accountData": [{"account": "OTHER", "tokenBalanceChanges": [
        {"userAccount": "OTHER", "mint": "X",
         "rawTokenAmount": {"tokenAmount": "1", "decimals": 6}}]}]}, addr) is None
