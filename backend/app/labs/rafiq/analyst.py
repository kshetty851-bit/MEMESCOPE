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

#: Below this many trades in common, two arms have not been compared often
#: enough for "they agree" to mean anything. 20 rather than MIN_CONCLUSIVE_N
#: because this is a paired comparison — the same tokens, the same ticks — so
#: it needs far fewer observations than an unpaired win rate does.
MIN_SHARED_TRADES = 20

#: How much of the shared book must have been entered under a DIFFERENT rule
#: parameter before "they agree anyway" is a finding about the price record
#: rather than about the configuration.
#:
#: Learned from the live lab the hour this shipped. A and D agree on 46 of 47
#: trades and differ in stop level on exactly ONE of them — they both run a
#: flat 12% stop, so agreeing is arithmetic. Without this threshold the check
#: said "despite entering 1 of those under a different stop level" and blamed
#: the price sampling, which was an overclaim on a pair whose stops are the
#: same. A and C, by contrast, differ on all 55.
RULE_DIVERGENCE = Decimal("0.5")

#: At or above this fraction of identical outcomes, the two arms are reported
#: as indistinguishable. Not 1.0: one differing trade in fifty is noise, and a
#: check that only fired on perfect equality would miss the case this exists
#: for by a single row.
INDISTINGUISHABLE = Decimal("0.9")

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


@dataclass(frozen=True, slots=True)
class Overlap:
    """How one arm's closed book compares with a neighbour's, trade for trade."""

    peer: str
    shared: int
    #: Same token, same realised P&L to the cent.
    identical: int
    #: Of the shared trades, how many were entered under a DIFFERENT rule
    #: parameter. This is the number that turns "they agree" from a tautology
    #: into a finding: two arms with the same stop SHOULD agree.
    different_rule: int


async def _overlaps(session: AsyncSession, strategy_id, mine: list) -> list[Overlap]:
    """Compare this arm's settled trades against every other arm's, by token.

    ── WHY THIS EXISTS ──────────────────────────────────────────────────

    Strategy C's entire purpose is a volatility-derived stop instead of A's
    flat one, and on the live book it produced a different stop level on all
    55 shared trades and the same realised P&L on 54 of them. Every stop that
    fired closed at the same tick, at the same observed price, in both arms —
    because the price record is sampled coarsely enough that a move jumps past
    both levels between two snapshots.

    That is not a bug in either rule. It is the experiment failing to resolve:
    running C alongside A is currently buying no information, and no amount of
    reading C's own book on its own could ever reveal it. A desk that only
    looks at its own trades cannot see that its neighbour got the same answer.

    The comparison is paired — same token, same ticks — which is why it needs
    so few observations to be worth stating.
    """
    peer_rows = (
        await session.execute(
            select(
                RafiqLabStrategy.code,
                RafiqLabPosition.mint_address,
                RafiqLabPosition.exit_proceeds_usd,
                RafiqLabPosition.cost_basis,
                RafiqLabPosition.stop_price,
            )
            .join(RafiqLabPosition, RafiqLabPosition.strategy_id == RafiqLabStrategy.id)
            .where(
                RafiqLabPosition.strategy_id != strategy_id,
                RafiqLabPosition.closed_at.is_not(None),
                RafiqLabPosition.exit_proceeds_usd.is_not(None),
            )
        )
    ).all()

    books: dict[str, dict[str, tuple[Decimal, Decimal]]] = {}
    for peer_code, mint, proceeds, basis, stop in peer_rows:
        books.setdefault(peer_code, {})[mint] = (proceeds - basis, stop)

    ours = {
        row.mint_address: (row.exit_proceeds_usd - row.cost_basis, row.stop_price)
        for row in mine
    }

    out: list[Overlap] = []
    for peer_code, book in sorted(books.items()):
        shared = identical = different_rule = 0
        for mint, (our_pnl, our_stop) in ours.items():
            theirs = book.get(mint)
            if theirs is None:
                continue
            their_pnl, their_stop = theirs
            shared += 1
            if our_pnl == their_pnl:
                identical += 1
            if our_stop != their_stop:
                different_rule += 1
        if shared:
            out.append(Overlap(peer_code, shared, identical, different_rule))
    return out


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

    # ---- is this arm telling us anything the others do not? --------------
    #
    # Placed last among the per-book findings and first in importance when it
    # fires: if an arm cannot be distinguished from its neighbour, every other
    # finding about it is a finding about the neighbour too, and the reader
    # needs to know that before acting on any of them.
    for overlap in await _overlaps(session, strategy.id, settled):
        if overlap.shared < MIN_SHARED_TRADES:
            continue
        agreement = Decimal(overlap.identical) / Decimal(overlap.shared)
        if agreement < INDISTINGUISHABLE:
            continue
        differed = overlap.different_rule
        # Does the pair actually differ in the geometry, or are they configured
        # alike? Only the first case says anything about the price record.
        rules_differ = Decimal(differed) / Decimal(overlap.shared) >= RULE_DIVERGENCE
        findings.append(
            Finding(
                key=f"indistinguishable_from_{overlap.peer.lower()}",
                headline=(
                    f"This arm and Strategy {overlap.peer} cannot be told apart"
                ),
                evidence=(
                    f"They took {overlap.shared} of the same tokens and returned the "
                    f"same realised P&L on {overlap.identical} of them "
                    f"({agreement * 100:.0f}%)"
                    + (
                        f", despite entering {differed} of those under a different "
                        "stop level."
                        if rules_differ
                        else (
                            f" — and only {differed} of those were entered under a "
                            "different stop level, so agreeing is what they should do."
                        )
                    )
                ),
                lever=(
                    (
                        "The two rules genuinely differ and the record cannot show it. "
                        "That is a property of the price sampling, not of either rule: "
                        "the gap between snapshots is wider than the gap between the "
                        "two levels, so a move crosses both between one observation "
                        "and the next. Until that gap narrows, running both arms "
                        "measures one rule twice."
                    )
                    if rules_differ
                    else (
                        "Nothing to separate here: the two arms entered these trades "
                        "under the same geometry, so an identical outcome is "
                        "arithmetic rather than a result. Whatever distinguishes them "
                        "is not visible in the entry conditions, and this comparison "
                        "cannot speak to it."
                    )
                ),
                source="paired on mint_address: exit_proceeds_usd − cost_basis, stop_price",
            )
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
