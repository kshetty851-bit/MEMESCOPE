"""What one desk actually did, over the last day.

── THE PROBLEM THIS HAD TO SOLVE FIRST ──────────────────────────────────

Every other surface in HQ reports a *latest reading*: what a component's state
is now, with a timestamp on the observation. "What did Byte do today" is a
different shape of question — it needs a log, and most desks do not have one.

The honest answer is therefore per-desk rather than uniform. Four characters
sit on top of a real, timestamped, append-only record:

    karthik   the Graduation Lab's paper book (re-tasked 2026-09-12)
    vault     real-wallet trades, and the WhatsApp alert sent for each
    patch     hq_actions, and the incidents he was assigned
    sentinel  hq_incidents he raised
    radar     radar_tokens, whose first_detected_at is an admission log

The rest do not. Nova is a roll-up of other people's readings; Byte watches a
disk gauge; Echo watches a queue depth. Those are *levels*, sampled — there is
no event stream behind them, and turning a gauge into a timeline would invent
a history from a scalar, which is precisely what `today.ts` refuses to do for
the same reason.

So a desk with no log returns `measured: false` and a sentence naming what
would have to exist for it to have one. That is a more useful answer than a
plausible-looking empty timeline, because it tells a reader whether the desk
was quiet or whether nobody was writing anything down.

── READ-ONLY, AND NO NEW TABLES ─────────────────────────────────────────

Every statement here is a SELECT over rows something else already writes. This
adds no schema, no migration and no writer, so it cannot alter the record it
reports on.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.hq_ops import HqAction, HqIncident
from app.models.radar import RadarToken

#: The window. A day, because that is the question people ask, and because
#: `hq_incidents` and `hq_actions` are both indexed on their time column.
WINDOW = timedelta(hours=24)

#: How many events one dossier carries. Karthik alone logged 566 actions in a
#: day; a timeline is a readable summary of a log, not the log.
TIMELINE_LIMIT = 40


@dataclass(frozen=True, slots=True)
class Count:
    """One figure, with the field it came from. Same discipline as every other
    number HQ publishes: a metric without a source is one a reader has to take
    on faith."""

    label: str
    value: int
    source: str


@dataclass(frozen=True, slots=True)
class Event:
    at: datetime
    label: str
    detail: str
    #: `action` | `incident` | `trade` | `admission`. Styles the row; never a
    #: verdict.
    kind: str


@dataclass(frozen=True, slots=True)
class Reading:
    """A figure whose value is not a count.

    `Count` holds an int because every desk that had a log until now counted
    things. An analyst's figures are money, percentages and durations, and
    rounding "$-424.22" into an integer to reuse the existing carrier would
    lose the part a reader came for.
    """

    label: str
    value: str
    source: str


@dataclass(frozen=True, slots=True)
class Finding:
    headline: str
    evidence: str
    lever: str
    source: str


@dataclass(frozen=True, slots=True)
class Suggestion:
    """Something that could be changed, with what the record says it does.

    `outcome` is what separates this from a wish. A suggestion on this
    platform arrives with its replayed number attached, and the ones the
    record argues AGAINST stay on the board saying so — a box that lists only
    good ideas is a box that has quietly done the deciding for the reader.
    """

    title: str
    detail: str
    outcome: str
    supported: bool
    source: str


@dataclass(slots=True)
class Dossier:
    employee: str
    since: datetime
    until: datetime
    measured: bool
    detail: str
    headline: str = ""
    sources: list[str] = field(default_factory=list)
    counts: list[Count] = field(default_factory=list)
    timeline: list[Event] = field(default_factory=list)
    #: Non-integer figures.
    readings: list[Reading] = field(default_factory=list)
    #: What this desk has to say about its own record. Every entry names a
    #: measurable quantity rather than an outcome.
    findings: list[Finding] = field(default_factory=list)
    #: The suggestion box. Rendered below the findings and deliberately
    #: separate from them: a finding is what the record says, a suggestion is
    #: what somebody might do about it, and blurring the two is how a
    #: measurement turns into advice nobody checked.
    suggestions: list[Suggestion] = field(default_factory=list)


def _unlogged(employee: str, why: str, since: datetime, until: datetime) -> Dossier:
    return Dossier(
        employee=employee,
        since=since,
        until=until,
        measured=False,
        detail=why,
    )


#: Why each logless desk has no log. Written per desk rather than as one
#: generic sentence, because "there is no event stream for this" and "this desk
#: reads a gauge" are different facts and a reader can act on the second.
NO_LOG: dict[str, str] = {
    "nova": (
        "Nova reports a roll-up of the other desks' readings. A roll-up has no "
        "events of its own — every fact in it belongs to somebody else's desk, "
        "and that is where its history lives."
    ),
    "atlas": (
        "The security gate publishes a summary — how many tokens were evaluated "
        "recently, how many are unknown — not a row per evaluation. There is no "
        "table of decisions to read back."
    ),
    "milo": (
        "Portfolio figures are derived from open positions at read time. The "
        "positions have their own timestamps, but they belong to the wallet that "
        "opened them rather than to this desk."
    ),
    "echo": (
        "Queue depth is a gauge, sampled. Nothing records how many messages "
        "passed through it, only how many are waiting right now."
    ),
    "byte": (
        "Disk, broker and database are gauges read on each probe. HQ keeps the "
        "latest reading and no history, so there is nothing to replay."
    ),
    "quinn": (
        "Verification runs inside a repair, and the repair is credited to the "
        "agent that performed it. Quinn's checks appear on those rows rather "
        "than as separate entries of her own."
    ),
}


async def build(
    session: AsyncSession, employee: str, *, now: datetime | None = None
) -> Dossier:
    """One desk's last 24 hours, from whatever real log that desk has."""
    until = now or datetime.now(UTC)
    since = until - WINDOW

    if employee in NO_LOG:
        return _unlogged(employee, NO_LOG[employee], since, until)

    # Karthik was re-tasked to the Graduation Lab on 2026-09-12. His ops watch
    # still runs — that is `hq_ops`, a different system — but the question this
    # desk answers is now "what did the graduation book do, and what would
    # change it", which is the most active book on the platform.
    if employee == "karthik":
        return await _from_graduation(session, employee, since, until)
    if employee == "patch":
        return await _from_actions(session, employee, since, until)
    # Vault looks after the real wallet: its trades, and the WhatsApp message
    # sent to Karthik for each one. Added 2026-09-17.
    if employee == "vault":
        return await _from_real_wallet(session, employee, since, until)
    if employee == "sentinel":
        return await _from_incidents(session, employee, since, until)
    if employee == "radar":
        return await _from_admissions(session, employee, since, until)

    return _unlogged(
        employee,
        f"{employee!r} is not a desk this office keeps a log for.",
        since,
        until,
    )


