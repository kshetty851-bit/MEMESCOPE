"""Everything the leaderboard reports, and the honesty flags that go with it.

Separate from the replay because a metric is a *reading* of a result, not part
of producing one. Changing how drawdown is presented must never be able to
change what the strategy did.

── THE RANKING, PUBLISHED IN FULL ───────────────────────────────────────────

§11 forbids ranking by win rate and requires a risk-adjusted wallet outcome
that one monster token cannot buy. `LAB_SCORE` is:

    LAB_SCORE = (R / (1 + D)) * S * P

    R  robust wallet return %, computed **with the single best trade removed**
    D  maximum drawdown, as a fraction
    S  sample shrink, min(1, N / 100) — pulls a thin record toward zero
    P  profit-factor multiplier, clamp(PF, 0.5, 2.0), inverted when R ≤ 0 so
       it always pushes in the direction of quality rather than against it

Four inputs, all four published beside the score, and the underlying metrics
are never hidden behind it. R is the outlier defence: a strategy carried by one
token scores on what it did without that token.

`S` shrinks toward zero rather than penalising, which is the right shape for
both signs — thin evidence should move a strategy toward "we do not know",
not toward "bad".
"""

from __future__ import annotations

import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from app.strategy_lab.replay import Position, Result
from app.strategy_lab.rules import NON_EXECUTABLE_REASONS

_ZERO = Decimal(0)
_ONE = Decimal(1)

#: Bumped when a formula changes. Stored beside every persisted leaderboard so
#: two vintages are never averaged into each other.
METRICS_VERSION = "1.0.0"

#: Below this, every figure carries SMALL_SAMPLE. Not a significance test — a
#: reminder that four lucky trades are not a result.
SMALL_SAMPLE_N = 30

#: Full weight in the ranking is reached here.
FULL_CONFIDENCE_N = 100

#: Share of a strategy's trades that may fall on one UTC day before the record
#: is flagged. Derived from the trades, never passed in — this dataset has a
#: single day carrying 61% of the control's positions at a 68% catastrophe
#: rate, and a leaderboard that did not say so would be reporting one bad
#: Thursday as a strategy result.
REGIME_CONCENTRATION_PCT = Decimal(60)

#: The multiples the moonshot analysis reports on.
MOONSHOT_LEVELS: tuple[Decimal, ...] = (Decimal(2), Decimal(5), Decimal(10))


class Flag:
    """Honesty labels. Every one is derived, none is typed by hand."""

    SMALL_SAMPLE = "SMALL_SAMPLE"
    OUTLIER_DOMINATED = "OUTLIER_DOMINATED"
    OUTLIER_DEPENDENT = "OUTLIER_DEPENDENT"
    REGIME_CONCENTRATED = "REGIME_CONCENTRATED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    UNSETTLED_POSITIONS = "UNSETTLED_POSITIONS"


@dataclass(frozen=True, slots=True)
class Robustness:
    """§24. What is left of a strategy once its luckiest trades are removed."""

    normal_pnl: Decimal
    ex_best_1_pnl: Decimal
    ex_best_3_pnl: Decimal
    ex_worst_1_pnl: Decimal
    ex_worst_3_pnl: Decimal
    #: Share of total *gross profit* produced by the top 1 / 3 / 5 trades.
    top_1_share_pct: Decimal | None
    top_3_share_pct: Decimal | None
    top_5_share_pct: Decimal | None
    #: Profitable normally, unprofitable without its best trade.
    outlier_dependent: bool


@dataclass(frozen=True, slots=True)
class MoonshotCapture:
    """§12. What the strategy actually monetised out of what it could have.

    The denominator is the position's value at its **executable** peak — the
    best price printed against a pool deep enough to sell into. Never the
    observed peak: a 40x tick against a drained pool is not upside anyone could
    have taken, and using it would make every strategy look like a failure
    against a number that never existed.
    """

    level: Decimal
    #: Positions whose executable path reached this multiple.
    reached: int
    #: Of those, how many the strategy actually turned into this multiple.
    captured: int
    opportunity_usd: Decimal
    realised_usd: Decimal

    @property
    def efficiency_pct(self) -> Decimal | None:
        if self.opportunity_usd <= 0:
            return None
        return self.realised_usd / self.opportunity_usd * 100


@dataclass(frozen=True, slots=True)
class RugImpact:
    """§15, per strategy. What the catastrophes cost after partial profits."""

    count: int
    capital_invested: Decimal
    capital_recovered_before: Decimal
    residual_recovered: Decimal
    net_loss: Decimal
    #: How many reached each rung level before collapsing. The direct answer to
    #: "did partial profit-taking protect us".
    reached_125: int
    reached_150: int
    reached_175: int
    reached_200: int


