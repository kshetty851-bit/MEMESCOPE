"""The fast exit loop: it must refuse by default, and it must not stop at one step.

The bug it exists to prevent is silent — an exit that works, just late — so the
check is on the two properties that make it different from the minute tick.
"""
from __future__ import annotations

import inspect

import pytest

from app.core.config import settings
from app.real_wallet import scheduler


class _FakeOutcome:
    def __init__(self, state: str, changed: bool) -> None:
        self.state, self.changed = state, changed
        self.intent_id, self.reason = "i1", None

    def as_dict(self) -> dict[str, object]:
        return {"state": self.state, "changed": self.changed}


class _FakeExecutor:
    """Four transitions then terminal, like the real state machine."""

    def __init__(self, session: object) -> None:
        self.calls = 0

    async def advance(self, intent_id: object, *, now: object) -> _FakeOutcome:
        self.calls += 1
        states = ["safety_approved", "order_created", "submitted", "reconciled"]
        if self.calls > len(states):
            return _FakeOutcome("reconciled", False)
        return _FakeOutcome(states[self.calls - 1], True)


class _FakeScalars:
    def __init__(self, ids: list[str]) -> None:
        self._ids = ids

    def all(self) -> list[str]:
        return self._ids


class _FakeSession:
    """Counts commits; `locks` answers the advisory-lock queries in order."""

    def __init__(self, ids: list[str], locks: list[bool] | None = None) -> None:
        self._ids = ids
        self._locks = list(locks or [])
        self.commits = 0

    async def scalars(self, _stmt: object) -> _FakeScalars:
        return _FakeScalars(self._ids)

    async def scalar(self, _stmt: object) -> bool:
        return self._locks.pop(0) if self._locks else True

    async def commit(self) -> None:
        self.commits += 1


@pytest.mark.asyncio
async def test_refuses_while_execution_mode_is_disabled(monkeypatch) -> None:
    """Its default must be a no-op: deploying it may not start anything."""
    monkeypatch.setattr(settings, "REAL_WALLET_EXECUTION_MODE", "disabled")
    assert await scheduler._real_wallet_fast_exit_tick() == {
        "skipped": "execution_mode_disabled"
    }


@pytest.mark.asyncio
async def test_idles_when_nothing_is_open(monkeypatch) -> None:
    """Production runs at mode="live" with the switch off, so the mode check
    gates nothing there. An empty book must not leave a 3-second loop polling."""
    monkeypatch.setattr(settings, "REAL_WALLET_EXECUTION_MODE", "live")

    async def _no_work() -> bool:
        return False

    monkeypatch.setattr(scheduler, "_has_work", _no_work)
    assert await scheduler._real_wallet_fast_exit_tick() == {"skipped": "nothing_open"}


@pytest.mark.asyncio
async def test_drain_walks_an_intent_past_a_single_transition(monkeypatch) -> None:
    """The whole point: one pass reaches SUBMITTED, not one step towards it.

    The minute tick advances once per call, so a SELL needed four more minutes
    to be submitted. If this ever regresses to one step the exit is late again
    and nothing else in the system notices.
    """
    monkeypatch.setattr(scheduler, "RealWalletExecutor", _FakeExecutor)
    moved = await scheduler._drain(_FakeSession(["i1"]), now_fn=lambda: None)
    assert [m["state"] for m in moved] == [
        "safety_approved", "order_created", "submitted", "reconciled"
    ]


@pytest.mark.asyncio
async def test_drain_commits_each_step_before_the_next(monkeypatch) -> None:
    """The signer is another process: it reloads the intent by id and sees only
    committed rows. With the steps chained in one transaction, the first live
    buy (2026-09-17) was refused `intent_not_found` at the signing step."""
    session = _FakeSession(["i1"])
    committed_before: list[int] = []

    class _Recording(_FakeExecutor):
        async def advance(self, intent_id: object, *, now: object) -> _FakeOutcome:
            committed_before.append(session.commits)
            return await super().advance(intent_id, now=now)

    monkeypatch.setattr(scheduler, "RealWalletExecutor", _Recording)
    await scheduler._drain(session, now_fn=lambda: None)
    assert committed_before == [0, 1, 2, 3, 4]


