"""When the wallet says it will next look at the Radar.

Small, but worth pinning: the dashboard publishes a future timestamp, and a
prediction derived from a constant nobody checks is a prediction that eventually
goes wrong quietly.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.paper import cadence

pytestmark = pytest.mark.unit


class TestTheNextEvaluation:
    @pytest.mark.parametrize(
        ("minute", "expected"),
        [(0, 15), (1, 15), (14, 15), (16, 30), (31, 45), (46, 0)],
    )
    def test_it_lands_on_the_crontab_boundary(self, minute: int, expected: int) -> None:
        """Crontab minutes are absolute — `*/15` fires at :00, :15, :30, :45 —
        so this is the next boundary, not `now` plus fifteen minutes."""
        at = datetime(2026, 8, 5, 12, minute, 30, tzinfo=UTC)

        assert cadence.next_evaluation(at).minute == expected

    def test_a_tick_exactly_on_a_boundary_returns_the_next_one(self) -> None:
        """The moment has arrived, and the answer to "when next" is never "now"."""
        at = datetime(2026, 8, 5, 12, 15, 0, tzinfo=UTC)

        assert cadence.next_evaluation(at) == datetime(2026, 8, 5, 12, 30, tzinfo=UTC)

    def test_it_rolls_over_the_hour(self) -> None:
        at = datetime(2026, 8, 5, 12, 47, tzinfo=UTC)

        assert cadence.next_evaluation(at) == datetime(2026, 8, 5, 13, 0, tzinfo=UTC)


class TestItMatchesTheJobThatActuallyRuns:
    def test_the_published_cadence_is_the_radar_sweep_crontab(self) -> None:
        """The one thing that could make this module lie. If the beat is
        retimed and this constant is not, the page predicts an evaluation that
        does not happen.
        """
        from app.workers.celery_app import celery_app

        schedule = celery_app.conf.beat_schedule["radar-sweep"]["schedule"]

        assert schedule.minute == set(range(0, 60, cadence.RADAR_SWEEP_MINUTES))
