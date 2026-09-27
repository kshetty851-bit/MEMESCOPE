"""Karthik's Lab counts every graduation since the book opened, bought or not."""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.labs.graduation import api, config
from app.labs.graduation.models import GradMigration

pytestmark = pytest.mark.integration


async def test_every_graduation_since_the_start_counts(db_session):
    start = next(s for s in config.FRESH_BOOKS if s.book == "KARTHIK_QUIET_5M").start
    db_session.add_all([
        GradMigration(mint="before", ts=start - timedelta(minutes=1)),
        GradMigration(mint="after1", ts=start + timedelta(hours=1)),
        GradMigration(mint="after2", ts=start + timedelta(days=2)),
    ])
    await db_session.flush()
    out = await api.karthik_book(db_session)
    assert out["graduations_seen"] == 2
    assert out["trades"] == 0            # none bought, and still counted