@pytest.mark.asyncio
async def test_drain_stops_when_another_pass_holds_the_lock(monkeypatch) -> None:
    """A commit releases the locks. If the minute tick takes them in that gap,
    this pass must leave the intent to it rather than advance it alongside."""
    monkeypatch.setattr(scheduler, "RealWalletExecutor", _FakeExecutor)
    # Both locks at the start, then the executor's is taken after step one.
    session = _FakeSession(["i1"], locks=[True, True, True, False])
    moved = await scheduler._drain(session, now_fn=lambda: None)
    assert [m["state"] for m in moved] == ["safety_approved"]
    assert await scheduler._drain(_FakeSession(["i1"], locks=[False]),
                                  now_fn=lambda: None) == []


@pytest.mark.asyncio
async def test_drain_is_bounded(monkeypatch) -> None:
    """A handler that reports `changed` without moving must not eat the window."""
    class _Stuck:
        def __init__(self, session: object) -> None:
            pass

        async def advance(self, intent_id: object, *, now: object) -> _FakeOutcome:
            return _FakeOutcome("created", True)

    monkeypatch.setattr(scheduler, "RealWalletExecutor", _Stuck)
    moved = await scheduler._drain(_FakeSession(["i1"]), now_fn=lambda: None)
    assert len(moved) == settings.REAL_WALLET_FAST_EXIT_MAX_STEPS


@pytest.mark.asyncio
async def test_the_fast_loop_enters_as_well_as_exits() -> None:
    """A five-minute hold cannot be entered on a once-a-minute beat.

    The clock starts at the WALLET's fill; the collapse starts at GRADUATION.
    So a late buy does not merely delay the sale, it pushes it PAST the cliff.
    Replayed over the graduation arm's own 145 trades:

        entry lag        wallet wiped
        0-15s                      0%
        0-30s                      9%
        0-60s                     51%
        exactly 60s              100%

    If this regresses to exit-only, entries fall back to `crontab(minute="*")`
    and nothing else in the system notices.
    """
    src = inspect.getsource(scheduler._real_wallet_fast_exit_tick)
    assert "RealWalletDriver(session).tick" in src, (
        "the fast loop must drive ENTRIES; exits alone leave buys on the "
        "minute beat, which wiped the wallet in 51% of replayed draws")
    assert "RealWalletExitDriver(session).tick" in src, "and still exit"


@pytest.mark.asyncio
async def test_a_fresh_decision_counts_as_work() -> None:
    """Idling on an empty book must not idle through the minute a buy is due.

    `_has_work` short-circuits the 3-second loop when nothing is open. Once the
    loop also enters, that is exactly the window an entry has to land in — so a
    fresh, eligible decision for the nominated strategy is work.
    """
    src = inspect.getsource(scheduler._has_work)
    assert "LabDecision" in src and "nominated_strategy" in src, (
        "with entries in the loop, a fresh decision is work — otherwise the "
        "fast path sleeps through the window it exists to serve")


@pytest.mark.asyncio
async def test_the_graduation_arm_keeps_the_loop_awake(monkeypatch) -> None:
    """Its decisions land mid-minute and are stale in sixty seconds; a loop
    that waited for the next beat to see one bought a median 55s late."""
    from types import SimpleNamespace

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return None

        async def scalar(self, _stmt):
            return 0  # nothing open, nothing unfinished, no decision yet

    def _switch(strategy):
        class _Service:
            def __init__(self, session):
                pass

            async def state(self):
                return SimpleNamespace(enabled=True, nominated_strategy=strategy)
        return _Service

    monkeypatch.setattr(scheduler, "SessionFactory", _Session)
    monkeypatch.setattr(scheduler, "AutotradeSwitchService", _switch("G-B3-5M"))
    assert await scheduler._has_work() is True
    # A strategy that decides on a ten-minute horizon still waits for a decision.
    monkeypatch.setattr(scheduler, "AutotradeSwitchService", _switch("V7-06"))
    assert await scheduler._has_work() is False
