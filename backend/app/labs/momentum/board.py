"""The scoreboard: each strategy's trades turned into a $1,000 wallet. Pure.

## Two different questions, kept apart

* **Is the RULE any good?** Every trade it took, each at the $100 it was
  measured at: mean return, win rate, and the gap to its yardstick. Nothing
  here depends on which trades a wallet happened to have cash for.
* **What would a $1,000 wallet have made?** The same trades walked in the
  order they opened, cut into a split — 1 x $1,000, 2 x $500, 5 x $200,
  10 x $100 or 20 x $50. A wallet with every ticket in use SKIPS the next
  signal; a bigger ticket pays proportionally more impact.

## Chance, measured between hours

Trades inside one hour are one market, not independent draws, so the error
of a mean is measured between hourly averages. A per-trade error would treat
two hundred fills of one rally as two hundred pieces of evidence.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from math import sqrt
from statistics import fmean, median, pstdev

from app.labs.momentum import config


@dataclass(frozen=True, slots=True)
class Trade:
    opened_at: datetime
    closed_at: datetime
    #: Net of every cost, at `TICKET_USD`.
    ret: float
    impact_open: float = 0.0
    impact_close: float = 0.0


@dataclass(frozen=True, slots=True)
class Walk:
    split: int
    ticket: float
    end: float
    low: float
    funded: int
    skipped: int


def multiple(t: Trade, k: float) -> float:
    """What one dollar became, at `k` times the size the trade was measured
    at. Impact is linear in order size, so both legs move `k` times as far."""
    out = 1.0 + t.ret
    if k != 1.0:
        out *= ((1 + t.impact_open) / (1 + k * t.impact_open)
                * (1 + t.impact_close) / (1 + k * t.impact_close))
    return out


def walk(trades: Sequence[Trade], split: int, *,
         start: float = float(config.START_USD),
         measured: float = float(config.TICKET_USD)) -> Walk:
    """A `start` wallet cut into `split` tickets, taking these trades in the
    order they opened while it has a ticket free."""
    ticket = start / split
    cash, low = start, start
    held: list[tuple[datetime, float, float]] = []  # (closes, multiple, stake)
    funded = skipped = 0

    def release(until: datetime | None) -> None:
        nonlocal cash, low, held
        due = sorted((h for h in held if until is None or h[0] <= until),
                     key=lambda h: h[0])
        held = [h for h in held if not (until is None or h[0] <= until)]
        equity = cash + sum(h[2] for h in held) + sum(h[2] for h in due)
        for _, m, stake in due:
            cash += stake * m
            equity += stake * (m - 1)
            low = min(low, equity)

    for t in sorted(trades, key=lambda t: t.opened_at):
        release(t.opened_at)
        if cash < ticket * config.MIN_STAKE_FRACTION:
            skipped += 1
            continue
        stake = min(cash, ticket)
        cash -= stake
        held.append((t.closed_at, multiple(t, stake / measured), stake))
        funded += 1
    release(None)
    return Walk(split, ticket, cash, low, funded, skipped)


@dataclass(frozen=True, slots=True)
class Stats:
    n: int
    wins: int
    mean: float | None
    median: float | None
    #: Standard error of the mean, between entry-hours.
    se: float | None
    hours: int
    pf: float | None
    best: float | None
    worst: float | None


def stats(trades: Sequence[Trade]) -> Stats:
    rets = [t.ret for t in trades]
    if not rets:
        return Stats(0, 0, None, None, None, 0, None, None, None)
    by_hour: dict[datetime, list[float]] = defaultdict(list)
    for t in trades:
        by_hour[t.opened_at.replace(minute=0, second=0, microsecond=0)].append(t.ret)
    means = [fmean(v) for v in by_hour.values()]
    se = pstdev(means) / sqrt(len(means)) if len(means) > 1 else None
    up = sum(r for r in rets if r > 0)
    down = -sum(r for r in rets if r < 0)
    return Stats(n=len(rets), wins=sum(1 for r in rets if r > 0), mean=fmean(rets),
                 median=median(rets), se=se, hours=len(means),
                 pf=up / down if down > 0 else None,
                 best=max(rets), worst=min(rets))


#: Fifty comparisons: at z > 2 one or two pass by luck alone. Three is the bar.
Z_BAR = 3.0
MIN_TRADES = 30


def versus(a: Stats, b: Stats) -> float | None:
    """How many standard errors `a`'s mean sits above `b`'s."""
    if a.mean is None or b.mean is None or a.se is None or b.se is None:
        return None
    spread = sqrt(a.se ** 2 + b.se ** 2)
    return (a.mean - b.mean) / spread if spread > 0 else None


def verdict(a: Stats, z: float | None, vs: str | None, *, is_control: bool) -> str:
    """One line, in words, that never claims more than the numbers do."""
    if a.n < MIN_TRADES:
        return f"waiting: {a.n} of {MIN_TRADES} trades"
    alone = (a.mean or 0) / a.se if a.se else None
    if is_control:
        return "control: a random rule, no edge possible"
    if z is None or vs is None:
        return "no yardstick yet"
    if z >= Z_BAR and alone is not None and alone >= 2:
        return f"beats {vs} and makes money"
    if z >= Z_BAR:
        return f"beats {vs}, profit not proven yet"
    if z <= -Z_BAR:
        return f"worse than {vs}"
    return f"no different from {vs} yet"