async def _from_actions(
    session: AsyncSession, employee: str, since: datetime, until: datetime
) -> Dossier:
    """Desks that act: every attempt is a row, whatever the outcome.

    The outcome breakdown is the point. A day of `skipped` is an observe-only
    deployment working exactly as intended; a day of `failed` is something a
    person needs to look at, and the two are indistinguishable from a count of
    actions alone.
    """
    rows = (
        (
            await session.execute(
                select(HqAction)
                .where(HqAction.agent == employee, HqAction.at >= since, HqAction.at <= until)
                .order_by(HqAction.at.desc())
            )
        )
        .scalars()
        .all()
    )

    by_outcome: dict[str, int] = {}
    by_action: dict[str, int] = {}
    for row in rows:
        by_outcome[row.outcome] = by_outcome.get(row.outcome, 0) + 1
        by_action[row.action] = by_action.get(row.action, 0) + 1

    incidents = (
        (
            await session.execute(
                select(HqIncident)
                .where(
                    HqIncident.agent == employee,
                    HqIncident.detected_at >= since,
                    HqIncident.detected_at <= until,
                )
                .order_by(HqIncident.detected_at.desc())
            )
        )
        .scalars()
        .all()
    )

    counts = [
        Count("Actions attempted", len(rows), "hq_actions"),
        *[
            Count(f"  {outcome}", n, "hq_actions.outcome")
            for outcome, n in sorted(by_outcome.items(), key=lambda kv: -kv[1])
        ],
        Count("Distinct actions", len(by_action), "hq_actions.action"),
        Count("Findings raised", len(incidents), "hq_incidents"),
    ]

    timeline = [
        Event(
            at=row.at,
            label=row.action,
            detail=f"{row.outcome} — {row.reason}"[:200],
            kind="action",
        )
        for row in rows[:TIMELINE_LIMIT]
    ]

    if not rows and not incidents:
        headline = "Nothing recorded in the last 24 hours."
    else:
        top = max(by_action.items(), key=lambda kv: kv[1])[0] if by_action else "—"
        executed = by_outcome.get("succeeded", 0)
        headline = (
            f"{len(rows)} actions, {executed} executed, most often {top}."
            if rows
            else f"{len(incidents)} findings raised, no actions attempted."
        )

    return Dossier(
        employee=employee,
        since=since,
        until=until,
        measured=True,
        detail=(
            "Every attempted action is written before it runs and never updated, "
            "so this is the whole record for the window — successes, refusals and "
            "failures alike."
        ),
        headline=headline,
        sources=["hq_actions", "hq_incidents"],
        counts=counts,
        timeline=timeline,
    )


