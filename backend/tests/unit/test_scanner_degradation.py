"""Reconnect escalation.

The scanner sat on attempt 959 against an exhausted Helius quota for four days,
logging `warning` every time. The backoff was correct; the silence was not.
"""

from __future__ import annotations

import logging

import pytest

from app.core.config import settings
from app.services.scanner.scanner import TokenScanner

pytestmark = pytest.mark.unit


@pytest.fixture
def scanner() -> TokenScanner:
    # No connection is made: these tests drive the logging decision directly.
    return TokenScanner(ws_url="wss://example.invalid", programs=["prog"])


def _levels(caplog: pytest.LogCaptureFixture) -> list[int]:
    return [record.levelno for record in caplog.records]


class TestEscalation:
    def test_early_failures_stay_at_warning(
        self, scanner: TokenScanner, caplog: pytest.LogCaptureFixture
    ) -> None:
        """One failed reconnect is routine and must not page anybody."""
        with caplog.at_level(logging.DEBUG):
            scanner.stats.consecutive_failures = 1
            scanner._log_reconnect(RuntimeError("blip"), 1.0)

        assert _levels(caplog) == [logging.WARNING]

    def test_crossing_the_threshold_logs_error(
        self,
        scanner: TokenScanner,
        caplog: pytest.LogCaptureFixture,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(settings, "SCANNER_RECONNECT_ERROR_ATTEMPTS", 5)

        with caplog.at_level(logging.DEBUG):
            scanner.stats.consecutive_failures = 5
            scanner._log_reconnect(RuntimeError("HTTP 429"), 30.0)

        assert _levels(caplog) == [logging.ERROR]
        assert "scanner_reconnect_failing" in caplog.text

    def test_error_is_throttled_after_the_first(
        self,
        scanner: TokenScanner,
        caplog: pytest.LogCaptureFixture,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A weekend outage must not write a million identical ERROR lines."""
        monkeypatch.setattr(settings, "SCANNER_RECONNECT_ERROR_ATTEMPTS", 5)
        monkeypatch.setattr(settings, "SCANNER_RECONNECT_ERROR_EVERY", 20)

        with caplog.at_level(logging.DEBUG):
            for attempt in range(5, 46):
                scanner.stats.consecutive_failures = attempt
                scanner._log_reconnect(RuntimeError("HTTP 429"), 30.0)

        # Attempts 5, 25 and 45 — first escalation, then one in twenty.
        assert _levels(caplog) == [logging.ERROR] * 3

    def test_nothing_is_logged_at_warning_once_escalated(
        self,
        scanner: TokenScanner,
        caplog: pytest.LogCaptureFixture,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The explicit requirement: stop warning forever.

        Past the threshold the condition is either reported as an error or not
        reported at all — never downgraded back to a routine warning.
        """
        monkeypatch.setattr(settings, "SCANNER_RECONNECT_ERROR_ATTEMPTS", 3)
        monkeypatch.setattr(settings, "SCANNER_RECONNECT_ERROR_EVERY", 10)

        with caplog.at_level(logging.DEBUG):
            for attempt in range(3, 30):
                scanner.stats.consecutive_failures = attempt
                scanner._log_reconnect(RuntimeError("HTTP 429"), 30.0)

        assert logging.WARNING not in _levels(caplog)

    def test_the_error_names_the_consequence(
        self,
        scanner: TokenScanner,
        caplog: pytest.LogCaptureFixture,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A reader must not have to infer that discovery has stopped."""
        monkeypatch.setattr(settings, "SCANNER_RECONNECT_ERROR_ATTEMPTS", 2)

        with caplog.at_level(logging.DEBUG):
            scanner.stats.consecutive_failures = 2
            scanner._log_reconnect(RuntimeError("HTTP 429"), 30.0)

        assert "Discovery has stopped" in caplog.text
        assert "HTTP 429" in caplog.text


class TestStats:
    def test_consecutive_failures_are_tracked_separately_from_the_total(
        self, scanner: TokenScanner
    ) -> None:
        """`reconnects` never falls, so it cannot answer "is it failing now".

        A scanner that dropped twice last week and is connected right now must
        not read as degraded.
        """
        scanner.stats.reconnects = 959
        scanner.stats.consecutive_failures = 0

        assert scanner.stats.as_dict()["reconnects"] == 959
        assert scanner.stats.as_dict()["consecutive_failures"] == 0

    def test_failure_reason_is_reported(self, scanner: TokenScanner) -> None:
        scanner.stats.last_failure_reason = "InvalidStatus: HTTP 429"
        assert scanner.stats.as_dict()["last_failure_reason"] == "InvalidStatus: HTTP 429"


class TestRecoveryGapMarker:
    """The gap marker decides which slots a recovery walk covers, so losing it
    loses every launch in the outage it was meant to cover."""

    async def test_the_marker_is_snapshotted_before_live_consumption_resumes(
        self, scanner: TokenScanner
    ) -> None:
        """Read inside the task instead, the first live notification after a
        reconnect advances `_last_slot` to the tip within milliseconds and the
        walk finds "no gap" — observed live on 2026-08-20."""
        scanner._last_slot = 500

        scanner._maybe_start_recovery()

        assert scanner._pending_recovery_slot == 500
        assert scanner._recovery is not None
        scanner._recovery.cancel()

    async def test_a_reconnect_during_a_walk_queues_its_gap_rather_than_dropping_it(
        self, scanner: TokenScanner
    ) -> None:
        """A second outage while the first walk is still running must not be
        forfeited: live consumption has already advanced past it."""
        scanner._last_slot = 500
        scanner._maybe_start_recovery()
        running = scanner._recovery
        assert running is not None

        # The walk claims the marker, as `_recovery_loop` does.
        scanner._pending_recovery_slot = None
        scanner._last_slot = 3000
        scanner._maybe_start_recovery()

        assert scanner._pending_recovery_slot == 3000
        # Still the same task: walks never overlap.
        assert scanner._recovery is running
        running.cancel()

    async def test_the_earliest_queued_gap_wins(self, scanner: TokenScanner) -> None:
        """Two reconnects while a walk runs: recovery must resume from the
        older marker, or the slots between them are never read."""
        scanner._last_slot = 900
        scanner._maybe_start_recovery()
        task = scanner._recovery
        assert task is not None

        scanner._last_slot = 1200
        scanner._maybe_start_recovery()

        assert scanner._pending_recovery_slot == 900
        task.cancel()

    async def test_recovery_is_off_when_the_slot_budget_is_zero(
        self, scanner: TokenScanner, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "SCANNER_RECOVERY_MAX_SLOTS", 0)
        scanner._last_slot = 500

        scanner._maybe_start_recovery()

        assert scanner._recovery is None
        assert scanner._pending_recovery_slot is None
