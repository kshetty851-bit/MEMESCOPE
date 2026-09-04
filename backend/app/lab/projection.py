"""Where a strategy's next thirty days land, as a DISTRIBUTION.

A single projected return would be a lie of precision. This resamples the
strategy's own closed trades and reports the spread, because on a book whose
losses are total and whose wins are capped, the spread is the whole story: the
median and the mean of the same thirty days can sit on opposite sides of zero.

## Method

Bootstrap. Draw N trades with replacement from the ones this strategy has
actually closed, where N is its observed trade rate carried forward thirty
days, and add their P&L to today's equity. Repeat, and report percentiles.

Additive, not compounded. The Lab holds position size fixed, so a strategy that
doubles its book does not double its stake until the growth ladder's first rung
at 2x — far outside any projection this will produce. Compounding here would
invent returns the mechanics do not deliver.

## What it deliberately refuses to do

**It will not project below `MIN_TRADES`.** V6-07 looked like a 3.0 profit
factor on 23 trades and ended at -25%; the number that would have been printed
beside it was the most dangerous thing this page could have said. Under the
threshold it returns `projectable=False` and the reason, and the caller must
render that rather than a figure.

**It always projects the RANDOM CONTROL too.** A strategy's projection means
nothing on its own — the question is never "will this make money" but "does it
beat blind entry from the same pool". If the control's band overlaps the
strategy's, the strategy has shown nothing, and the reader is entitled to see
that in the same breath rather than in a different part of the page.

**It assumes the next thirty days resemble the last few.** They will not. Every
V6 strategy peaked above its start and eighteen of twenty then died; a
projection taken at that peak would have pointed the wrong way with total
confidence. This is arithmetic on a sample, not a forecast, and the wording it
returns says so.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal

#: Closed trades below which no projection is offered at all.
#:
#: 50 is the Lab's own "EARLY" confidence band. Its 100-trade band is only
#: called "PRELIMINARY", so even a projection that clears this bar is being made
#: on a sample the platform itself does not call substantial.
MIN_TRADES = 50

#: Resamples. Enough that the reported percentiles are stable to about a
#: hundredth; more buys precision the input does not have.
DRAWS = 2000

HORIZON_DAYS = 30


@dataclass(frozen=True, slots=True)
class Projection:
    projectable: bool
    reason: str = ""
    trades_observed: int = 0
    trades_per_day: float = 0.0
    projected_trades: int = 0
    #: Equity percentiles across the resamples.
    p10: Decimal | None = None
    p50: Decimal | None = None
    p90: Decimal | None = None
    #: Fraction of resampled thirty-day paths ending above today's equity.
    p_profit: float | None = None
    #: Fraction ending below the failure floor.
    p_ruin: float | None = None
    notes: tuple[str, ...] = field(default_factory=tuple)

    def as_dict(self) -> dict[str, object]:
        return {
            "projectable": self.projectable,
            "reason": self.reason,
            "trades_observed": self.trades_observed,
            "trades_per_day": round(self.trades_per_day, 2),
            "projected_trades": self.projected_trades,
            "horizon_days": HORIZON_DAYS,
            "p10": str(self.p10) if self.p10 is not None else None,
            "p50": str(self.p50) if self.p50 is not None else None,
            "p90": str(self.p90) if self.p90 is not None else None,
            "p_profit": self.p_profit,
            "p_ruin": self.p_ruin,
            "notes": list(self.notes),
        }


def project(
    *,
    pnls: list[Decimal],
    equity_now: Decimal,
    first_trade_at: datetime | None,
    now: datetime,
    failure_floor: Decimal,
    seed: int = 0,
) -> Projection:
    """Thirty days of this strategy's own trades, resampled.

    `seed` is fixed by default so the same book yields the same band on every
    request. A projection that flickered between page loads would invite
    refreshing until it looked good.
    """
    n = len(pnls)
    if n < MIN_TRADES:
        return Projection(
            projectable=False,
            reason=(f"{n} closed trades. No projection is offered below "
                    f"{MIN_TRADES} — a profit factor measured on a handful of "
                    "trades has already pointed the wrong way here."),
            trades_observed=n,
        )
    if first_trade_at is None:
        return Projection(projectable=False, reason="No trade history to date.",
                          trades_observed=n)

    days = max((now - first_trade_at).total_seconds() / 86400, 0.5)
    rate = n / days
    projected = max(int(round(rate * HORIZON_DAYS)), 1)

    rng = random.Random(seed)
    finals: list[Decimal] = []
    for _ in range(DRAWS):
        total = Decimal(0)
        for _ in range(projected):
            total += pnls[rng.randrange(n)]
        finals.append(equity_now + total)
    finals.sort()

    def pct(p: float) -> Decimal:
        return finals[min(int(p * len(finals)), len(finals) - 1)]

    return Projection(
        projectable=True,
        trades_observed=n,
        trades_per_day=rate,
        projected_trades=projected,
        p10=pct(0.10), p50=pct(0.50), p90=pct(0.90),
        p_profit=round(sum(1 for f in finals if f > equity_now) / len(finals), 3),
        p_ruin=round(sum(1 for f in finals if f < failure_floor) / len(finals), 3),
        notes=(
            f"Resampled from this strategy's own {n} closed trades at its "
            f"observed rate of {rate:.1f}/day.",
            "Arithmetic on a sample, not a forecast: it assumes the next thirty "
            "days resemble the last few, and in V6 they did not — eighteen of "
            "twenty strategies peaked above their start and then died.",
            "Compare the band against the random control before reading "
            "anything into it.",
        ),
    )


__all__ = ["DRAWS", "HORIZON_DAYS", "MIN_TRADES", "Projection", "project"]
