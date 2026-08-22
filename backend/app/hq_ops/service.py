"""Detection, classification, and the one path that is allowed to act.

── DETECTION IS IDEMPOTENT, AND THAT IS THE WHOLE TRICK ─────────────────

Every condition has a `signature`. An incident is opened only when no incident
with that signature is already open. A component that flaps for an hour
produces one incident, not one every tick — which matters because the alternative
is an incident list nobody reads, and an incident list nobody reads is worse
than no incident list.

── THE ORDER OF OPERATIONS IS THE SAFETY PROPERTY ───────────────────────

    capture invariants
    fresh probe
    check precondition          ← against the fresh probe, never the stale one
    write audit row (attempted) ← before acting, so a crash still leaves evidence
    execute
    fresh probe
    verify
    capture invariants, compare ← a protected rule that moved fails the action
    complete audit row

The invariant check is last and it can fail an action that otherwise succeeded.
That is intentional. §26 says a deployment that changed a protected trading
rule must fail and raise an incident even if the thing it was doing worked.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.hq_ops import invariants
from app.hq_ops.probe import snapshot
from app.hq_ops.remediation import REMEDIATIONS, Remediation
from app.hq_ops.schemas import OperationsHealth
from app.models.hq_ops import HqAction, HqIncident

logger = get_logger(__name__)


@dataclass(frozen=True)
class Condition:
    """Something worth opening an incident about."""

    signature: str
    component: str
    severity: str
    summary: str
    #: The allowlist key that would repair it, when one exists. `None` is a
    #: first-class answer and the honest one for a dead Redis: HQ has no way
    #: to restart it, and the incident says so instead of implying otherwise.
    remediation: str | None
    symptoms: dict[str, Any]


def detect(health: OperationsHealth) -> list[Condition]:
    """Turn a reading into conditions. Pure — no database, no clock.

    Nothing here fires on `unknown`. An unmeasured component is not an
    incident: raising one would mean a broken probe generates a stream of
    incidents about itself, and the real signal — `unmeasured` on the
    operations endpoint — is already visible to anyone looking.
    """
    found: list[Condition] = []

    if health.worker.status == "down":
        found.append(
            Condition(
                signature="worker:not-answering",
                component="worker",
                severity="critical",
                summary="No Celery worker answered the control ping.",
                remediation="worker.pool_restart",
                symptoms={"detail": health.worker.detail, "replies": health.worker.replies},
            )
        )

    if health.disk.measured and health.disk.percent_used is not None:
        if health.disk.percent_used >= health.disk.critical_percent:
            found.append(
                Condition(
                    signature="disk:critical",
                    component="disk",
                    severity="critical",
                    summary=f"Disk at {health.disk.percent_used}%, past the critical line.",
                    remediation="disk.emergency_check",
                    symptoms={
                        "percent_used": health.disk.percent_used,
                        "critical_percent": health.disk.critical_percent,
                    },
                )
            )
        elif health.disk.percent_used >= health.disk.warning_percent:
            found.append(
                Condition(
                    signature="disk:warning",
                    component="disk",
                    severity="degraded",
                    summary=f"Disk at {health.disk.percent_used}%, past the warning line.",
                    remediation="disk.run_retention",
                    symptoms={
                        "percent_used": health.disk.percent_used,
                        "warning_percent": health.disk.warning_percent,
                    },
                )
            )

    if health.scheduler.status == "down":
        found.append(
            Condition(
                signature="scheduler:stopped",
                component="scheduler",
                severity="critical",
                summary="The scheduler has stopped publishing a heartbeat.",
                # No remediation exists. Beat has no control channel and the
                # API has no Docker socket, so restarting it is a human action.
                remediation=None,
                symptoms={
                    "seconds_since_beat": health.scheduler.seconds_since_beat,
                    "expected_within_seconds": health.scheduler.expected_within_seconds,
                },
            )
        )

    if health.redis.status == "down":
        found.append(
            Condition(
                signature="redis:down",
                component="redis",
                severity="critical",
                summary="Redis did not answer a ping.",
                remediation=None,
                symptoms={"detail": health.redis.detail},
            )
        )

    if health.database.status == "down":
        found.append(
            Condition(
                signature="database:down",
                component="database",
                severity="critical",
                summary="The database did not answer a query.",
                remediation=None,
                symptoms={"detail": health.database.detail},
            )
        )

    if health.queues.status == "degraded":
        found.append(
            Condition(
                signature="queues:backed-up",
                component="queues",
                severity="degraded",
                summary=health.queues.detail,
                # Depth alone is not a fault — a busy queue is a working queue.
                # This is raised so it is visible, not so it is fixed.
                remediation=None,
                symptoms={"depths": health.queues.depths, "total": health.queues.total},
            )
        )

    return found


#: Statuses that mean an incident is still live.
OPEN_STATUSES = ("open", "investigating", "repairing", "verifying", "awaiting_owner")

#: How many times HQ will attempt the same repair for one incident before it
#: stops and asks for a person.
#:
#: Not a rate limit — an admission. `worker.pool_restart` cannot fix a worker
#: whose *container* is stopped: there is no pool to restart, so the attempt
#: fails identically forever. Without this the audit trail fills with the same
#: failed repair every two minutes and the useful signal — that this needs
#: hands — never surfaces. Three attempts is enough to ride out a restart that
#: is merely slow, and few enough that the escalation still means something.
MAX_REPAIR_ATTEMPTS = 3


async def _next_sequence(session: AsyncSession, kind: str) -> int:
    result = await session.execute(
        select(func.coalesce(func.max(HqIncident.sequence), 0)).where(HqIncident.kind == kind)
    )
    return int(result.scalar_one()) + 1


CODE_PREFIX = {"incident": "INC", "investigation": "INV", "approval": "REQ"}


async def open_incident(
    session: AsyncSession,
    condition: Condition,
    *,
    kind: str = "incident",
    autonomy: str = "green",
    agent: str | None = "sentinel",
    owner_rationale: str | None = None,
) -> tuple[HqIncident, bool]:
    """Open an incident for a condition, or return the one already open.

    Returns `(incident, created)`. The caller needs to know which, because
    "Sentinel detected a worker failure" should be said once, not on every
    sixty-second tick for the rest of the outage.
    """
    existing = await session.execute(
        select(HqIncident)
        .where(
            HqIncident.signature == condition.signature,
            HqIncident.status.in_(OPEN_STATUSES),
        )
        .order_by(HqIncident.detected_at.desc())
        .limit(1)
    )
    found = existing.scalar_one_or_none()
    if found is not None:
        return found, False

    sequence = await _next_sequence(session, kind)
    incident = HqIncident(
        code=f"{CODE_PREFIX.get(kind, 'INC')}-{sequence:03d}",
        sequence=sequence,
        kind=kind,
        component=condition.component,
        severity=condition.severity,
        status="open",
        autonomy=autonomy,
        agent=agent,
        signature=condition.signature,
        symptoms={"summary": condition.summary, **condition.symptoms},
        owner_rationale=owner_rationale,
    )
    session.add(incident)
    await session.flush()
    logger.info(
        "hq_incident_opened",
        code=incident.code,
        component=incident.component,
        severity=incident.severity,
    )
    return incident, True


async def _attempts_so_far(
    session: AsyncSession, incident: HqIncident, action_key: str
) -> int:
    """How many times this repair has already been tried for this incident."""
    result = await session.execute(
        select(func.count())
        .select_from(HqAction)
        .where(
            HqAction.incident_id == incident.id,
            HqAction.action == action_key,
            HqAction.outcome.in_(("failed", "attempted")),
        )
    )
    return int(result.scalar_one())


async def resolve_incident(
    session: AsyncSession, incident: HqIncident, *, root_cause: str | None = None
) -> None:
    incident.status = "resolved"
    incident.resolved_at = datetime.now(UTC)
    if root_cause:
        incident.root_cause = root_cause
    await session.flush()
    logger.info("hq_incident_resolved", code=incident.code)


@dataclass
class ActionOutcome:
    """What actually happened, in the shape the audit row wants."""

    outcome: str
    detail: str
    result: dict[str, Any]
    verification: dict[str, Any]


async def run_remediation(
    session: AsyncSession,
    action: Remediation,
    *,
    incident: HqIncident | None,
    reason: str,
    health: OperationsHealth | None = None,
) -> ActionOutcome:
    """Run one permitted action, with the full §25 spine around it.

    `health` is only a hint for logging. The precondition is always evaluated
    against a probe taken here, because the reading that triggered detection
    may be a minute old and describing a condition that has since cleared —
    and restarting a worker that recovered on its own is a repair that causes
    the outage it was called for.
    """
    before_invariants = invariants.capture()
    fresh = await snapshot(session)
    ok, why = action.precondition(fresh)

    audit = HqAction(
        incident_id=incident.id if incident is not None else None,
        agent=action.agent,
        action=action.key,
        autonomy=action.autonomy,
        reason=reason,
        outcome="attempted",
        preconditions={"met": ok, "why": why, "checked_at": fresh.observed_at.isoformat()},
    )
    session.add(audit)
    # Committed before the action runs. An action that kills the process must
    # still leave a row saying it was attempted — a trail that only records
    # successes cannot explain an outage.
    await session.commit()

    if not ok:
        audit.outcome = "skipped"
        audit.result = {"note": "precondition not met"}
        await session.commit()
        return ActionOutcome("skipped", why, {}, {})

    try:
        result = await action.execute()
    except Exception as exc:
        logger.exception("hq_remediation_failed", action=action.key, error=str(exc))
        audit.outcome = "failed"
        audit.result = {"error": str(exc)}
        await session.commit()
        return ActionOutcome("failed", f"The action raised: {exc}", {"error": str(exc)}, {})

    after = await snapshot(session)
    recovered, verify_why = action.verify(after)
    after_invariants = invariants.capture()
    invariant_check = invariants.compare(before_invariants, after_invariants)

    verification = {
        "recovered": recovered,
        "why": verify_why,
        "checked_at": after.observed_at.isoformat(),
        "invariants": invariant_check,
    }

    if not invariant_check["held"]:
        # The action may well have worked. It does not matter: a protected
        # trading rule moved while HQ was acting, and the only safe reading of
        # that is that something outside this process changed policy mid-flight.
        logger.error(
            "hq_invariant_violation", action=action.key, changed=invariant_check["changed"]
        )
        audit.outcome = "failed"
        audit.result = result
        audit.verification = verification
        await session.commit()
        await open_incident(
            session,
            Condition(
                signature="invariants:changed",
                component="trading-policy",
                severity="critical",
                summary="A protected trading rule changed during an autonomous action.",
                remediation=None,
                symptoms=invariant_check["changed"],
            ),
            autonomy="red",
            agent="quinn",
            owner_rationale=(
                "Protected trading policy changed while HQ was acting. No autonomous "
                "action may proceed until a person confirms this was an intended "
                "deployment."
            ),
        )
        await session.commit()
        return ActionOutcome(
            "failed", "Protected trading rules changed.", result, verification
        )

    audit.outcome = "succeeded" if recovered else "failed"
    audit.result = result
    audit.verification = verification
    await session.commit()
    return ActionOutcome(audit.outcome, verify_why, result, verification)


async def tick(session: AsyncSession) -> dict[str, Any]:
    """One autonomous pass: detect, open, repair what is permitted, close.

    This is the only code path in MEMESCOPE that acts on production without a
    person asking it to, and it is deliberately short enough to read in full.
    """
    health = await snapshot(session)
    conditions = detect(health)
    live = {condition.signature for condition in conditions}

    report: dict[str, Any] = {
        "observed_at": health.observed_at.isoformat(),
        "overall": health.overall,
        "detected": sorted(live),
        "opened": [],
        "repaired": [],
        "resolved": [],
    }

    # ── close what has recovered ────────────────────────────────────────
    # Before opening anything: an incident whose condition is gone is resolved
    # on evidence — the condition is absent from a fresh reading — rather than
    # by a timer or by somebody clicking it away.
    open_rows = await session.execute(
        select(HqIncident).where(
            HqIncident.status.in_(OPEN_STATUSES),
            HqIncident.kind == "incident",
        )
    )
    for incident in open_rows.scalars().all():
        if incident.signature not in live and incident.signature != "invariants:changed":
            await resolve_incident(
                session, incident, root_cause=incident.root_cause or "Condition cleared."
            )
            report["resolved"].append(incident.code)
    await session.commit()

    # ── open what is new, and repair what may be repaired ───────────────
    for condition in conditions:
        incident, created = await open_incident(session, condition)
        await session.commit()
        if created:
            report["opened"].append(incident.code)

        if condition.remediation is None:
            continue
        action = REMEDIATIONS.get(condition.remediation)
        if action is None or action.autonomy != "green":
            # Not autonomous. The incident stands and waits for a person.
            continue

        attempts = await _attempts_so_far(session, incident, action.key)
        if attempts >= MAX_REPAIR_ATTEMPTS:
            if incident.status != "awaiting_owner":
                incident.status = "awaiting_owner"
                incident.owner_rationale = (
                    f"{action.key} failed {attempts} times. HQ has no further "
                    f"permitted action for this condition and it needs a person."
                )
                await session.commit()
                logger.warning(
                    "hq_repair_escalated",
                    code=incident.code,
                    action=action.key,
                    attempts=attempts,
                )
            report["repaired"].append(
                {"code": incident.code, "action": action.key, "outcome": "escalated"}
            )
            continue

        incident.status = "repairing"
        await session.commit()
        outcome = await run_remediation(
            session,
            action,
            incident=incident,
            reason=condition.summary,
            health=health,
        )
        report["repaired"].append(
            {"code": incident.code, "action": action.key, "outcome": outcome.outcome}
        )
        # Status returns to `open` rather than `resolved`. Resolution is the
        # next tick's job, and only on evidence that the condition is gone —
        # a repair that reports success is not the same as a system that
        # recovered, and only one of those is worth telling somebody about.
        incident.status = "open" if outcome.outcome != "succeeded" else "verifying"
        await session.commit()

    return report
