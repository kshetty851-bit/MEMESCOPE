"""Settings whose VALUES are load-bearing, pinned so a change is deliberate."""

from __future__ import annotations

from app.labs.graduation import config


def test_the_call_budget_covers_the_poll_rate() -> None:
    """A bucket sized below what the poller needs does not fail — it THROTTLES,
    which silently lengthens the interval. That is the exact thing the
    three-second poll exists to fix, so it would be an invisible regression.

    Measured 2026-09-12: half of all graduates complete their curve within a
    minute of the lab first seeing them, and at a fifteen-second poll only 34%
    were ever observed incomplete, 16.6% at 90% or above. The poll interval is
    the population filter for every pre-graduation question, not a detail.
    """
    calls_per_poll = -(-config.MAX_WATCH_SET // config.MAX_ACCOUNTS_PER_CALL)
    needed = calls_per_poll * (60 / config.POLL_INTERVAL_S)
    assert needed <= config.RPC_CALLS_PER_MINUTE, (
        f"bucket {config.RPC_CALLS_PER_MINUTE}/min cannot sustain "
        f"{config.MAX_WATCH_SET} tokens every {config.POLL_INTERVAL_S}s "
        f"({needed:.0f}/min needed)")


def test_the_poll_is_fast_enough_to_see_a_curve_climb() -> None:
    """Half of graduates finish within a minute of first sighting, so a poll
    slower than a few seconds photographs the climb four times and calls the
    result a population."""
    assert config.POLL_INTERVAL_S <= 5
