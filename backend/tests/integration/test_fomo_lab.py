"""FOMO Lab's paper book against a real database.

Prices are stubbed (the lab reads MEMESCOPE's market snapshots and, failing
that, the enrichment pipeline over the network); everything else -- the
ledger, dedupe, lot matching, cash and the pending-sell retry -- is the real
service writing real rows.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from app.labs.fomo.models import FomoBook, FomoPosition, FomoSignal
from app.labs.fomo.service import STARTING_USD, TRADE_USD, FomoService
from app.labs.fomo.source import Leader
from app.pumpfun.follower import LeaderTrade

pytestmark = pytest.mark.integration

NOW = datetime(2026, 10, 18, 12, 0, tzinfo=UTC)
W1 = "Wallet1111111111111111111111111111111111111"
W2 = "Wallet2222222222222222222222222222222222222"
MINT = "Mint111111111111111111111111111111111111111"


def trade(sig: str, side: str, at: datetime, mint: str = MINT) -> LeaderTrade:
    return LeaderTrade(signature=sig, slot=1, mint=mint, side=side, sol_amount=None, at=at)


@pytest.fixture
def prices(monkeypatch: pytest.MonkeyPatch) -> dict[str, Decimal | None]:
    """mint -> price; None means no fresh price anywhere."""
    book: dict[str, Decimal | None] = {}

    async def price(self, mint, now):
        p = book.get(mint)
        if p is None:
            return None
        return SimpleNamespace(price_usd=p, liquidity_usd=Decimal(1_000_000))

    async def quote_now(self, trade, now):
        return None, "no_market"

    monkeypatch.setattr(FomoService, "price", price)
    monkeypatch.setattr(FomoService, "quote_now", quote_now)
    return book


async def started(db, *, cash: Decimal = STARTING_USD, captured: datetime = NOW) -> FomoBook:
    book = FomoBook(started_at=NOW - timedelta(hours=1), cash_usd=cash)
    db.add(book)
    await db.flush()
    leaders = [Leader("u1", "one", W1, 1, None), Leader("u2", "two", W2, 2, None)]
    await FomoService(db).roster(book, leaders, NOW - timedelta(hours=1))
    book.source_captured_at = captured
    return book


async def signals(db, book) -> list[str]:
    rows = (await db.scalars(select(FomoSignal.outcome).where(FomoSignal.book_id == book.id)
                             .order_by(FomoSignal.traded_at, FomoSignal.signature))).all()
    return list(rows)


async def open_lots(db, book) -> list[FomoPosition]:
    return list((await db.scalars(select(FomoPosition).where(
        FomoPosition.book_id == book.id, FomoPosition.status == "open")
        .order_by(FomoPosition.leader_bought_at))).all())


async def test_a_swap_seen_twice_is_copied_once(db_session, prices):
    prices[MINT] = Decimal("0.001")
    book = await started(db_session)
    s = FomoService(db_session)
    buy = (W1, trade("sig-a", "buy", NOW - timedelta(seconds=30)))
    assert await s.apply(book, [buy, buy], NOW) == {"opened": 1}
    assert await s.apply(book, [buy], NOW + timedelta(minutes=2)) == {}   # next tick
    assert len(await open_lots(db_session, book)) == 1
    assert book.cash_usd == STARTING_USD - TRADE_USD
    assert await db_session.scalar(select(func.count()).select_from(FomoSignal)) == 1


async def test_a_sell_without_a_price_waits_and_closes_later(db_session, prices):
    prices[MINT] = Decimal("0.001")
    book = await started(db_session)
    s = FomoService(db_session)
    await s.apply(book, [(W1, trade("b", "buy", NOW - timedelta(seconds=20)))], NOW)
    prices[MINT] = None
    later = NOW + timedelta(minutes=2)
    assert await s.apply(book, [(W1, trade("s", "sell", later - timedelta(seconds=10)))],
                         later) == {"pending_price": 1}
    assert book.cash_usd == STARTING_USD - TRADE_USD                    # nothing invented
    prices[MINT] = Decimal("0.002")
    await s.retry_sells(book, later + timedelta(hours=1))   # after an outage
    assert await open_lots(db_session, book) == []
    assert await signals(db_session, book) == ["opened", "closed"]
    assert book.cash_usd > STARTING_USD                                  # doubled, less costs


async def test_a_stale_roster_stops_buys_but_not_sells(db_session, prices):
    prices[MINT] = Decimal("0.001")
    book = await started(db_session)
    s = FomoService(db_session)
    await s.apply(book, [(W1, trade("b1", "buy", NOW - timedelta(seconds=20)))], NOW)
    book.source_captured_at = NOW - timedelta(hours=3)
    later = NOW + timedelta(minutes=2)
    seen = [(W1, trade("b2", "buy", later - timedelta(seconds=5))),
            (W1, trade("s1", "sell", later - timedelta(seconds=4)))]
    counts = await s.apply(book, seen, later)
    assert counts == {"roster_stale": 1, "closed": 1}
    assert await open_lots(db_session, book) == []


async def test_old_or_unranked_buys_are_recorded_not_copied(db_session, prices):
    prices[MINT] = Decimal("0.001")
    book = await started(db_session)
    s = FomoService(db_session)
    counts = await s.apply(book, [
        (W1, trade("old", "buy", NOW - timedelta(minutes=6))),
        ("Stranger111111111111111111111111111111111111", trade("x", "buy", NOW)),
        (W1, trade("pre", "buy", book.started_at - timedelta(minutes=1)))], NOW)
    assert counts == {"stale_signal": 1, "not_ranked_at_trade": 1, "before_start": 1}
    assert book.cash_usd == STARTING_USD


def coin(i: int) -> str:
    return f"Coin{i:02d}" + "1" * 36


async def test_cash_and_the_twenty_lot_cap_bound_the_book(db_session, prices):
    for i in range(25):
        prices[coin(i)] = Decimal("0.001")
    book = await started(db_session, cash=Decimal("30"))
    s = FomoService(db_session)
    counts = await s.apply(book, [(W1, trade(f"c{i}", "buy", NOW - timedelta(seconds=9 - i),
                                             coin(i))) for i in (1, 2)], NOW)
    assert counts == {"opened": 1, "insufficient_cash": 1}          # $25 lots
    assert book.cash_usd == Decimal("5")

    book.cash_usd = Decimal("1000")
    counts = await s.apply(book, [(W2, trade(f"m{i}", "buy", NOW - timedelta(seconds=30 - i),
                                             coin(i + 3))) for i in range(20)], NOW)
    assert counts == {"opened": 19, "max_open_trades": 1}
    assert len(await open_lots(db_session, book)) == 20


async def test_one_lot_per_coin_and_a_sell_closes_its_traders_lot(db_session, prices):
    prices[MINT] = Decimal("0.001")
    book = await started(db_session)
    s = FomoService(db_session)
    t1, t2 = NOW - timedelta(seconds=50), NOW - timedelta(seconds=40)
    both = [(W1, trade("b1", "buy", t1)), (W2, trade("b2", "buy", t2))]
    counts = await s.apply(book, both, NOW)
    assert counts == {"opened": 1, "already_held": 1}   # a repeat buy is no new lot
    assert book.cash_usd == STARTING_USD - TRADE_USD
    (lot,) = await open_lots(db_session, book)
    later = NOW + timedelta(minutes=2)
    counts = await s.apply(book, [
        (W2, trade("other", "sell", later - timedelta(seconds=9))),     # not W2's lot
        (W1, trade("early", "sell", t1 - timedelta(seconds=1))),         # before the buy
        (W1, trade("s1", "sell", later - timedelta(seconds=5)))], later)
    assert counts == {"not_held": 1, "before_buy": 1, "closed": 1}
    assert lot.status == "closed" and await open_lots(db_session, book) == []


async def test_the_consensus_book_buys_only_a_second_traders_buy(db_session, prices):
    from app.labs.fomo.service import CONSENSUS_WINDOW
    prices[MINT] = Decimal("0.001")
    prices[coin(1)] = Decimal("0.001")
    main = await started(db_session)
    s = FomoService(db_session)
    con = await s.consensus_book(NOW - timedelta(minutes=30))
    gate = lambda w, t: s.other_buyer_before(main, w, t)  # noqa: E731

    async def tick(obs, at):
        await s.apply(main, obs, at)
        return await s.apply(con, obs, at, roster_book=main, gate=gate)

    def at(minutes: float) -> datetime:
        return NOW - timedelta(minutes=20) + timedelta(minutes=minutes)

    seen = timedelta(seconds=30)
    one = await tick([(W1, trade("a", "buy", at(0)))], at(0) + seen)
    assert one == {"no_consensus": 1}
    again = await tick([(W1, trade("a2", "buy", at(5)))], at(5) + seen)   # same trader again
    assert again == {"no_consensus": 1}
    second = await tick([(W2, trade("b", "buy", at(10)))], at(10) + seen)
    assert second == {"opened": 1}
    late = CONSENSUS_WINDOW.total_seconds() / 60 + 5
    alone = await tick([(W2, trade("c", "buy", at(late), coin(1)))], at(late) + seen)
    assert alone == {"no_consensus": 1}                          # nobody else bought that coin
    # Its lot follows the trader it copied: W1 selling does not close it, W2 does.
    out = at(22)
    w1_sells = await s.apply(con, [(W1, trade("s1", "sell", out))], out + seen,
                             roster_book=main, gate=gate)
    assert w1_sells == {"not_held": 1}
    w2_sells = await s.apply(con, [(W2, trade("s2", "sell", out))], out + seen,
                             roster_book=main, gate=gate)
    assert w2_sells == {"closed": 1}
    assert con.cash_usd > 0 and main.kind == "main" and con.kind == "consensus"


async def test_two_sells_cannot_close_one_lot_twice(db_session, prices):
    prices[MINT] = Decimal("0.001")
    book = await started(db_session)
    s = FomoService(db_session)
    await s.apply(book, [(W1, trade("b", "buy", NOW - timedelta(seconds=20)))], NOW)
    later = NOW + timedelta(minutes=2)
    sells = [(W1, trade("s1", "sell", later - timedelta(seconds=9))),
             (W1, trade("s2", "sell", later - timedelta(seconds=8)))]
    counts = await s.apply(book, sells, later)
    assert counts == {"closed": 1, "not_held": 1}
    proceeds = (await db_session.scalars(select(FomoPosition.proceeds_usd))).one()
    assert round(book.cash_usd, 4) == STARTING_USD - TRADE_USD + proceeds


async def test_bookmarks_are_kept_per_wallet(db_session, prices):
    book = await started(db_session)
    s = FomoService(db_session)
    assert await s.cursors(book) == {W1: None, W2: None}
    await s.set_cursors(book, {W1: "sigA"})
    assert await s.cursors(book) == {W1: "sigA", W2: None}
    await s.set_cursors(book, {W1: "sigB", W2: "sigC"})
    assert await s.cursors(book) == {W1: "sigB", W2: "sigC"}
