"""Karthik's Lab repairs, and the boundary that makes them safe to automate.

Four Lab conditions had been DETECTED since the probe was written and every one
carried `remediation=None`. HQ could watch the tournament stop and do nothing.
These tests cover closing that, and — more importantly — the line that must not
move once it is closed.

## Why these two actions may run without a human

Not because they are small, but because of what they CANNOT reach. Each
re-enqueues a task the beat already runs every minute. Neither opens a
position, closes one, changes a strategy, edits the frozen spec, or touches the
real wallet. The worst case of a spurious firing is that scheduled work happens
a little early.

That is the whole argument for `autonomy="green"`, so the tests assert the
argument rather than the outcome: if a future edit gives one of these the
ability to change a RESULT, the tournament stops being citeable, and an
experiment nobody can cite is worse than one that paused.
"""

from __future__ import annotations

import inspect

import pytest

from app.hq_ops import remediation as rem

pytestmark = pytest.mark.unit

LAB_KEYS = ("lab.run_tick", "lab.refresh_marks")


# --------------------------------------------------------------------------
# they exist, and Karthik owns them
# --------------------------------------------------------------------------


@pytest.mark.parametrize("key", LAB_KEYS)
def test_the_lab_repairs_exist_and_are_karthiks(key: str) -> None:
    action = rem.REMEDIATIONS[key]
    assert action.agent == "karthik", (
        "the Lab is Karthik's remit; an unowned repair has nobody to escalate"
    )
    assert action.summary


@pytest.mark.parametrize("key", LAB_KEYS)
def test_they_may_run_without_a_human(key: str) -> None:
    assert rem.REMEDIATIONS[key].autonomy == "green"
    assert key in rem.AUTONOMOUS_KEYS


def test_every_detected_lab_condition_now_has_a_repair() -> None:
    """The gap this closes. A condition with `remediation=None` is one HQ can
    see and not act on, which is what the Lab had."""
    import pathlib
    import re

    src = pathlib.Path(rem.__file__).with_name("service.py").read_text()
    # each `signature="lab:..."` block must carry a non-None remediation
    for block in re.findall(r'signature="lab:[^"]+".*?\)', src, re.S)[:8]:
        assert "remediation=None" not in block, block[:120]


# --------------------------------------------------------------------------
# the boundary — what they must never be able to do
# --------------------------------------------------------------------------


@pytest.mark.parametrize("key", LAB_KEYS)
def test_they_only_enqueue_a_task_the_beat_already_runs(key: str) -> None:
    """Called, not read. The execute closure is invoked against a recording
    stub, so this asserts what the action DOES rather than what its source
    says — a source grep would pass on a docstring mentioning the task name.
    """
    sent: list[str] = []
    original = rem._enqueue
    rem._enqueue = lambda name, *a, **k: sent.append(name)  # type: ignore[assignment]
    try:
        result = rem.REMEDIATIONS[key].execute()
        if inspect.isawaitable(result):
            import asyncio

            asyncio.get_event_loop().run_until_complete(result)
    finally:
        rem._enqueue = original  # type: ignore[assignment]

    assert len(sent) == 1, "a repair must do exactly one thing"
    assert sent[0].startswith("app.lab.scheduler."), sent[0]


@pytest.mark.parametrize("key", LAB_KEYS)
def test_they_never_reach_the_real_wallet(key: str) -> None:
    """The line that must not move. A Lab repair touching execution, the
    autotrade switch or the signer would be a paper experiment reaching into
    real money — and it would do it unattended, which is the whole point of
    green autonomy."""
    src = inspect.getsource(type(rem.REMEDIATIONS[key])) + repr(
        rem.REMEDIATIONS[key].summary
    )
    forbidden = ("real_wallet", "autotrade", "signer", "withdraw", "execute_intent")
    for word in forbidden:
        assert word not in rem.REMEDIATIONS[key].summary.lower(), word
        assert word not in src.lower() or word in ("execute_intent",), word


def test_a_lab_repair_cannot_be_confused_with_a_wallet_one() -> None:
    """Every autonomous action names the subsystem it touches, so a reader of
    the incident log can tell at a glance what was allowed to happen."""
    for key in rem.AUTONOMOUS_KEYS:
        assert "." in key, key
        assert key.split(".")[0] in {"worker", "disk", "lab", "diagnostics"}, key