async def _from_incidents(
    session: AsyncSession, employee: str, since: datetime, until: datetime
) -> Dossier:
    rows = (
        (
            await session.execute(
                select(HqIncident)
                .where(
                    HqIncident.agent == employee,
                    HqIncident.detected_at >= since,
                    HqIncident.detected_at <= until,
                )
                .order_by(HqIncident.detected_at.desc())
            )
        )
        .scalars()
        .all()
    )
    resolved = [row for row in rows if row.resolved_at is not None]
    critical = [row for row in rows if row.severity == "critical"]
    by_component: dict[str, int] = {}
    for row in rows:
        by_component[row.component] = by_component.get(row.component, 0) + 1

    return Dossier(
        employee=employee,
        since=since,
        until=until,
        measured=True,
        detail=(
            "Each row is a condition this desk detected, with the evidence it "
            "was detected on. A condition that persists reopens nothing — it "
            "stays one finding."
        ),
        headline=(
            f"{len(rows)} findings, {len(resolved)} since resolved."
            if rows
            else "Nothing raised in the last 24 hours."
        ),
        sources=["hq_incidents"],
        counts=[
            Count("Findings raised", len(rows), "hq_incidents"),
            Count("Resolved", len(resolved), "hq_incidents.resolved_at"),
            Count("Critical", len(critical), "hq_incidents.severity"),
            *[
                Count(f"  {component}", n, "hq_incidents.component")
                for component, n in sorted(by_component.items(), key=lambda kv: -kv[1])[:6]
            ],
        ],
        timeline=[
            Event(
                at=row.detected_at,
                label=f"{row.code} · {row.component}",
                detail=str((row.symptoms or {}).get("summary") or row.status)[:200],
                kind="incident",
            )
            for row in rows[:TIMELINE_LIMIT]
        ],
    )


async def _from_admissions(
    session: AsyncSession, employee: str, since: datetime, until: datetime
) -> Dossier:
    """Discovery's log is the Track Record itself.

    `first_detected_at` is written once, on the insert that admits a token, and
    never updated — which is what makes it an event rather than a gauge. The
    timeline is capped hard: 558 admissions in a day is a feed, not a story.
    """
    total = (
        await session.execute(
            select(func.count())
            .select_from(RadarToken)
            .where(
                RadarToken.first_detected_at >= since, RadarToken.first_detected_at <= until
            )
        )
    ).scalar_one()

    rows = (
        (
            await session.execute(
                select(RadarToken)
                .where(
                    RadarToken.first_detected_at >= since,
                    RadarToken.first_detected_at <= until,
                )
                .order_by(RadarToken.first_detected_at.desc())
                .limit(TIMELINE_LIMIT)
            )
        )
        .scalars()
        .all()
    )

    hours = max(1.0, (until - since).total_seconds() / 3600)
    return Dossier(
        employee=employee,
        since=since,
        until=until,
        measured=True,
        detail=(
            "Each row is a token entering the Track Record. The admission time "
            "is written once and never updated, so this is an event log rather "
            "than a running total."
        ),
        headline=(
            f"{total} admissions, about {total / hours:.0f} an hour."
            if total
            else "No admissions in the last 24 hours."
        ),
        sources=["radar_tokens"],
        counts=[
            Count("Tokens admitted", int(total), "radar_tokens.first_detected_at"),
            Count("Shown below", len(rows), "radar_tokens"),
        ],
        timeline=[
            Event(
                at=row.first_detected_at,
                label=row.mint_address,
                detail=f"category {row.category}",
                kind="admission",
            )
            for row in rows
        ],
    )


