"""The lifecycle pass is actually scheduled.

The engine's transitions were complete and correct while nothing in production
called them, so the registration is the part worth asserting: a task that beat
does not know about is indistinguishable from one that was never written.
"""

from __future__ import annotations

import pytest

from app.workers.celery_app import celery_app

pytestmark = pytest.mark.unit


def test_the_lifecycle_pass_is_registered_with_beat() -> None:
    entry = celery_app.conf.beat_schedule["opportunity-review"]

    assert entry["task"] == "app.opportunities.scheduler.opportunity_review"
    assert set(entry["schedule"].minute) == set(range(0, 60, 5))


def test_the_scheduler_module_is_imported_by_the_worker() -> None:
    """Registered in beat but absent from `include` is a NotRegistered at run
    time — the failure only appears once the schedule first fires."""
    assert "app.opportunities.scheduler" in celery_app.conf.include
