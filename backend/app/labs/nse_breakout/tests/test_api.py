"""The health route: what it reports, and that it is actually mounted."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.labs.nse_breakout import api, config
from app.labs.nse_breakout.ingest import Ingest
from app.labs.nse_breakout.models import BtCandle
from app.labs.nse_breakout.tests.fakes import FakeArchive, row

NOW = datetime(2026, 9, 11, 13, 0, tzinfo=UTC)
D10 = date(2026, 9, 10)


def test_the_route_is_mounted_where_the_brief_says() -> None:
    """The brief asks for `/api/tracker/health`; this app prefixes every
    router with `/api/v1`. Read the served contract rather than `app.routes`:
    this FastAPI keeps an included router as one lazy object, so walking the
    route list finds nothing and an assertion over it would pass on a router
    that was never registered."""
    from app.main import app
    assert "/api/v1/tracker/health" in app.openapi()["paths"]


def test_the_route_is_read_only() -> None:
    from app.main import app
    for path, methods in app.openapi()["paths"].items():
        if path.startswith("/api/v1/tracker"):
            assert set(methods) <= {"get", "head"}, path


@pytest.mark.integration
async def test_the_flag_off_says_not_running_without_touching_the_database(
    monkeypatch,
) -> None:
    """`running: false` and "ran and found nothing" must not render alike —
    and with the flag off there may be no `bt_` tables at all, so this must
    not issue a query."""
    monkeypatch.setenv("NSE_BREAKOUT_ENABLED", "false")

    class Exploding:
        async def execute(self, *a, **k):
            raise AssertionError("queried the database with the flag off")

    assert await api.tracker_health(Exploding()) == {"running": False}


@pytest.mark.integration
async def test_health_reports_coverage_against_scorable_names(
    tracker_session, tracker_enabled,
) -> None:
    bars = []
    for symbol, n in (("DEEP", config.MIN_BARS_FOR_LEVELS + 5), ("SHALLOW", 30)):
        for i in range(n):
            when = D10 - timedelta(days=n - 1 - i)
            bars.append({"symbol": symbol, "date": when, "open": Decimal("500"),
                         "high": Decimal("505"), "low": Decimal("495"),
                         "close": Decimal("500"), "volume": 1000,
                         "turnover": Decimal("50000000"), "adjusted": False,
                         "suspect_gap": False})
    await tracker_session.execute(pg_insert(BtCandle).values(bars))
    await Ingest(tracker_session, FakeArchive()).rebuild_universe(now=NOW)

    out = await api.tracker_health(tracker_session)

    assert out["running"] is True
    assert out["universe"]["active"] == 2
    assert out["coverage"]["symbols_active"] == 2
    assert out["coverage"]["symbols_covered"] == 1, "SHALLOW cannot carry a level"
    assert out["coverage"]["pct"] == 50.0
    assert out["coverage"]["last_bar"] == D10.isoformat()
    assert out["corporate_actions"]["adjusted"] is False


@pytest.mark.integration
async def test_health_lists_the_days_that_failed(
    tracker_session, tracker_enabled,
) -> None:
    """The DoD asks for the failures list by name, not just a count: a
    backfill that is 96% complete is only trustworthy if you can see which
    4% is missing and why."""
    job = Ingest(tracker_session, FakeArchive({D10: [row("AAA", D10)]},
                                             fail={D10 - timedelta(days=1)}))
    await job.day(D10, now=NOW)
    await job.day(D10 - timedelta(days=1), now=NOW)
    await job.day(D10 - timedelta(days=2), now=NOW)   # holiday

    out = await api.tracker_health(tracker_session)
    assert out["bhavcopy"]["days_ok"] == 1
    assert out["bhavcopy"]["days_missing"] == 1
    assert out["bhavcopy"]["days_failed"] == 1
    assert [f["date"] for f in out["bhavcopy"]["failed_days"]] == [
        (D10 - timedelta(days=1)).isoformat()]
    assert out["bhavcopy"]["failed_days"][0]["error"]


@pytest.mark.integration
async def test_health_survives_an_empty_database(
    tracker_session, tracker_enabled,
) -> None:
    """Day one, before anything has been ingested. Divide-by-zero here would
    make the route 500 exactly when it is being used to ask why it is empty."""
    out = await api.tracker_health(tracker_session)
    assert out["running"] is True
    assert out["coverage"]["pct"] == 0.0
    assert out["coverage"]["last_bar"] is None
    assert out["last_run"] == {}
