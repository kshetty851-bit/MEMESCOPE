"""The engine against a real database, and the two routes it feeds.

Three seeded coins — an uptrend, a downtrend, a sideways chop — on both
timeframes, inside a transaction that is rolled back.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select

from app.db.session import get_db
from app.labs.crypto_trend import config
from app.labs.crypto_trend.api import router
from app.labs.crypto_trend.data import get_regime, get_trend_state
from app.labs.crypto_trend.engine import TrendEngine
from app.labs.crypto_trend.models import CtRegime, CtTrendState, CtUniverseMember
from app.labs.crypto_trend.service import CryptoTrendService
from app.labs.crypto_trend.tests.fakes import (
    NOW,
    FakeSource,
    downtrend_closes,
    sideways_closes,
    synthetic_candles,
    uptrend_closes,
)

pytestmark = pytest.mark.integration

COINS = {"BTCUSDT": uptrend_closes, "ETHUSDT": downtrend_closes, "SOLUSDT": sideways_closes}


async def seed(session, *, bars: int = 200) -> None:
    service = CryptoTrendService(session, FakeSource())
    for rank, (symbol, path) in enumerate(COINS.items(), start=1):
        session.add(CtUniverseMember(
            coingecko_id=symbol.lower(), ticker=symbol[:-4], name=symbol,
            binance_symbol=symbol,
            rank=rank, market_cap_rank=rank, market_cap_usd=Decimal(1), added_at=NOW,
            refreshed_at=NOW))
        for tf in config.TIMEFRAMES:
            await service.upsert_candles(synthetic_candles(path(bars), symbol=symbol,
                                                           timeframe=tf))
    await session.flush()


async def count(session, model) -> int:
    return await session.scalar(select(func.count()).select_from(model))


async def test_one_run_writes_a_state_per_symbol_and_timeframe(lab_session) -> None:
    await seed(lab_session)
    result = await TrendEngine(lab_session).run(now=NOW)

    assert result["states"] == 6 and result["skipped"] == []
    assert await count(lab_session, CtTrendState) == 6
    by_key = {(s.symbol, s.timeframe): s for s in await get_trend_state(lab_session)}
    assert {k: v.direction for k, v in by_key.items()} == {
        ("BTCUSDT", "1h"): "UP", ("BTCUSDT", "4h"): "UP",
        ("ETHUSDT", "1h"): "DOWN", ("ETHUSDT", "4h"): "DOWN",
        ("SOLUSDT", "1h"): "FLAT", ("SOLUSDT", "4h"): "FLAT"}
    assert all(s.computed_at == NOW for s in by_key.values())

    # 1 UP, 1 DOWN, 1 FLAT of 3: neither breadth reaches 0.6.
    (regime,) = await get_regime(lab_session)
    assert (regime.coins, regime.regime) == (3, "CHOP")
    assert regime.breadth_up == pytest.approx(1 / 3, abs=1e-4)  # stored to 4 places
    assert (regime.btc_direction, regime.eth_direction) == ("UP", "DOWN")
    assert result["regime"] == "CHOP"


async def test_rerunning_between_bar_closes_rewrites_the_same_rows(lab_session) -> None:
    await seed(lab_session)
    engine = TrendEngine(lab_session)
    await engine.run(now=NOW)
    await engine.run(now=NOW + timedelta(minutes=1))
    assert await count(lab_session, CtTrendState) == 6
    assert await count(lab_session, CtRegime) == 1
    assert all(s.computed_at == NOW + timedelta(minutes=1)
               for s in await get_trend_state(lab_session))


async def test_a_new_bar_adds_a_row_and_the_latest_wins(lab_session) -> None:
    await seed(lab_session)
    engine = TrendEngine(lab_session)
    await engine.run(now=NOW)
    # One more hourly candle for BTC, closing an hour later.
    later = synthetic_candles(uptrend_closes(201), symbol="BTCUSDT", timeframe="1h",
                              end_ms=int((NOW + timedelta(hours=1)).timestamp() * 1000))
    await CryptoTrendService(lab_session, FakeSource()).upsert_candles(later)
    await engine.run(now=NOW + timedelta(hours=1))
    rows = await lab_session.scalar(select(func.count()).select_from(CtTrendState)
                                    .where(CtTrendState.symbol == "BTCUSDT",
                                           CtTrendState.timeframe == "1h"))
    assert rows == 2
    (latest,) = await get_trend_state(lab_session, symbol="BTCUSDT", timeframe="1h")
    assert latest.bar_close_time == later[-1].close_time
    assert await count(lab_session, CtRegime) == 2


async def test_get_trend_state_filters(lab_session) -> None:
    await seed(lab_session)
    await TrendEngine(lab_session).run(now=NOW)
    assert {s.symbol for s in await get_trend_state(lab_session, timeframe="4h")} == set(COINS)
    assert [s.timeframe for s in await get_trend_state(lab_session, symbol="ETHUSDT")] == [
        "1h", "4h"]
    assert await get_trend_state(lab_session, symbol="NOPEUSDT") == []


async def test_too_new_a_contract_is_skipped_not_written(lab_session) -> None:
    await seed(lab_session, bars=config.MIN_BARS - 1)
    result = await TrendEngine(lab_session).run(now=NOW)
    assert result["states"] == 0
    assert sorted(result["skipped"]) == sorted(f"{s} {tf}" for s in COINS
                                               for tf in config.TIMEFRAMES)
    assert result["regime"] is None
    assert await count(lab_session, CtRegime) == 0


async def test_rows_older_than_the_retention_are_pruned(lab_session) -> None:
    await seed(lab_session)
    old = NOW - timedelta(days=config.TREND_RETENTION_DAYS + 1)
    lab_session.add(CtTrendState(
        symbol="BTCUSDT", timeframe="1h", bar_close_time=old, computed_at=old,
        direction="UP", strength=1, slope=Decimal(0), atr_pct=Decimal(1), bars_in_state=1,
        ema_fast=Decimal(1), ema_slow=Decimal(1), ema_trend=None, adx=Decimal(1),
        structure="MIXED", structure_veto=False, close=Decimal(1)))
    lab_session.add(CtRegime(bar_close_time=old, computed_at=old, coins=1,
                             breadth_up=Decimal(1), breadth_down=Decimal(0), regime="CHOP"))
    await lab_session.flush()
    result = await TrendEngine(lab_session).run(now=NOW)
    assert result["pruned"] == 2
    assert await count(lab_session, CtTrendState) == 6
    assert await count(lab_session, CtRegime) == 1


# --- routes ---------------------------------------------------------------------------

def app_for(session) -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")

    async def override():
        yield session

    app.dependency_overrides[get_db] = override
    return app


async def test_the_trend_route(lab_session, lab_enabled) -> None:
    await seed(lab_session)
    await TrendEngine(lab_session).run(now=NOW)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app_for(lab_session)),
                                 base_url="http://t") as client:
        r = await client.get("/api/v1/labs/crypto-trend/trend")
    assert r.status_code == 200
    body = r.json()
    assert body["running"] is True
    assert body["computed_at"] == NOW.isoformat().replace("+00:00", "Z")
    assert [c["symbol"] for c in body["coins"]] == ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    btc, eth, sol = body["coins"]
    assert (btc["verdict"], btc["reason"]) == ("LONG_BIAS", "4h UP, 1h UP")
    assert (eth["verdict"], eth["reason"]) == ("SHORT_BIAS", "4h DOWN, 1h DOWN")
    assert (sol["verdict"], sol["reason"]) == ("NEUTRAL", "4h FLAT, 1h FLAT")
    assert btc["rank"] == 1
    assert set(btc["states"]) == {"1h", "4h"}
    s = btc["states"]["4h"]
    assert s["direction"] == "UP" and s["structure"] == "HH_HL"
    assert {"strength", "slope", "atr_pct", "bars_in_state", "ema_fast", "ema_slow",
            "ema_trend", "adx", "close", "bar_close_time", "structure_veto"} <= set(s)
    assert s["structure_veto"] is False


async def test_the_regime_route(lab_session, lab_enabled) -> None:
    await seed(lab_session)
    engine = TrendEngine(lab_session)
    await engine.run(now=NOW)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app_for(lab_session)),
                                 base_url="http://t") as client:
        r = await client.get("/api/v1/labs/crypto-trend/regime")
    assert r.status_code == 200
    body = r.json()
    assert body["running"] is True
    assert body["latest"]["regime"] == "CHOP" and body["latest"]["coins"] == 3
    assert body["history"] == [body["latest"]]


async def test_routes_answer_not_running_without_the_flag(lab_session, monkeypatch) -> None:
    monkeypatch.delenv("CRYPTO_TREND_LAB_ENABLED", raising=False)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app_for(lab_session)),
                                 base_url="http://t") as client:
        trend = await client.get("/api/v1/labs/crypto-trend/trend")
        regime = await client.get("/api/v1/labs/crypto-trend/regime")
    assert trend.json() == {"running": False, "computed_at": None, "coins": []}
    assert regime.json() == {"running": False, "latest": None, "history": []}


async def test_a_coin_without_states_is_listed_as_neutral(lab_session, lab_enabled) -> None:
    await seed(lab_session, bars=config.MIN_BARS - 1)
    await TrendEngine(lab_session).run(now=NOW)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app_for(lab_session)),
                                 base_url="http://t") as client:
        body = (await client.get("/api/v1/labs/crypto-trend/trend")).json()
    assert body["computed_at"] is None
    assert all(c["verdict"] == "NEUTRAL" and c["reason"] == "no 4h state"
               and c["states"] == {"1h": None, "4h": None} for c in body["coins"])


# --- the CLI table ----------------------------------------------------------------------

async def test_the_cli_prints_a_table_not_just_the_summary(lab_session, lab_enabled,
                                                            monkeypatch) -> None:
    """The engine summary carries a `skipped` list even when nothing was
    skipped; the table must not mistake that for the disabled marker."""
    from contextlib import nullcontext

    from app.labs.crypto_trend import __main__ as cli

    await seed(lab_session)
    result = await TrendEngine(lab_session).run(now=NOW)

    async def fake_trend_tick():
        return result

    monkeypatch.setattr(cli, "trend_tick", fake_trend_tick)
    monkeypatch.setattr(cli, "SessionFactory", lambda: nullcontext(lab_session))
    out = await cli._trend()
    lines = out.splitlines()
    assert lines[0].startswith("symbol")
    assert any(line.startswith("BTCUSDT") and "LONG_BIAS" in line for line in lines)
    assert any(line.startswith("ETHUSDT") and "SHORT_BIAS" in line for line in lines)
    assert any(line.startswith("regime CHOP") for line in lines)
    assert lines[-1].startswith("{")  # the summary, last


async def test_the_cli_reports_a_disabled_lab(monkeypatch) -> None:
    from app.labs.crypto_trend import __main__ as cli

    monkeypatch.delenv("CRYPTO_TREND_LAB_ENABLED", raising=False)
    assert await cli._trend() == '{"skipped": "crypto_trend_lab_disabled"}'
