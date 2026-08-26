"""The driver had no heartbeat.

Everything about the real wallet was built and correct — switch, nomination,
policy, order factory, signer — and nothing called `RealWalletDriver.tick`. The
operator could nominate a strategy, press START, and watch a switch that was on
while no intent was ever created. These tests exist so that cannot come back
silently.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app.real_wallet import scheduler as sched
from app.workers.celery_app import celery_app

pytestmark = pytest.mark.unit


def test_the_driver_is_actually_scheduled():
    entry = celery_app.conf.beat_schedule["real-wallet-driver-tick"]
    assert entry["task"] == "app.real_wallet.scheduler.real_wallet_driver_tick"
    # Every minute: a Lab decision is actionable for ten, and a slower tick
    # would spend most of that shelf life asleep.
    assert entry["schedule"].minute == {m for m in range(60)}


def test_the_scheduled_task_is_registered_under_the_name_beat_calls():
    assert "app.real_wallet.scheduler.real_wallet_driver_tick" in celery_app.tasks


def test_the_task_adds_no_authority_of_its_own():
    """It may call the driver and commit. It must not reach past it to create
    intents, sign, or submit — every barrier lives downstream of `tick`."""
    tree = ast.parse(Path(sched.__file__).read_text())
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.AsyncFunctionDef)
              and n.name == "_real_wallet_driver_tick")
    called = {n.func.attr for n in ast.walk(fn)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    assert "tick" in called
    assert not called & {"create_intent", "prepare", "sign", "submit",
                         "execute", "authorise", "sign_intent"}


def test_a_driver_failure_cannot_stop_the_beat():
    """Contained like the Lab's. Beat also carries the tasks that watch the
    kill switch's neighbours, and one wallet must not take them down."""
    tree = ast.parse(Path(sched.__file__).read_text())
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.AsyncFunctionDef)
              and n.name == "_real_wallet_driver_tick")
    handlers = [h for n in ast.walk(fn) if isinstance(n, ast.Try) for h in n.handlers]
    assert handlers, "an unhandled driver failure would raise into beat"
    assert not any(isinstance(n, ast.Raise) for h in handlers for n in ast.walk(h))


def test_two_ticks_cannot_run_at_once():
    """The intent's idempotency key stops a duplicate row, but two concurrent
    ticks would each read the open-position count before either wrote, and the
    policy would be counting a book that no longer exists."""
    src = Path(sched.__file__).read_text()
    assert "pg_try_advisory_xact_lock" in src
    assert sched.DRIVER_LOCK_KEY != sched.DRY_RUN_LOCK_KEY


async def test_the_switch_being_off_is_what_stops_it(monkeypatch):
    """The default state refuses at the first condition, so scheduling it
    changes nothing until an operator deliberately starts it."""
    from app.real_wallet.driver import RealWalletDriver

    class _Switch:
        enabled = False
        nominated_strategy = None

    class _Service:
        def __init__(self, _session): ...
        async def state(self): return _Switch()

    monkeypatch.setattr("app.real_wallet.driver.AutotradeSwitchService", _Service)
    outcome = await RealWalletDriver(object()).tick()
    assert outcome.created == 0
    assert outcome.skipped == "autotrade_switch_off"