@dataclass(frozen=True, slots=True)
class Row:
    """One leaderboard line. §11's columns, plus what makes them trustworthy."""

    strategy_id: str
    version: str
    name: str
    definition_hash: str
    benchmark: bool

    n: int
    offered: int
    starting_capital: Decimal
    final_equity: Decimal
    net_pnl: Decimal
    gross_pnl: Decimal
    total_costs: Decimal
    wallet_return_pct: Decimal
    profit_factor: Decimal | None
    expectancy: Decimal | None
    win_rate_pct: Decimal | None
    median_trade_return_pct: Decimal | None
    mean_trade_return_pct: Decimal | None
    max_drawdown_pct: Decimal
    rug_loss_usd: Decimal
    rugs: int
    blocked: int
    blocked_for_cash: int
    capital_blocked_usd: Decimal
    capture_pct: Decimal
    avg_concurrency: Decimal
    peak_concurrency: int
    avg_hold_minutes: Decimal | None
    unsettled: int

    moonshots: tuple[MoonshotCapture, ...]
    robustness: Robustness
    rug_impact: RugImpact

    #: Share of trades opened on the busiest single UTC day. Published beside
    #: the flag so a reader can see how concentrated, not merely that it is.
    day_concentration_pct: Decimal | None

    lab_score: Decimal
    score_r: Decimal
    score_d: Decimal
    score_s: Decimal
    score_p: Decimal
    flags: tuple[str, ...]

    def moonshot(self, level: Decimal) -> MoonshotCapture | None:
        return next((m for m in self.moonshots if m.level == level), None)


def profit_factor(positions: Sequence[Position]) -> Decimal | None:
    gains = sum((p.net_pnl for p in positions if p.net_pnl > 0), _ZERO)
    losses = -sum((p.net_pnl for p in positions if p.net_pnl < 0), _ZERO)
    return gains / losses if losses > 0 else None


def max_drawdown_pct(curve: Sequence[tuple[datetime, Decimal]], start: Decimal) -> Decimal:
    peak = start
    worst = _ZERO
    for _, equity in curve:
        peak = max(peak, equity)
        if peak > 0:
            worst = max(worst, (peak - equity) / peak * 100)
    return worst


def robustness(result: Result) -> Robustness:
    """§24, computed by removing trades and re-summing — not by re-simulating.

    Re-running the wallet without its best trade would change every subsequent
    entry it could afford, which measures a different strategy rather than the
    same one minus a token. Summing P&L without it answers the question actually
    asked: how much of this result is that one trade.
    """
    pnls = sorted((p.net_pnl for p in result.positions), reverse=True)
    total = sum(pnls, _ZERO)
    gross_profit = sum((x for x in pnls if x > 0), _ZERO)

    def share(k: int) -> Decimal | None:
        if gross_profit <= 0:
            return None
        return sum(pnls[:k], _ZERO) / gross_profit * 100

    ex_best_1 = total - sum(pnls[:1], _ZERO)
    return Robustness(
        normal_pnl=total,
        ex_best_1_pnl=ex_best_1,
        ex_best_3_pnl=total - sum(pnls[:3], _ZERO),
        ex_worst_1_pnl=total - sum(pnls[-1:], _ZERO),
        ex_worst_3_pnl=total - sum(pnls[-3:], _ZERO),
        top_1_share_pct=share(1),
        top_3_share_pct=share(3),
        top_5_share_pct=share(5),
        outlier_dependent=total > 0 and ex_best_1 <= 0,
    )


def moonshot_capture(result: Result, level: Decimal) -> MoonshotCapture:
    cohort = [p for p in result.positions if p.executable_peak_multiple >= level]
    opportunity = sum((p.size_usd * p.executable_peak_multiple for p in cohort), _ZERO)
    realised = sum((p.net_proceeds for p in cohort), _ZERO)
    captured = sum(1 for p in cohort if p.net_proceeds >= p.size_usd * level)
    return MoonshotCapture(
        level=level,
        reached=len(cohort),
        captured=captured,
        opportunity_usd=opportunity,
        realised_usd=realised,
    )


