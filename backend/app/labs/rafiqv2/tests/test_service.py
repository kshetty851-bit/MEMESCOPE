"""Whole ticks against a real database: entries, exits, the death-rate and
daily breakers, the learning pass, and the read-only routes over HTTP."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select

from app.db.session import get_db
from app.labs.rafiqv2.api import router
from app.labs.rafiqv2.models import Rafiqv2Adjustment, Rafiqv2Book, Rafiqv2Position
from app.labs.rafiqv2.service import Rafiqv2Service
from app.models.market import TokenMarketSnapshot, TradingStatus
from app.models.radar import RadarToken
from app.models.token import DiscoveredToken

pytestmark = pytest.mark.integration

#: Noon, so no test can straddle a UTC day and roll the daily breaker.
NOW = datetime(2026, 9, 19, 12, tzinfo=UTC)
BOOKS = ["A2", "B2", "C2", "D2", "E2", "G2"]


def s(seconds: float) -> timedelta:
    return timedelta(seconds=seconds)


async def mark(session, token, at, price, *, status=TradingStatus.TRADING,
               liquidity=250_000) -> None:
    tid, mint = token
    session.add(TokenMarketSnapshot(
        token_id=tid, mint_address=mint, captured_at=at,
        price_usd=None if price is None else Decimal(price),
        liquidity_usd=Decimal(liquidity), market_cap=Decimal(2_000_000),
        volume_5m=Decimal(5_000), volume_1h=Decimal(50_000), buy_count_24h=800,
        sell_count_24h=400, trading_status=status, provider="test",
        pool_address=("Pool" + mint[3:]).ljust(44, "3")[:44]))
    await session.flush()


async def admission(session, tag: str, detected: datetime) -> tuple[uuid.UUID, str]:
    """A Radar admission at score 85 with a deep market every 20s up to +2m,
    which every book's gate admits."""
    mint = ("Rq2" + tag).ljust(44, "7")[:44]
    token = DiscoveredToken(
        id=uuid.uuid4(), mint_address=mint, symbol=tag.upper(), name="Rafiqv2 test",
        signature=("sig" + uuid.uuid4().hex).ljust(64, "4")[:64], slot=1,
        discovered_at=detected)
    session.add(token)
    await session.flush()
    session.add(RadarToken(
        token_id=token.id, mint_address=mint, first_detected_at=detected,
        first_opportunity_score=Decimal(85), first_confidence=Decimal(80),
        detection_reason=["test"], category="admission",
        current_opportunity_score=Decimal(85), current_confidence=Decimal(80),
        current_category="admission", is_active=True, model_version="test",
        last_evaluated_at=detected))
    for k in range(7):
        await mark(session, (token.id, mint), detected + s(20 * k), "0.001")
    return token.id, mint


async def rows(session, mint) -> dict[str, Rafiqv2Position]:
    out = (await session.execute(
        select(Rafiqv2Book.code, Rafiqv2Position)
        .join(Rafiqv2Book, Rafiqv2Book.id == Rafiqv2Position.book_id)
        .where(Rafiqv2Position.mint_address == mint))).all()
    return dict(out)


async def started(session) -> Rafiqv2Service:
    service = Rafiqv2Service(session)
    await service.activate(now=NOW - timedelta(hours=1))
    return service


async def test_six_books_scale_out_and_then_lock_their_winners(lab_session) -> None:
    service = await started(lab_session)
    token = await admission(lab_session, "run", NOW - s(120))
    report = await service.tick(now=NOW)
    assert {c: b["opened"] for c, b in report["books"].items()} == dict.fromkeys(BOOKS, 1)

    await mark(lab_session, token, NOW + s(40), "0.00135")   # ~1.345x entry
    await Rafiqv2Service(lab_session).tick(now=NOW + s(40))
    held = await rows(lab_session, token[1])
    assert {c for c, p in held.items() if p.scaled_out} == {"A2", "B2", "C2", "E2", "G2"}
    assert held["A2"].fraction_open == Decimal("0.2") and held["A2"].status == "open"

    await mark(lab_session, token, NOW + s(80), "0.0011")    # ~1.096x: under 1.14
    await Rafiqv2Service(lab_session).tick(now=NOW + s(80))
    for code, p in (await rows(lab_session, token[1])).items():
        assert (p.status, p.exit_reason, p.died) == ("closed", "profit_lock", False), code
        assert p.exit_proceeds_usd > p.cost_basis, code      # a winner stayed one
        book = (await lab_session.execute(
            select(Rafiqv2Book).where(Rafiqv2Book.code == code))).scalar_one()
        assert await service.cash(book) == Decimal(1000) - p.cost_basis + p.exit_proceeds_usd
        assert book.state["death"]["recent"] == [False]
    # D2 never scaled out, so it held the whole position to the lock.
    assert not (await rows(lab_session, token[1]))["D2"].scaled_out


