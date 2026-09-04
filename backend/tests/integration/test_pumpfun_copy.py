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

import pytest
from sqlalchemy import select

from app.models.lab import LabPosition, LabStrategy
from app.models.pumpfun import PumpfunSignal
from app.pumpfun import service as svc_mod
from app.pumpfun import spec
from app.pumpfun.follower import LeaderTrade
from app.pumpfun.service import PumpfunService

from tests.integration.test_lab_accounting import _radar_token

pytestmark = pytest.mark.integration

NOW = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)
MINT = "K" + "1" * 20


def _trade(side, at, mint=MINT, sig=None):
    return LeaderTrade(signature=sig or f"sig-{side}-{at.timestamp()}",
                       mint=mint, side=side, sol_amount=1.0, at=at)


@pytest.fixture
def leader(monkeypatch):
    """Replace the chain with a list we control."""
    box: dict[str, list[LeaderTrade]] = {"trades": []}

    async def fake(**_kw):
        return list(box["trades"])

    monkeypatch.setattr(svc_mod, "recent_trades", fake)
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
    assert pos[0].size_usd == D("20"), "our size, not his"
    assert row.cash == spec.STARTING_EQUITY - D("20")


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
    assert row.cash > spec.STARTING_EQUITY - D("20")


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
    assert row.cash == spec.STARTING_EQUITY - D("20")


async def test_a_token_we_cannot_price_is_refused_not_guessed(db_session, leader):
    """Only 10% of his month had enough snapshots here. Inventing an entry
    price for the rest would make the whole book fiction."""
    await PumpfunService(db_session).tick(now=NOW)
    leader["trades"] = [_trade("buy", NOW + timedelta(seconds=10),
                               mint="Z" + "9" * 20, sig="nop")]
    out = await PumpfunService(db_session).tick(now=NOW + timedelta(seconds=20))
    assert out["signals"].get("unpriceable") == 1
    row = await _row(db_session)
    assert row.cash == spec.STARTING_EQUITY


async def test_the_book_stops_at_five_positions(db_session, leader):
    await PumpfunService(db_session).tick(now=NOW)
    mints = []
    for i in range(7):
        m = f"M{i}" + "8" * 19
        await _priced(db_session, mint=m)
        mints.append(m)
    leader["trades"] = [
        _trade("buy", NOW + timedelta(seconds=10 + i), mint=m, sig=f"c{i}")
        for i, m in enumerate(mints)
    ]
    out = await PumpfunService(db_session).tick(now=NOW + timedelta(seconds=30))
    assert out["signals"].get("opened") == 5
    assert out["signals"].get("max_concurrent") == 2


async def test_we_never_hold_the_same_token_twice(db_session, leader):
    await _priced(db_session)
    await PumpfunService(db_session).tick(now=NOW)
    leader["trades"] = [_trade("buy", NOW + timedelta(seconds=10), sig="d1")]
    await PumpfunService(db_session).tick(now=NOW + timedelta(seconds=20))
    leader["trades"] = [_trade("buy", NOW + timedelta(seconds=40), sig="d2")]
    out = await PumpfunService(db_session).tick(now=NOW + timedelta(seconds=50))
    assert out["signals"].get("already_held") == 1


async def test_a_sell_of_something_we_never_bought_is_recorded(db_session, leader):
    """He sells names we could not price on the way in. That gap is the finding,
    so it is counted rather than ignored."""
    await PumpfunService(db_session).tick(now=NOW)
    leader["trades"] = [_trade("sell", NOW + timedelta(seconds=10), sig="orphan")]
    out = await PumpfunService(db_session).tick(now=NOW + timedelta(seconds=20))
    assert out["signals"].get("not_held") == 1


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