def rug_impact(result: Result) -> RugImpact:
    rugs = [p for p in result.positions if p.is_catastrophic]
    invested = sum((p.size_usd for p in rugs), _ZERO)
    banked = sum((p.banked_before_final for p in rugs), _ZERO)
    residual = sum(
        (
            net
            for p in rugs
            for f, net, _ in p.fills[-1:]
            if f.reason not in NON_EXECUTABLE_REASONS
        ),
        _ZERO,
    )

    def reached(level: str) -> int:
        return sum(1 for p in rugs if p.executable_peak_multiple >= Decimal(level))

    return RugImpact(
        count=len(rugs),
        capital_invested=invested,
        capital_recovered_before=banked,
        residual_recovered=residual,
        net_loss=sum((p.net_pnl for p in rugs), _ZERO),
        reached_125=reached("1.25"),
        reached_150=reached("1.50"),
        reached_175=reached("1.75"),
        reached_200=reached("2.00"),
    )


def _score(
    robust_return_pct: Decimal, drawdown_pct: Decimal, n: int, pf: Decimal | None
) -> tuple[Decimal, Decimal, Decimal, Decimal, Decimal]:
    r = robust_return_pct
    d = drawdown_pct / 100
    s = min(_ONE, Decimal(n) / Decimal(FULL_CONFIDENCE_N))
    clamped = _ONE if pf is None else max(Decimal("0.5"), min(Decimal(2), pf))
    # Inverted below zero so a bad profit factor always makes a losing strategy
    # rank worse rather than better.
    p = clamped if r > 0 else _ONE / clamped
    return (r / (_ONE + d)) * s * p, r, d, s, p


def day_concentration_pct(positions: Sequence[Position]) -> Decimal | None:
    """Share of trades opened on the single busiest UTC day."""
    if not positions:
        return None
    by_day: dict[str, int] = {}
    for position in positions:
        key = position.opened_at.date().isoformat()
        by_day[key] = by_day.get(key, 0) + 1
    return Decimal(max(by_day.values())) / Decimal(len(positions)) * 100


def row(result: Result, *, name: str, benchmark: bool) -> Row:
    positions = result.positions
    n = len(positions)
    returns = [p.return_pct for p in positions]
    wins = [p for p in positions if p.net_pnl > 0]
    rob = robustness(result)
    dd = max_drawdown_pct(result.equity_curve, result.starting_capital)
    impact = rug_impact(result)

    robust_return_pct = rob.ex_best_1_pnl / result.starting_capital * 100
    pf = profit_factor(positions)
    score, r, d, s, p = _score(robust_return_pct, dd, n, pf)

    flags: list[str] = []
    if n < SMALL_SAMPLE_N:
        flags.append(Flag.SMALL_SAMPLE)
    if n == 0:
        flags.append(Flag.INSUFFICIENT_EVIDENCE)
    if rob.top_1_share_pct is not None and rob.top_1_share_pct >= 50:
        flags.append(Flag.OUTLIER_DOMINATED)
    if rob.outlier_dependent:
        flags.append(Flag.OUTLIER_DEPENDENT)
    concentration = day_concentration_pct(positions)
    if concentration is not None and concentration >= REGIME_CONCENTRATION_PCT:
        flags.append(Flag.REGIME_CONCENTRATED)
    unsettled = sum(1 for x in positions if x.unsettled)
    if unsettled:
        flags.append(Flag.UNSETTLED_POSITIONS)

    hold = result.avg_hold
    return Row(
        strategy_id=result.strategy_id,
        version=result.version,
        name=name,
        definition_hash=result.definition_hash,
        benchmark=benchmark,
        n=n,
        offered=result.offered,
        starting_capital=result.starting_capital,
        final_equity=result.final_equity,
        net_pnl=result.net_pnl,
        gross_pnl=result.gross_pnl,
        total_costs=result.total_costs,
        wallet_return_pct=result.wallet_return_pct,
        profit_factor=pf,
        expectancy=(sum((x.net_pnl for x in positions), _ZERO) / n if n else None),
        win_rate_pct=(Decimal(len(wins)) / Decimal(n) * 100 if n else None),
        median_trade_return_pct=(
            Decimal(str(statistics.median([float(x) for x in returns]))) if returns else None
        ),
        mean_trade_return_pct=(sum(returns, _ZERO) / n if n else None),
        max_drawdown_pct=dd,
        rug_loss_usd=-impact.net_loss,
        rugs=impact.count,
        blocked=result.blocked,
        blocked_for_cash=result.blocked_for_cash,
        capital_blocked_usd=Decimal(result.blocked_for_cash) * result.entry_size_usd,
        capture_pct=result.capture_pct,
        avg_concurrency=result.avg_concurrency,
        peak_concurrency=result.peak_concurrent,
        avg_hold_minutes=(
            Decimal(str(round(hold.total_seconds() / 60, 2))) if hold is not None else None
        ),
        unsettled=unsettled,
        day_concentration_pct=concentration,
        moonshots=tuple(moonshot_capture(result, level) for level in MOONSHOT_LEVELS),
        robustness=rob,
        rug_impact=impact,
        lab_score=score,
        score_r=r,
        score_d=d,
        score_s=s,
        score_p=p,
        flags=tuple(flags),
    )


