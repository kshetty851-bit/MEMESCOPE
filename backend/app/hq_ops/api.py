"""`GET /api/v1/hq/operations`.

Its own `/hq` namespace rather than a third route under `/health`, because it
answers a different question from either endpoint already there. `/live` and
`/ready` report this process. `/health/pipeline` reports whether the platform
is still producing anything. This reports whether the machinery underneath
both is alive — and it is the only one of the three that a cartoon character
stands in front of, which is exactly why it must never round an unmeasured
component up to healthy.

Read-only. Nothing here can restart, enqueue, prune or repair; remediation is
a separate surface with its own audit trail, and keeping the reading apart
from the acting is what lets this be polled freely.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Response, status
from sqlalchemy import select

from app.api.deps import DbSession
from app.hq_ops import invariants as invariant_guard
from app.hq_ops.probe import snapshot
from app.hq_ops.remediation import REMEDIATIONS, autonomy_enabled
from app.hq_ops.schemas import (
    HqOperations,
    Incident,
    IncidentAction,
    OperationsHealth,
    RemediationInfo,
)
from app.hq_ops.service import OPEN_STATUSES
from app.karthik_ops.service import KARTHIK_KINDS
from app.models.hq_ops import HqAction, HqIncident

router = APIRouter(prefix="/hq", tags=["hq"])


@router.get(
    "/operations",
    response_model=OperationsHealth,
    summary="Infrastructure health behind HQ's production watch",
)
async def operations(session: DbSession, response: Response) -> OperationsHealth:
    """Report disk, broker, database, worker, scheduler and queue state.

    Returns 503 only when a component was measured and found `down`, matching
    `/health/pipeline`'s contract so the same external monitor can read both
    without parsing a body. A roll-up of `unknown` returns 200: "nobody could
    look" is not an outage, and paging on it would train the reader to ignore
    the page that matters.
    """
    health = await snapshot(session)
    if health.overall == "down":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return health


#: How far back the room looks for work that has already closed. Long enough
#: that an incident resolved during a coffee break is still visible; short
#: enough that the panel is about now rather than about history.
RECENT_WINDOW = timedelta(hours=24)

#: Audit rows returned in one response. The trail is append-only and grows
#: forever; the panel shows the tail of it and says so.
ACTIVITY_LIMIT = 50


def _action(row: HqAction) -> IncidentAction:
    return IncidentAction(
        at=row.at,
        agent=row.agent,
        action=row.action,
        autonomy=row.autonomy,
        reason=row.reason,
        outcome=row.outcome,
        preconditions=row.preconditions or {},
        result=row.result or {},
        verification=row.verification or {},
    )


def _incident(row: HqIncident, actions: list[HqAction]) -> Incident:
    return Incident(
        code=row.code,
        kind=row.kind,
        component=row.component,
        severity=row.severity,
        status=row.status,
        autonomy=row.autonomy,
        agent=row.agent,
        signature=row.signature,
        symptoms=row.symptoms or {},
        root_cause=row.root_cause,
        owner_rationale=row.owner_rationale,
        detected_at=row.detected_at,
        resolved_at=row.resolved_at,
        actions=[_action(action) for action in actions],
    )


@router.get(
    "",
    response_model=HqOperations,
    summary="Everything HQ's operational layer knows",
)
async def operations_state(session: DbSession) -> HqOperations:
    """Health, open work, recent work, the audit trail and the allowlist.

    One response rather than five endpoints. The HQ brief is explicit that the
    frontend must not independently poll a dozen surfaces, and the deeper
    reason is consistency: five responses can disagree, and a room assembled
    from disagreeing readings is a room telling a story nobody can check.

    The allowlist is published rather than described. A reader who wants to
    know what HQ can do to production does not have to trust a sentence in a
    panel — they can read the four keys, and there is no fifth.
    """
    since = datetime.now(UTC) - RECENT_WINDOW

    health = await snapshot(session)

    # Karthik's findings live in the same two tables — they are the same
    # lifecycle, and a parallel pair would be duplicated schema with no added
    # truth — but they are not Sentinel's work and must not fill his panel.
    # The exclusion imports the *same* frozenset the Karthik surface filters
    # on, so inclusion there and exclusion here cannot drift apart.
    open_rows = (
        (
            await session.execute(
                select(HqIncident)
                .where(
                    HqIncident.status.in_(OPEN_STATUSES),
                    HqIncident.kind.notin_(KARTHIK_KINDS),
                )
                .order_by(HqIncident.detected_at.desc())
            )
        )
        .scalars()
        .all()
    )
    recent_rows = (
        (
            await session.execute(
                select(HqIncident)
                .where(
                    HqIncident.status.notin_(OPEN_STATUSES),
                    HqIncident.kind.notin_(KARTHIK_KINDS),
                    HqIncident.detected_at >= since,
                )
                .order_by(HqIncident.detected_at.desc())
                .limit(20)
            )
        )
        .scalars()
        .all()
    )
    activity_rows = (
        (
            await session.execute(
                select(HqAction)
                .where(HqAction.agent != "karthik")
                .order_by(HqAction.at.desc())
                .limit(ACTIVITY_LIMIT)
            )
        )
        .scalars()
        .all()
    )

    # One query for every incident's actions rather than one per incident.
    by_incident: dict[object, list[HqAction]] = {}
    ids = [row.id for row in [*open_rows, *recent_rows]]
    if ids:
        for action in (
            (
                await session.execute(
                    select(HqAction)
                    .where(HqAction.incident_id.in_(ids))
                    .order_by(HqAction.at.asc())
                )
            )
            .scalars()
            .all()
        ):
            by_incident.setdefault(action.incident_id, []).append(action)

    return HqOperations(
        health=health,
        incidents=[_incident(row, by_incident.get(row.id, [])) for row in open_rows],
        recent=[_incident(row, by_incident.get(row.id, [])) for row in recent_rows],
        activity=[_action(row) for row in activity_rows],
        allowlist=[
            RemediationInfo(
                key=action.key,
                autonomy=action.autonomy,
                agent=action.agent,
                summary=action.summary,
                reversible=action.reversible,
            )
            for action in sorted(REMEDIATIONS.values(), key=lambda a: a.key)
        ],
        autonomy_enabled=autonomy_enabled(),
        invariants=invariant_guard.capture(),
    )
