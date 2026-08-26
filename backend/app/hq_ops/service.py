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
from app.hq_ops.remediation import (
    AUTONOMY_ENV_VAR,
    REMEDIATIONS,
    Remediation,
    autonomy_enabled,
)
from app.hq_ops.task_outcomes import FAILURE_THRESHOLD as TASK_FAILURE_THRESHOLD

#: Lab thresholds. Here rather than in `app.lab.health`, with every other
#: threshold HQ acts on, so "amber at what?" has one answer in one place.
#:
#: Half the book. Not a tenth: some staleness is normal — a token stops being
#: enriched the moment it stops mattering — and a watch that fires on the normal
#: case is one nobody reads. At 72%, which is what was actually happening, the
#: Lab has stopped measuring most of what it holds.
LAB_STALE_PCT = 50.0

#: Below this, most of the book's VALUE rests on the CPMM model rather than on a
#: quote anyone could act on. Two thirds is deliberately demanding: the model
#: priced dying positions at cost, and the leaderboard is the thing a real
#: strategy gets chosen from.
LAB_QUOTE_BACKED_PCT = 66.0

#: Execution-rail thresholds.
#:
#: Five minutes of no movement. The executor advances one state per tick at one
#: tick a minute, so this is several passes with nothing happening — a stall,
#: not a slow step.
WALLET_STUCK_MINUTES = 5.0

#: Identical refusals in an hour before it is a wall rather than a decision.
#: Ten: a quiet hour legitimately produces a handful of the same skip, and
#: firing on three would report the system working.
WALLET_REPEAT_COUNT = 10