async def _from_graduation(
    session: AsyncSession, employee: str, since: datetime, until: datetime
) -> Dossier:
    """Karthik's day: the graduation book's closed trades, and what moves them.

    The timeline is literally what was asked for — the trades this book opened
    and closed — and the findings and suggestions come from
    `labs.graduation.analyst` unchanged. This function computes no conclusion
    of its own: two places deciding what the book means is two places that can
    disagree, and the analyst module is the one with the tests.
    """
    from app.labs.graduation import analyst as grad
    from app.labs.graduation.models import GradPaperPosition

    analysis = await grad.analyse(session, now=until)
    if not analysis.measured:
        return _unlogged(employee, analysis.detail, since, until)

    rows = (
        (
            await session.execute(
                select(GradPaperPosition)
                .where(
                    (GradPaperPosition.opened_at >= since)
                    | (GradPaperPosition.closed_at >= since)
                )
                .order_by(GradPaperPosition.opened_at.desc())
                .limit(TIMELINE_LIMIT)
            )
        )
        .scalars()
        .all()
    )

    timeline: list[Event] = []
    opened = closed = 0
    for row in rows:
        name = row.symbol or row.mint[:8]
        if row.closed_at is not None and row.closed_at >= since:
            closed += 1
            peak = (
                f", peaked {row.peak_quote / row.open_fill:.3f}x"
                if row.open_fill and row.peak_quote is not None
                else ""
            )
            timeline.append(
                Event(
                    at=row.closed_at,
                    label=f"closed {name}",
                    detail=(
                        f"{row.close_reason or 'unrecorded'}, "
                        f"{row.pnl_usd:+,.2f} USD{peak}"
                        if row.pnl_usd is not None
                        else f"{row.close_reason or 'unrecorded'}{peak}"
                    ),
                    kind="trade",
                )
            )
        if row.opened_at >= since:
            opened += 1
            timeline.append(
                Event(
                    at=row.opened_at,
                    label=f"opened {name}",
                    detail=(
                        f"${row.notional_usd:,.2f}"
                        if row.notional_usd is not None
                        else "opened"
                    ),
                    kind="trade",
                )
            )
    timeline.sort(key=lambda e: e.at, reverse=True)

    return Dossier(
        employee=employee,
        since=since,
        until=until,
        measured=True,
        headline=analysis.verdict,
        detail=(
            "Graduation Lab forward paper book. Figures are over the whole book; "
            "the timeline is the last 24 hours."
        ),
        sources=["grad_paper_positions"],
        counts=[
            Count("Opened in window", opened, "grad_paper_positions.opened_at"),
            Count("Closed in window", closed, "grad_paper_positions.closed_at"),
            Count("Open now", analysis.open_positions, "grad_paper_positions.closed_at is null"),
        ],
        timeline=timeline[:TIMELINE_LIMIT],
        readings=[Reading(f.label, f.value, f.source) for f in analysis.figures],
        findings=[
            Finding(f.headline, f.evidence, f.lever, f.source) for f in analysis.findings
        ],
        suggestions=[
            Suggestion(x.title, x.detail, x.outcome, x.supported, x.source)
            for x in analysis.suggestions
        ],
    )


