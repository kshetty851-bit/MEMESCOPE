"""HQ must see Postgres connection saturation, because nothing else does.

On 2026-09-08 a redeploy restarted nine services at once. Each opens a pool of
DB_POOL_SIZE + DB_MAX_OVERFLOW, so the fleet asked for far more than Postgres's
100 and roughly half of `/api/v1/radar` began failing with "too many clients".

**HQ reported the database healthy throughout.** Its probe runs `SELECT 1` on a
connection it has ALREADY acquired, so saturation is the one database failure
that a liveness probe cannot see — it is precisely the class of thing that made
HQ green while the Lab froze 72% of its book. Hence a measured number and a
threshold rather than a ping.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.hq_ops.schemas import (
    ComponentHealth,
    DiskHealth,
    OperationsHealth,
    QueueHealth,
    SchedulerHealth,
    WorkerHealth,
)
from app.hq_ops.service import DB_CONNECTIONS_WARN_PCT, detect


def _health(*, used: int | None, cap: int | None) -> OperationsHealth:
    ok = ComponentHealth(component="x", status="healthy", detail="", measured=True)
    db = ComponentHealth(component="database", status="healthy", detail="",
                         measured=True, connections_used=used, connections_max=cap)
    return OperationsHealth(
        disk=DiskHealth(status="healthy", percent_used=10.0, warning_percent=80,
                        critical_percent=90, detail="", measured=True),
        redis=ok, database=db,
        worker=WorkerHealth(status="healthy", nodes=["a"], replies=1, detail="",
                            measured=True),
        scheduler=SchedulerHealth(status="healthy", last_beat=None,
                                  seconds_since_beat=1.0,
                                  expected_within_seconds=120, detail="",
                                  measured=True),
        queues=QueueHealth(status="healthy", depths={}, total=0, detail="",
                           measured=True),
        tasks=[], tasks_failing=0,
        overall="healthy", unmeasured=0, environment="test", version="0",
        observed_at=datetime.now(UTC),
    )


def _signatures(health) -> set[str]:
    return {c.signature for c in detect(health)}


def test_a_quiet_pool_raises_nothing():
    assert "database:connections-high" not in _signatures(_health(used=40, cap=100))


def test_crossing_the_threshold_raises_a_condition():
    assert "database:connections-high" in _signatures(_health(used=90, cap=100))


def test_the_incident_that_prompted_this_would_now_be_caught():
    """105 of 100 — the actual reading while /api/v1/radar was failing."""
    found = [c for c in detect(_health(used=105, cap=100))
             if c.signature == "database:connections-high"]
    assert found, "the exact production incident must raise"
    assert "105" in found[0].summary and "100" in found[0].summary


def test_it_never_carries_a_remediation():
    """Nothing safe can be done automatically. Terminating backends kills real
    queries, and the fix is a pool-size or max_connections decision weighed
    against the box's RAM — 3GB here, which is why max_connections was NOT
    raised when this happened."""
    found = [c for c in detect(_health(used=99, cap=100))
             if c.signature == "database:connections-high"]
    assert found and found[0].remediation is None


def test_it_is_a_warning_not_a_critical():
    """A full pool degrades service; it does not mean the database is down, and
    crying critical on a warning is how a reader learns to ignore the page."""
    found = [c for c in detect(_health(used=95, cap=100))
             if c.signature == "database:connections-high"]
    assert found and found[0].severity == "warning"


def test_an_unreadable_count_says_nothing_rather_than_all_clear():
    """UNKNOWN is not healthy. If the count could not be read, the absence of a
    condition must come from having no measurement — never from a zero that was
    never observed."""
    assert "database:connections-high" not in _signatures(_health(used=None, cap=None))
    assert "database:connections-high" not in _signatures(_health(used=95, cap=None))


def test_the_threshold_is_a_percentage_not_a_count():
    """So it survives someone raising max_connections instead of silently
    becoming meaningless — 90 connections of 200 is not a problem."""
    assert DB_CONNECTIONS_WARN_PCT == 90.0
    assert "database:connections-high" not in _signatures(_health(used=90, cap=200))
    assert "database:connections-high" in _signatures(_health(used=180, cap=200))
