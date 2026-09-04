"""The safety properties of HQ's autonomy, as assertions rather than prose.

Everything here is about what HQ must *refuse* to do. The happy path — a
worker restarts and the incident closes — was verified against real
infrastructure; what a test suite is for is the set of things that must never
happen no matter how the code is edited later.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.hq_ops import invariants
from app.hq_ops.remediation import AUTONOMOUS_KEYS, REMEDIATIONS, get
from app.hq_ops.schemas import (
    ComponentHealth,
    DiskHealth,
    OperationsHealth,
    QueueHealth,
    SchedulerHealth,
    WorkerHealth,
)
from app.hq_ops.service import detect

NOW = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)


def health(**overrides) -> OperationsHealth:
    """A healthy stack, with the parts a test cares about overridden."""
    base = dict(
        disk=DiskHealth(
            status="healthy",
            percent_used=20.0,
            warning_percent=75.0,
            critical_percent=85.0,
            detail="20% used.",
        ),
        redis=ComponentHealth(component="redis", status="healthy", detail="ok"),
        database=ComponentHealth(component="database", status="healthy", detail="ok"),
        worker=WorkerHealth(status="healthy", nodes=["celery@a"], replies=1, detail="ok"),
        scheduler=SchedulerHealth(
            status="healthy",
            last_beat=NOW,
            seconds_since_beat=5.0,
            expected_within_seconds=200.0,
            detail="ok",
        ),
        queues=QueueHealth(status="healthy", depths={"celery": 0}, total=0, detail="ok"),
        overall="healthy",
        unmeasured=0,
        environment="test",
        version="0.0.0",
        observed_at=NOW,
    )
    base.update(overrides)
    return OperationsHealth(**base)


# ── the allowlist is the security model ─────────────────────────────────


def test_the_allowlist_is_small_enough_to_read():
    """If this fails, somebody added a capability. That should be deliberate.

    The number is not sacred; the review is. A test that breaks when the set of
    things HQ can do to production changes is the cheapest possible way to make
    that change visible in a diff.
    """
    assert set(REMEDIATIONS) == {
        "worker.pool_restart",
        "disk.run_retention",
        "disk.emergency_check",
        "diagnostics.reprobe",
        # Added deliberately: the Lab could be watched stopping and not
        # restarted. Both do one thing — re-enqueue a task the beat already
        # runs — and `test_hq_lab_remediation` holds them to it by calling
        # them, not by reading their source.
        "lab.run_tick",
        "lab.refresh_marks",
    }


def test_nothing_outside_the_allowlist_resolves():
    for attempt in [
        "",
        "worker.pool_restart ",
        "../../etc/passwd",
        "app.workers.retention_tasks.prune_telemetry",
        "os.system",
        "worker.POOL_RESTART",
    ]:
        assert get(attempt) is None, f"{attempt!r} resolved to an action"


def test_only_green_actions_are_autonomous():
    for key in AUTONOMOUS_KEYS:
        assert REMEDIATIONS[key].autonomy == "green"
    for key, action in REMEDIATIONS.items():
        if action.autonomy != "green":
            assert key not in AUTONOMOUS_KEYS


def test_every_action_is_credited_to_a_real_hq_agent():
    # The room shows this name. A name here that no character has is a name the
    # office invents, which is the one thing HQ is not allowed to do.
    known = {"nova", "sentinel", "patch", "quinn", "byte", "echo", "karthik"}
    for action in REMEDIATIONS.values():
        assert action.agent in known, f"{action.key} credits unknown agent {action.agent}"


def test_no_action_claims_to_touch_trading():
    """A crude but load-bearing check on the summaries a person reads."""
    forbidden = ("wallet", "position", "strategy", "trade", "sign", "sell", "buy")
    for action in REMEDIATIONS.values():
        lowered = action.summary.lower()
        for word in forbidden:
            assert word not in lowered, f"{action.key} mentions {word!r}"


# ── preconditions refuse the dangerous cases ────────────────────────────


def test_worker_restart_refuses_when_the_broker_is_the_real_problem():
    """The case that matters most.

    A worker cannot answer when Redis is down — but the worker is not the
    fault, Redis is. Restarting a pool by shouting into a broker that is not
    there fails, and buries the real incident under a failed worker repair.
    """
    action = REMEDIATIONS["worker.pool_restart"]
    ok, why = action.precondition(
        health(
            worker=WorkerHealth(status="down", nodes=[], replies=0, detail="silent"),
            redis=ComponentHealth(component="redis", status="down", detail="gone"),
        )
    )
    assert ok is False
    assert "broker is down" in why


def test_worker_restart_refuses_a_worker_that_is_answering():
    action = REMEDIATIONS["worker.pool_restart"]
    ok, _why = action.precondition(health())
    assert ok is False


def test_worker_restart_accepts_a_silent_worker_on_a_live_broker():
    action = REMEDIATIONS["worker.pool_restart"]
    ok, _why = action.precondition(
        health(worker=WorkerHealth(status="down", nodes=[], replies=0, detail="silent"))
    )
    assert ok is True


def test_retention_refuses_when_no_worker_could_run_it():
    # Queueing a prune at a dead worker is not a repair, it is a message in a
    # bottle that also makes the incident look handled.
    action = REMEDIATIONS["disk.run_retention"]
    ok, _why = action.precondition(
        health(
            disk=DiskHealth(
                status="degraded",
                percent_used=80.0,
                warning_percent=75.0,
                critical_percent=85.0,
                detail="80% used.",
            ),
            worker=WorkerHealth(status="down", nodes=[], replies=0, detail="silent"),
        )
    )
    assert ok is False


def test_retention_refuses_on_an_unmeasured_disk():
    action = REMEDIATIONS["disk.run_retention"]
    ok, _why = action.precondition(
        health(
            disk=DiskHealth(
                status="unknown",
                percent_used=None,
                warning_percent=75.0,
                critical_percent=85.0,
                measured=False,
                detail="unreadable",
            )
        )
    )
    assert ok is False


# ── detection ───────────────────────────────────────────────────────────


def test_a_healthy_stack_produces_no_conditions():
    assert detect(health()) == []


def test_an_unmeasured_component_is_never_an_incident():
    """A broken probe must not generate a stream of incidents about itself."""
    conditions = detect(
        health(
            worker=WorkerHealth(
                status="unknown", nodes=[], replies=0, measured=False, detail="no channel"
            ),
            scheduler=SchedulerHealth(
                status="unknown",
                last_beat=None,
                seconds_since_beat=None,
                expected_within_seconds=200.0,
                measured=False,
                detail="no heartbeat",
            ),
            overall="unknown",
            unmeasured=2,
        )
    )
    assert conditions == []


def test_conditions_with_no_repair_say_so_rather_than_implying_one():
    """Redis, Postgres and the scheduler cannot be restarted from here.

    The API has no Docker socket and beat has no control channel. An incident
    that named a remediation for these would be promising something HQ cannot
    deliver.
    """
    conditions = detect(
        health(
            redis=ComponentHealth(component="redis", status="down", detail="gone"),
            database=ComponentHealth(component="database", status="down", detail="gone"),
            scheduler=SchedulerHealth(
                status="down",
                last_beat=NOW,
                seconds_since_beat=9999.0,
                expected_within_seconds=200.0,
                detail="stopped",
            ),
            overall="down",
        )
    )
    signatures = {condition.signature for condition in conditions}
    assert signatures == {"redis:down", "database:down", "scheduler:stopped"}
    for condition in conditions:
        assert condition.remediation is None


def test_disk_critical_and_warning_are_different_incidents():
    critical = detect(
        health(
            disk=DiskHealth(
                status="down",
                percent_used=90.0,
                warning_percent=75.0,
                critical_percent=85.0,
                detail="90%",
            ),
            overall="down",
        )
    )
    assert [c.signature for c in critical] == ["disk:critical"]
    assert critical[0].remediation == "disk.emergency_check"

    warning = detect(
        health(
            disk=DiskHealth(
                status="degraded",
                percent_used=80.0,
                warning_percent=75.0,
                critical_percent=85.0,
                detail="80%",
            ),
            overall="degraded",
        )
    )
    assert [c.signature for c in warning] == ["disk:warning"]
    assert warning[0].remediation == "disk.run_retention"


def test_signatures_are_stable_so_a_flapping_component_opens_one_incident():
    # The idempotency key. If these ever became time- or value-dependent, a
    # component that flapped for an hour would open thirty incidents.
    a = detect(
        health(worker=WorkerHealth(status="down", nodes=[], replies=0, detail="silent"))
    )
    b = detect(
        health(worker=WorkerHealth(status="down", nodes=[], replies=0, detail="different"))
    )
    assert [c.signature for c in a] == [c.signature for c in b]


# ── the protected trading rules ─────────────────────────────────────────


def test_the_invariant_fingerprint_is_stable_across_reads():
    assert invariants.compare(invariants.capture(), invariants.capture())["held"] is True


def test_the_fingerprint_actually_covers_the_rules_the_brief_names():
    values = invariants.capture()["values"]
    assert "REAL_WALLET_AUTOTRADE_ENABLED" in values
    assert "TOKEN_SECURITY_EVALUATION_ENABLED" in values

    strategies = values["_strategies"]
    assert isinstance(strategies, dict), "the strategy fingerprint failed to read"

    # Targeted by id rather than by "whichever one is operational". Which
    # strategies are operational varies by environment, and a test that keyed
    # off that would be asserting a config fact while claiming to assert a
    # policy one. The three numbers §26 protects belong to this strategy
    # whether or not this environment runs it.
    live = strategies["trailing_stop_25_secured_hold6h_v3"]
    assert live["hold_for_seconds"] == 6 * 3600
    assert live["trailing_drawdown"] == "0.25"
    assert live["trade_size_usd"] == "100"
    assert (
        "trailing_stop_25_secured_hold6h_v3" in strategies["_security_gated"]
    ), "the live strategy is not behind the security gate"


@pytest.mark.parametrize(
    "field",
    [
        "REAL_WALLET_AUTOTRADE_ENABLED",
        "TOKEN_SECURITY_EVALUATION_ENABLED",
        "REAL_WALLET_SAFETY_MAX_BUY_PRICE_IMPACT_PCT",
    ],
)
def test_a_changed_protected_rule_is_caught_and_named(field):
    import copy

    before = invariants.capture()
    after = copy.deepcopy(before)
    after["values"][field] = "TAMPERED"
    after["digest"] = "different"

    verdict = invariants.compare(before, after)
    assert verdict["held"] is False
    assert field in verdict["changed"]
    assert verdict["changed"][field]["after"] == "TAMPERED"


def test_a_changed_strategy_is_caught():
    import copy

    before = invariants.capture()
    after = copy.deepcopy(before)
    strategies = after["values"]["_strategies"]
    key = next(k for k, v in strategies.items() if isinstance(v, dict))
    strategies[key]["trade_size_usd"] = "999999"
    after["digest"] = "different"

    verdict = invariants.compare(before, after)
    assert verdict["held"] is False
    assert "_strategies" in verdict["changed"]
