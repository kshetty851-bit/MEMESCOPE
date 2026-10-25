"""Run only on the disposable, network-isolated sprint_test Postgres."""

import asyncio
import os
from datetime import timedelta
from decimal import Decimal

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.labs.graduation import pool_sprint as api
from app.labs.graduation.pool_sprint_book import START, WSOL_MINT, Observation


@pytest.fixture
async def isolated(monkeypatch):
    dsn = os.environ["TEST_DATABASE_URI"]
    assert dsn == "postgresql+asyncpg://memescope@127.0.0.1:5432/sprint_test"
    engine = create_async_engine(dsn)
    async with engine.begin() as c:
        await c.execute(text("DROP TABLE IF EXISTS grad_postgrad_samples"))
        await c.execute(text("DROP TABLE IF EXISTS grad_tokens"))
        await c.execute(
            text(
                "CREATE TABLE grad_tokens "
                "(mint varchar PRIMARY KEY, symbol varchar, name varchar, "
                "migrated_at timestamptz, creator varchar)"
            )
        )
        await c.execute(
            text("""CREATE TABLE grad_postgrad_samples (
          mint varchar, ts timestamptz, pair_address varchar, source varchar,
          price_usd numeric, liquidity_usd numeric, txns_m5_buys int, txns_m5_sells int,
          UNIQUE(mint,ts))""")
        )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(api, "SessionFactory", factory)
    monkeypatch.setattr(api, "snapshot", lambda: (START, ()))

    async def identities(pairs):
        return {pair: (mint, WSOL_MINT, "synthetic_test") for pair, mint in pairs.items()}

    monkeypatch.setattr(api, "verify_pairs", identities)
    for name, value in [
        ("_records", None),
        ("_book", None),
        ("_watermark", None),
        ("_live_as_of", None),
        ("_refreshing", None),
        ("_last_attempt", 0.0),
    ]:
        monkeypatch.setattr(api, name, value)
    monkeypatch.setattr(api, "_lock", asyncio.Lock())

    async def add(
        mint,
        seconds,
        price=1,
        liquidity=15000,
        pair=None,
        source="dexscreener",
        buys=65,
        sells=35,
        age=10,
        creator=None,
    ):
        async with factory() as s:
            await s.execute(
                text(
                    "INSERT INTO grad_tokens (mint,migrated_at,creator) "
                    "VALUES (:mint,:at,:creator) "
                    "ON CONFLICT DO NOTHING"
                ),
                {
                    "mint": mint,
                    "at": START + timedelta(seconds=seconds - age),
                    "creator": creator,
                },
            )
            await s.execute(
                text("""INSERT INTO grad_postgrad_samples
              VALUES (:mint,:ts,:pair,:source,:price,:liq,:buys,:sells)"""),
                {
                    "mint": mint,
                    "ts": START + timedelta(seconds=seconds),
                    "pair": pair or mint,
                    "source": source,
                    "price": price,
                    "liq": liquidity,
                    "buys": buys,
                    "sells": sells,
                },
            )
            await s.commit()

    yield add
    await engine.dispose()


@pytest.mark.asyncio
async def test_first_liquidity_is_used_not_later_drop_into_band(isolated):
    await isolated("outside", 1, liquidity=50000)
    await isolated("outside", 30, liquidity=20000)
    await isolated("inside", 2, liquidity=10000)
    await isolated("upper", 3, liquidity=40000)
    await api.refresh(START + timedelta(minutes=10))
    assert set(api._records) == {"inside"}


@pytest.mark.asyncio
async def test_later_buy_counts_do_not_qualify_a_refused_first_observation(isolated):
    await isolated("refused", 10, buys=64, sells=36)
    await isolated("refused", 40, buys=100, sells=0)
    await isolated("stale", 20, age=31)
    await isolated("good", 30, buys=13, sells=7, age=30)
    await api.refresh(START + timedelta(minutes=10))
    assert api._records["refused"].entry_buys == 64
    assert api._book["signals"] == 1
    assert api._book["excluded_entry_rule"] == 2
    assert api._book["trades_list"][0]["mint"] == "good"


@pytest.mark.asyncio
async def test_exit_cannot_switch_pools(isolated):
    await isolated("coin", 10)
    await isolated("coin", 310, price=100, pair="wrong")
    await isolated("coin", 320, price=2)
    await api.refresh(START + timedelta(minutes=10))
    assert api._records["coin"].exit_price == 2
    assert api._records["coin"].pair == "coin"
    assert api._book["priced_pnl_usd"] == "50.00"


@pytest.mark.asyncio
async def test_candle_close_is_available_at_minute_end_and_waits_for_deadline(isolated):
    await isolated("coin", 30)
    await isolated("coin", 240, price=100, source="geckoterminal")
    await isolated("coin", 300, price=2, source="geckoterminal")
    await api.refresh(START + timedelta(seconds=420))
    assert not api._records["coin"].priced  # seven minutes since entry not elapsed
    await api.refresh(START + timedelta(seconds=480))
    c = api._records["coin"]
    assert c.exit_price == 2  # never use the earlier candle's future close
    assert c.exited_at == START + timedelta(seconds=360)
    assert c.candle_start_at == START + timedelta(seconds=300)