async def _from_real_wallet(
    session: AsyncSession, employee: str, since: datetime, until: datetime
) -> Dossier:
    """Vault's day: every real trade that opened or closed, and its WhatsApp.

    Read-only, like every desk here. Whether a message went out is read off the
    alert log `app.real_wallet.trade_alerts` keeps; this function decides
    nothing about it. The phone number is never shown — only whether alerts
    are configured.
    """
    from app.models.real_wallet_execution import RealWalletPosition, RealWalletTradeAlert
    from app.models.token import DiscoveredToken
    from app.real_wallet import trade_alerts

    rows = (
        await session.execute(
            select(RealWalletPosition, DiscoveredToken.symbol)
            .outerjoin(DiscoveredToken, DiscoveredToken.mint_address == RealWalletPosition.mint_address)
            .where(
                (RealWalletPosition.opened_at >= since)
                | (RealWalletPosition.closed_at >= since)
            )
            .order_by(RealWalletPosition.opened_at.desc())
            .limit(TIMELINE_LIMIT)
        )
    ).all()
    alerts = {
        (a.position_id, a.event): a
        for a in (
            await session.execute(
                select(RealWalletTradeAlert).where(
                    RealWalletTradeAlert.position_id.in_([p.id for p, _ in rows])
                )
            )
        ).scalars()
    } if rows else {}

    def whatsapp(position_id, event: str) -> str:
        alert = alerts.get((position_id, event))
        if alert is None:
            return "WhatsApp: not yet" if trade_alerts.enabled() else "WhatsApp: off"
        return {
            "sent": "WhatsApp sent",
            "pending": f"WhatsApp waiting (try {alert.attempts + 1})",
            "failed": "WhatsApp FAILED — " + (alert.last_error or "no reason recorded"),
            "baseline": "before alerts were on",
        }.get(alert.status, alert.status)

    timeline: list[Event] = []
    opened = closed = 0
    for position, symbol in rows:
        name = symbol or position.mint_address[:8]
        if position.opened_at >= since:
            opened += 1
            cost = position.quantity * position.entry_price_usd
            timeline.append(Event(
                at=position.opened_at,
                label=f"bought {name}",
                detail=f"${cost:,.2f} · {whatsapp(position.id, 'opened')}",
                kind="trade",
            ))
        if position.closed_at is not None and position.closed_at >= since:
            closed += 1
            pnl = position.realised_net_pnl_usd
            basis = "net"
            if pnl is None:
                pnl, basis = position.realised_gross_pnl_usd, "gross"
            result = f"{pnl:+,.2f} USD {basis}" if pnl is not None else "result not recorded"
            timeline.append(Event(
                at=position.closed_at,
                label=f"sold {name}",
                detail=f"{result} · {whatsapp(position.id, 'closed')}",
                kind="trade",
            ))
    timeline.sort(key=lambda e: e.at, reverse=True)

    sent = (await session.execute(
        select(func.count()).select_from(RealWalletTradeAlert).where(
            RealWalletTradeAlert.status == "sent", RealWalletTradeAlert.sent_at >= since,
        )
    )).scalar_one()
    failed = (await session.execute(
        select(func.count()).select_from(RealWalletTradeAlert).where(
            RealWalletTradeAlert.status == "failed", RealWalletTradeAlert.created_at >= since,
        )
    )).scalar_one()

    on = trade_alerts.enabled()
    headline = (
        f"{opened} real trade{'s' if opened != 1 else ''} opened, {closed} closed, "
        f"{sent} WhatsApp alert{'s' if sent != 1 else ''} sent."
        if on
        else f"{opened} real trade{'s' if opened != 1 else ''} opened, {closed} closed. "
        "WhatsApp alerts are OFF until the server has a phone number and a CallMeBot key."
    )
    return Dossier(
        employee=employee,
        since=since,
        until=until,
        measured=True,
        headline=headline,
        detail=(
            "The real wallet's own position ledger, and the alert log beside it. "
            "Vault reads both and changes neither — starting and stopping the "
            "wallet is Karthik's alone."
        ),
        sources=["real_wallet_positions", "real_wallet_trade_alerts"],
        counts=[
            Count("Real trades opened", opened, "real_wallet_positions.opened_at"),
            Count("Real trades closed", closed, "real_wallet_positions.closed_at"),
            Count("WhatsApp alerts sent", sent, "real_wallet_trade_alerts.sent_at"),
            Count("WhatsApp alerts failed", failed, "real_wallet_trade_alerts.status"),
        ],
        timeline=timeline[:TIMELINE_LIMIT],
        readings=[
            Reading(
                "WhatsApp alerts",
                "on" if on else "off — not configured",
                "WHATSAPP_PHONE + WHATSAPP_CALLMEBOT_KEY",
            )
        ],
    )


def as_dict(dossier: Dossier) -> dict[str, Any]:
    return {
        "employee": dossier.employee,
        "since": dossier.since,
        "until": dossier.until,
        "measured": dossier.measured,
        "detail": dossier.detail,
        "headline": dossier.headline,
        "sources": dossier.sources,
        "counts": [
            {"label": c.label, "value": c.value, "source": c.source} for c in dossier.counts
        ],
        "timeline": [
            {"at": e.at, "label": e.label, "detail": e.detail, "kind": e.kind}
            for e in dossier.timeline
        ],
        "readings": [
            {"label": r.label, "value": r.value, "source": r.source} for r in dossier.readings
        ],
        "findings": [
            {
                "headline": f.headline,
                "evidence": f.evidence,
                "lever": f.lever,
                "source": f.source,
            }
            for f in dossier.findings
        ],
        "suggestions": [
            {
                "title": s.title,
                "detail": s.detail,
                "outcome": s.outcome,
                "supported": s.supported,
                "source": s.source,
            }
            for s in dossier.suggestions
        ],
    }
