"""Unit tests for the secondary provider's call budget.

The clock is injected everywhere, so these are exact rather than timing-
dependent — a budget test that sleeps is a flaky test.
"""

from __future__ import annotations

import pytest

from app.services.market.providers.rate_budget import CallBudget

pytestmark = pytest.mark.unit


class FakeClock:
    def __init__(self, now: float = 0.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def test_starts_full() -> None:
    """A freshly started worker has spent nothing."""
    budget = CallBudget(25, clock=FakeClock())
    assert budget.available() == 25


def test_spends_down_to_zero_then_refuses() -> None:
    budget = CallBudget(3, clock=FakeClock())
    assert [budget.try_acquire() for _ in range(3)] == [True, True, True]
    assert budget.try_acquire() is False
    assert budget.available() == 0


def test_refuses_rather_than_waits() -> None:
    """The contract that keeps a slow secondary from stalling enrichment."""
    budget = CallBudget(1, clock=FakeClock())
    assert budget.try_acquire() is True
    # No sleep, no block — an immediate False.
    assert budget.try_acquire() is False


def test_refills_continuously_not_in_steps() -> None:
    """Half a window returns half the allowance, not nothing and not all."""
    clock = FakeClock()
    budget = CallBudget(30, window_seconds=60.0, clock=clock)
    for _ in range(30):
        budget.try_acquire()
    assert budget.available() == 0

    clock.advance(30.0)
    assert budget.available() == 15

    clock.advance(30.0)
    assert budget.available() == 30


def test_refill_never_exceeds_capacity() -> None:
    """Otherwise an idle worker banks an unbounded burst."""
    clock = FakeClock()
    budget = CallBudget(10, window_seconds=60.0, clock=clock)
    clock.advance(3600.0)
    assert budget.available() == 10


def test_a_stalled_clock_does_not_mint_tokens() -> None:
    """Guards against a non-monotonic clock handing out free calls."""
    clock = FakeClock()
    budget = CallBudget(5, clock=clock)
    for _ in range(5):
        budget.try_acquire()
    clock.advance(-100.0)
    assert budget.try_acquire() is False


def test_denials_are_counted_so_the_gap_is_reportable() -> None:
    budget = CallBudget(1, clock=FakeClock())
    budget.try_acquire()
    budget.try_acquire()
    budget.try_acquire()
    assert budget.denied == 2


def test_zero_capacity_refuses_everything() -> None:
    budget = CallBudget(0, clock=FakeClock())
    assert budget.try_acquire() is False


def test_acquiring_nothing_is_free() -> None:
    budget = CallBudget(0, clock=FakeClock())
    assert budget.try_acquire(0) is True


@pytest.mark.parametrize(
    ("capacity", "window"),
    [(-1, 60.0), (5, 0.0), (5, -1.0)],
)
def test_invalid_configuration_fails_loudly(capacity: int, window: float) -> None:
    with pytest.raises(ValueError):
        CallBudget(capacity, window_seconds=window)
