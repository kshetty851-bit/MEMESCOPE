"""§16's bug list, and §17's rule for what may be done about each one.

── THE CATALOGUE IS DATA, THE DETECTOR IS CODE ──────────────────────────

`DEFECTS` names every condition Karthik looks for and, for each, the
classification that decides his authority over it. Keeping the classification
*beside the definition* rather than in the handler is the point: a reader can
see in one screen that "cash mismatch" is OWNER_REQUIRED and that no code path
exists which could quietly reclassify it, because the classification is not
computed anywhere.

── WHY MOST OF THIS LIST IS OWNER_REQUIRED ──────────────────────────────

Nearly every defect worth detecting is a defect *in the record*: a duplicate
trade, a mismatched cash figure, a target that fired at the wrong price. None
of those can be repaired without deciding what the record should have said, and
that is a judgement about the experiment's result. §17 is explicit — never
rewrite historical P&L to "repair" a result — so the honest outcome for these
is a structured incident, not a fix.

The three AUTO_FIX entries are the ones where the *record is fine* and only a
derived artefact is wrong: a stale quote, a stopped loop, a stale read model.
Those are the entire overlap between "Karthik can tell what happened" and
"acting cannot change what the experiment measured".

── DETECTION NEVER ASSERTS WHAT IT CANNOT SEE ───────────────────────────

Several checks need a decision record the wallet does not have — whether an
admission was *skipped by a rule* or *missed by a gap* is not derivable from a
position table. Those are declared here with `detectable=False` and reported as
not-yet-checkable rather than silently passing. §16's closing line is the whole
reason: do not create false certainty when evidence is missing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.karthik_ops import tables
from app.karthik_ops.monitor import (
    DECISION_EXPECTED_WITHIN,
    QUOTE_STALE_AFTER,
    accounting,
    positions_screen,
)
from app.karthik_ops.wallet import Binding
from app.models.radar import RadarToken

#: §17's three classes. `OBSERVE_ONLY` here is a property of a *defect* — a
#: pattern that needs more evidence before anyone acts — and is not the same
#: thing as the `OBSERVE_ONLY` autonomy mode in `authority.py`, which is a
#: property of the deployment. Both names come from the brief.
Rectification = Literal["AUTO_FIX", "OWNER_REQUIRED", "OBSERVE_ONLY"]

Severity = Literal["info", "degraded", "critical"]


@dataclass(frozen=True, slots=True)
class Defect:
    """One thing that can be wrong, and what Karthik is allowed to do about it."""

    key: str
    label: str
    rectification: Rectification
    severity: Severity
    #: The allowlist key that would repair it. Only ever set on AUTO_FIX rows,
    #: asserted below — an OWNER_REQUIRED defect that named a repair would be
    #: one refactor away from being repaired.
    repair: str | None = None
    #: False when the evidence to check this does not exist yet. Reported, not
    #: hidden: an unchecked condition is a gap in the audit, and a reader is
    #: entitled to know which ones they are.
    detectable: bool = True
    #: Why it cannot be checked. Required when `detectable` is False.
    gap: str | None = None


DEFECTS: tuple[Defect, ...] = (
    Defect(
        key="duplicate_position",
        label="Two positions for one mint",
        rectification="OWNER_REQUIRED",
        severity="critical",
    ),
    Defect(
        key="entry_size_wrong",
        label="Entry amount is not $10",
        rectification="OWNER_REQUIRED",
        severity="critical",
    ),
    Defect(
        key="pre_activation_entry",
        label="A position opened before the wallet started",
        rectification="OWNER_REQUIRED",
        severity="critical",
    ),
    Defect(
        key="negative_proceeds",
        label="A closed trade with impossible proceeds",
        rectification="OWNER_REQUIRED",
        severity="critical",
    ),
    Defect(
        key="forbidden_exit",
        label="A position closed by a stop or a time rule the wallet does not have",
        rectification="OWNER_REQUIRED",
        severity="critical",
    ),
    Defect(
        key="target_below_multiple",
        label="A target fill below the published 1.25x",
        rectification="OWNER_REQUIRED",
        severity="critical",
    ),
    Defect(
        key="accounting_mismatch",
        label="Cash plus open value does not reconcile with equity",
        rectification="OWNER_REQUIRED",
        severity="critical",
    ),
    Defect(
        key="missing_detection_time",
        label="A position with no recorded detection time",
        rectification="OWNER_REQUIRED",
        severity="degraded",
    ),
    Defect(
        key="stale_quote",
        label="An open position valued from a stale price",
        rectification="AUTO_FIX",
        severity="degraded",
        repair="karthik.position_subscriptions_reprime",
    ),
    Defect(
        key="monitor_loop_stopped",
        label="Karthik's monitoring loop is not reporting",
        rectification="AUTO_FIX",
        severity="degraded",
        repair="karthik.monitor_loop_restart",
    ),
    Defect(
        key="read_model_stale",
        label="The panel's derived read model is behind its own source rows",
        rectification="AUTO_FIX",
        severity="info",
        repair="karthik.read_model_refresh",
    ),
    Defect(
        key="missed_admission",
        label="An eligible Track Record admission with no decision recorded",
        rectification="OWNER_REQUIRED",
        severity="degraded",
    ),
    Defect(
        key="unknown_decision",
        label="A decision the operator does not recognise",
        rectification="OWNER_REQUIRED",
        severity="degraded",
    ),
    Defect(
        key="late_decision",
        label="A decision recorded long after the admission that prompted it",
        rectification="OBSERVE_ONLY",
        severity="info",
    ),
    Defect(
        key="target_missed",
        label="A target not taken despite a valid executable price",
        rectification="OBSERVE_ONLY",
        severity="degraded",
        detectable=False,
        gap=(
            "Needs the executable price series the wallet's own execution model saw. "
            "Re-deriving it from stored snapshots would be a second execution model "
            "disagreeing with the first."
        ),
    ),
    Defect(
        key="dead_zero_fantasy_profit",
        label="A dead token booked at a profit",
        rectification="OBSERVE_ONLY",
        severity="critical",
        detectable=False,
        gap=(
            "Requires a liquidity reading at exit to say a price was unexecutable. "
            "Calling a booked exit fantasy without that would be an accusation, not "
            "a finding."
        ),
    ),
)

DEFECT_BY_KEY = {defect.key: defect for defect in DEFECTS}

# Asserted at import, because the failure it prevents is silent. An
# OWNER_REQUIRED defect carrying a repair key is one careless handler away
# from being auto-repaired, and the repair would look authorised.
for _defect in DEFECTS:
    if _defect.repair is not None and _defect.rectification != "AUTO_FIX":  # pragma: no cover
        raise ValueError(f"{_defect.key} is {_defect.rectification} but names a repair")
    if _defect.rectification == "AUTO_FIX" and _defect.repair is None:  # pragma: no cover
        raise ValueError(f"{_defect.key} is AUTO_FIX but names no repair")
    if not _defect.detectable and _defect.gap is None:  # pragma: no cover
        raise ValueError(f"{_defect.key} is undetectable but does not say why")


@dataclass(frozen=True, slots=True)
class Finding:
    """One detected instance of a defect, with the evidence behind it."""

    defect: str
    label: str
    rectification: Rectification
    severity: Severity
    #: Stable identity, so a condition that persists reopens nothing. Mirrors
    #: `hq_ops`'s signature discipline.
    signature: str
    summary: str
    evidence: dict[str, object] = field(default_factory=dict)


#: Fallback entry size, used only if the wallet row does not publish one.
#: The declared size is read from the wallet itself — Karthik checks fills
#: against the rule the wallet published, never against a constant of his own,
#: because a constant here could disagree with the rule that produced the trade.
DEFAULT_ENTRY_USD = Decimal(10)
#: How far cash + open value may drift from equity before it is a mismatch
#: rather than rounding. Money is stored to four places; a cent of slack across
#: a whole book is generous and still catches a real accounting fault.
ACCOUNTING_TOLERANCE = Decimal("0.01")


def _count(value: object) -> int:
    """Read a count out of a `dict[str, object]` reading. A non-number reads as
    zero, which under-reports rather than raising inside a monitoring read."""
    return int(value) if isinstance(value, (int, str)) else 0


async def run(session: AsyncSession, binding: Binding) -> list[Finding]:
    """Every check Karthik can actually make, right now.

    Returns an empty list when there is nothing to check — not a clean bill of
    health. The caller distinguishes the two by asking the binding, which is
    why this does not return a verdict of its own.
    """
    if not binding.readable:
        return []

    findings: list[Finding] = []
    positions = tables.karthik_positions
    opportunities = tables.karthik_opportunities

    rows = (
        await session.execute(
            select(
                positions.c.id,
                positions.c.mint_address,
                positions.c.opened_at,
                positions.c.detected_at,
                positions.c.entry_price,
                positions.c.cost_basis,
                positions.c.exit_price,
                positions.c.exit_proceeds_usd,
                positions.c.exit_reason,
            ).where(positions.c.wallet_id == binding.wallet_id)
        )
    ).all()

    def add(defect: str, signature: str, summary: str, **evidence: object) -> None:
        spec = DEFECT_BY_KEY[defect]
        findings.append(
            Finding(
                defect=defect,
                label=spec.label,
                rectification=spec.rectification,
                severity=spec.severity,
                signature=signature,
                summary=summary,
                evidence=evidence,
            )
        )

    # --- duplicates -----------------------------------------------------
    for mint, count in (
        await session.execute(
            select(positions.c.mint_address, func.count())
            .where(positions.c.wallet_id == binding.wallet_id)
            .group_by(positions.c.mint_address)
            .having(func.count() > 1)
        )
    ).all():
        add(
            "duplicate_position",
            f"karthik.duplicate_position:{mint}",
            f"{count} positions exist for {mint}; the wallet's rule is one per token.",
            mint=mint,
            positions=count,
        )

    # --- sizing, timing and impossible arithmetic ------------------------
    declared = binding.trade_size or DEFAULT_ENTRY_USD
    target_multiple = binding.take_profit_multiple or Decimal("1.25")
    started = binding.started_at
    for row in rows:
        if row.cost_basis != declared:
            add(
                "entry_size_wrong",
                f"karthik.entry_size_wrong:{row.id}",
                f"{row.mint_address} was entered at ${row.cost_basis}, not the published "
                f"${declared}.",
                mint=row.mint_address,
                cost_basis=str(row.cost_basis),
                declared=str(declared),
            )
        if started and row.opened_at < started:
            add(
                "pre_activation_entry",
                f"karthik.pre_activation_entry:{row.id}",
                (
                    f"{row.mint_address} opened at {row.opened_at.isoformat()}, before the "
                    f"wallet was activated at {started.isoformat()}. A forward-only "
                    "experiment cannot contain a backdated trade."
                ),
                mint=row.mint_address,
                opened_at=row.opened_at.isoformat(),
            )
        if row.detected_at is None:
            add(
                "missing_detection_time",
                f"karthik.missing_detection_time:{row.id}",
                f"{row.mint_address} has no recorded detection time, so its entry delay is "
                f"unknowable.",
                mint=row.mint_address,
            )
        if row.exit_proceeds_usd is not None and row.exit_proceeds_usd < 0:
            add(
                "negative_proceeds",
                f"karthik.negative_proceeds:{row.id}",
                f"{row.mint_address} closed with negative proceeds, which is not a possible "
                f"sale.",
                mint=row.mint_address,
                proceeds=str(row.exit_proceeds_usd),
            )
        if row.exit_reason is not None and row.exit_reason not in tables.KNOWN_EXIT_REASONS:
            add(
                "forbidden_exit",
                f"karthik.forbidden_exit:{row.id}",
                (
                    f"{row.mint_address} closed with reason {row.exit_reason!r}. The wallet "
                    "has a target and no stop; nothing else should be able to close it."
                ),
                mint=row.mint_address,
                exit_reason=row.exit_reason,
            )
        if (
            row.exit_reason == "target_1_25x"
            and row.exit_price is not None
            and row.entry_price
            and row.exit_price / row.entry_price < target_multiple
        ):
            add(
                "target_below_multiple",
                f"karthik.target_below_multiple:{row.id}",
                (
                    f"{row.mint_address} booked a target fill at "
                    f"{row.exit_price / row.entry_price}x, below the published "
                    f"{target_multiple}x."
                ),
                mint=row.mint_address,
                multiple=str(row.exit_price / row.entry_price),
            )

    # --- the decision record --------------------------------------------
    #
    # The wallet writes one row per admission it saw, which is what makes a
    # *miss* measurable rather than inferred. An admission after activation with
    # no decision row is a gap in the experiment's coverage; a decision the
    # operator does not recognise means the wallet grew a rule this layer has
    # not been told about, which is worth an owner's attention either way.
    if started is not None:
        seen = {
            mint
            for (mint,) in await session.execute(
                select(opportunities.c.mint_address).where(
                    opportunities.c.wallet_id == binding.wallet_id
                )
            )
        }
        admissions = (
            await session.execute(
                select(RadarToken.mint_address, RadarToken.first_detected_at).where(
                    RadarToken.first_detected_at >= started
                )
            )
        ).all()
        missed = [mint for mint, _ in admissions if mint not in seen]
        if missed:
            add(
                "missed_admission",
                "karthik.missed_admission",
                (
                    f"{len(missed)} Track Record admissions since activation have no "
                    "decision recorded against them."
                ),
                missed=len(missed),
                admissions=len(admissions),
                mints=missed[:10],
            )

        for mint, decision, track_at, decided_at in (
            await session.execute(
                select(
                    opportunities.c.mint_address,
                    opportunities.c.decision,
                    opportunities.c.track_record_at,
                    opportunities.c.decided_at,
                ).where(opportunities.c.wallet_id == binding.wallet_id)
            )
        ).all():
            if decision not in tables.KNOWN_DECISIONS:
                add(
                    "unknown_decision",
                    f"karthik.unknown_decision:{decision}",
                    f"{mint} carries decision {decision!r}, which this operator does not "
                    f"recognise.",
                    mint=mint,
                    decision=decision,
                )
            if (decided_at - track_at) > DECISION_EXPECTED_WITHIN:
                add(
                    "late_decision",
                    f"karthik.late_decision:{mint}",
                    (
                        f"{mint} was decided "
                        f"{int((decided_at - track_at).total_seconds())}s after its "
                        f"admission,"
                        f"beyond the {int(DECISION_EXPECTED_WITHIN.total_seconds())}s "
                        f"expected."
                    ),
                    mint=mint,
                    delay_seconds=(decided_at - track_at).total_seconds(),
                )

    # --- stale quotes ----------------------------------------------------
    live = await positions_screen(session, binding)
    # `values` is `dict[str, object]`; these two are counts. Narrowed rather
    # than cast, so a value that is somehow not a number reads as zero and
    # under-reports instead of raising inside a monitoring read.
    stale_total = _count(live.values.get("stale_total"))
    open_total = _count(live.values.get("open_total"))
    if stale_total:
        add(
            "stale_quote",
            "karthik.stale_quote",
            (
                f"{stale_total} of {open_total} open positions have no price newer "
                f"than {int(QUOTE_STALE_AFTER.total_seconds() // 60)} minutes."
            ),
            positions=stale_total,
            open_total=open_total,
            mints=[row["mint"] for row in live.rows if row.get("quote_stale")][:10],
        )

    # --- the accounting invariant ----------------------------------------
    # Only when `accounting` reports a *measured* comparison. It currently does
    # not — see its docstring: equity is derived from cash plus open value, so
    # the difference is zero by construction. This branch is what runs once an
    # independently derived equity is available to compare against.
    books = await accounting(session, binding)
    if books.measured:
        cash = Decimal(str(books.values["cash_usd"]))
        open_value = Decimal(str(books.values["open_value_usd"]))
        equity = Decimal(str(books.values["equity_usd"]))
        drift = abs((cash + open_value) - equity)
        if drift > ACCOUNTING_TOLERANCE:
            add(
                "accounting_mismatch",
                "karthik.accounting_mismatch",
                f"cash + open value differs from equity by ${drift}.",
                cash_usd=str(cash),
                open_value_usd=str(open_value),
                equity_usd=str(equity),
                difference_usd=str(drift),
            )

    return findings


def coverage() -> dict[str, object]:
    """What Karthik checks, and what he cannot yet check.

    Published with every response. A monitoring surface that lists only its
    passing checks is a surface whose silence a reader will misread as
    coverage — and three of the most serious conditions in §16 are exactly the
    ones no available evidence can establish.
    """
    return {
        "checked_at": datetime.now(UTC).isoformat(),
        "checks": [
            {
                "key": defect.key,
                "label": defect.label,
                "rectification": defect.rectification,
                "severity": defect.severity,
                "detectable": defect.detectable,
                "gap": defect.gap,
            }
            for defect in DEFECTS
        ],
        "detectable": sum(1 for defect in DEFECTS if defect.detectable),
        "not_detectable": sum(1 for defect in DEFECTS if not defect.detectable),
    }
