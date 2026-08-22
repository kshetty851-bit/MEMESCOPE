"""The operations probe, tested for the one property that matters.

A monitoring surface fails in a specific and expensive way: it reports healthy
when it could not see. Every test here is a variation on that — a probe that
raised, a heartbeat that never arrived, a worker that answered nothing — and
what each asserts is that the result says so rather than rounding up.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from app.hq_ops import probe as ops


class _FakeRedis:
    def __init__(self, *, value: object = None, fail: bool = False, llen: int = 0) -> None:
        self._value = value
        self._fail = fail
        self._llen = llen

    async def ping(self) -> bool:
        if self._fail:
            raise ConnectionError("no route to broker")
        return True

    async def get(self, _key: str) -> object:
        if self._fail:
            raise ConnectionError("no route to broker")
        return self._value

    async def llen(self, _key: str) -> int:
        if self._fail:
            raise ConnectionError("no route to broker")
        return self._llen


class _FakeSession:
    def __init__(self, *, fail: bool = False) -> None:
        self._fail = fail

    async def execute(self, _statement: object) -> None:
        if self._fail:
            raise ConnectionError("database is not accepting connections")


NOW = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)


# ── disk ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_disk_that_cannot_be_read_is_unknown_not_healthy(monkeypatch):
    def explode(_path: str):
        raise OSError("statvfs failed")

    monkeypatch.setattr(ops.shutil, "disk_usage", explode)
    disk = await ops._probe_disk()

    assert disk.status == "unknown"
    assert disk.measured is False
    assert disk.percent_used is None
    assert "could not be read" in disk.detail


@pytest.mark.asyncio
async def test_disk_uses_the_same_thresholds_the_retention_task_acts_on(monkeypatch):
    from app.core.config import settings

    # One percent past critical. The retention task would emergency-prune here,
    # so the room must not be showing a calm disk row.
    critical = settings.DISK_CRITICAL_PERCENT
    monkeypatch.setattr(
        ops.shutil, "disk_usage", lambda _p: (100.0, critical + 1.0, 0.0)
    )
    disk = await ops._probe_disk()

    assert disk.status == "down"
    assert disk.critical_percent == critical


@pytest.mark.asyncio
async def test_disk_below_the_warning_line_is_healthy(monkeypatch):
    monkeypatch.setattr(ops.shutil, "disk_usage", lambda _p: (100.0, 10.0, 90.0))
    disk = await ops._probe_disk()

    assert disk.status == "healthy"
    assert disk.percent_used == 10.0


# ── worker ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_worker_that_answers_nothing_is_down(monkeypatch):
    monkeypatch.setattr(ops, "_ping_workers", lambda: [])
    worker = await ops._probe_worker()

    assert worker.status == "down"
    assert worker.nodes == []
    assert worker.measured is True


@pytest.mark.asyncio
async def test_an_unreachable_control_channel_is_unknown_not_down(monkeypatch):
    # The distinction is the point. "The worker is dead" and "we could not ask"
    # call for different reactions, and only one of them is an incident.
    def explode():
        raise OSError("broker unreachable")

    monkeypatch.setattr(ops, "_ping_workers", explode)
    worker = await ops._probe_worker()

    assert worker.status == "unknown"
    assert worker.measured is False


@pytest.mark.asyncio
async def test_replying_workers_are_named(monkeypatch):
    monkeypatch.setattr(
        ops, "_ping_workers", lambda: [{"celery@b": {"ok": "pong"}}, {"celery@a": {"ok": "pong"}}]
    )
    worker = await ops._probe_worker()

    assert worker.status == "healthy"
    assert worker.nodes == ["celery@a", "celery@b"]
    assert worker.replies == 2


# ── scheduler ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_missing_heartbeat_is_unknown_because_it_is_ambiguous(monkeypatch):
    monkeypatch.setattr(ops, "get_redis", lambda: _FakeRedis(value=None))
    scheduler = await ops._probe_scheduler(now=NOW)

    assert scheduler.status == "unknown"
    assert scheduler.measured is False


@pytest.mark.asyncio
async def test_a_stale_heartbeat_is_down(monkeypatch):
    stale = (NOW - timedelta(seconds=ops.BEAT_EXPECTED_WITHIN_SECONDS + 60)).isoformat()
    monkeypatch.setattr(
        ops, "get_redis", lambda: _FakeRedis(value=json.dumps({"at": stale}))
    )
    scheduler = await ops._probe_scheduler(now=NOW)

    assert scheduler.status == "down"
    assert scheduler.seconds_since_beat is not None
    assert scheduler.seconds_since_beat > ops.BEAT_EXPECTED_WITHIN_SECONDS


@pytest.mark.asyncio
async def test_a_recent_heartbeat_is_healthy(monkeypatch):
    recent = (NOW - timedelta(seconds=30)).isoformat()
    monkeypatch.setattr(
        ops, "get_redis", lambda: _FakeRedis(value=json.dumps({"at": recent}))
    )
    scheduler = await ops._probe_scheduler(now=NOW)

    assert scheduler.status == "healthy"
    assert scheduler.seconds_since_beat == 30.0


@pytest.mark.asyncio
async def test_a_corrupt_heartbeat_does_not_raise(monkeypatch):
    monkeypatch.setattr(ops, "get_redis", lambda: _FakeRedis(value="{not json"))
    scheduler = await ops._probe_scheduler(now=NOW)

    assert scheduler.status == "unknown"
    assert scheduler.measured is False


# ── the roll-up ─────────────────────────────────────────────────────────


def test_unmeasured_components_neither_win_nor_lose_the_roll_up():
    # Four green rows and one probe that could not run is not an outage, and it
    # is not a clean bill of health either. The roll-up reports the worst thing
    # actually measured; the unmeasured row is surfaced by `unmeasured`.
    assert ops._roll_up(["healthy", "unknown", "healthy"]) == "healthy"
    assert ops._roll_up(["healthy", "unknown", "down"]) == "down"
    assert ops._roll_up(["healthy", "degraded"]) == "degraded"


def test_a_roll_up_with_nothing_measured_is_unknown():
    assert ops._roll_up(["unknown", "unknown"]) == "unknown"


# ── the whole snapshot ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_total_blackout_reports_unknown_rather_than_healthy(monkeypatch):
    """Every probe fails. Nothing in the result may look reassuring."""
    monkeypatch.setattr(ops, "get_redis", lambda: _FakeRedis(fail=True))
    monkeypatch.setattr(ops.shutil, "disk_usage", lambda _p: (_ for _ in ()).throw(OSError("x")))

    def explode():
        raise OSError("broker unreachable")

    monkeypatch.setattr(ops, "_ping_workers", explode)

    health = await ops.snapshot(_FakeSession(fail=True), now=NOW)

    assert health.overall in {"down", "unknown"}
    assert health.unmeasured >= 4
    assert health.disk.status != "healthy"
    assert health.worker.status != "healthy"
    assert health.scheduler.status != "healthy"
    # Redis and the database were *measured* and found dead — that is a real
    # outage, not an absence of information, and it must read as one.
    assert health.redis.status == "down"
    assert health.database.status == "down"


@pytest.mark.asyncio
async def test_a_healthy_stack_rolls_up_healthy(monkeypatch):
    recent = (NOW - timedelta(seconds=10)).isoformat()
    monkeypatch.setattr(
        ops, "get_redis", lambda: _FakeRedis(value=json.dumps({"at": recent}), llen=3)
    )
    monkeypatch.setattr(ops.shutil, "disk_usage", lambda _p: (100.0, 20.0, 80.0))
    monkeypatch.setattr(ops, "_ping_workers", lambda: [{"celery@a": {"ok": "pong"}}])

    health = await ops.snapshot(_FakeSession(), now=NOW)

    assert health.overall == "healthy"
    assert health.unmeasured == 0
    assert health.queues.total == 3
    assert health.observed_at == NOW