LAB_ENTRY_SILENCE_MINUTES = 60.0
LAB_EXIT_SILENCE_MINUTES = 180.0
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

    # A task that RUNS and FAILS. Liveness cannot see this: the beat published,
    # the worker answered, the queue drained — and the task returned
    # {"failed": True} every time. That is what happened to the Lab's
    # sellability sweep for an hour on 2026-08-26 while HQ showed green.
    #
    # No remediation. Restarting a worker does not fix a task that is failing
    # for its own reasons, and pretending otherwise would put a useless action
    # in the audit trail on every pass.
    for row in health.tasks:
        if row.consecutive_failures >= TASK_FAILURE_THRESHOLD:
            found.append(
                Condition(
                    signature=f"task:failing:{row.task}",
                    component="worker",
                    severity="degraded",
                    summary=(
                        f"{row.task} has failed {row.consecutive_failures} runs in a "
                        f"row: {row.reason or 'no reason recorded'}."
                    ),
                    remediation=None,
                    symptoms={
                        "task": row.task,
                        "consecutive_failures": row.consecutive_failures,
                        "reason": row.reason,
                        "last_at": row.at,
                    },
                )
            )

    # ── the Strategy Lab ────────────────────────────────────────────────
    #
    # None of these has a remediation and none of them ever will. HQ may
    # restart a worker; it may not touch a tournament, and an action here would
    # be changing the experiment it is supposed to be observing.
    lab = health.lab
    if lab is not None and lab.measured:
        if lab.stale_pct is not None and lab.stale_pct >= LAB_STALE_PCT:
            found.append(
                Condition(
                    signature="lab:book-unmarkable",
                    component="worker",
                    severity="degraded",
                    summary=(
                        f"{lab.stale_pct}% of the Lab's open book cannot be marked "
                        f"({lab.stale_positions} of {lab.open_positions} positions). "
                        "Those positions are frozen at their last price and are not "
                        "being evaluated for an exit."
                    ),
                    remediation=None,
                    symptoms={"stale_pct": lab.stale_pct,
                              "stale_positions": lab.stale_positions,
                              "open_positions": lab.open_positions},
                )
            )

        # By VALUE, not by count. The question is how much of the book's worth
        # rests on a model that has been wrong before, and a dust position and a
        # large one do not weigh the same.
        if (lab.quote_backed_pct is not None
                and lab.open_positions
                and lab.quote_backed_pct < LAB_QUOTE_BACKED_PCT):
            found.append(
                Condition(
                    signature="lab:marks-unverified",
                    component="worker",
                    severity="degraded",
                    summary=(
                        f"Only {lab.quote_backed_pct}% of the Lab's open value is "
                        "priced from a real sell quote; the rest is the CPMM model "
                        "over reported liquidity, which overstated dying positions "
                        "at cost before."
                    ),
                    remediation=None,
                    symptoms={"quote_backed_pct": lab.quote_backed_pct},
                )
            )

        # Silence, on both sides. Entries stopping and exits stopping are
        # different faults with the same appearance from outside: a beat that
        # keeps ticking.
        if (lab.minutes_since_decision is not None
                and lab.minutes_since_decision >= LAB_ENTRY_SILENCE_MINUTES):
            found.append(
                Condition(
                    signature="lab:no-decisions",
                    component="worker",
                    severity="degraded",
                    summary=(
                        f"The Lab has made no decision for {lab.minutes_since_decision:.0f} "
                        "minutes. Checkpoints run at admission, +30 and +60, so nothing "
                        "has reached any of them."
                    ),
                    remediation=None,
                    symptoms={"minutes_since_decision": lab.minutes_since_decision},
                )
            )

        if (lab.open_positions
                and lab.minutes_since_close is not None
                and lab.minutes_since_close >= LAB_EXIT_SILENCE_MINUTES):
            found.append(
                Condition(
                    signature="lab:no-closes",
                    component="worker",
                    severity="degraded",
                    summary=(
                        f"No Lab position has closed for {lab.minutes_since_close:.0f} "
                        f"minutes while {lab.open_positions} are open. Every trading "
                        "strategy carries a time exit of six hours or less, so the "
                        "exits themselves have stopped rather than the market gone quiet."
                    ),
                    remediation=None,
                    symptoms={"minutes_since_close": lab.minutes_since_close,
                              "open_positions": lab.open_positions},
                )
            )

    # ── the execution wallet ────────────────────────────────────────────
    wallet = health.wallet
    if wallet is not None and wallet.measured:
        # THE SECURITY ONE. Every other guard in this platform sits in front of
        # the rail and asks whether a spend may proceed. This is money that
        # never used the rail — a key used elsewhere, a signature produced
        # outside it. Critical, and deliberately the only wallet signal that is.
        if wallet.balance_unexplained:
            moved = abs(wallet.balance_delta_lamports or 0) / 1e9
            found.append(
                Condition(
                    signature="wallet:balance-unexplained",
                    component="worker",
                    severity="critical",
                    summary=(
                        f"The execution wallet is {moved:.6f} SOL lighter with no "
                        "submitted or confirmed intent to account for it. Money left "
                        "without going through the rail."
                    ),
                    # There is nothing safe to do automatically. Anything that
                    # could move funds in response is the same capability that
                    # may already be being misused.
                    remediation=None,
                    symptoms={
                        "delta_lamports": wallet.balance_delta_lamports,
                        "lamports": wallet.balance_lamports,
                        "observed_minutes_ago": wallet.balance_observed_minutes_ago,
                    },
                )
            )

        if (wallet.stuck_intents
                and wallet.oldest_stuck_minutes is not None
                and wallet.oldest_stuck_minutes >= WALLET_STUCK_MINUTES):
            found.append(
                Condition(
                    signature="wallet:intents-stuck",
                    component="worker",
                    severity="degraded",
                    summary=(
                        f"{wallet.stuck_intents} execution intent(s) have not advanced, "
                        f"the oldest for {wallet.oldest_stuck_minutes:.0f} minutes. The "
                        "executor advances one state per tick, so these are not moving."
                    ),
                    remediation=None,
                    symptoms={"stuck_intents": wallet.stuck_intents,
                              "oldest_stuck_minutes": wallet.oldest_stuck_minutes},
                )
            )

        # One rejection is the system working. Forty identical ones is a wall
        # nobody can see — which is exactly what `safety:` with nothing after it
        # was, for hours, while every intent was blocked.
        if (wallet.repeated_count is not None
                and wallet.repeated_count >= WALLET_REPEAT_COUNT):
            found.append(
                Condition(
                    signature="wallet:blocked-repeatedly",
                    component="worker",
                    severity="degraded",
                    summary=(
                        f"{wallet.repeated_count} intents blocked with the same reason "
                        f"in the last hour: {wallet.repeated_reason}. A refusal that "
                        "repeats is a wall, not a decision."
                    ),
                    remediation=None,
                    symptoms={"reason": wallet.repeated_reason,
                              "count": wallet.repeated_count},
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

    # Read once per pass rather than per condition, so a tick cannot be armed
    # for one incident and disarmed for the next.
    armed = autonomy_enabled()

    report: dict[str, Any] = {
        "observed_at": health.observed_at.isoformat(),
        "overall": health.overall,
        "armed": armed,
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

        if not armed:
            # Observe-only. Everything above this line still ran — the
            # condition was detected, the incident is open, and it will still
            # resolve on evidence when it clears. What is withheld is the hand
            # on the lever, and the incident says so rather than sitting in
            # `open` looking like nothing could be done about it.
            if incident.status != "awaiting_owner":
                incident.status = "awaiting_owner"
                incident.owner_rationale = (
                    f"HQ is in observe-only mode. {action.key} would have run here "
                    f"— {action.summary} Set {AUTONOMY_ENV_VAR}=true to arm execution."
                )
                await session.commit()
            report["repaired"].append(
                {"code": incident.code, "action": action.key, "outcome": "withheld"}
            )
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
