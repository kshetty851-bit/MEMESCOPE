"""The `--all` loops. One test here is worth an incident.

`_backfill_all` and `_replay_all` drive the bounded beat passes in a loop until
there is nothing left. "Nothing left" has to be defined as **no progress**, not
as **no work done** — the two differ exactly once, and that once happened in
production on 2026-09-11: with only today's unpublished bhavcopy pending, every
pass reported one day walked while the pending count stayed at one, and the
loop span at an NSE request per second until it was killed.
"""

from __future__ import annotations

import asyncio

import pytest

from app.labs.nse_breakout import __main__ as cli


async def test_the_backfill_loop_stops_when_the_pending_count_stops_falling(
    monkeypatch,
) -> None:
    """**The production bug, reproduced.** A day too early to settle is walked
    on every pass and settles nothing: days=1 for ever, remaining=1 for ever.
    A loop that stops on `not days` never stops."""
    stuck = {"days": 1, "ok": 0, "rows": 0, "remaining_days": 1}
    monkeypatch.setattr(cli, "backfill_tick", _ticker(stuck))

    result = await asyncio.wait_for(cli._backfill_all(40), timeout=10)
    assert result["remaining_days"] == 1
    assert result["stalled"] is True, "it stopped, and said why"


async def test_the_backfill_loop_runs_while_it_is_making_progress(
    monkeypatch,
) -> None:
    passes = iter([
        {"days": 40, "ok": 38, "rows": 1000, "remaining_days": 80},
        {"days": 40, "ok": 40, "rows": 1000, "remaining_days": 40},
        {"days": 40, "ok": 40, "rows": 1000, "remaining_days": 0},
    ])
    monkeypatch.setattr(cli, "backfill_tick", lambda **_kw: _ready(next(passes)))

    result = await asyncio.wait_for(cli._backfill_all(40), timeout=5)
    assert result["days"] == 120 and result["rows"] == 3000
    assert result["remaining_days"] == 0 and result["stalled"] is False


async def test_the_replay_loop_stops_on_the_same_rule(monkeypatch) -> None:
    """A symbol the walk skips — too few bars — still counts as a symbol, so
    the replay loop has the identical failure available to it."""
    stuck = {"symbols": 1, "episodes": 0, "remaining": 1}
    monkeypatch.setattr(cli, "replay_tick", _ticker(stuck))

    result = await asyncio.wait_for(cli._replay_all(), timeout=10)
    assert result["remaining"] == 1 and result["stalled"] is True


async def test_a_loop_gives_up_on_an_error_rather_than_retrying_it(
    monkeypatch,
) -> None:
    monkeypatch.setattr(cli, "backfill_tick",
                        lambda **_kw: _ready({"error": "nse_tracker_backfill_failed"}))
    result = await asyncio.wait_for(cli._backfill_all(40), timeout=5)
    assert result["stopped"]["error"]


#: How many passes a loop may take before the test calls it stuck. Generous
#: against any real run (a 900-day backfill is 23 passes) and small enough that
#: a runaway loop fails in milliseconds.
STUCK_AFTER = 60


def _ticker(value: dict):
    """A stand-in tick that returns `value` and REFUSES to be called for ever.

    The refusal is the point. Without it a loop that cannot terminate does not
    fail the test, it writes unbounded progress output into pytest's capture
    buffer until the machine gives up — which is what happened the first time
    this test was written, and a test whose failure mode is "your laptop stops"
    is not a test anyone will keep.
    """
    calls = {"n": 0}

    def tick(**_kw):
        calls["n"] += 1
        if calls["n"] > STUCK_AFTER:
            raise AssertionError(
                f"the loop ran {STUCK_AFTER} passes without stopping")

        async def done() -> dict:
            return value
        return done()

    return tick


def _ready(value: dict):
    """`value` as an awaitable, so it can stand in for a tick coroutine."""
    async def done() -> dict:
        return value
    return done()


@pytest.mark.parametrize("command", ["ingest", "backfill", "detect", "near",
                                     "replay", "outcomes", "stats", "universe",
                                     "health"])
def test_every_documented_command_is_in_the_manual(command) -> None:
    """The CLI's module docstring is the operator's manual. A command missing
    from it is one nobody finds at 18:30 when the ingest has not landed."""
    assert command in cli.__doc__
