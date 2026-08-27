"""Nursery lifecycle: DISCOVERED -> OBSERVING -> decided, with history kept."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.models.research_data import NurseryAdmission
from app.models.token import DiscoveredToken
from app.radar import nursery
from app.radar.models import RadarSeries

pytestmark = pytest.mark.integration

NOW = datetime(2026, 8, 24, 12, 0, tzinfo=UTC)


class _Result:
    score = Decimal("61.5")


async def _token(db_session, *, discovered_at):
    token = DiscoveredToken(
        mint_address=f"MINT{uuid.uuid4().hex[:8]}",
        signature=f"SIG{uuid.uuid4().hex}",
        slot=1,
        discovered_at=discovered_at,
        source_program="pumpfun",
    )
    db_session.add(token)
    await db_session.flush()
    return token


def _series(token):
    return RadarSeries(
        mint_address=token.mint_address,
        observations=[],
        discovered_at=token.discovered_at,
        token_id=token.id,
    )


async def test_young_token_is_held_and_recorded(db_session, monkeypatch):
    monkeypatch.setattr(settings, "RADAR_MIN_OBSERVATION_MINUTES", 60)
    token = await _token(db_session, discovered_at=NOW - timedelta(minutes=5))
    gate = nursery.NurseryGate(db_session)

    assert await gate.hold(_series(token), _Result(), now=NOW) is True
    row = (await db_session.execute(
        select(NurseryAdmission).where(NurseryAdmission.token_id == token.id)
    )).scalar_one()
    assert row.status == "observing"
    assert row.window_minutes == 60
    assert row.entry_score == Decimal("61.5")


async def test_old_enough_token_is_released_and_decision_recorded_once(db_session, monkeypatch):
    monkeypatch.setattr(settings, "RADAR_MIN_OBSERVATION_MINUTES", 60)
    token = await _token(db_session, discovered_at=NOW - timedelta(minutes=5))
    gate = nursery.NurseryGate(db_session)
    series = _series(token)
    assert await gate.hold(series, _Result(), now=NOW) is True

    later = NOW + timedelta(minutes=61)
    assert await gate.hold(series, _Result(), now=later) is False
    await gate.record_window_decision(series, qualified=True, reason="qualified_at_window", now=later)
    await gate.record_admission(series, now=later)

    row = (await db_session.execute(
        select(NurseryAdmission).where(NurseryAdmission.token_id == token.id)
    )).scalar_one()
    assert row.status == "qualified"
    assert row.admitted_at is not None

    # A second decision cannot rewrite the first: status left 'observing'.
    await gate.record_window_decision(series, qualified=False, reason="score_10", now=later)
    await db_session.refresh(row)
    assert row.status == "qualified" and row.decision_reason == "qualified_at_window"


async def test_rejection_keeps_history_when_admitted_late(db_session, monkeypatch):
    monkeypatch.setattr(settings, "RADAR_MIN_OBSERVATION_MINUTES", 60)
    token = await _token(db_session, discovered_at=NOW - timedelta(minutes=1))
    gate = nursery.NurseryGate(db_session)
    series = _series(token)
    assert await gate.hold(series, _Result(), now=NOW)

    at_window = NOW + timedelta(minutes=90)
    await gate.record_window_decision(series, qualified=False, reason="score_31", now=at_window)
    much_later = NOW + timedelta(hours=5)
    await gate.record_admission(series, now=much_later)

    row = (await db_session.execute(
        select(NurseryAdmission).where(NurseryAdmission.token_id == token.id)
    )).scalar_one()
    assert row.status == "rejected"          # the window verdict stands...
    assert row.admitted_at == much_later     # ...and the late admission is a second fact


async def test_disabled_gate_changes_nothing(db_session, monkeypatch):
    monkeypatch.setattr(settings, "RADAR_MIN_OBSERVATION_MINUTES", 0)
    token = await _token(db_session, discovered_at=NOW - timedelta(seconds=30))
    gate = nursery.NurseryGate(db_session)
    assert await gate.hold(_series(token), _Result(), now=NOW) is False
    rows = (await db_session.execute(select(NurseryAdmission))).scalars().all()
    assert rows == []


async def test_expiry_closes_only_stale_observing_rows(db_session, monkeypatch):
    monkeypatch.setattr(settings, "RADAR_MIN_OBSERVATION_MINUTES", 60)
    monkeypatch.setattr(settings, "RADAR_NURSERY_EXPIRE_HOURS", 24)
    gate = nursery.NurseryGate(db_session)
    stale = await _token(db_session, discovered_at=NOW - timedelta(minutes=3))
    fresh = await _token(db_session, discovered_at=NOW - timedelta(minutes=3))
    assert await gate.hold(_series(stale), _Result(), now=NOW - timedelta(hours=30))
    assert await gate.hold(_series(fresh), _Result(), now=NOW)

    expired = await nursery.expire_stale(db_session, now=NOW)
    assert expired == 1
    statuses = dict(
        (await db_session.execute(
            select(NurseryAdmission.token_id, NurseryAdmission.status)
        )).all()
    )
    assert statuses[stale.id] == "expired" and statuses[fresh.id] == "observing"
