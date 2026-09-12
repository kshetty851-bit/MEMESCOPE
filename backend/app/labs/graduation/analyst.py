"""What the graduation book's own record says about why it makes money.

── THE QUESTION THIS DESK WAS GIVEN ─────────────────────────────────────

"Read the closed trades and suggest how we improve so we don't have a loss."

The first thing an honest reading has to say is that the book is not, at the
moment, losing: 76 closed trades, +$126.60. The second thing it has to say is
that this is almost entirely one trade. Remove the single best result and the
same book is -$86.05. That is not a quibble — it is the difference between a
rule that works and a rule that bought a lottery ticket, and this platform has
already recorded one lab whose headline number was a corrupt denominator and
another whose "edge" vanished the moment the best trade was removed.

── WHY THE OBVIOUS IMPROVEMENT IS THE WRONG ONE ─────────────────────────

The intuitive fix for "one trade carries it" is to take profit earlier and
bank the winners. Replayed against this book's own peaks, that is wrong at
every level tested — +2%, +5%, +10%, +25% and +50% all turn a positive book
negative, and they get worse the tighter they are, because the one trade that
pays for everything is precisely the one a cap cuts off.

So the suggestions here do not propose an exit level. They report what the
record says each level WOULD have done, which is a count and an arithmetic
sum rather than a forecast, and they leave the conclusion where it belongs.

── THE LIMIT OF EVERY COUNTERFACTUAL BELOW ──────────────────────────────

`peak_quote` is the best price a SNAPSHOT saw. A limit order at that level
would only have filled if the price was actually available to trade there, and
the Rafiq work established that this platform's price record is sampled too
coarsely to guarantee it — two stop levels 2.4 points apart resolved to the
same fill on 17 of 17 trades. Every "would have" in this module is therefore
an upper bound on what the level could have captured, and it is labelled as
one rather than quietly presented as a result.

Read-only: SELECTs over rows the paper book's own runner writes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.labs.graduation.models import GradPaperPosition

#: Below this many closed trades nothing here is worth arguing about.
MIN_CONCLUSIVE_N = 30

#: The exit levels replayed in the suggestion box, as multiples of the fill.
#: Chosen to bracket what this book actually reaches: its median trade peaks
#: at 1.019x and its 90th percentile at 1.229x, so a ladder that started at
#: 1.5x would be reporting on four trades and calling it a study.
LADDER: tuple[Decimal, ...] = (
    Decimal("1.02"),
    Decimal("1.05"),
    Decimal("1.10"),
    Decimal("1.25"),
    Decimal("1.50"),
)

#: A trade that gave back essentially everything. Not "a loss" — a wipeout is
#: a different event from a bad exit and mixing them hides the tail.
WIPEOUT = Decimal("-0.95")


@dataclass(frozen=True, slots=True)
class Figure:
    label: str
    value: str
    source: str


@dataclass(frozen=True, slots=True)
class Finding:
    key: str
    headline: str
    evidence: str
    #: A measurable quantity that would have to move. Never an outcome.
    lever: str
    source: str


@dataclass(frozen=True, slots=True)
class Suggestion:
    """One thing that could be changed, with what the record says it does.

    `outcome` is the whole point: a suggestion on this platform arrives with
    the replayed number attached, so a reader is never asked to take a
    proposal on faith. Where the number says the idea is bad, the suggestion
    stays on the board saying so — a box that only lists good ideas is a box
    that has quietly done the deciding.
    """

    title: str
    detail: str
    outcome: str
    #: True when the record supports trying it. False is the common case and
    #: is not a failure of the box.
    supported: bool
    source: str


@dataclass(slots=True)
class Analysis:
    measured: bool
    detail: str
    observed_at: datetime
    verdict: str = ""
    closed: int = 0
    open_positions: int = 0
    figures: list[Figure] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    suggestions: list[Suggestion] = field(default_factory=list)


def _money(v: Decimal) -> str:
    return f"${v:,.2f}"


def _pct(n: int, d: int) -> str:
    return f"{(100.0 * n / d):.0f}%" if d else "—"


def _median(values: list[Decimal]) -> Decimal:
    return sorted(values)[len(values) // 2]


async def analyse(session: AsyncSession, *, now: datetime | None = None) -> Analysis:
    """The graduation paper book, read as an analyst would read it."""
    observed_at = now or datetime.now(UTC)

    rows = (await session.execute(select(GradPaperPosition))).scalars().all()
    closed = [r for r in rows if r.closed_at is not None and r.pnl_usd is not None]
    live = [r for r in rows if r.closed_at is None]

    if not closed:
        return Analysis(
            measured=False,
            detail=(
                "The graduation paper book has not closed a position yet. There is "
                "nothing to read — which is a reading, not a gap."
            ),
            observed_at=observed_at,
        )

    findings: list[Finding] = []

    pnls = [r.pnl_usd for r in closed]
    total = sum(pnls, Decimal(0))
    best = max(pnls)
    worst = min(pnls)
    minus_best = total - best
    winners = [r for r in closed if r.pnl_usd > 0]
    wipeouts = [r for r in closed if r.net_return is not None and r.net_return <= WIPEOUT]

    peaks = [
        r.peak_quote / r.open_fill
        for r in closed
        if r.open_fill and r.peak_quote is not None
    ]
    returns = [r.net_return for r in closed if r.net_return is not None]

    figures = [
        Figure("Closed trades", str(len(closed)), "grad_paper_positions.closed_at"),
        Figure("Open now", str(len(live)), "grad_paper_positions.closed_at is null"),
        Figure("Realised P&L", _money(total), "sum(pnl_usd)"),
        Figure("Without the best trade", _money(minus_best), "sum(pnl_usd) − max(pnl_usd)"),
        Figure("Best trade", _money(best), "max(pnl_usd)"),
        Figure("Worst trade", _money(worst), "min(pnl_usd)"),
        Figure("Win rate", _pct(len(winners), len(closed)), "pnl_usd > 0"),
    ]
    if returns:
        figures.append(
            Figure("Median return", f"{_median(returns) * 100:.2f}%", "median(net_return)")
        )
    if peaks:
        figures.append(
            Figure("Median peak", f"{_median(peaks):.3f}x", "median(peak_quote / open_fill)")
        )

    # ---- the finding that outranks every other one here -------------------
    #
    # A positive total carried by one row is the single most misleading shape
    # a book can have, and it is the shape this one is in.
    if minus_best <= 0 < total:
        findings.append(
            Finding(
                key="one_trade_is_the_book",
                headline="The entire profit is one trade",
                evidence=(
                    f"{len(closed)} closed trades total {_money(total)}. Remove the "
                    f"single best ({_money(best)}) and the same book is "
                    f"{_money(minus_best)}. The other {len(closed) - 1} trades lose "
                    "money together."
                ),
                lever=(
                    "Nothing about the rule needs changing for this to be true — it "
                    "is a statement about the shape of the returns, not their sign. "
                    "What it means practically is that the headline total is not a "
                    "sample of anything: it is one outcome, and the honest figure to "
                    f"track alongside it is the {_money(minus_best)} above."
                ),
                source="sum(pnl_usd) vs sum(pnl_usd) − max(pnl_usd)",
            )
        )

    # ---- how the trades end ----------------------------------------------
    reasons: dict[str, int] = {}
    for r in closed:
        reasons[r.close_reason or "unrecorded"] = reasons.get(r.close_reason or "unrecorded", 0) + 1
    top, count = max(reasons.items(), key=lambda kv: kv[1])
    figures.append(Figure("Most common exit", f"{top} ({_pct(count, len(closed))})", "close_reason"))
    if count == len(closed) and len(closed) >= 5:
        findings.append(
            Finding(
                key="single_exit_path",
                headline=f"Every trade ends the same way: {top}",
                evidence=(
                    f"All {len(closed)} closed trades exited on {top!r}. No other exit "
                    "branch has ever fired."
                ),
                lever=(
                    "The book has one live exit and the others cannot be evaluated "
                    "from this record because they have no observations at all. The "
                    "suggestion box below replays what the unused levels would have "
                    "caught."
                ),
                source="grad_paper_positions.close_reason",
            )
        )

    # ---- what the trades gave back ---------------------------------------
    if peaks and returns:
        median_peak_move = _median(peaks) - 1
        median_return = _median(returns)
        if median_peak_move > median_return:
            findings.append(
                Finding(
                    key="peak_giveback",
                    headline="The median trade is exited below its own high",
                    evidence=(
                        f"The median trade rose {median_peak_move * 100:.1f}% above its "
                        f"fill at some point and was closed at {median_return * 100:.2f}%."
                    ),
                    lever=(
                        "The gap between those two numbers is what an exit rule could "
                        "in principle capture. The replay below is what it actually "
                        "captures once every trade is counted rather than the ones "
                        "that went up."
                    ),
                    source="median(peak_quote / open_fill) vs median(net_return)",
                )
            )

    # ---- execution against the move it is paid out of --------------------
    entry_slip = [
        (r.open_fill - r.open_quote) / r.open_quote
        for r in closed
        if r.open_quote and r.open_fill is not None
    ]
    exit_slip = [
        (r.close_quote - r.close_fill) / r.close_quote
        for r in closed
        if r.close_quote and r.close_fill is not None
    ]
    if entry_slip and exit_slip:
        round_trip = _median(entry_slip) + _median(exit_slip)
        figures.append(
            Figure("Round-trip execution", f"{round_trip * 100:.2f}%", "open/close fill vs quote")
        )
        if peaks:
            move = _median(peaks) - 1
            if move > 0 and round_trip / move >= Decimal("0.25"):
                findings.append(
                    Finding(
                        key="execution_eats_the_move",
                        headline="Execution costs a large share of the median trade's whole move",
                        evidence=(
                            f"Getting in and out costs {round_trip * 100:.2f}% while the "
                            f"median trade only ever rose {move * 100:.1f}% above its "
                            f"fill — {(round_trip / move) * 100:.0f}% of the best move "
                            "the median trade offered."
                        ),
                        lever=(
                            "This is set by position size against the curve's depth, "
                            "not by any entry or exit condition. It is the one cost "
                            "here that can be changed without altering which tokens "
                            "the book trades."
                        ),
                        source="median entry+exit slippage vs median peak move",
                    )
                )

    # ---- the tail --------------------------------------------------------
    if wipeouts:
        findings.append(
            Finding(
                key="wipeouts",
                headline=f"{len(wipeouts)} of {len(closed)} trades lost essentially everything",
                evidence=(
                    f"{len(wipeouts)} closed at {WIPEOUT * -100:.0f}% or worse of the "
                    f"capital put in, the worst at {_money(worst)}."
                ),
                lever=(
                    "A max-hold exit cannot prevent this: the loss happens inside the "
                    "hold window, not at the end of it. What bounds it is position "
                    "size and which tokens are entered — both recorded."
                ),
                source="grad_paper_positions.net_return",
            )
        )

    # ---- sample adequacy, first in the verdict ---------------------------
    if len(closed) < MIN_CONCLUSIVE_N:
        findings.insert(
            0,
            Finding(
                key="sample_too_small",
                headline="Too few closed trades to conclude anything",
                evidence=(
                    f"{len(closed)} closed trades. At this size the figures above "
                    "describe what happened and do not predict anything."
                ),
                lever=(
                    f"{MIN_CONCLUSIVE_N - len(closed)} more closes before the numbers "
                    "are worth arguing about. Nothing needs changing to get them."
                ),
                source="count(grad_paper_positions where closed_at is not null)",
            ),
        )
        verdict = f"No conclusion available. {len(closed)} closed, {_money(total)} realised."
    else:
        verdict = (
            f"{_money(total)} over {len(closed)} closed trades — "
            f"{_money(minus_best)} without the best one."
        )

    return Analysis(
        measured=True,
        detail=(
            "Computed from the graduation paper book's own closed rows. Every figure "
            "names the columns behind it; nothing here is modelled."
        ),
        observed_at=observed_at,
        verdict=verdict,
        closed=len(closed),
        open_positions=len(live),
        figures=figures,
        findings=findings,
        suggestions=_suggest(closed, peaks, exit_slip),
    )


def _suggest(closed, peaks, exit_slip) -> list[Suggestion]:
    """The suggestion box: every exit level, replayed against this book.

    Each entry carries the number rather than an opinion. The levels that make
    the book worse stay on the board saying so — that is the most useful thing
    this box can tell a reader, because "take profit earlier" is the first idea
    anybody has and the record has already answered it.
    """
    if not peaks or not closed:
        return []

    slip = _median(exit_slip) if exit_slip else Decimal(0)
    actual = sum((r.pnl_usd for r in closed), Decimal(0))
    out: list[Suggestion] = []

    for level in LADDER:
        fired = 0
        book = Decimal(0)
        for row in closed:
            if not row.open_fill or row.peak_quote is None or row.notional_usd is None:
                continue
            reached = (row.peak_quote / row.open_fill) >= level
            if reached:
                fired += 1
                book += (level - 1 - slip) * row.notional_usd
            else:
                book += row.pnl_usd
        delta = book - actual
        out.append(
            Suggestion(
                title=f"Take profit at +{(level - 1) * 100:.0f}%",
                detail=(
                    f"{fired} of {len(closed)} trades printed this level at some point. "
                    "The rest are left exactly as they closed."
                ),
                outcome=(
                    f"{_money(book)} instead of {_money(actual)} "
                    f"({'+' if delta >= 0 else ''}{_money(delta)})"
                ),
                supported=delta > 0,
                source="peak_quote / open_fill, replayed at this level",
            )
        )

    if all(not s.supported for s in out):
        out.insert(
            0,
            Suggestion(
                title="Do not add a take-profit",
                detail=(
                    "Every level below makes this book worse, and the tighter the cap "
                    "the worse it gets. The reason is visible in the figures above: "
                    "one trade is the entire profit, and a cap is precisely what "
                    "removes it."
                ),
                outcome=f"Leaving the rule alone keeps {_money(actual)}.",
                supported=True,
                source="the replay below, every level",
            ),
        )

    out.append(
        Suggestion(
            title="Treat every number above as an upper bound",
            detail=(
                "A replay assumes a level that PRINTED could have been traded. This "
                "platform's price record is sampled too coarsely to guarantee that — "
                "the Rafiq lab had two stop levels resolve to the same fill on 17 of "
                "17 trades. Real fills would be worse than these, never better."
            ),
            outcome="No figure here is achievable; each is a ceiling.",
            supported=False,
            source="peak_quote is a snapshot high, not a tradeable quote",
        )
    )
    return out


def as_dict(a: Analysis) -> dict[str, Any]:
    return {
        "measured": a.measured,
        "detail": a.detail,
        "observed_at": a.observed_at,
        "verdict": a.verdict,
        "closed": a.closed,
        "open_positions": a.open_positions,
        "figures": [{"label": f.label, "value": f.value, "source": f.source} for f in a.figures],
        "findings": [
            {
                "key": f.key,
                "headline": f.headline,
                "evidence": f.evidence,
                "lever": f.lever,
                "source": f.source,
            }
            for f in a.findings
        ],
        "suggestions": [
            {
                "title": s.title,
                "detail": s.detail,
                "outcome": s.outcome,
                "supported": s.supported,
                "source": s.source,
            }
            for s in a.suggestions
        ],
    }
