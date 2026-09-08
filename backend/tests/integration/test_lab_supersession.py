"""A superseded tournament must wind DOWN, never freeze.

The bug these exist for: `LabService._my_strategy_rows` scoped on `spec_hash`,
so the moment a registry shipped a new spec its previous tournament stopped
matching — and stopped being settled, marked or re-quoted. An open position in
a superseded book could then never be marked, never exited, and could not even
reach its time exit, because that fires inside `settle`.

It is INC-056 by another road, and it was found with a live 4.8x in the book:
deploying `pumpfun-1.2.0` over the running `pumpfun-1.0.0` would have stranded
an $87 position permanently, with no rule able to close it and no sweep able to
re-price it.

The fix scopes on `strategy_id` instead, which follows a registry across its
own versions. What keeps that safe is `test_strategy_ids_are_globally_unique`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

import pytest
from sqlalchemy import select

from app.lab.service import LabService
from app.models.lab import LabPosition, LabStrategy
from app.models.market import TokenMarketSnapshot, TradingStatus
from app.pumpfun import service as svc_mod
from app.pumpfun import spec
from app.pumpfun.follower import LeaderTrade
from app.pumpfun.service import PumpfunService
from tests.integration.test_lab_accounting import _radar_token

pytestmark = pytest.mark.integration

NOW = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)
MINT = "S" + "2" * 20
OLD_HASH = "0" * 64  # stands in for a retired release's spec hash


@pytest.fixture
def leader(monkeypatch):
    box: dict = {"trades": []}

    async def fake(**_kw):
        return list(box["trades"])

    monkeypatch.setattr(svc_mod, "recent_trades", fake)
    return box


def _trade(side, at, sig):
    return LeaderTrade(signature=sig, slot=1, mint=MINT, side=side,
                       sol_amount=1.0, at=at)


async def _book_with_one_open(db_session, leader):
    """A pumpfun book holding one position, ready to be superseded."""
    await _radar_token(db_session, mint=MINT, detected=NOW - timedelta(minutes=69),
                       liq=D("600000"), price=D("0.001"), pool="PSUP")
    await PumpfunService(db_session).tick(now=NOW)
    leader["trades"] = [_trade("buy", NOW + timedelta(seconds=10), "sup1")]
    await PumpfunService(db_session).tick(now=NOW + timedelta(seconds=20))
    pos = (await db_session.execute(
        select(LabPosition).where(LabPosition.mint_address == MINT)
    )).scalars().first()
    assert pos is not None and pos.status == "open"
    return pos


async def _supersede(db_session, *, move_exits: bool):
    """Age the strategy row into a previous release."""
    row = (await db_session.execute(
        select(LabStrategy).where(LabStrategy.strategy_id == "CPY-01")
    )).scalars().first()
    row.spec_hash = OLD_HASH
    if move_exits:
        rules = dict(row.rules or {})
        rules["exits"] = {**rules.get("exits", {}), "take_profit": "2.0"}
        row.rules = rules
    await db_session.flush()
    return row


async def test_a_superseded_book_is_still_settled(db_session, leader):
    """The whole point. An old book must keep being marked so it can wind down."""
    pos = await _book_with_one_open(db_session, leader)
    await _supersede(db_session, move_exits=False)

    out = await LabService(db_session, registry=spec).settle(now=NOW + timedelta(minutes=5))
    assert out["open"] == 1, "the superseded position was not even looked at"
    assert out["stale"] == 0

    await db_session.refresh(pos)
    assert pos.last_evaluated_at is not None, "never marked — this is the stranding bug"


async def test_a_superseded_book_can_still_reach_its_time_exit(db_session, leader):
    """A stranded position cannot close at all: its time exit fires in `settle`."""
    pos = await _book_with_one_open(db_session, leader)
    await _supersede(db_session, move_exits=False)

    # 168h is CPY-01's only backstop. The mark has to be FRESH at that moment,
    # so extend the price history rather than re-creating the token.
    later = NOW + timedelta(hours=169)
    for i in range(5):
        db_session.add(TokenMarketSnapshot(
            token_id=pos.token_id, mint_address=MINT,
            captured_at=later - timedelta(minutes=4 - i),
            price_usd=D("0.001"), liquidity_usd=D("600000"),
            trading_status=TradingStatus.TRADING, provider="test", suspect=False,
            pool_address="PSUP",
        ))
    await db_session.flush()
    await LabService(db_session, registry=spec).settle(now=later)

    await db_session.refresh(pos)
    assert pos.status == "closed"
    assert pos.exit_reason is not None


async def test_a_superseded_book_whose_exits_MOVED_is_left_alone(db_session, leader):
    """Winding an old book down under NEW rules would misreport it.

    `settle` reads `s.exits` from the live registry. A tournament's claim is
    that its result followed the rules frozen at its start, so when those rules
    have moved the honest answer is to refuse and say so — not to default.
    """
    pos = await _book_with_one_open(db_session, leader)
    await _supersede(db_session, move_exits=True)

    out = await LabService(db_session, registry=spec).settle(now=NOW + timedelta(minutes=5))
    assert out["open"] == 0, "settled a book whose frozen exits no longer match"

    await db_session.refresh(pos)
    assert pos.status == "open"


async def test_another_registry_is_still_never_touched(db_session, leader):
    """The protection the old scope provided must survive the widening.

    `settle` looks a strategy up in its own registry; picking up a foreign row
    is what stopped a whole tournament ticking. Scoping on `strategy_id` keeps
    that out, and does so without a hash.
    """
    await _book_with_one_open(db_session, leader)
    rows = await LabService(db_session, registry=spec)._my_strategy_rows()
    assert {r.strategy_id for r in rows} <= set(spec.BY_ID)
    assert all(not r.strategy_id.startswith(("V7-", "CMP-", "MOM-", "DPT-", "SOC-"))
               for r in rows)
