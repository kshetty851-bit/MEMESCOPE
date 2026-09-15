"""The fast exit loop: it must refuse by default, and it must not stop at one step.

The bug it exists to prevent is silent — an exit that works, just late — so the
check is on the two properties that make it different from the minute tick.
"""
from __future__ import annotations

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
    def __init__(self, ids: list[str]) -> None:
        self._ids = ids

    async def scalars(self, _stmt: object) -> _FakeScalars:
        return _FakeScalars(self._ids)


@pytest.mark.asyncio
async def test_refuses_while_execution_mode_is_disabled(monkeypatch) -> None:
    """Its default must be a no-op: deploying it may not start anything."""
    monkeypatch.setattr(settings, "REAL_WALLET_EXECUTION_MODE", "disabled")
    assert await scheduler._real_wallet_fast_exit_tick() == {
        "skipped": "execution_mode_disabled"
    }


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
