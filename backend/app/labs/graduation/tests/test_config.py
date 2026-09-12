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


def test_the_mark_interval_can_resolve_the_shortest_hold() -> None:
    """A position can only leave at a price that was RECORDED, so the sampler's
    interval is the floor on exit accuracy — the tick cannot beat it.

    At sixty-second marks a two-minute hold could only exit at 2:00 or 3:00, a
    fifty per cent overshoot on the one variable the tournament is now about:
    wipeout rate rises monotonically with every extra minute held.
    """
    from app.labs.graduation.tournament import ARMS

    shortest = min(a.hold for a in ARMS) * 60
    assert shortest / 2 >= config.POSTGRAD_INTERVAL_S, (
        f"{config.POSTGRAD_INTERVAL_S}s marks cannot resolve a "
        f"{shortest}s hold")
    assert config.PAPER_INTERVAL_SECONDS <= config.POSTGRAD_INTERVAL_S, (
        "ticking slower than the marks arrive throws away resolution already "
        "paid for")