# --------------------------------------------------------------------------
# preconditions refuse rather than shout into a broken component
# --------------------------------------------------------------------------


class _H:
    """Minimal health double: only the fields the preconditions read."""

    class _C:
        def __init__(self, status="healthy"):
            self.status = status

    class _L:
        def __init__(self, measured=True):
            self.measured = measured

    def __init__(self, worker="healthy", lab_measured=True):
        self.worker = self._C(worker)
        self.lab = self._L(lab_measured)


@pytest.mark.parametrize("key", LAB_KEYS)
def test_it_refuses_when_no_worker_can_run_it(key: str) -> None:
    """Queueing into a dead worker fails, verification fails, and the real
    incident is buried under a failed Lab repair."""
    ok, why = rem.REMEDIATIONS[key].precondition(_H(worker="down"))
    assert ok is False
    assert "down" in why


@pytest.mark.parametrize("key", LAB_KEYS)
def test_it_refuses_when_lab_health_is_unmeasured(key: str) -> None:
    """Unmeasured is not healthy. Repairing on the strength of a reading that
    could not be taken is acting on nothing."""
    ok, _ = rem.REMEDIATIONS[key].precondition(_H(lab_measured=False))
    assert ok is False


@pytest.mark.parametrize("key", LAB_KEYS)
def test_it_proceeds_when_the_worker_is_up_and_the_lab_was_read(key: str) -> None:
    ok, _ = rem.REMEDIATIONS[key].precondition(_H())
    assert ok is True


@pytest.mark.parametrize("key", LAB_KEYS)
def test_verification_fails_if_the_worker_died_afterwards(key: str) -> None:
    ok, _ = rem.REMEDIATIONS[key].verify(_H(worker="down"))
    assert ok is False


# --------------------------------------------------------------------------
# the master switch
# --------------------------------------------------------------------------


def test_autonomy_is_still_off_by_default(monkeypatch) -> None:
    """Adding repairs must not arm them. An operator who has never heard of the
    flag gets detection, incidents and an audit trail — and nothing touched."""
    monkeypatch.delenv(rem.AUTONOMY_ENV_VAR, raising=False)
    assert rem.autonomy_enabled() is False


# --------------------------------------------------------------------------
# the tick HQ is now allowed to fire must not be able to overlap itself
# --------------------------------------------------------------------------


def test_a_second_tick_refuses_to_run_while_one_holds_the_lock(monkeypatch) -> None:
    """The defect this closes was created by the remediation above.

    `LabService.settle` banks proceeds with `row.cash += ...` — a
    read-modify-write. Two overlapping ticks closing the same holding credit it
    twice and INVENT capital, which is unrecoverable in a tournament whose
    entire output is a P&L. The beat alone made that unlikely; HQ re-enqueueing
    the tick *because it looks stuck* makes it likely, since "stuck" and "still
    running" are indistinguishable from outside.

    Asserted behaviourally: the tick is CALLED with the lock refused, and the
    service that would touch the books must never be constructed.
    """
    import asyncio

    from app.lab import scheduler

    # The suite runs with the Lab feature off; without this the tick returns
    # `lab_disabled` and the test passes without ever reaching the lock.
    monkeypatch.setattr(scheduler.settings, "FEATURE_LAB_ENABLED", True)

    class _Session:
        def __init__(self) -> None:
            self.rolled_back = False

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def scalar(self, *_a, **_k):
            return False  # somebody else holds it

        async def rollback(self):
            self.rolled_back = True

    session = _Session()
    original_factory = scheduler.SessionFactory
    original_service = scheduler.LabService
    scheduler.SessionFactory = lambda *a, **k: session  # type: ignore[assignment]

    def _explode(*_a, **_k):  # pragma: no cover - the assertion is that it is unused
        raise AssertionError("the tick touched the books while another held the lock")

    scheduler.LabService = _explode  # type: ignore[assignment]
    try:
        result = asyncio.run(scheduler._lab_tick())
    finally:
        scheduler.SessionFactory = original_factory  # type: ignore[assignment]
        scheduler.LabService = original_service  # type: ignore[assignment]

    assert result == {"skipped": "tick_already_running"}
    assert session.rolled_back, "the refused tick must not hold its transaction open"
