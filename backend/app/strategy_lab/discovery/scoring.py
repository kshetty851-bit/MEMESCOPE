"""Survival filters, the ranking score, and the champion bar. §13, §17, §18, §26.

── THE SCORE, PUBLISHED IN FULL ─────────────────────────────────────────────

    DISCOVERY_SCORE = penalise(R_robust, by = 1/(1+D), S, C, Q)

    R_robust  out-of-sample wallet return %, **with the single best trade
              removed** — the outlier defence built into the number rather than
              bolted on beside it
    D         maximum drawdown as a fraction
    S         sample shrink, min(1, N / 50) — pulls a thin record toward zero
    C         capture penalty, §18. 1.0 at or above 20% capture, falling
              linearly to 0.4 at zero capture
    Q         day-consistency factor, from the share of profitable days

── WHY `penalise` EXISTS INSTEAD OF PLAIN MULTIPLICATION ────────────────────

A factor in (0, 1] shrinks a positive return toward zero, which is the intended
penalty. Applied to a **negative** return it shrinks the loss toward zero too —
which *raises* the rank. Multiplying by penalties is therefore exactly backwards
for a losing strategy, and on a dataset where every strategy loses it inverts
the entire board.

That is not hypothetical. The first run of this engine ranked
`$10 entries on tokens where age >= 12h` first out of 1,850: it captured 16% of
opportunities, traded 45 times, and lost 1.5% instead of 90%. Every penalty the
score applied — low capture, thin sample, day concentration — made its loss
smaller and its rank better. It was scoring near-abstention as skill, which is
the precise failure §18 was written to prevent.

`penalise` multiplies when the base is positive and **divides** when it is
negative, so a penalty always moves the score down. Same behaviour above zero,
correct behaviour below it.

── WHY CAPTURE IS PENALISED AT ALL ──────────────────────────────────────────

S9 "won" the hand-built lab by refusing 89% of opportunities and losing 11.7%
instead of 90%. That is real capital preservation and it is also not a strategy:
a rule that almost never trades cannot compound, cannot be measured, and
cannot be distinguished from luck at N=55. §18 asks for the penalty explicitly.
It is a penalty and not a disqualification — the row stays on the board, ranked
lower, flagged `LOW_CAPTURE`.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.strategy_lab.discovery.engine import Evaluation

_ZERO = Decimal(0)
_ONE = Decimal(1)

SCORING_VERSION = "1.0.0"

#: §13's guidance. Preferred, not absolute — below it the row is flagged rather
#: than dropped, because "we have too little evidence" is itself a finding.
MIN_OOS_TRADES = 50

#: The absolute floor. §13 says not to make the sample rule absolute *when data
#: is insufficient*, and this is where that stops being a courtesy: below ten
#: trades a profit factor, a drawdown and a win rate are arithmetic on noise.
#: A row under it is not "a survivor with a small sample", it is a row with no
#: evidence, and calling it a survivor is how a funnel comes to report four
#: lucky trades as a validated strategy.
EVIDENCE_FLOOR_N = 10

#: §13's hard rejections.
MAX_DRAWDOWN_PCT = Decimal(60)

#: §18. Below this share of offered opportunities the row is flagged and its
#: score is scaled down.
MIN_CAPTURE_PCT = Decimal(20)

#: Full sample weight is reached here.
FULL_SAMPLE_N = 50


class Flag:
    NO_EVIDENCE = "NO_EVIDENCE"
    SMALL_SAMPLE = "SMALL_SAMPLE"
    LOW_CAPTURE = "LOW_CAPTURE"
    OUTLIER_DEPENDENT = "OUTLIER_DEPENDENT"
    OUTLIER_DEPENDENT_TOP3 = "OUTLIER_DEPENDENT_TOP3"
    DAY_CONCENTRATED = "DAY_CONCENTRATED"
    NEGATIVE_EXPECTANCY = "NEGATIVE_EXPECTANCY"
    EXCESSIVE_DRAWDOWN = "EXCESSIVE_DRAWDOWN"
    NO_TRADES = "NO_TRADES"


class Status:
    GENERATED = "GENERATED"
    DISCOVERY = "DISCOVERY"
    VALIDATION = "VALIDATION"
    HOLDOUT = "HOLDOUT"
    CHAMPION = "CHAMPION"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class Verdict:
    """Whether a candidate may advance, and every reason it may not."""

    survives: bool
    reasons: tuple[str, ...]
    flags: tuple[str, ...]
    score: Decimal
    components: dict[str, Decimal]


def flags_for(evaluation: Evaluation) -> tuple[str, ...]:
    out: list[str] = []
    if evaluation.n == 0:
        return (Flag.NO_TRADES,)
    if evaluation.n < EVIDENCE_FLOOR_N:
        out.append(Flag.NO_EVIDENCE)
    if evaluation.n < MIN_OOS_TRADES:
        out.append(Flag.SMALL_SAMPLE)
    if evaluation.capture_pct < MIN_CAPTURE_PCT:
        out.append(Flag.LOW_CAPTURE)
    if evaluation.outlier_dependent:
        out.append(Flag.OUTLIER_DEPENDENT)
    if evaluation.outlier_dependent_top3:
        out.append(Flag.OUTLIER_DEPENDENT_TOP3)
    concentration = evaluation.day_concentration_pct
    if concentration is not None and concentration >= 60:
        out.append(Flag.DAY_CONCENTRATED)
    expectancy = evaluation.expectancy
    if expectancy is not None and expectancy <= 0:
        out.append(Flag.NEGATIVE_EXPECTANCY)
    if evaluation.max_drawdown_pct > MAX_DRAWDOWN_PCT:
        out.append(Flag.EXCESSIVE_DRAWDOWN)
    return tuple(out)


def _capture_factor(capture_pct: Decimal) -> Decimal:
    """1.0 at or above the minimum, falling linearly to 0.4 at zero capture."""
    if capture_pct >= MIN_CAPTURE_PCT:
        return _ONE
    floor = Decimal("0.4")
    return floor + (_ONE - floor) * (capture_pct / MIN_CAPTURE_PCT)


def _day_factor(evaluation: Evaluation) -> Decimal:
    """From the share of profitable days. Unknown days score neutral.

    §15: a strategy profitable on one day of ten because of a single monster
    token should not rank highly. With fewer than two days there is nothing to
    measure, so the factor is 1 and `DAY_CONCENTRATED` carries the warning
    instead of a silent penalty.
    """
    days = evaluation.daily()
    if len(days) < 2:
        return _ONE
    share = evaluation.profitable_day_pct or _ZERO
    # 0.5 at never-profitable, 1.0 at always-profitable.
    return Decimal("0.5") + Decimal("0.5") * (share / 100)


def penalise(base: Decimal, factor: Decimal) -> Decimal:
    """Apply a penalty in (0, 1] so it always moves the score **down**.

    Multiplies a gain, divides a loss. See the module docstring: plain
    multiplication rewards a losing strategy for trading less, which is the
    opposite of what §18 asks for.
    """
    if factor <= _ZERO:
        return base
    return base * factor if base > _ZERO else base / factor


def score(evaluation: Evaluation) -> tuple[Decimal, dict[str, Decimal]]:
    """The published formula, with every component returned beside it."""
    if evaluation.n == 0:
        return _ZERO, {
            "robust_return_pct": _ZERO,
            "drawdown": _ZERO,
            "sample": _ZERO,
            "capture": _ZERO,
            "day": _ZERO,
        }

    robust_return = evaluation.without(best=1) / evaluation.starting_capital * 100
    drawdown = evaluation.max_drawdown_pct / 100
    sample = min(_ONE, Decimal(evaluation.n) / Decimal(FULL_SAMPLE_N))
    capture = _capture_factor(evaluation.capture_pct)
    day = _day_factor(evaluation)

    value = robust_return
    for factor in (_ONE / (_ONE + drawdown), sample, capture, day):
        value = penalise(value, factor)
    return value, {
        "robust_return_pct": robust_return,
        "drawdown": drawdown,
        "sample": sample,
        "capture": capture,
        "day": day,
    }


def judge(evaluation: Evaluation, *, strict: bool = True) -> Verdict:
    """§13's survival filters. `strict` applies the hard rejections.

    The sample-size rule is deliberately soft: §13 says not to make it absolute
    when data is insufficient, so a thin record is flagged and allowed to
    advance rather than silently deleted. Every other rule is hard, because a
    strategy with a profit factor at or below 1.0 out of sample has no claim to
    make regardless of how it got there.
    """
    reasons: list[str] = []
    flags = flags_for(evaluation)
    value, components = score(evaluation)

    if evaluation.n == 0:
        return Verdict(False, ("no trades",), flags, value, components)

    profit_factor = evaluation.profit_factor
    if strict:
        if evaluation.n < EVIDENCE_FLOOR_N:
            reasons.append(
                f"only {evaluation.n} trades — below the {EVIDENCE_FLOOR_N}-trade "
                f"evidence floor, so no metric here is measurable"
            )
        if profit_factor is None and evaluation.n < MIN_OOS_TRADES:
            reasons.append(
                "no losing trade at this sample size — profit factor is undefined, "
                "not infinite"
            )
        if profit_factor is not None and profit_factor <= _ONE:
            reasons.append(f"profit factor {profit_factor:.2f} <= 1.0")
        expectancy = evaluation.expectancy
        if expectancy is None or expectancy <= 0:
            reasons.append("expectancy <= 0")
        if evaluation.return_pct <= 0:
            reasons.append(f"wallet return {evaluation.return_pct:.1f}% <= 0")
        if evaluation.max_drawdown_pct > MAX_DRAWDOWN_PCT:
            reasons.append(
                f"max drawdown {evaluation.max_drawdown_pct:.1f}% > {MAX_DRAWDOWN_PCT}%"
            )
        if evaluation.outlier_dependent:
            reasons.append("unprofitable without its single best trade")

    return Verdict(
        survives=not reasons,
        reasons=tuple(reasons),
        flags=flags,
        score=value,
        components=components,
    )


# ── §26's champion standards ────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class ChampionStandard:
    label: str
    met: bool
    detail: str


def champion_standards(evaluation: Evaluation) -> list[ChampionStandard]:
    """The research bar. **Not automatic production rules** — §26 says so."""
    profit_factor = evaluation.profit_factor
    expectancy = evaluation.expectancy
    concentration = evaluation.day_concentration_pct
    days = evaluation.daily()

    return [
        ChampionStandard(
            "OOS PF >= 1.20",
            profit_factor is not None and profit_factor >= Decimal("1.20"),
            "inf" if profit_factor is None else f"{profit_factor:.2f}",
        ),
        ChampionStandard(
            "positive expectancy",
            expectancy is not None and expectancy > 0,
            "—" if expectancy is None else f"${expectancy:.2f}",
        ),
        ChampionStandard(
            "positive wallet return",
            evaluation.return_pct > 0,
            f"{evaluation.return_pct:.1f}%",
        ),
        ChampionStandard(
            "max DD <= 40%",
            evaluation.max_drawdown_pct <= 40,
            f"{evaluation.max_drawdown_pct:.1f}%",
        ),
        ChampionStandard(
            "capture >= 20%",
            evaluation.capture_pct >= MIN_CAPTURE_PCT,
            f"{evaluation.capture_pct:.1f}%",
        ),
        ChampionStandard(
            "N >= 50",
            evaluation.n >= MIN_OOS_TRADES,
            str(evaluation.n),
        ),
        ChampionStandard(
            "profitable without best trade",
            not evaluation.outlier_dependent,
            f"ex-best-1 ${evaluation.without(best=1):.2f}",
        ),
        ChampionStandard(
            "profitable across multiple days",
            len(days) >= 2
            and (evaluation.profitable_day_pct or _ZERO) > 50
            and (concentration is None or concentration < 60),
            f"{len(days)} day(s), "
            f"{(evaluation.profitable_day_pct or _ZERO):.0f}% profitable, "
            f"{(concentration or _ZERO):.0f}% concentration",
        ),
    ]


def is_champion(evaluation: Evaluation) -> bool:
    return all(s.met for s in champion_standards(evaluation))