@pytest.mark.asyncio
async def test_future_prices_and_after_window_prices_are_not_used(isolated):
    await isolated("coin", 10)
    await isolated("coin", 320, price=2)
    await isolated("late", 20)
    await isolated("late", 450, price=20)
    await api.refresh(START + timedelta(seconds=300))
    assert not api._records["coin"].priced
    await api.refresh(START + timedelta(seconds=350))
    assert api._records["coin"].exit_price == 2
    await api.refresh(START + timedelta(seconds=500))
    assert not api._records["late"].priced


@pytest.mark.asyncio
async def test_late_candle_can_resolve_old_gap_without_duplicate_entry(isolated):
    await isolated("coin", 10)
    await api.refresh(START + timedelta(minutes=10))
    assert api._book["unpriced"] == 1
    await isolated("coin", 300, price=2, source="geckoterminal")
    await api.refresh(START + timedelta(minutes=11))
    assert api._book["unpriced"] == 0 and api._book["trades"] == 1
    assert api._book["priced_pnl_usd"] == "50.00"


@pytest.mark.asyncio
async def test_unprovisioned_snapshot_returns_503_without_inventing_a_balance(monkeypatch):
    monkeypatch.setattr(api, "_book", None)

    def absent():
        raise FileNotFoundError

    monkeypatch.setattr(api, "snapshot", absent)
    app = FastAPI()
    app.include_router(api.router, prefix="/labs/graduation")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/labs/graduation/pool-sprint")
        assert response.status_code == 503
        assert "not installed" in response.json()["detail"]


@pytest.mark.asyncio
async def test_routes_only_read_and_paginate_and_csv_escapes_metadata(monkeypatch):
    c = Observation(
        "mint",
        "pair",
        START,
        Decimal(1),
        Decimal(15000),
        symbol="=CMD()",
        base_mint="mint",
        quote_mint=WSOL_MINT,
        pair_evidence="synthetic_test",
        graduated_at=START - timedelta(seconds=10),
        entry_buys=65,
        entry_sells=35,
    )
    data = api.report([c], START + timedelta(minutes=10))

    async def cached():
        return data

    monkeypatch.setattr(api, "current", cached)
    app = FastAPI()
    app.include_router(api.router, prefix="/labs/graduation")
    assert all(r.methods <= {"GET", "HEAD"} for r in api.router.routes)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        summary = (await client.get("/labs/graduation/pool-sprint")).json()
        assert "trades_list" not in summary
        rows = (await client.get("/labs/graduation/pool-sprint/trades?status=unpriced")).json()
        assert rows["total"] == 1 and rows["trades"][0]["pct"] is None
        empty = (await client.get("/labs/graduation/pool-sprint/trades?offset=1")).json()
        assert empty["total"] == 1 and not empty["trades"]
        assert (
            await client.get("/labs/graduation/pool-sprint/trades?limit=10000")
        ).status_code == 422
        csv = await client.get("/labs/graduation/pool-sprint/trades.csv")
        assert "'=CMD()" in csv.text and csv.headers["content-type"].startswith("text/csv")


@pytest.mark.asyncio
async def test_unverified_entry_is_not_traded_and_can_be_verified_later(isolated, monkeypatch):
    await isolated("coin", 10)
    await isolated("coin", 320, price=2)

    async def unknown(pairs):
        return {}

    monkeypatch.setattr(api, "verify_pairs", unknown)
    await api.refresh(START + timedelta(minutes=10))
    assert api._book["trades"] == 0 and api._book["unverified_pools"] == 1

    async def non_sol(pairs):
        return {"coin": ("coin", "SPCX", "synthetic_test")}

    monkeypatch.setattr(api, "verify_pairs", non_sol)
    await api.refresh(START + timedelta(minutes=11))
    assert api._book["trades"] == 0 and api._book["excluded_non_sol"] == 1
    assert api._book["balance_usd"] == "500.00"


@pytest.mark.asyncio
async def test_creator_identity_is_read_and_blocked_rows_are_separate(isolated):
    await isolated("rug", 10, creator="A")
    await isolated("rug", 310, price="0.5", creator="A")
    await isolated("next", 311, creator="A")
    await api.refresh(START + timedelta(minutes=10))
    assert api._book["trades"] == 1 and api._book["creator_skipped"] == 1
    assert api._book["skipped"] == 0
    app = FastAPI()
    app.include_router(api.router, prefix="/labs/graduation")
    # Freeze refresh scheduling: this route check observes only the prepared cache.
    api._last_attempt = __import__("time").monotonic()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        b = (await client.get("/labs/graduation/pool-sprint")).json()
        assert "creator_blocked_list" not in b
        rs = (
            await client.get("/labs/graduation/pool-sprint/trades?status=creator_blocked")
        ).json()
        assert rs["total"] == 1 and rs["trades"][0]["creator"] == "A"
        assert rs["trades"][0]["mint"] == "next"
