"""The allowlist. Everything HQ is permitted to do to the running system.

── THE SHAPE OF THE GUARANTEE ───────────────────────────────────────────

`REMEDIATIONS` is a dict compiled into the image. An action can only run if it
is a key in that dict, and the only way to add a key is a code change that goes
through review and deployment. There is no shell, no `eval`, no dynamic import,
no name taken from a request body and resolved to a callable, and no Docker
socket. The set of things HQ can do to production is exactly as long as the
list below, and it is readable in one screen.

That is the whole security model, and it is deliberately boring. The
alternative — a general "run this remediation" executor — is a remote code
execution primitive wearing a monitoring costume.

── WHAT IS NOT HERE, AND WHY ────────────────────────────────────────────

Restarting a *container* is not here. The API has no Docker socket, by design:
a web process that can restart its siblings is a web process worth attacking.
So a dead Redis, a dead Postgres or a stopped scheduler raise an incident and
wait for a person. HQ says so rather than pretending otherwise.

Editing code is not here either. §6 of the brief describes Patch writing a fix
and Quinn running the suite; that needs a coding agent with repository write
and deploy authority, which MEMESCOPE does not have and which this module will
not quietly invent. YELLOW work is investigated, evidenced and handed over.

── EVERY ACTION HAS THE SAME SPINE ──────────────────────────────────────

Precondition → audit row → execute → re-probe → verify → invariant check →
audit row completed. §25 of the brief, expressed as a dataclass so that no
action can skip a step by being written differently from its neighbours.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal

from app.core.logging import get_logger
from app.hq_ops.schemas import OperationsHealth

logger = get_logger(__name__)

Autonomy = Literal["green", "yellow", "red"]

#: How long to wait after a restart before asking whether it worked. A prefork
#: pool comes back in well under this; being impatient here would record a
#: successful repair as a failure and trigger a pointless second attempt.
VERIFY_SETTLE_SECONDS = 6.0


@dataclass(frozen=True)
class Remediation:
    """One permitted action, with every stage of §25 attached to it."""

    key: str
    autonomy: Autonomy
    #: Which HQ agent is credited in the room and in the audit trail.
    agent: str
    #: One line, shown to a person. Says what will happen, not what it hopes.
    summary: str
    #: Must return (ok, why). Evaluated against a *fresh* probe immediately
    #: before execution — never against the reading that triggered detection,
    #: which may be minutes old and describing a condition that has cleared.
    precondition: Callable[[OperationsHealth], tuple[bool, str]]
    #: The action. Blocking work belongs in a thread; this is awaited.
    execute: Callable[[], Awaitable[dict[str, Any]]]
    #: Must return (recovered, why), against a probe taken after the action.
    verify: Callable[[OperationsHealth], tuple[bool, str]]
    #: True when the action can be undone. All four GREEN actions below are
    #: forward-only and idempotent — restarting a pool twice is a restarted
    #: pool, pruning twice is a pruned database — so none needs a rollback,
    #: and claiming one would be inventing a safety net that does not exist.
    reversible: bool = False


# ── the actions ─────────────────────────────────────────────────────────


def _ping_workers_blocking() -> list[dict[str, Any]]:
    from app.workers.celery_app import celery_app

    return celery_app.control.ping(timeout=3.0) or []


def _pool_restart_blocking() -> list[dict[str, Any]]:
    """Restart the worker's process pool in place.

    The fix for the failure mode `worker_probe.py` documents: on 2026-08-21 the
    worker wedged on a Redis transaction and consumed nothing for fifty minutes
    while its container sat there `running`. A wedged pool keeps its socket and
    its process; only a pool restart clears it.

    `reload=False` restarts the pool without re-importing task modules, which
    is what is wanted — reloading code from a monitoring action would make this
    a deployment mechanism, and it is not one.
    """
    from app.workers.celery_app import celery_app

    return (
        celery_app.control.broadcast(
            "pool_restart", arguments={"reload": False}, reply=True, timeout=15.0
        )
        or []
    )


async def _restart_worker_pool() -> dict[str, Any]:
    replies = await asyncio.to_thread(_pool_restart_blocking)
    await asyncio.sleep(VERIFY_SETTLE_SECONDS)
    return {"replies": replies, "settled_for_seconds": VERIFY_SETTLE_SECONDS}


async def _enqueue(task_name: str) -> dict[str, Any]:
    """Hand a task to the broker. Never runs it in this process.

    Enqueuing rather than calling is not ceremony: `prune_telemetry` opens its
    own database connections and deletes in batches, and running that inside
    the API's request pool is how a monitoring endpoint takes down the API.
    """

    def send() -> str:
        from app.workers.celery_app import celery_app

        result = celery_app.send_task(task_name)
        return str(result.id)

    task_id = await asyncio.to_thread(send)
    return {"task": task_name, "task_id": task_id}


def _worker_is_answering(health: OperationsHealth) -> tuple[bool, str]:
    if health.worker.status == "healthy":
        return True, health.worker.detail
    return False, health.worker.detail


REMEDIATIONS: dict[str, Remediation] = {
    "worker.pool_restart": Remediation(
        key="worker.pool_restart",
        autonomy="green",
        agent="patch",
        summary="Restart the Celery worker's process pool.",
        # Two conditions, and the second matters as much as the first. A
        # worker that cannot be reached *because the broker is down* must not
        # be "repaired" by shouting a restart into a broker that is not there:
        # the restart would fail, verification would fail, and the real
        # incident — Redis — would be buried under a failed worker repair.
        precondition=lambda h: (
            (True, "Worker is not answering and the broker is reachable.")
            if h.worker.status in {"down", "unknown"} and h.redis.status == "healthy"
            else (
                False,
                f"Worker is {h.worker.status} and the broker is {h.redis.status}.",
            )
        ),
        execute=_restart_worker_pool,
        verify=_worker_is_answering,
    ),
    "disk.run_retention": Remediation(
        key="disk.run_retention",
        autonomy="green",
        agent="patch",
        summary="Enqueue the retention prune to reclaim disk.",
        precondition=lambda h: (
            (True, f"Disk at {h.disk.percent_used}%, past the warning line.")
            if (
                h.disk.measured
                and h.disk.percent_used is not None
                and h.disk.percent_used >= h.disk.warning_percent
                and h.worker.status == "healthy"
            )
            else (
                False,
                "Disk is below the warning line, unmeasured, or no worker can run the prune.",
            )
        ),
        execute=lambda: _enqueue("app.workers.retention_tasks.prune_telemetry"),
        # Deliberately weak, and honest about why: the prune is asynchronous
        # and deletes in batches, so the disk will not have moved by the time
        # this runs. What can be verified now is that the system is still able
        # to run the job. Whether space was reclaimed shows up in the *next*
        # detection pass, as the absence of the condition.
        verify=lambda h: (
            (True, "Prune accepted; the worker is still consuming.")
            if h.worker.status == "healthy"
            else (False, "The worker stopped answering after the prune was queued.")
        ),
    ),
    "disk.emergency_check": Remediation(
        key="disk.emergency_check",
        autonomy="green",
        agent="patch",
        summary="Enqueue the disk check, which emergency-prunes past critical.",
        precondition=lambda h: (
            (True, f"Disk at {h.disk.percent_used}%, past the critical line.")
            if (
                h.disk.measured
                and h.disk.percent_used is not None
                and h.disk.percent_used >= h.disk.critical_percent
                and h.worker.status == "healthy"
            )
            else (False, "Disk is not past critical, or no worker can run the check.")
        ),
        execute=lambda: _enqueue("app.workers.retention_tasks.check_disk_space"),
        verify=lambda h: (
            (True, "Check accepted; the worker is still consuming.")
            if h.worker.status == "healthy"
            else (False, "The worker stopped answering after the check was queued.")
        ),
    ),
    # ── KARTHIK: the Strategy Lab ────────────────────────────────────────
    #
    # Four Lab conditions have been DETECTED since the day the probe was built
    # and every one carried `remediation=None`: HQ could see the tournament
    # stop and do nothing about it. These two close that, and they are
    # deliberately the smallest actions that can.
    #
    # WHAT THEY CANNOT DO, because it is the whole basis for making them green:
    # neither opens a position, closes one, changes a strategy, touches the
    # frozen spec, or goes anywhere near the real wallet. Each re-enqueues a
    # task the beat already runs every minute, so the worst case of a spurious
    # firing is that scheduled work happens slightly early. A repair that could
    # change a RESULT would make the tournament unciteable, and an experiment
    # nobody can cite is worse than one that paused.
    "lab.run_tick": Remediation(
        key="lab.run_tick",
        autonomy="green",
        agent="karthik",
        summary="Re-enqueue the Lab tick. Judges due checkpoints and settles exits.",
        # The beat publishes every minute, so a Lab that has gone quiet for an
        # hour is not a slow market — it is a tick that is not arriving or not
        # completing. Requires a healthy worker for the same reason the worker
        # restart requires a healthy broker: shouting into a component that is
        # itself down buries the real incident under a failed repair.
        precondition=lambda h: (
            (True, "The Lab has gone silent and a worker is available to run it.")
            if h.worker.status == "healthy" and h.lab.measured
            else (
                False,
                f"Worker is {h.worker.status}"
                + ("" if h.lab.measured else " and Lab health is unmeasured"),
            )
        ),
        execute=lambda: _enqueue("app.lab.scheduler.lab_tick"),
        # Weak on purpose, like the retention prune above. A tick takes seconds
        # and decisions land asynchronously, so what is checkable now is that
        # the system can still run the job. Whether the Lab resumed shows up in
        # the NEXT detection pass, as the absence of the condition.
        verify=lambda h: (
            (True, "Tick accepted; the worker is still consuming.")
            if h.worker.status == "healthy"
            else (False, "The worker stopped answering after the tick was queued.")
        ),
    ),
    "lab.refresh_marks": Remediation(
        key="lab.refresh_marks",
        autonomy="green",
        agent="karthik",
        # Worded to keep clear of the vocabulary check in `test_hq_ops_safety`:
        # no HQ summary may read as though the office is acting on the book.
        # This re-quotes prices; it does not touch what is held.
        summary="Re-quote the mints the Lab holds so its marks can be taken again.",
        # The failure this answers is specific and has happened: on 2026-08-26
        # 162 of 224 open positions were skipped every tick as stale, so 72% of
        # the book sat frozen at its last healthy price while every liveness
        # signal read normal. The sweep is what un-freezes it.
        precondition=lambda h: (
            (True, "Marks are stale or unverified and a worker can re-quote them.")
            if h.worker.status == "healthy" and h.lab.measured
            else (
                False,
                f"Worker is {h.worker.status}"
                + ("" if h.lab.measured else " and Lab health is unmeasured"),
            )
        ),
        execute=lambda: _enqueue("app.lab.scheduler.lab_sellability_refresh"),
        verify=lambda h: (
            (True, "Refresh accepted; the worker is still consuming.")
            if h.worker.status == "healthy"
            else (False, "The worker stopped answering after the refresh was queued.")
        ),
    ),
    "compound.run_tick": Remediation(
        key="compound.run_tick",
        autonomy="green",
        agent="karthik",
        summary="Re-enqueue the Compound Lab tick. Judges, settles and banks cycles.",
        # Safe to fire spuriously for the same reason the Lab's is, plus one
        # that is specific to this tournament: `compound_tick` takes its own
        # advisory lock, so a second copy arriving while one is running is a
        # no-op rather than a second pass at banking a cycle. Without that lock
        # this repair would be the most dangerous one here — cycle banking
        # credits the wallet with a read-modify-write.
        precondition=lambda h: (
            (True, "The Compound Lab has gone silent and a worker is available.")
            if h.worker.status == "healthy"
            and h.compound is not None and h.compound.measured
            else (
                False,
                f"Worker is {h.worker.status}"
                + ("" if h.compound is not None and h.compound.measured
                   else " and Compound Lab health is unmeasured"),
            )
        ),
        execute=lambda: _enqueue("app.compound.scheduler.compound_tick"),
        verify=lambda h: (
            (True, "Tick accepted; the worker is still consuming.")
            if h.worker.status == "healthy"
            else (False, "The worker stopped answering after the tick was queued.")
        ),
    ),
    "diagnostics.reprobe": Remediation(
        key="diagnostics.reprobe",
        autonomy="green",
        agent="sentinel",
        summary="Re-read every component. Changes nothing.",
        precondition=lambda _h: (True, "Diagnostics are always permitted."),
        execute=lambda: _noop(),
        verify=lambda h: (True, f"Re-read {6 - h.unmeasured} of 6 components."),
        reversible=True,
    ),
}


async def _noop() -> dict[str, Any]:
    """The read-only action. Its entire effect is the probe around it."""
    return {"note": "read-only"}


#: Actions that may run without a human. Derived from the table rather than
#: listed again, so a remediation cannot be GREEN in one place and YELLOW in
#: another — the classification lives with the action or it does not live.
AUTONOMOUS_KEYS: frozenset[str] = frozenset(
    key for key, action in REMEDIATIONS.items() if action.autonomy == "green"
)

#: The environment variable that arms execution.
AUTONOMY_ENV_VAR = "HQ_AUTONOMY_ENABLED"

_TRUE = frozenset({"1", "true", "yes", "on"})


def autonomy_enabled() -> bool:
    """May HQ execute repairs, or only detect and record?

    ── DEFAULT IS OFF, AND THAT IS THE POINT ───────────────────────────

    An operator who deploys this without knowing about the flag gets a system
    that watches, opens incidents, and writes an audit trail — and touches
    nothing. Defaulting the other way would mean a forgotten environment
    variable is the difference between observation and a process that restarts
    production workers, and that is the wrong way round for a default to fail.

    Detection, incident records, resolution-on-evidence and the audit trail all
    run regardless. This gates exactly one thing: whether a permitted repair is
    actually executed. Observe-only is not a degraded mode — it is the same
    system with its hands behind its back, and an incident it would have
    repaired says so in the Owner Approval queue instead.

    ponytail: read straight from the environment rather than from `Settings`,
    because `app/core/config.py` currently carries a concurrent session's
    uncommitted work and adding a field there would sweep 185 unrelated lines
    into this commit. Move it into `Settings` — with the same default — once
    that lands; it is a three-line change and this function is the only caller
    site to update.
    """
    return os.getenv(AUTONOMY_ENV_VAR, "false").strip().lower() in _TRUE


def get(key: str) -> Remediation | None:
    """Look up a permitted action. Anything not in the table does not exist."""
    return REMEDIATIONS.get(key)
