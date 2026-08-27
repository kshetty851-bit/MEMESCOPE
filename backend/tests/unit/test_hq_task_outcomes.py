"""HQ could not see a task that ran and failed.

On 2026-08-26 the Lab's sellability sweep returned `{"failed": True}` on every
run for an hour. The beat published, the worker answered its ping, the queue was
empty, and HQ was solid green. The task ran perfectly; it just did not work.

The gap is structural. Every scheduled task here deliberately swallows its own
exception so one failure cannot stop the beat carrying the rest — which is right,
and which is exactly why nothing upstream ever saw the failure.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app.hq_ops import service, task_outcomes
from app.hq_ops.schemas import TaskOutcome

pytestmark = pytest.mark.unit


def test_a_contained_failure_is_recognised():
    """`{"failed": True}` is the shape every contained task uses when it caught
    its own exception — the one that was invisible."""
    verdict, reason = task_outcomes._verdict("SUCCESS", {"failed": True})
    assert verdict == "failed"


def test_a_raised_task_is_recognised_separately_from_a_returned_failure():
    """They are different events and the reason should say which."""
    verdict, reason = task_outcomes._verdict("FAILURE", None)
    assert verdict == "error"
    assert "FAILURE" in reason


def test_a_skip_is_not_a_failure():
    """`{"skipped": "autotrade_switch_off"}` is the switch working exactly as
    designed. A watch that cried about correct refusals would be ignored inside
    a week — the same alarm-fatigue reasoning that keeps an armed vault idle."""
    verdict, _ = task_outcomes._verdict("SUCCESS", {"skipped": "autotrade_switch_off"})
    assert verdict == "skipped"
    assert verdict not in {"failed", "error"}


def test_ordinary_work_is_ok():
    assert task_outcomes._verdict("SUCCESS", {"created": 1})[0] == "ok"
    assert task_outcomes._verdict("SUCCESS", None)[0] == "ok"


def test_one_bad_pass_is_not_a_condition():
    """A single failed run is a bad minute — a blip, a rate limit, a restart.
    Raising on it trains the reader to dismiss the alert."""
    assert task_outcomes.FAILURE_THRESHOLD >= 2
    rows = [{"task": "x", "verdict": "failed", "reason": "", "at": "",
             "consecutive_failures": 1}]
    assert task_outcomes.failing(rows) == []


def test_a_run_of_failures_becomes_a_condition():
    health = _health(tasks=[TaskOutcome(
        task="app.lab.scheduler.lab_sellability_refresh", verdict="failed",
        reason="NameError: utcnow", at="2026-08-26T10:36:00Z",
        consecutive_failures=3,
    )])
    conditions = service.detect(health)
    task_conditions = [c for c in conditions if c.signature.startswith("task:failing:")]
    assert len(task_conditions) == 1
    found = task_conditions[0]
    # The reason has to travel with it. "A task failed" is not actionable;
    # "lab_sellability_refresh failed 3 runs: NameError" is.
    assert "lab_sellability_refresh" in found.summary
    assert "NameError" in found.summary
    # No remediation: restarting a worker does not fix a task failing for its
    # own reasons, and a useless action in the audit trail every pass is worse
    # than none.
    assert found.remediation is None


def test_a_skipping_task_never_becomes_a_condition():
    health = _health(tasks=[TaskOutcome(
        task="app.real_wallet.scheduler.real_wallet_driver_tick", verdict="skipped",
        reason="autotrade_switch_off", at="", consecutive_failures=0,
    )])
    assert [c for c in service.detect(health) if c.signature.startswith("task:")] == []


def test_task_faults_do_not_drag_down_the_infrastructure_verdict():
    """`overall` is a verdict on INFRASTRUCTURE. Folding a broken Lab sweep into
    it would make a failing task look like a sick database to anyone reading the
    top line. Different questions, different rows."""
    src = Path(__import__("app.hq_ops.probe", fromlist=["x"]).__file__).read_text()
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.AsyncFunctionDef) and n.name == "snapshot")
    body = ast.unparse(fn)
    parts = body[body.index("parts: list[ComponentStatus]"):body.index("return OperationsHealth")]
    assert "task" not in parts


def test_the_recorder_is_a_signal_so_no_task_can_forget_it():
    """A decorator or a registry is a list somebody forgets to add to — which is
    the exact failure mode this whole module exists to catch. A task written
    next year is covered the day it is written."""
    from app.workers import celery_app as ca

    src = Path(ca.__file__).read_text()
    assert "task_postrun.connect" in src
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "_record_task_outcome")
    # It must never be able to fail the task it observes.
    assert [h for n in ast.walk(fn) if isinstance(n, ast.Try) for h in n.handlers]


def test_unreadable_redis_reports_absence_not_health():
    """Empty means "nothing could be read", and the tasks row shows that rather
    than an implied all-clear."""
    src = Path(task_outcomes.__file__).read_text()
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.AsyncFunctionDef) and n.name == "read_all")
    body = ast.unparse(fn)
    assert "return []" in body
    assert "healthy" not in body


def _health(*, tasks):
    """A minimal OperationsHealth with everything else quiet."""
    from app.hq_ops.schemas import (
        ComponentHealth,
        DiskHealth,
        OperationsHealth,
        QueueHealth,
        SchedulerHealth,
        WorkerHealth,
    )
    from datetime import UTC, datetime

    ok = ComponentHealth(component="x", status="healthy", detail="", measured=True)
    return OperationsHealth(
        disk=DiskHealth(status="healthy", percent_used=10.0, warning_percent=80,
                        critical_percent=90, detail="", measured=True),
        redis=ok, database=ok,
        worker=WorkerHealth(status="healthy", nodes=["a"], replies=1, detail="",
                            measured=True),
        scheduler=SchedulerHealth(status="healthy", last_beat=None,
                                  seconds_since_beat=1.0,
                                  expected_within_seconds=120, detail="",
                                  measured=True),
        queues=QueueHealth(status="healthy", depths={}, total=0, detail="",
                           measured=True),
        tasks=tasks,
        tasks_failing=len([t for t in tasks if t.consecutive_failures >= 2]),
        overall="healthy", unmeasured=0, environment="test", version="0",
        observed_at=datetime.now(UTC),
    )
