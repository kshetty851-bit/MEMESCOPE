"""The read-only routes, over HTTP, for the current run and an archived one.

Through the router rather than the functions: a route can bind to the wrong
function and still pass every direct call.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select

from app.db.session import get_db
from app.labs.rafiq import registry
from app.labs.rafiq.api import router
from app.labs.rafiq.models import RafiqLabPosition, RafiqLabRunState
from app.labs.rafiq.service import RafiqLabService
from app.labs.rafiq.tests.test_full_cycle import seed_candidate

pytestmark = pytest.mark.integration


def client_for(lab_session) -> httpx.AsyncClient:
    app = FastAPI()
    app.include_router(router)

    async def session_override():
        yield lab_session

    app.dependency_overrides[get_db] = session_override
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://lab")


async def test_every_route_reads_one_run(lab_session, monkeypatch) -> None:
    monkeypatch.setenv("RAFIQ_LAB_ENABLED", "true")
    now = datetime.now(UTC)
    service = RafiqLabService(lab_session)
    archived = await service.activate(now=now - timedelta(days=1),
                                      run=registry.ARCHIVED_RUN)
    f2 = next(r for r in archived if r.code == "F2")
    lab_session.add(RafiqLabPosition(
        strategy_id=f2.id, lab_run_id=f2.lab_run_id, mint_address="Old".ljust(44, "9"),
        leg=1, opened_at=now - timedelta(days=1), entry_price=Decimal(1),
        entry_observed_price=Decimal(1), quantity=Decimal(10), cost_basis=Decimal(10),
        stop_price=Decimal("0.88"), stop_pct=Decimal(12), max_hold_seconds=28800,
        status="closed", peak_price=Decimal(1), last_evaluated_at=now,
        closed_at=now - timedelta(hours=20), exit_price=Decimal("0.5"),
        exit_observed_price=Decimal("0.5"), exit_proceeds_usd=Decimal(5),
        exit_reason="stop"))
    await service.activate(now=now - timedelta(hours=1))
    await seed_candidate(lab_session, now, tag="apirun")
    await service.tick(now=now)

    async with client_for(lab_session) as client:
        async def get(path, **params):
            response = await client.get(f"/labs/rafiq/{path}", params=params)
            assert response.status_code == 200, (path, params, response.text)
            return response.json()

        current = await get("status")
        assert current["run"] == registry.G1_RUN
        assert [s["code"] for s in current["strategies"]] == ["G1"]
        g1 = current["strategies"][0]
        assert g1["enters"] is True and g1["open_positions"] == 1
        assert g1["learning"]["abandon_gain_threshold"] == 0.08
        assert g1["learning"]["size_multiplier"] == 1.0
        assert g1["ratchet_floor"] is not None and g1["lab_run_id"] == registry.G1_RUN

        old = await get("status", run=registry.ARCHIVED_RUN)
        assert [s["code"] for s in old["strategies"]] == ["A2", "B2", "C2", "D2", "E2", "F2"]
        f2_out = next(s for s in old["strategies"] if s["code"] == "F2")
        assert f2_out["closed_trades"] == 1 and f2_out["realised_pnl"] == "-5.0000"
        assert f2_out["ratchet_floor"] is None and f2_out["enters"] is False

        positions = await get("positions")
        assert [p["strategy_code"] for p in positions] == ["G1"]
        assert positions[0]["fraction_open"] == "1.0000"
        assert await get("positions", run=registry.ARCHIVED_RUN) == []

        assert await get("trades") == []
        old_trades = await get("trades", run=registry.ARCHIVED_RUN)
        assert [(t["strategy_code"], t["exit_reason"]) for t in old_trades] == [("F2", "stop")]

        assert [b["strategy_code"] for b in await get("breaker")] == ["G1"]
        assert [a["code"] for a in await get("analysis")] == ["G1"]
        assert len(await get("analysis", run=registry.ARCHIVED_RUN)) == 6

        unknown = await get("status", run="no-such-run")
        assert unknown["strategies"] == []


async def test_reading_the_status_writes_nothing(lab_session, monkeypatch) -> None:
    """The router is read-only and its session commits on return, so asking
    for G1's learning state must not create the run's state row."""
    monkeypatch.setenv("RAFIQ_LAB_ENABLED", "true")
    await RafiqLabService(lab_session).activate(now=datetime.now(UTC))
    async with client_for(lab_session) as client:
        response = await client.get("/labs/rafiq/status")
    assert response.status_code == 200
    assert response.json()["strategies"][0]["learning"]["size_multiplier"] == 1.0
    assert (await lab_session.execute(select(RafiqLabRunState))).first() is None


async def test_a_scale_out_is_realised_while_its_runner_is_open(
    lab_session, monkeypatch
) -> None:
    """75% sold at +32%, 25% still riding. The sale's profit is realised now,
    the quarter still held is what is unrealised, and the two add up to what
    the book has gained — they used to leave the sale out until the runner
    closed."""
    from app.labs.rafiq.g1 import strategy_G1 as g1
    from app.labs.rafiq.tests.test_g1_engine import T0, path, seed_path

    monkeypatch.setenv("RAFIQ_LAB_ENABLED", "true")
    service = RafiqLabService(lab_session)
    await service.activate(now=T0 - timedelta(hours=1))
    mint = await seed_path(lab_session, "runneropen", T0,
                           path((0, 1), (5, "1.32"), length=10))
    await service.tick(now=T0)
    await service.tick(now=T0 + timedelta(minutes=5))
    row = (await lab_session.execute(
        select(RafiqLabPosition).where(RafiqLabPosition.mint_address == mint)
    )).scalars().one()
    assert (row.status, row.scaled_out, row.fraction_open) == ("open", True, Decimal("0.25"))

    async with client_for(lab_session) as client:
        g1_out = (await client.get("/labs/rafiq/status")).json()["strategies"][0]
        desk = (await client.get("/labs/rafiq/analysis")).json()[0]

    equity, start = Decimal(g1_out["equity"]), Decimal(g1_out["starting_equity"])
    realised, unrealised = Decimal(g1_out["realised_pnl"]), Decimal(g1_out["unrealised_pnl"])
    assert g1_out["closed_trades"] == 0 and realised > 0
    # Equal to Decimal's 28 significant digits, which round a $1,003 sum
    # and a $3 one at different places.
    assert abs((equity - start) - (realised + unrealised)) < Decimal("1e-12")
    assert realised == row.realised_usd - row.cost_basis * g1.SCALE_OUT_FRACTION
    assert Decimal(g1_out["gross_pnl_ex_fees"]) > realised     # fees came off it
    capital = next(f for f in desk["figures"] if f["label"] == "Capital in open trades")
    assert capital["value"] == f"${row.cost_basis * Decimal('0.25'):,.2f}"


def test_the_hq_desks_sit_at_the_books_the_lab_trades_now() -> None:
    """HQ seats its analysts from `registry.STRATEGIES`, "as the lab is
    registered now". Pointed at the archive, every desk looked its book up in
    G1's run and reported it as not registered."""
    desk = pytest.importorskip("app.hq_ops.desk")
    assert desk.strategy_for("anchor") == "G1"
    assert desk.strategy_for("tempo") is None
