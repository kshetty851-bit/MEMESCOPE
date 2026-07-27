"""Unit tests for the circuit breaker state machine."""

from __future__ import annotations

import pytest

from app.services.market.circuit_breaker import (
    CircuitBreaker,
    CircuitOpenError,
    CircuitState,
)

pytestmark = pytest.mark.unit


class FakeClock:
    """Controllable monotonic clock, so cooldowns need no sleeping."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _breaker(clock: FakeClock, **kwargs: object) -> CircuitBreaker:
    defaults = {"failure_threshold": 3, "reset_seconds": 10.0, "half_open_successes": 2}
    defaults.update(kwargs)
    return CircuitBreaker(name="test", _clock=clock, **defaults)  # type: ignore[arg-type]


def test_starts_closed_and_allows_requests() -> None:
    breaker = _breaker(FakeClock())
    assert breaker.state is CircuitState.CLOSED
    assert breaker.allows_request()


def test_opens_after_threshold_failures() -> None:
    breaker = _breaker(FakeClock())
    for _ in range(3):
        breaker.record_failure()
    assert breaker.state is CircuitState.OPEN
    assert not breaker.allows_request()


def test_stays_closed_below_threshold() -> None:
    breaker = _breaker(FakeClock())
    breaker.record_failure()
    breaker.record_failure()
    assert breaker.state is CircuitState.CLOSED


def test_success_resets_the_failure_count() -> None:
    """An intermittent failure must not accumulate towards tripping."""
    breaker = _breaker(FakeClock())
    breaker.record_failure()
    breaker.record_failure()
    breaker.record_success()
    breaker.record_failure()
    assert breaker.state is CircuitState.CLOSED


def test_open_breaker_raises_on_ensure_closed() -> None:
    breaker = _breaker(FakeClock())
    for _ in range(3):
        breaker.record_failure()
    with pytest.raises(CircuitOpenError, match="retry in"):
        breaker.ensure_closed()


def test_transitions_to_half_open_after_cooldown() -> None:
    clock = FakeClock()
    breaker = _breaker(clock)
    for _ in range(3):
        breaker.record_failure()
    assert breaker.state is CircuitState.OPEN

    clock.advance(10.0)
    assert breaker.state is CircuitState.HALF_OPEN
    assert breaker.allows_request()


def test_half_open_closes_after_enough_successes() -> None:
    clock = FakeClock()
    breaker = _breaker(clock)
    for _ in range(3):
        breaker.record_failure()
    clock.advance(10.0)

    breaker.record_success()
    assert breaker.state is CircuitState.HALF_OPEN
    breaker.record_success()
    assert breaker.state is CircuitState.CLOSED


def test_half_open_reopens_immediately_on_failure() -> None:
    """A failed probe means the dependency is still down; do not burn more."""
    clock = FakeClock()
    breaker = _breaker(clock)
    for _ in range(3):
        breaker.record_failure()
    clock.advance(10.0)
    assert breaker.state is CircuitState.HALF_OPEN

    breaker.record_failure()
    assert breaker.state is CircuitState.OPEN


def test_cooldown_restarts_after_reopening() -> None:
    clock = FakeClock()
    breaker = _breaker(clock)
    for _ in range(3):
        breaker.record_failure()
    clock.advance(10.0)
    breaker.record_failure()  # reopen at t=10

    clock.advance(5.0)
    assert breaker.state is CircuitState.OPEN
    clock.advance(5.0)
    assert breaker.state is CircuitState.HALF_OPEN


def test_reset_forces_closed() -> None:
    breaker = _breaker(FakeClock())
    for _ in range(3):
        breaker.record_failure()
    breaker.reset()
    assert breaker.state is CircuitState.CLOSED
    assert breaker.consecutive_failures == 0
