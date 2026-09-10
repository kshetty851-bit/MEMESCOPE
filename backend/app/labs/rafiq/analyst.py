"""What an analyst can honestly say about a strategy that is losing money.

── THE PROBLEM, STATED PLAINLY ──────────────────────────────────────────

The brief is "monitor the strategy and suggest what needs to be improved to be
in profit". The tempting shape for that is a character who reads a P&L and
offers a way to fix it, and on this platform that would be the single most
dishonest thing in the product. Eight separate research efforts here have ended
in a recorded no-edge finding — the Strategy Lab's twelve families, the V6.1
tournament's twenty wallets, the 15-minute window, the graduation sweep's
forty-eight combinations. A cartoon analyst proposing "widen the stop and it
turns positive" would be inventing precisely the claim all of that work was
unable to support.

── WHAT A REAL ANALYST DOES INSTEAD ─────────────────────────────────────

Measures, compares against a control, states what the sample can and cannot
support, and identifies the *binding constraint* mechanically. "Insufficient
evidence" is a professional answer and it is frequently the correct one.

So every finding here is an arithmetic statement about rows that exist, and
every one carries the figures it was computed from. Where a finding implies an
action it names a **lever**: a measurable quantity that would have to move, not
an outcome that would follow. "Execution cost is 31% of gross profit" is a
lever. "Trade the trend instead" is a fortune.

── THE MOST USEFUL COLUMN IN THE TABLE IS `peak_price` ──────────────────

It records the best price a position ever saw while open. That single column
separates the two failure modes an exit rule can have, without any modelling:

  * peaks reach the target and the position still lost  →  the EXIT binds
  * peaks never approach the target                     →  the ENTRY binds

An analyst who can distinguish those is doing real work. One who cannot is
guessing, and this module exists so that nobody has to guess.

Read-only throughout: SELECTs over rows the lab's own runner writes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.labs.rafiq.models import RafiqLabPosition, RafiqLabStrategy

#: Below this many closed trades, a win rate is a coin flip with a decimal
#: point. Not a magic number: at n=30 a 50% observed rate has a 95% interval of
#: roughly ±18pp, which is wider than any effect this lab is looking for. The
#: analysts say so rather than reporting a percentage that reads as a fact.
MIN_CONCLUSIVE_N = 30

#: A peak within this fraction of the target counts as "approached it". Loose
#: on purpose — the question is whether the target was ever in reach at all,
#: not whether it was touched.
APPROACH_BAND = Decimal("0.9")


@dataclass(frozen=True, slots=True)
class Figure:
    """One measured quantity, with the column it came from."""

    label: str
    value: str
    source: str


@dataclass(frozen=True, slots=True)
class Finding:
    key: str
    headline: str
    #: The arithmetic, with the numbers in it. This is what makes the finding
    #: checkable rather than assertable.
    evidence: str
    #: What would have to *move*, measurably. Empty when the honest answer is
    #: that the data does not point anywhere yet.
    lever: str
    source: str


@dataclass(slots=True)
class Analysis:
    code: str
    lane: str
    measured: bool
    detail: str
    observed_at: datetime
    verdict: str = ""
    figures: list[Figure] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    open_positions: int = 0
    closed_positions: int = 0


def _pct(numerator: int, denominator: int) -> str:
    return f"{(100.0 * numerator / denominator):.0f}%" if denominator else "—"


def _money(value: Decimal) -> str:
    return f"${value:,.2f}"


async def analyse(session: AsyncSession, code: str, *, now: datetime | None = None) -> Analysis:
    """One strategy's own trades, read as an analyst would read them."""
    observed_at = now or datetime.now(UTC)

    strategy = (
        await session.execute(select(RafiqLabStrategy).where(RafiqLabStrategy.code == code))
    ).scalar_one_or_none()
    if strategy is None:
        return Analysis(
            code=code,
            lane="",
            measured=False,
            detail=f"No strategy {code!r} is registered in this lab.",
            observed_at=observed_at,
        )

    rows = (
        (
            await session.execute(
                select(RafiqLabPosition).where(RafiqLabPosition.strategy_id == strategy.id)
            )
        )
        .scalars()
        .all()
    )
    closed = [row for row in rows if row.closed_at is not None]
    live = [row for row in rows if row.closed_at is None]
    settled = [row for row in closed if row.exit_proceeds_usd is not None]

    if not rows:
        return Analysis(
            code=code,
            lane=strategy.lane,
            measured=False,
            detail=(
                "This strategy has not opened a position yet. There is nothing to "
                "analyse — which is a reading, not a gap."
            ),
            observed_at=observed_at,
        )

    findings: list[Finding] = []

    # ---- P&L, and what it is worth at this sample size -------------------
    gross = sum((r.exit_proceeds_usd - r.cost_basis for r in settled), Decimal(0))
    winners = [r for r in settled if (r.exit_proceeds_usd or Decimal(0)) > r.cost_basis]
    allocated = sum((r.cost_basis for r in live), Decimal(0))

    figures = [
        Figure("Closed trades", str(len(closed)), "rafiq_lab_positions.closed_at"),
        Figure("Open positions", str(len(live)), "rafiq_lab_positions.status"),
        Figure("Realised P&L", _money(gross), "exit_proceeds_usd − cost_basis"),
        Figure("Capital in open trades", _money(allocated), "cost_basis"),
        Figure(
            "Win rate",
            _pct(len(winners), len(settled)) if settled else "—",
            "exit_proceeds_usd > cost_basis",
        ),
    ]

    # ---- the asymmetry, which is where a high win rate goes to die -------
    #
    # The finding a professional says first and an amateur never says at all.
    # Strategy B wins 64% of its trades and loses money; that is not a paradox
    # and it is not bad luck, it is arithmetic: given an average winner W and
    # an average loser L, a book breaks even at a win rate of L / (W + L).
    # Nothing is predicted here — the breakeven rate is an identity over two
    # numbers already in the table, and comparing it to the observed rate says
    # which of the two has to move. That is a lever.
    losers = [r for r in settled if (r.exit_proceeds_usd or Decimal(0)) <= r.cost_basis]
    if winners and losers:
        avg_win = sum((r.exit_proceeds_usd - r.cost_basis for r in winners), Decimal(0)) / len(winners)
        avg_loss = sum((r.cost_basis - r.exit_proceeds_usd for r in losers), Decimal(0)) / len(losers)
        figures.append(
            Figure("Average winner", _money(avg_win), "exit_proceeds_usd − cost_basis, winners")
        )
        figures.append(
            Figure("Average loser", _money(-avg_loss), "exit_proceeds_usd − cost_basis, losers")
        )
        if avg_win + avg_loss > 0:
            breakeven = avg_loss / (avg_win + avg_loss)
            observed = Decimal(len(winners)) / Decimal(len(settled))
            figures.append(
                Figure(
                    "Breakeven win rate",
                    f"{breakeven * 100:.0f}%",
                    "avg_loss / (avg_win + avg_loss)",
                )
            )
            if observed < breakeven:
                findings.append(
                    Finding(
                        key="asymmetry",
                        headline=(
                            f"Winning {observed * 100:.0f}% of trades is not enough at this "
                            "win/loss ratio"
                        ),
                        evidence=(
                            f"The average winner returns {_money(avg_win)} and the average "
                            f"loser costs {_money(avg_loss)}. At that ratio the book needs "
                            f"{breakeven * 100:.0f}% winners to break even and it is getting "
                            f"{observed * 100:.0f}%."
                        ),
                        lever=(
                            "Two quantities can close that gap and the record says which is "
                            f"which: the average loser ({_money(avg_loss)}) is set by where "
                            "the stop sits, the average winner "
                            f"({_money(avg_win)}) by where the exit sits. Neither is a "
                            "forecast — both are measured, and the peak distribution below "
                            "says whether the exit had room to move."
                        ),
                        source="mean(exit_proceeds_usd − cost_basis) by outcome",
                    )
                )

    # ---- the binding constraint, from peak_price -------------------------
    #
    # The finding this whole module was built around.
    approached = 0
    reached = 0
    peaks: list[Decimal] = []
    for row in closed:
        if not row.entry_price or not row.target_price:
            continue
        target_multiple = row.target_price / row.entry_price
        peak_multiple = row.peak_price / row.entry_price if row.entry_price else Decimal(0)
        peaks.append(peak_multiple)
        if peak_multiple >= target_multiple:
            reached += 1
        elif peak_multiple >= target_multiple * APPROACH_BAND:
            approached += 1

    if peaks:
        median_peak = sorted(peaks)[len(peaks) // 2]
        never = len(peaks) - reached - approached
        if reached == 0:
            findings.append(
                Finding(
                    key="target_never_reached",
                    headline="The target was never in reach",
                    evidence=(
                        f"Of {len(peaks)} closed trades, 0 ever printed the target and "
                        f"{approached} came within {int((1 - APPROACH_BAND) * 100)}% of it. "
                        f"The median trade peaked at {median_peak:.3f}x its entry."
                    ),
                    lever=(
                        "The exit level is not what is costing this strategy — no exit "
                        "inside the rule's range would have fired. What binds is which "
                        "tokens are being entered, and the measurable version of that "
                        "question is the peak distribution above."
                    ),
                    source="rafiq_lab_positions.peak_price vs target_price",
                )
            )
        elif reached and len(peaks) - reached:
            findings.append(
                Finding(
                    key="target_sometimes_reached",
                    headline="The target is reachable, and most trades do not get there",
                    evidence=(
                        f"{reached} of {len(peaks)} closed trades printed the target; "
                        f"{never} never came within {int((1 - APPROACH_BAND) * 100)}% of it. "
                        f"Median peak {median_peak:.3f}x."
                    ),
                    lever=(
                        "Both ends are live here. The comparison worth making is the "
                        "entry characteristics of the trades that reached the target "
                        "against those that did not — the columns for that are "
                        "entry_liquidity_usd and detected_at."
                    ),
                    source="rafiq_lab_positions.peak_price vs target_price",
                )
            )

    # ---- how the trades actually end -------------------------------------
    by_reason: dict[str, int] = {}
    for row in closed:
        by_reason[row.exit_reason or "unrecorded"] = by_reason.get(row.exit_reason or "unrecorded", 0) + 1
    if by_reason:
        top, count = max(by_reason.items(), key=lambda kv: kv[1])
        figures.append(
            Figure("Most common exit", f"{top} ({_pct(count, len(closed))})", "exit_reason")
        )
        if count == len(closed) and len(closed) >= 5:
            findings.append(
                Finding(
                    key="single_exit_path",
                    headline=f"Every trade ends the same way: {top}",
                    evidence=(
                        f"All {len(closed)} closed trades exited on {top!r}. The other "
                        "exit paths in this rule have never fired."
                    ),
                    lever=(
                        "A rule with one live branch is simpler than it looks. The "
                        "unused branches cannot be evaluated from this record because "
                        "they have no observations at all."
                    ),
                    source="rafiq_lab_positions.exit_reason",
                )
            )

    # ---- execution cost, which is a real and fixable number --------------
    entry_slip: list[Decimal] = []
    for row in closed:
        if row.entry_observed_price and row.entry_price:
            entry_slip.append((row.entry_price - row.entry_observed_price) / row.entry_observed_price)
    if entry_slip:
        median_slip = sorted(entry_slip)[len(entry_slip) // 2]
        figures.append(
            Figure(
                "Median entry slippage",
                f"{median_slip * 100:.2f}%",
                "entry_price vs entry_observed_price",
            )
        )
        # Slippage only means something next to the move it is being paid out
        # of. 1% is nothing against a 3x and it is the whole trade against a
        # median peak of 1.02x — and on this lab it is frequently the latter.
        if peaks:
            median_peak_move = sorted(peaks)[len(peaks) // 2] - 1
            # Guard the denominator, not just against zero. When the median
            # trade never really moved, slippage over that move is an enormous
            # meaningless number (Strategy D printed 99074% before this line
            # existed). Below half a percent of movement the honest finding is
            # the peak one above — "nothing went anywhere" — and this ratio has
            # nothing to add to it.
            if median_peak_move >= Decimal("0.005"):
                share = median_slip / median_peak_move
                if share >= Decimal("0.25"):
                    findings.append(
                        Finding(
                            key="execution_eats_the_move",
                            headline="Execution costs a large share of the whole available move",
                            evidence=(
                                f"Median entry slippage is {median_slip * 100:.2f}% while the "
                                f"median trade only ever rose {median_peak_move * 100:.1f}% "
                                f"above its entry. Getting in costs {share * 100:.0f}% of the "
                                "best move the median trade ever offered."
                            ),
                            lever=(
                                "This one is not about the rule at all. It is the gap between "
                                "entry_observed_price and entry_price, and it is set by trade "
                                "size against entry_liquidity_usd — both recorded, both "
                                "measurable without changing a single entry condition."
                            ),
                            source="entry slippage vs median peak_price / entry_price",
                        )
                    )

    # ---- how long the money is committed ---------------------------------
    holds = [
        (row.closed_at - row.opened_at).total_seconds()
        for row in closed
        if row.closed_at is not None
    ]
    if holds:
        median_hold = sorted(holds)[len(holds) // 2]
        figures.append(
            Figure("Median hold", f"{median_hold / 60:.0f} min", "closed_at − opened_at")
        )

    # ---- entry delay, where the record supports it -----------------------
    delays = [
        (row.opened_at - row.detected_at).total_seconds()
        for row in closed
        if row.detected_at is not None
    ]
    if delays:
        median_delay = sorted(delays)[len(delays) // 2]
        figures.append(
            Figure("Median entry delay", f"{median_delay:.0f}s", "opened_at − detected_at")
        )

    # ---- sample adequacy, which outranks every other finding -------------
    #
    # Deliberately last in the list and first in the verdict: it is the finding
    # that says how much the others are worth.
    if len(settled) < MIN_CONCLUSIVE_N:
        findings.insert(
            0,
            Finding(
                key="sample_too_small",
                headline="Too few closed trades to conclude anything",
                evidence=(
                    f"{len(settled)} settled trades. At this size a win rate carries an "
                    f"interval wider than any effect this lab is looking for, so the "
                    f"{_pct(len(winners), len(settled))} above is a description of what "
                    "happened and not a prediction."
                ),
                lever=(
                    f"{MIN_CONCLUSIVE_N - len(settled)} more closed trades before the "
                    "rate is worth arguing about. Nothing needs changing to get them."
                ),
                source="count(rafiq_lab_positions where closed_at is not null)",
            ),
        )
        verdict = (
            f"No conclusion available. {len(settled)} settled trades, "
            f"{_money(gross)} realised."
        )
    else:
        verdict = (
            f"{_money(gross)} realised over {len(settled)} settled trades, "
            f"{_pct(len(winners), len(settled))} of them profitable."
        )

    return Analysis(
        code=code,
        lane=strategy.lane,
        measured=True,
        detail=(
            "Computed from this strategy's own position rows. Every figure names "
            "the columns behind it; nothing here is modelled or projected."
        ),
        observed_at=observed_at,
        verdict=verdict,
        figures=figures,
        findings=findings,
        open_positions=len(live),
        closed_positions=len(closed),
    )


def as_dict(analysis: Analysis) -> dict[str, Any]:
    return {
        "code": analysis.code,
        "lane": analysis.lane,
        "measured": analysis.measured,
        "detail": analysis.detail,
        "observed_at": analysis.observed_at,
        "verdict": analysis.verdict,
        "open_positions": analysis.open_positions,
        "closed_positions": analysis.closed_positions,
        "figures": [
            {"label": f.label, "value": f.value, "source": f.source} for f in analysis.figures
        ],
        "findings": [
            {
                "key": f.key,
                "headline": f.headline,
                "evidence": f.evidence,
                "lever": f.lever,
                "source": f.source,
            }
            for f in analysis.findings
        ],
    }
