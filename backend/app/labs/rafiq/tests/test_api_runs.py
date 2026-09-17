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

from app.db.session import get_db
from app.labs.rafiq import registry
from app.labs.rafiq.api import router
from app.labs.rafiq.models import RafiqLabPosition
from app.labs.rafiq.service import RafiqLabService
from app.labs.rafiq.tests.test_full_cycle import seed_candidate

pytestmark = pytest.mark.integration


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

    app = FastAPI()
    app.include_router(router)

    async def session_override():
        yield lab_session

    app.dependency_overrides[get_db] = session_override
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://lab") as client:
        async def get(path, **params):
            response = await client.get(f"/labs/rafiq/{path}", params=params)
            assert response.status_code == 200, (path, params, response.text)
            return response.json()

        current = await get("status")
        assert current["run"] == registry.G1_RUN
        assert [s["code"] for s in current["strategies"]] == ["G1"]
        g1 = current["strategies"][0]
        assert g1["enters"] is True and g1["open_positions"] == 1
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
