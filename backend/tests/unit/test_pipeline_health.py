"""Pure health logic: classification, roll-up, and the scanner state contract.

These need no database. The endpoint's real queries are covered in
`tests/integration/test_pipeline_health_api.py`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.health.service import ScannerState, _minutes_since, classify, worst

pytestmark = pytest.mark.unit


class TestClassify:
    def test_fresh_output_is_healthy(self) -> None:
        assert classify(1.0, degraded_after=15, down_after=60) == "healthy"

    def test_between_the_thresholds_is_degraded(self) -> None:
        assert classify(20.0, degraded_after=15, down_after=60) == "degraded"

    def test_past_the_down_threshold_is_down(self) -> None:
        assert classify(90.0, degraded_after=15, down_after=60) == "down"

    @pytest.mark.parametrize(("minutes", "expected"), [(15.0, "degraded"), (60.0, "down")])
    def test_thresholds_are_inclusive(self, minutes: float, expected: str) -> None:
        """Exactly on the boundary is the worse state, not the better one.

        A stage sitting precisely on its threshold every poll should not
        alternate between two verdicts depending on rounding.
        """
        assert classify(minutes, degraded_after=15, down_after=60) == expected

    def test_a_stage_that_has_never_produced_anything_is_down(self) -> None:
        """Not healthy.

        A stage with no output has not demonstrated that it works, and
        reporting an empty pipeline as healthy is exactly the false reassurance
        this module exists to remove.
        """
        assert classify(None, degraded_after=15, down_after=60) == "down"


class TestWorst:
    def test_picks_the_worst_present(self) -> None:
        assert worst(["healthy", "degraded", "down"]) == "down"
        assert worst(["healthy", "degraded"]) == "degraded"
        assert worst(["healthy", "healthy"]) == "healthy"

    def test_no_enabled_stages_is_healthy(self) -> None:
        """An API-only replica with the whole pipeline switched off.

        Reporting it as down would make every such deployment page forever.
        """
        assert worst([]) == "healthy"


class TestMinutesSince:
    def test_measures_elapsed_minutes(self) -> None:
        now = datetime(2026, 8, 2, 12, 0, tzinfo=UTC)
        assert _minutes_since(now - timedelta(minutes=30), now=now) == pytest.approx(30.0)

    def test_never_returns_none_for_a_real_timestamp(self) -> None:
        now = datetime(2026, 8, 2, 12, 0, tzinfo=UTC)
        assert _minutes_since(now, now=now) == 0.0

    def test_absent_timestamp_is_none(self) -> None:
        assert _minutes_since(None, now=datetime.now(UTC)) is None

    def test_a_future_row_reads_as_zero_not_negative(self) -> None:
        """Container clock skew must not manufacture impossible health.

        A row stamped slightly ahead of the reader's clock would otherwise
        produce a negative age, which classifies as healthy no matter how far
        ahead it is.
        """
        now = datetime(2026, 8, 2, 12, 0, tzinfo=UTC)
        assert _minutes_since(now + timedelta(minutes=5), now=now) == 0.0


class TestScannerState:
    def test_parses_a_published_state(self) -> None:
        state = ScannerState.parse(
            '{"connected": false, "reconnect_attempts": 959, "failure_reason": "429"}'
        )
        assert state is not None
        assert state.connected is False
        assert state.reconnect_attempts == 959
        assert state.failure_reason == "429"

    def test_missing_state_is_none(self) -> None:
        assert ScannerState.parse(None) is None
        assert ScannerState.parse("") is None

    @pytest.mark.parametrize(
        "raw",
        ["not json at all", "[1, 2, 3]", '{"reconnect_attempts": "many"}', "null"],
    )
    def test_garbage_never_raises(self, raw: str) -> None:
        """The health endpoint must not 500 because a Redis value was junk.

        Unknown is a reportable state; an exception is not.
        """
        assert ScannerState.parse(raw) is None

    def test_absent_fields_default_rather_than_raising(self) -> None:
        state = ScannerState.parse('{"connected": true}')
        assert state is not None
        assert state.reconnect_attempts == 0
        assert state.failure_reason is None
