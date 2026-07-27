"""Unit tests for the retry backoff policy."""

from __future__ import annotations

import pytest

from app.core.backoff import BackoffPolicy

pytestmark = pytest.mark.unit


def test_delay_grows_exponentially_without_jitter() -> None:
    policy = BackoffPolicy(initial_seconds=1.0, max_seconds=60.0, multiplier=2.0, jitter=False)
    assert [policy.delay_for(n) for n in range(1, 6)] == [1.0, 2.0, 4.0, 8.0, 16.0]


def test_delay_is_capped() -> None:
    policy = BackoffPolicy(initial_seconds=1.0, max_seconds=10.0, multiplier=2.0, jitter=False)
    assert policy.delay_for(20) == 10.0


def test_jitter_stays_within_the_cap() -> None:
    """Full jitter spreads reconnects so clients do not retry in lockstep."""
    policy = BackoffPolicy(initial_seconds=1.0, max_seconds=8.0, multiplier=2.0, jitter=True)
    samples = [policy.delay_for(4) for _ in range(200)]
    assert all(0.0 <= sample <= 8.0 for sample in samples)
    # Astronomically unlikely to be constant unless jitter is broken.
    assert len(set(samples)) > 1


def test_attempt_must_be_positive() -> None:
    with pytest.raises(ValueError, match="attempt must be >= 1"):
        BackoffPolicy().delay_for(0)
