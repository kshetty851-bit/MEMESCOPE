"""What the scheduled tasks actually RETURNED, not merely that they ran.

HQ measures liveness. Every probe it has answers "is this component up" — and
that is a genuinely different question from "is this component working". On
2026-08-26 the Lab's sellability sweep returned `{"failed": True}` on every run
for an hour: the beat published, the worker answered its ping, the queue was
empty, and HQ was solid green. The task ran perfectly. It just did not work.

The gap is structural, not accidental. Every scheduled task in this codebase
deliberately swallows its own exception so one failure cannot stop the beat that
carries the rest — which is right, and which is precisely why nothing upstream
ever sees the failure. The containment and the blindness are the same line of
code.

## How it works

One `task_postrun` signal handler. No task changes its code, and a task added
next year is covered the day it is written — an opt-in registry would be a list
somebody forgets to add to, which is the failure mode this module exists to
catch.

## What counts as a failure

Only two things: the task raised, or it returned a mapping with a truthy
`failed`. **`skipped` is not a failure.** `{"skipped": "autotrade_switch_off"}`
is the switch working, and a watch that cried about correct refusals would be
ignored inside a week — which is the same alarm-fatigue reasoning that keeps a
permanently-armed vault reported as idle.

## What it deliberately does not do

It does not store results, arguments or return values. It keeps a counter, a
timestamp and one short reason per task name, because a monitoring store that
accumulates payloads becomes a second database nobody is maintaining. Redis
holds it with a TTL, so a task that stops running disappears rather than
lingering as a stale green row.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.core.logging import get_logger

logger = get_logger(__name__)

#: One key per task name. Small on purpose: a counter, a verdict, a timestamp
#: and a short reason.
KEY_PREFIX = "hq:task:"

#: Long enough that an hourly task is still present at the next pass, short
#: enough that a task removed from the schedule vanishes rather than sitting
#: there green for ever. A stale row is worse than a missing one: it answers a
#: question nobody asked it any more.
TTL_SECONDS = 3 * 60 * 60

#: Consecutive failures before HQ calls it a condition. Two, not one: a single
#: failed pass is a bad minute — a network blip, a rate limit, a restart — and
#: raising on it would train the reader to dismiss the alert. Two consecutive is
#: a pattern, and at a one-minute cadence it is still noticed inside three.
FAILURE_THRESHOLD = 2

#: Reason strings are truncated rather than stored whole. This is a monitoring
#: row, not a log.
MAX_REASON = 120


def _verdict(state: str, result: Any) -> tuple[str, str]:
    """(verdict, reason) for one finished task.

    `skipped` is deliberately NOT a failure. A task that declines to act because
    a switch is off has worked exactly as designed, and treating a correct
    refusal as a fault is how a watch becomes noise.
    """
    if state != "SUCCESS":
        return "error", f"raised: {state}"
    if isinstance(result, dict):
        if result.get("failed"):
            # The shape every contained task uses when it caught its own
            # exception — the one that was invisible.
            reason = str(result.get("reason") or result.get("error") or "failed")
            return "failed", reason[:MAX_REASON]
        if result.get("skipped"):
            return "skipped", str(result["skipped"])[:MAX_REASON]
    return "ok", ""


async def record(task_name: str, *, state: str, result: Any,
                 now: datetime | None = None) -> None:
    """Write one outcome. Never raises into the task that just finished."""
    from app.core.redis import get_redis

    verdict, reason = _verdict(state, result)
    at = (now or datetime.now(UTC)).isoformat()
    key = f"{KEY_PREFIX}{task_name}"
    try:
        redis = await get_redis()
        pipe = redis.pipeline()
        pipe.hset(key, mapping={
            "verdict": verdict, "reason": reason, "at": at, "task": task_name,
        })
        # Consecutive, not total: what matters is whether it is failing NOW.
        # A task that failed twice last week and has worked since is not a
        # condition, and a total would say it was.
        if verdict in {"failed", "error"}:
            pipe.hincrby(key, "consecutive", 1)
        else:
            pipe.hset(key, "consecutive", 0)
        pipe.expire(key, TTL_SECONDS)
        await pipe.execute()
    except Exception:  # noqa: BLE001
        # A monitoring write must never be able to fail the thing it monitors.
        logger.debug("hq_task_outcome_write_failed", task=task_name, exc_info=True)


async def read_all() -> list[dict[str, Any]]:
    """Every task outcome currently known. Unreadable Redis returns empty."""
    from app.core.redis import get_redis

    try:
        redis = await get_redis()
        keys = [k async for k in redis.scan_iter(match=f"{KEY_PREFIX}*", count=200)]
        if not keys:
            return []
        pipe = redis.pipeline()
        for key in keys:
            pipe.hgetall(key)
        rows = await pipe.execute()
    except Exception:  # noqa: BLE001 - unreadable is not healthy, it is absent
        logger.warning("hq_task_outcomes_unreadable", exc_info=True)
        return []

    out: list[dict[str, Any]] = []
    for row in rows:
        if not row:
            continue
        out.append({
            "task": row.get("task", ""),
            "verdict": row.get("verdict", "unknown"),
            "reason": row.get("reason", ""),
            "at": row.get("at", ""),
            "consecutive_failures": int(row.get("consecutive", 0) or 0),
        })
    return sorted(out, key=lambda r: (-r["consecutive_failures"], r["task"]))


def failing(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The ones a person should be told about."""
    return [r for r in rows if r["consecutive_failures"] >= FAILURE_THRESHOLD]


__all__ = [
    "FAILURE_THRESHOLD",
    "KEY_PREFIX",
    "TTL_SECONDS",
    "failing",
    "read_all",
    "record",
]