def rank(rows: Sequence[Row]) -> list[Row]:
    """Highest `lab_score` first. Benchmarks are ranked in, never hidden."""
    return sorted(rows, key=lambda x: x.lab_score, reverse=True)


# ── Bootstrap confidence, for the comparisons that carry a conclusion ───────


def bootstrap_mean_ci(
    values: Sequence[Decimal], *, iterations: int = 2000, seed: int = 20260822
) -> tuple[Decimal, Decimal] | None:
    """A 95% percentile interval for mean trade P&L. Deterministic.

    Seeded from a fixed constant so the same result set produces the same
    interval on every run — an interval that moved between page loads would
    invite reading the movement as information.
    """
    if len(values) < 10:
        return None
    import random

    # Reproducibility, not secrecy: a seeded PRNG is the point.
    rng = random.Random(seed)  # noqa: S311
    floats = [float(v) for v in values]
    size = len(floats)
    means = sorted(sum(rng.choices(floats, k=size)) / size for _ in range(iterations))
    lo = means[int(0.025 * iterations)]
    hi = means[int(0.975 * iterations) - 1]
    return Decimal(str(round(lo, 4))), Decimal(str(round(hi, 4)))


# ── Market regime, §16 ──────────────────────────────────────────────────────

#: Bumped when the partition changes. Versioned because a regime label that
#: silently changed meaning would restate every comparison drawn on it.
REGIME_VERSION = "1.0.0"

REGIME_DEFINITION = (
    "Each UTC day is labelled by two deterministic splits against the dataset's "
    "own medians: discovery volume (canonical opportunities that day, HIGH or "
    "LOW vs median) and catastrophe rate (share of that day's opportunities "
    "whose executable path ended in a non-executable pool or below -90%, HIGH "
    "or LOW vs median). These are POST-HOC DESCRIPTIVE PARTITIONS of a finished "
    "dataset. They are not signals, they are not available at entry time, and "
    "no strategy reads them."
)


@dataclass(frozen=True, slots=True)
class DayRegime:
    day: str
    opportunities: int
    catastrophe_rate_pct: Decimal
    volume_label: str
    rug_label: str

    @property
    def label(self) -> str:
        return f"{self.volume_label}_VOLUME/{self.rug_label}_RUG"


def regimes(reference: Result) -> list[DayRegime]:
    """Day labels derived from one reference strategy's outcomes.

    One reference rather than a blend: the partition must not depend on which
    strategies happen to be in the comparison. The control (S5, pure hold) is
    the right reference because it takes every opportunity it can fund and
    applies no exit logic, so its catastrophe count is the market's, not a
    strategy's.
    """
    by_day: dict[str, list[Position]] = {}
    for position in reference.positions:
        by_day.setdefault(position.opened_at.date().isoformat(), []).append(position)
    if not by_day:
        return []

    counts = sorted(len(v) for v in by_day.values())
    rates = sorted(
        Decimal(sum(1 for p in v if p.is_catastrophic)) / Decimal(len(v)) * 100
        for v in by_day.values()
    )
    median_count = counts[len(counts) // 2]
    median_rate = rates[len(rates) // 2]

    out: list[DayRegime] = []
    for day in sorted(by_day):
        group = by_day[day]
        rate = Decimal(sum(1 for p in group if p.is_catastrophic)) / Decimal(len(group)) * 100
        out.append(
            DayRegime(
                day=day,
                opportunities=len(group),
                catastrophe_rate_pct=rate,
                volume_label="HIGH" if len(group) >= median_count else "LOW",
                rug_label="HIGH" if rate >= median_rate else "LOW",
            )
        )
    return out


@dataclass
class DailyPnl:
    day: str
    pnl: Decimal
    trades: int


def daily_pnl(result: Result) -> list[DailyPnl]:
    """P&L attributed to the day a position **closed**, not the day it opened."""
    by_day: dict[str, DailyPnl] = {}
    for position in result.positions:
        closed = position.closed_at or position.opened_at
        day = closed.date().isoformat()
        entry = by_day.setdefault(day, DailyPnl(day=day, pnl=_ZERO, trades=0))
        entry.pnl += position.net_pnl
        entry.trades += 1
    return [by_day[d] for d in sorted(by_day)]
