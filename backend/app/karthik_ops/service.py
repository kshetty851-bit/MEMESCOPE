"""Karthik's incident lifecycle, action log and integrity evaluation.

── WHY THIS REUSES `hq_incidents` AND `hq_actions` ──────────────────────

Because they are already exactly the right tables. They carry a component, a
severity, a status, an autonomy class, an owning agent, a stable signature, the
observed symptoms, a root cause, an owner rationale, and an append-only action
row with preconditions, result and verification. That is Karthik's §9 and §10
in full, and a parallel pair of tables would be the same columns under
different names — duplicated schema with no added truth, plus a migration on a
deployment that already has four in flight.

Isolation is by *kind* rather than by table: every Karthik row carries a kind
from `KARTHIK_KINDS`, and both surfaces filter on it. The HQ operations panel
excludes them so Sentinel's room does not fill with wallet findings, and this
module reads nothing else. The two never mix, and neither can grow a foreign
key into a trading table because neither table has one.

── THE CODES ARE `INC-KAR-014`, AND THE SEQUENCE IS HIS OWN ─────────────

`_next_sequence` counts within a kind, so Karthik's numbering is independent of
Sentinel's and an operator can say "INC-KAR-14" out loud without ambiguity.

── EVERY ACTION IS WRITTEN BEFORE IT RUNS ───────────────────────────────

Copied deliberately from `hq_ops.service`. An action that crashes the process
must still leave a row saying it was attempted; a trail that records only
successes cannot explain an outage. §10 says never hide a failed repair, and
writing first is how that becomes structural rather than conscientious.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.karthik_ops.authority import AutonomyMode, Permission, autonomy, permit
from app.karthik_ops.detect import DEFECT_BY_KEY, Finding
from app.karthik_ops.integrity import Deduction, Integrity, score, unmeasured
from app.karthik_ops.monitor import Reading
from app.karthik_ops.wallet import Binding
from app.models.hq_ops import HqAction, HqIncident

logger = get_logger(__name__)

#: The kinds that belong to Karthik. Anything not in this set is Sentinel's.
#: Declared as a frozenset and imported by `hq_ops` so the exclusion on that
#: side cannot drift from the inclusion on this one.
KARTHIK_KINDS: frozenset[str] = frozenset(
    {"karthik_incident", "karthik_approval", "karthik_observation"}
)

CODE_PREFIX = {
    "karthik_incident": "INC-KAR",
    "karthik_approval": "REQ-KAR",
    "karthik_observation": "OBS-KAR",
}

#: Which kind a defect's classification opens. AUTO_FIX and the undetectable
#: OBSERVE_ONLY class are both *observations* until something acts on them;
#: OWNER_REQUIRED is the only one that goes straight to the owner queue.
KIND_FOR = {
    "AUTO_FIX": "karthik_incident",
    "OWNER_REQUIRED": "karthik_approval",
    "OBSERVE_ONLY": "karthik_observation",
}

#: Mirrors `hq_ops.service.OPEN_STATUSES`. A finding stays open until something
#: closes it; nothing here closes a row on a timer.
OPEN_STATUSES = ("open", "investigating", "repairing", "verifying", "awaiting_owner")

#: How far back the panel looks for closed work. Same window as `hq_ops`.
RECENT_WINDOW = timedelta(hours=24)
ACTIVITY_LIMIT = 50

#: Permission verdict → the autonomy class `hq_actions.autonomy` stores.
#: `allowed` is a green action that ran; `observe_only` is a green action the
#: deployment has not armed; `not_allowlisted` is red by definition — there is
#: no allowlist entry, so no autonomy level could reach it.
VERDICT_CLASS = {
    "allowed": "green",
    "observe_only": "yellow",
    "not_allowlisted": "red",
}

#: The agent credited on every row. Must match the HQ employee id, because the
#: room renders it: a name here that nobody recognises is a name the room made
#: up, which is the one thing this feature must never do.
AGENT = "karthik"


async def _next_sequence(session: AsyncSession, kind: str) -> int:
    result = await session.execute(
        select(func.coalesce(func.max(HqIncident.sequence), 0)).where(HqIncident.kind == kind)
    )
    return int(result.scalar_one()) + 1


async def open_finding(session: AsyncSession, finding: Finding) -> tuple[HqIncident, bool]:
    """Record a finding, or return the row already open for it.

    Returns `(row, created)`. The caller needs to know which, because a
    condition that persists across ticks should be *one* incident rather than
    one per tick — the signature is what makes that true, and it is the same
    idempotency discipline `hq_ops` relies on.
    """
    existing = (
        await session.execute(
            select(HqIncident)
            .where(
                HqIncident.signature == finding.signature,
                HqIncident.status.in_(OPEN_STATUSES),
            )
            .order_by(HqIncident.detected_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing, False

    kind = KIND_FOR[finding.rectification]
    sequence = await _next_sequence(session, kind)
    defect = DEFECT_BY_KEY[finding.defect]
    row = HqIncident(
        code=f"{CODE_PREFIX[kind]}-{sequence:03d}",
        sequence=sequence,
        kind=kind,
        # Namespaced so a Karthik row can never be confused for an
        # infrastructure row even if somebody queries the table by hand.
        component=f"karthik.{finding.defect}",
        severity=finding.severity,
        status="awaiting_owner" if finding.rectification == "OWNER_REQUIRED" else "open",
        # `red` is `hq_ops`'s word for "no autonomous action may touch this".
        # OWNER_REQUIRED maps onto it exactly, so the existing panel styling and
        # the existing refusal both apply without a second vocabulary.
        autonomy={"AUTO_FIX": "green", "OWNER_REQUIRED": "red", "OBSERVE_ONLY": "yellow"}[
            finding.rectification
        ],
        agent=AGENT,
        signature=finding.signature,
        symptoms={"summary": finding.summary, **finding.evidence},
        owner_rationale=(
            defect.gap
            if not defect.detectable
            else (
                "Affects the experiment's recorded result. §17 forbids rewriting "
                "historical P&L to repair an outcome, so this needs an owner decision."
            )
            if finding.rectification == "OWNER_REQUIRED"
            else None
        ),
    )
    session.add(row)
    await session.flush()
    logger.info(
        "karthik_finding_opened",
        code=row.code,
        component=row.component,
        severity=row.severity,
        rectification=finding.rectification,
    )
    return row, True


async def record_action(
    session: AsyncSession,
    *,
    incident: HqIncident | None,
    action_key: str,
    permission: Permission,
    reason: str,
    preconditions: dict[str, object] | None = None,
) -> HqAction:
    """Write the audit row for an attempted action.

    Written whatever the verdict, including — especially — when the verdict is
    a refusal. §10 says never hide a failed repair, and a refusal is the most
    informative row in an observe-only deployment: it is the evidence the owner
    reviews before deciding whether to arm anything.
    """
    row = HqAction(
        incident_id=incident.id if incident else None,
        agent=AGENT,
        action=action_key,
        # The *class*, not the verdict. `hq_actions.autonomy` is `String(8)` and
        # holds green/yellow/red — it answers "what kind of action is this",
        # which is a property of the action rather than of one attempt at it.
        # The verdict is per-attempt and belongs in `result`, where it already
        # is and where it has room to be a sentence.
        autonomy=VERDICT_CLASS[permission.verdict],
        reason=reason,
        outcome="attempted" if permission.allowed else "skipped",
        preconditions=preconditions or {},
        result={"permission": permission.verdict, "detail": permission.reason},
        verification={},
    )
    session.add(row)
    await session.flush()
    return row


async def consider(
    session: AsyncSession, finding: Finding, *, mode: AutonomyMode | None = None
) -> tuple[HqIncident, Permission]:
    """Open a finding and decide, on the record, whether Karthik may act.

    The single entry point from detection to the audit trail, so there is no
    second path where something could be repaired without a row. Under
    `OBSERVE_ONLY` — the production default — `permission.allowed` is always
    False and the row records that it was allowlisted but not armed.

    **This function never executes a repair.** Execution is a separate surface
    with its own preconditions and verification; keeping the decision apart
    from the doing is what lets an observe-only deployment exercise the whole
    decision path in production without a single side effect.
    """
    incident, _created = await open_finding(session, finding)
    defect = DEFECT_BY_KEY[finding.defect]
    if defect.repair is None:
        permission = Permission(
            allowed=False,
            verdict="not_allowlisted",
            reason=(
                f"{defect.key} is classified {defect.rectification}; no repair is "
                "allowlisted for it and none can be."
            ),
        )
        await record_action(
            session,
            incident=incident,
            action_key=f"karthik.no_repair_for.{defect.key}",
            permission=permission,
            reason=finding.summary,
            preconditions=dict(finding.evidence),
        )
        return incident, permission

    permission = permit(defect.repair, mode=mode)
    await record_action(
        session,
        incident=incident,
        action_key=defect.repair,
        permission=permission,
        reason=finding.summary,
        preconditions=dict(finding.evidence),
    )
    return incident, permission


@dataclass(frozen=True, slots=True)
class Ledger:
    """The rows behind §9's queue and §10's log, read once."""

    open_rows: list[HqIncident]
    recent_rows: list[HqIncident]
    actions: list[HqAction]
    actions_by_incident: dict[object, list[HqAction]]

    @property
    def owner_attention(self) -> list[HqIncident]:
        return [row for row in self.open_rows if row.kind == "karthik_approval"]


async def ledger(session: AsyncSession, *, now: datetime | None = None) -> Ledger:
    """Every Karthik row the panel needs, in four queries rather than N+1."""
    clock = now or datetime.now(UTC)
    since = clock - RECENT_WINDOW

    open_rows = list(
        (
            await session.execute(
                select(HqIncident)
                .where(
                    HqIncident.kind.in_(KARTHIK_KINDS),
                    HqIncident.status.in_(OPEN_STATUSES),
                )
                .order_by(HqIncident.detected_at.desc())
            )
        )
        .scalars()
        .all()
    )
    recent_rows = list(
        (
            await session.execute(
                select(HqIncident)
                .where(
                    HqIncident.kind.in_(KARTHIK_KINDS),
                    HqIncident.status.notin_(OPEN_STATUSES),
                    HqIncident.detected_at >= since,
                )
                .order_by(HqIncident.detected_at.desc())
                .limit(20)
            )
        )
        .scalars()
        .all()
    )
    actions = list(
        (
            await session.execute(
                select(HqAction)
                .where(HqAction.agent == AGENT)
                .order_by(HqAction.at.desc())
                .limit(ACTIVITY_LIMIT)
            )
        )
        .scalars()
        .all()
    )

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

    return Ledger(
        open_rows=open_rows,
        recent_rows=recent_rows,
        actions=actions,
        actions_by_incident=by_incident,
    )


def _count(value: object) -> int:
    """Read a counter out of a finding's `dict[str, object]` evidence.

    The evidence bag is deliberately untyped — a finding carries whatever is
    relevant to it — so the few numbers the score reads are narrowed here
    rather than assumed at each use. A value that is not a number counts as
    zero, which under-deducts: the safe direction for a data-quality penalty
    is never to invent one.
    """
    return int(value) if isinstance(value, (int, str)) else 0


def evaluate_integrity(
    binding: Binding,
    *,
    findings: list[Finding],
    positions: Reading,
    books: Reading,
    open_rows: list[HqIncident],
) -> Integrity:
    """Turn what was observed into §11's score.

    Each factor is deducted from a *named* observation, and a factor whose
    input was not measured is recorded unmeasured rather than clean. The
    arithmetic is deliberately dull: penalty proportional to the share of the
    book affected, capped at the factor's declared maximum. Anything cleverer
    would be a model, and a model is exactly what §11 forbids.
    """
    if not binding.readable:
        return unmeasured(binding.detail)

    by_defect: dict[str, list[Finding]] = {}
    for finding in findings:
        by_defect.setdefault(finding.defect, []).append(finding)

    total_positions = len(positions.rows) or 1

    def hit(defect: str) -> bool:
        return defect in by_defect

    deductions = [
        Deduction(
            factor="event_completeness",
            label="Track Record event completeness",
            # Proportional to the share of admissions that produced no decision
            # at all, capped at the factor's declared maximum. Dull on purpose:
            # anything cleverer would be a model, and §11 asks for documented
            # deductions rather than one.
            penalty=(
                min(
                    22,
                    round(
                        22
                        * _count(by_defect["missed_admission"][0].evidence.get("missed", 0))
                        / max(
                            1,
                            _count(
                                by_defect["missed_admission"][0].evidence.get("admissions", 1)
                            ),
                        )
                    ),
                )
                if hit("missed_admission")
                else 0
            ),
            measured=True,
            detail=(
                by_defect["missed_admission"][0].summary
                if hit("missed_admission")
                else "Every Track Record admission since activation has a decision recorded."
            ),
        ),
        Deduction(
            factor="duplicate_events",
            label="Duplicate-event rate",
            penalty=14 if hit("duplicate_position") else 0,
            measured=True,
            detail=(
                f"{len(by_defect.get('duplicate_position', []))} mints hold more than one "
                f"position."
                if hit("duplicate_position")
                else "One position per mint across the whole book."
            ),
        ),
        Deduction(
            factor="entry_latency",
            label="Entry-processing latency",
            # Two points per late decision, to the cap. A late entry does not
            # invalidate a trade — it changes the price the experiment got, and
            # that is a fact about the result's comparability, not a fault.
            penalty=min(12, 2 * len(by_defect.get("late_decision", []))),
            measured=True,
            detail=(
                f"{len(by_defect['late_decision'])} decisions recorded later than expected."
                if hit("late_decision")
                else "Every decision was recorded within the expected window of its admission."
            ),
        ),
        Deduction(
            factor="quote_freshness",
            label="Quote and monitoring freshness",
            # `positions` in the evidence is already a count. It was wrapped in
            # `len()` here, which raised on the first bound wallet the tests
            # exercised — the reason this class exists rather than trusting the
            # unbound path to cover the arithmetic.
            penalty=(
                min(
                    18,
                    round(
                        18
                        * _count(by_defect["stale_quote"][0].evidence.get("positions", 0))
                        / total_positions
                    ),
                )
                if hit("stale_quote")
                else 0
            )
            if positions.measured
            else 0,
            measured=positions.measured,
            detail=(
                positions.detail
                if not positions.measured
                else (
                    f"{by_defect['stale_quote'][0].evidence.get('positions', 0)} of "
                    f"{len(positions.rows)} open positions priced from a stale quote."
                )
                if hit("stale_quote")
                else f"All {len(positions.rows)} open positions have a fresh quote."
            ),
        ),
        Deduction(
            factor="accounting_consistency",
            label="Accounting consistency",
            penalty=20 if hit("accounting_mismatch") else 0,
            measured=books.measured,
            detail=(
                books.detail
                if not books.measured
                else by_defect["accounting_mismatch"][0].summary
                if hit("accounting_mismatch")
                else "cash + executable open value reconciles with equity."
            ),
        ),
        Deduction(
            factor="target_provenance",
            label="Target execution provenance",
            penalty=8 if hit("target_below_multiple") else 0,
            measured=True,
            detail=(
                by_defect["target_below_multiple"][0].summary
                if hit("target_below_multiple")
                else "Every target fill is at or above the published 1.25x."
            ),
        ),
        Deduction(
            factor="worker_uptime",
            label="Worker uptime and unresolved incidents",
            penalty=min(6, 2 * len([row for row in open_rows if row.severity == "critical"])),
            measured=True,
            detail=(
                f"{len(open_rows)} open findings, "
                f"{len([r for r in open_rows if r.severity == 'critical'])} of them critical."
            ),
        ),
    ]
    return score(deductions)


def autonomy_mode() -> AutonomyMode:
    """Published on every response, so the panel never guesses."""
    return autonomy()
