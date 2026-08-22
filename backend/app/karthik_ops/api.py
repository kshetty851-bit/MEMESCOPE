"""`GET /api/v1/karthik-ops` — everything Karthik's operational layer knows.

Its own namespace, and specifically **not** `/karthik`. That prefix belongs to
the wallet itself: `/karthik` publishes what the experiment did, and this
publishes whether it is being run properly. They are answers to different
questions and one of them must never be able to shadow the other on a route
table — the wallet's figures are the product, and an operator that could
intercept them would be an operator that could restate them.

It is also not a route under `/paper`. Filing a Karthik-wallet operator under
the Original Paper Wallet's prefix would invite exactly the confusion §7 exists
to prevent, and the isolation has to be visible in the URL for a reader to
trust it in the code.

── READ-ONLY, AND STRUCTURALLY SO ───────────────────────────────────────

There is no POST, PUT, PATCH or DELETE on this router. Karthik's authority to
act is `authority.SAFE_REPAIRS`, evaluated by a worker against a fresh reading;
it is deliberately not reachable from a page load. A monitoring surface that
can also repair is a monitoring surface an unauthenticated GET can weaponise.

── WHY `while_away` TAKES ITS START FROM THE CALLER ─────────────────────

§13 asks for "since your previous visit", and the server does not know when
that was — HQ has no per-user session record and inventing one for a cartoon
panel would be a tracking feature nobody asked for. The browser holds the
stamp in local storage and sends it. A caller that sends nothing gets "first
visit", which is the honest answer rather than a silent 24 hours.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Query

from app.api.deps import DbSession
from app.hq_ops.probe import snapshot
from app.karthik_ops import detect, monitor, reports, service
from app.karthik_ops.authority import SAFE_REPAIRS
from app.karthik_ops.schemas import (
    DefectCheck,
    ExperimentIntegrity,
    IntegrityDeduction,
    KarthikAction,
    KarthikIncident,
    KarthikReport,
    KarthikScreens,
    KarthikState,
    SafeRepairInfo,
    ScreenReading,
    WalletBinding,
    WhileAwaySummary,
)
from app.karthik_ops.wallet import Binding, resolve
from app.models.hq_ops import HqAction, HqIncident

router = APIRouter(prefix="/karthik-ops", tags=["karthik"])


def _screen(reading: monitor.Reading) -> ScreenReading:
    return ScreenReading(
        measured=reading.measured,
        detail=reading.detail,
        values=reading.values,
        rows=reading.rows,
    )


def _binding(binding: Binding) -> WalletBinding:
    return WalletBinding(
        state=binding.state,
        designated_strategy_id=binding.designated_strategy_id,
        detail=binding.detail,
        readable=binding.readable,
        needs_owner=binding.needs_owner,
        wallet_id=binding.wallet_id,
        strategy_version=binding.strategy_version,
        generation=binding.generation,
        starting_balance=(
            str(binding.starting_balance) if binding.starting_balance is not None else None
        ),
        started_at=binding.started_at,
        archived_at=binding.archived_at,
    )


def _action(row: HqAction) -> KarthikAction:
    return KarthikAction(
        at=row.at,
        agent=row.agent,
        action=row.action,
        autonomy=row.autonomy,
        # Lifted out of `result` rather than stored twice. The column holds the
        # action's class; this is what happened to one attempt at it, and the
        # panel needs both to say "allowlisted, but nothing is armed".
        verdict=str((row.result or {}).get("permission", "")) or None,
        reason=row.reason,
        outcome=row.outcome,
        preconditions=row.preconditions or {},
        result=row.result or {},
        verification=row.verification or {},
    )


def _incident(row: HqIncident, actions: list[HqAction]) -> KarthikIncident:
    return KarthikIncident(
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
    response_model=KarthikState,
    summary="The Karthik Paper Wallet's operational state, as its operator reads it",
)
async def karthik_state(
    session: DbSession,
    since: datetime | None = Query(
        default=None,
        description=(
            "ISO timestamp of the reader's previous visit, for the "
            "'what happened while you were away' summary. Omit on a first visit."
        ),
    ),
) -> KarthikState:
    """One reading of everything, or one honest account of why there is none.

    Returns 200 even when Karthik has no wallet. An unbound operator is not an
    error — it is the expected state of a deployment whose owner has not created
    the wallet yet — and returning 404 or 503 would make the room unreachable
    rather than empty, which is a worse answer to the same question.
    """
    now = datetime.now(UTC)
    binding = await resolve(session)

    wallet = await monitor.wallet_screen(session, binding)
    feed = await monitor.feed_screen(session, binding)
    positions = await monitor.positions_screen(session, binding)
    targets = await monitor.target_screen(session, binding)
    books = await monitor.accounting(session, binding)

    findings = await detect.run(session, binding)
    ledger = await service.ledger(session, now=now)

    # SCREEN 5 is the shared infrastructure probe plus Karthik's own loop. One
    # prober for the platform, per §26 — two would eventually disagree about
    # whether the worker is up, and a room showing both would be unreadable.
    infra = await snapshot(session)
    health = monitor.Reading(
        measured=True,
        detail=f"{infra.overall} overall; {infra.unmeasured} components unmeasured.",
        values={
            "overall": infra.overall,
            "unmeasured": infra.unmeasured,
            "database": infra.database.status,
            "redis": infra.redis.status,
            "worker": infra.worker.status,
            "scheduler": infra.scheduler.status,
            "disk": infra.disk.status,
            # Karthik's own loop has no heartbeat until a wallet gives it
            # something to do. Reported absent rather than as `down`, which
            # would be an outage the deployment does not have.
            "karthik_loop": "not running" if not binding.readable else "unknown",
            "karthik_loop_detail": (
                binding.detail
                if not binding.readable
                else "No heartbeat is published by the Karthik loop yet."
            ),
        },
    )

    integrity = service.evaluate_integrity(
        binding,
        findings=findings,
        positions=positions,
        books=books,
        open_rows=ledger.open_rows,
    )

    owner_count = len(ledger.owner_attention)
    repairs_done = len([row for row in ledger.actions if row.outcome == "succeeded"])

    built = {
        window: await reports.build(
            session,
            binding,
            window=window,
            now=now,
            integrity=integrity,
            bugs=len(findings),
            repairs=repairs_done,
            owner_attention=owner_count,
        )
        for window in ("daily", "weekly", "lifetime")
    }

    # SCREEN 6 renders the latest report's headline and the incident counts,
    # rather than re-deriving either. One derivation, two surfaces.
    daily = built["daily"]
    screen_reports = monitor.Reading(
        measured=daily.measured,
        detail=daily.detail,
        values={
            "latest_window": "daily",
            "bugs_detected": len(findings),
            "repairs_performed": repairs_done,
            "owner_attention": owner_count,
            "integrity_score": integrity.score,
            "integrity_band": integrity.band,
        },
        rows=[
            {
                "code": row.code,
                "severity": row.severity,
                "summary": row.symptoms.get("summary"),
            }
            for row in ledger.open_rows[:6]
        ],
    )

    away = await reports.while_away(
        session,
        binding,
        since=since,
        now=now,
        integrity=integrity,
        bugs=len(findings),
        repairs=repairs_done,
        owner_attention=owner_count,
    )

    return KarthikState(
        binding=_binding(binding),
        autonomy=service.autonomy_mode(),
        screens=KarthikScreens(
            wallet=_screen(wallet),
            feed=_screen(feed),
            positions=_screen(positions),
            targets=_screen(targets),
            health=_screen(health),
            reports=_screen(screen_reports),
        ),
        accounting=_screen(books),
        integrity=ExperimentIntegrity(
            score=integrity.score,
            band=integrity.band,
            headline=integrity.headline,
            deductions=[
                IntegrityDeduction(
                    factor=d.factor,
                    label=d.label,
                    penalty=d.penalty,
                    measured=d.measured,
                    detail=d.detail,
                )
                for d in integrity.deductions
            ],
            unmeasured=integrity.unmeasured,
        ),
        incidents=[
            _incident(row, ledger.actions_by_incident.get(row.id, []))
            for row in ledger.open_rows
        ],
        recent=[
            _incident(row, ledger.actions_by_incident.get(row.id, []))
            for row in ledger.recent_rows
        ],
        actions=[_action(row) for row in ledger.actions],
        allowlist=[
            SafeRepairInfo(
                key=repair.key,
                summary=repair.summary,
                precondition=repair.precondition,
                reversible=repair.reversible,
            )
            for repair in sorted(SAFE_REPAIRS.values(), key=lambda r: r.key)
        ],
        checks=[
            DefectCheck(
                key=defect.key,
                label=defect.label,
                rectification=defect.rectification,
                severity=defect.severity,
                detectable=defect.detectable,
                gap=defect.gap,
            )
            for defect in detect.DEFECTS
        ],
        reports={
            window: KarthikReport(**report.as_dict()) for window, report in built.items()
        },
        while_away=WhileAwaySummary(**away.as_dict()),
        observed_at=now,
    )