async def test_gone_pools_are_deaths_and_the_eighth_halts_every_book(lab_session) -> None:
    service = await started(lab_session)
    dead = [await admission(lab_session, f"dead{i}", NOW - s(120)) for i in range(8)]
    await service.tick(now=NOW)
    for token in dead:  # an inactive reading after the last tradeable print
        await mark(lab_session, token, NOW + s(30), None, status=TradingStatus.INACTIVE,
                   liquidity=0)
    # One reading of "gone" is not enough: it must still read gone 10 minutes
    # after the last tick that found a tradeable print.
    held = await Rafiqv2Service(lab_session).tick(now=NOW + s(150))
    assert all(b["closed"] == 0 for b in held["books"].values()), held
    late = await admission(lab_session, "late", NOW + timedelta(minutes=9))

    report = await Rafiqv2Service(lab_session).tick(now=NOW + timedelta(minutes=11))
    for code in BOOKS:
        book = report["books"][code]
        assert (book["closed"], book["opened"]) == (8, 0), (code, book)
        assert any(h.startswith("death-rate breaker") for h in book["halted"]), book
        # $80 of $1,000 gone in a day trips the daily breaker too.
        assert any(h.startswith("daily breaker") for h in book["halted"]), book
    assert not await rows(lab_session, late[1])
    gone = await rows(lab_session, dead[0][1])
    assert all((p.exit_reason, p.died, p.exit_proceeds_usd) == ("pool_gone", True, 0)
               for p in gone.values())
    halts = (await lab_session.execute(
        select(Rafiqv2Adjustment.reason)
        .where(Rafiqv2Adjustment.parameter == "entries_halted"))).scalars().all()
    assert len(halts) == 12 and sum("8 of the last 8" in h for h in halts) == 6


async def test_the_learner_hears_each_close_once_after_its_hour(lab_session) -> None:
    service = await started(lab_session)
    token = await admission(lab_session, "cut", NOW - s(120))
    await service.tick(now=NOW)
    book = (await lab_session.execute(
        select(Rafiqv2Book).where(Rafiqv2Book.code == "A2"))).scalar_one()
    assert token[1] in book.state["learning"]["open_trades"]      # on_entry, kept

    await mark(lab_session, token, NOW + s(35), "0.00095")        # under 0.97
    await service.tick(now=NOW + s(35))
    assert (await rows(lab_session, token[1]))["A2"].exit_reason == "rug_30s"
    await mark(lab_session, token, NOW + timedelta(minutes=10), "0.0015")  # it ran

    closed = NOW + s(35)
    early = await Rafiqv2Service(lab_session).tick(now=closed + timedelta(minutes=59))
    assert early["books"]["A2"]["learned"] == 0
    due = await Rafiqv2Service(lab_session).tick(now=closed + timedelta(minutes=61))
    assert all(due["books"][c]["learned"] == 1 for c in BOOKS)
    again = await Rafiqv2Service(lab_session).tick(now=closed + timedelta(minutes=62))
    assert all(again["books"][c]["learned"] == 0 for c in BOOKS)

    p = (await rows(lab_session, token[1]))["A2"]
    assert p.forward_peak_multiple == (Decimal("0.0015") / p.entry_price).quantize(
        Decimal("0.000001"))                                        # as stored
    learned = book.state["learning"]
    assert learned["cut_but_recovered"] == [True] and not learned["open_trades"]


async def test_the_routes_read_what_the_tick_wrote(lab_session, monkeypatch) -> None:
    monkeypatch.setenv("RAFIQV2_LAB_ENABLED", "true")
    now = datetime.now(UTC)
    service = Rafiqv2Service(lab_session)
    await service.activate(now=now - timedelta(hours=1))
    await admission(lab_session, "api", now - s(120))
    await service.tick(now=now)

    app = FastAPI()
    app.include_router(router)

    async def session_override():
        yield lab_session

    app.dependency_overrides[get_db] = session_override
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://lab") as client:
        status = (await client.get("/labs/rafiqv2/status")).json()
        held = (await client.get("/labs/rafiqv2/positions")).json()
        trades = await client.get("/labs/rafiqv2/trades", params={"limit": 5})
    assert status["running"] is True
    assert [b["code"] for b in status["books"]] == BOOKS
    a2 = status["books"][0]
    assert (a2["open_positions"], a2["halted"]) == (1, [])
    assert Decimal(a2["equity"]) - 1000 == \
        Decimal(a2["realised_pnl"]) + Decimal(a2["unrealised_pnl"])
    assert a2["learning"]["size_multiplier"] == 1.0
    assert a2["rules"]["exits"]["stop"] == 0.88 and "_identity" not in a2["rules"]
    assert sorted(p["book"] for p in held) == BOOKS
    assert trades.status_code == 200 and trades.json() == []
