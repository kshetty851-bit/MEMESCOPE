"""Pump.fun Radar scheduling stays separate from opportunity scoring."""

from __future__ import annotations

import pytest

from app.workers.celery_app import celery_app

pytestmark = pytest.mark.unit


def test_pumpfun_radar_has_one_fifteen_minute_beat_entry() -> None:
    entry = celery_app.conf.beat_schedule["pumpfun-radar-scan"]

    assert entry["task"] == "app.radar.scheduler.pumpfun_radar_scan"
    assert set(entry["schedule"].minute) == {0, 15, 30, 45}
