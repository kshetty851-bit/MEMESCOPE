"""Judging the entry-filter A/B. Read-only, and it will not answer early.

The experiment is two paper books over the SAME graduations: `F01_all_2m`
takes every one, `F14_symnight_2m` takes only those whose symbol has been used
before and whose pool opened between 18:00 and 06:00 UTC. Nothing here writes
a row or touches either book.

## Why the excluded set is the endpoint

The filtered book is a strict subset of the control, so the two differ by
exactly one thing: the graduations the filter refused. Comparing book totals
measures that difference *plus* the noise of every trade the two share, and
that noise is most of the variance. Measuring the refused set measures only the
difference.

Stated as a question the data can answer: **were the trades the filter threw
away, together, losers?** If they were not, the filter cost money.

## Why a random filter is the bar

Discarding 54% of a book improves that book about half the time by luck alone.
So the real filter is compared against random filters of the same selectivity,
drawn from the same control book. Beating the book's own average is not
evidence; beating 95% of equally selective random discards is.

This is the term that has killed the most findings on this platform, and it is
the one most easily left out, because a filter that "looks like it helped" has
usually only discarded trades from a losing distribution.

## Why the admitted set must stand on its own

Track Record V2 cut its catastrophe rate from 26.7-90% to 1.4% and still scored
PF 0.54. Removing disasters from a book that loses anyway produces a smaller
loss, not an edge. So the survivors are checked separately, and a filter that
only shrinks a loss is reported as exactly that.
"""

from __future__ import annotations

import random
import statistics
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.labs.graduation import config
from app.labs.graduation.models import GradPaperPosition

CONTROL, FILTERED = config.PAPER_BOOKS


@dataclass(frozen=True, slots=True)
class Check:
    """One pre-registered term, and whether the data met it."""

    name: str
    passed: bool
    detail: str


@dataclass(frozen=True, slots=True)
class Verdict:
    ready: bool
    adopt: bool
    checks: tuple[Check, ...]
    stats: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "ready": self.ready,
            "adopt": self.adopt,
            "judge_date": config.AB_JUDGE_DATE.isoformat(),
            "checks": [
                {"name": c.name, "passed": c.passed, "detail": c.detail} for c in self.checks
            ],
            **self.stats,
        }


def _f(d: Decimal | float | None) -> float:
    return float(d) if d is not None else 0.0


async def _closed(session: AsyncSession, book: str) -> list[GradPaperPosition]:
    rows = (
        await session.execute(
            select(GradPaperPosition)
            .where(
                GradPaperPosition.book == book,
                GradPaperPosition.closed_at.is_not(None),
            )
            .order_by(GradPaperPosition.opened_at)
        )
    ).scalars()
    return list(rows)


def _null_distribution(pnls: list[float], k: int) -> list[float]:
    """Mean P&L of `k` positions drawn at random, many times over.

    Centred on the book's own mean by construction, which is the point: it is
    what "discarding this many trades" looks like when the choice carries no
    information.
    """
    # S311: a seeded null distribution, not a secret.
    rng = random.Random(config.AB_RANDOM_SEED)  # noqa: S311
    n = len(pnls)
    if k <= 0 or k > n:
        return []
    return [statistics.fmean(rng.sample(pnls, k)) for _ in range(config.AB_RANDOM_DRAWS)]


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return float("nan")
    s = sorted(values)
    i = max(0, min(len(s) - 1, round(pct / 100 * (len(s) - 1))))
    return s[i]


def judge(
    control: list[GradPaperPosition],
    filtered: list[GradPaperPosition],
    today: date | None = None,
) -> Verdict:
    """Apply the pre-registered terms. Pure — takes rows, returns a verdict."""
    today = today or datetime.now(UTC).date()
    admitted_mints = {p.mint for p in filtered}
    excluded = [p for p in control if p.mint not in admitted_mints]
    admitted = [p for p in control if p.mint in admitted_mints]

    ex_pnl = [_f(p.pnl_usd) for p in excluded]
    ad_pnl = [_f(p.pnl_usd) for p in admitted]
    all_pnl = [_f(p.pnl_usd) for p in control]

    ex_mean = statistics.fmean(ex_pnl) if ex_pnl else 0.0
    ad_mean = statistics.fmean(ad_pnl) if ad_pnl else 0.0

    # The null: random discards of the same size from the same book.
    null = _null_distribution(all_pnl, len(excluded))
    bar = _percentile(null, config.AB_RANDOM_PERCENTILE) if null else float("nan")

    # Concentration: no single mint may carry the excluded set's loss.
    by_mint: dict[str, float] = {}
    for p in excluded:
        by_mint[p.mint] = by_mint.get(p.mint, 0.0) + _f(p.pnl_usd)
    losses = {m: v for m, v in by_mint.items() if v < 0}
    total_loss = sum(losses.values())
    worst_share = max(losses.values(), key=abs) / total_loss if losses and total_loss else 0.0

    checks = (
        Check(
            "judge date reached",
            today >= config.AB_JUDGE_DATE,
            f"{today.isoformat()} vs {config.AB_JUDGE_DATE.isoformat()}",
        ),
        Check(
            "enough refused",
            len(excluded) >= config.AB_MIN_EXCLUDED,
            f"{len(excluded)} refused, need {config.AB_MIN_EXCLUDED}",
        ),
        Check(
            "enough admitted",
            len(admitted) >= config.AB_MIN_ADMITTED,
            f"{len(admitted)} admitted, need {config.AB_MIN_ADMITTED}",
        ),
        Check(
            "refused set lost money",
            ex_mean < 0,
            f"mean ${ex_mean:+.4f} per refused graduation",
        ),
        Check(
            "beats a random filter of the same selectivity",
            ex_mean < bar,
            f"${ex_mean:+.4f} vs ${bar:+.4f} (5th pct of "
            f"{len(null)} random discards of {len(excluded)})",
        ),
        Check(
            "no single token carries it",
            abs(worst_share) <= float(config.AB_MAX_TOKEN_SHARE),
            f"worst mint is {abs(worst_share):.1%} of the refused loss, "
            f"cap {float(config.AB_MAX_TOKEN_SHARE):.0%}",
        ),
        Check(
            "admitted set is positive on its own",
            ad_mean > 0,
            f"mean ${ad_mean:+.4f} per admitted graduation "
            f"(V2 cut catastrophes 26.7%->1.4% and still scored PF 0.54)",
        ),
    )

    ready = checks[0].passed and checks[1].passed and checks[2].passed
    return Verdict(
        ready=ready,
        adopt=all(c.passed for c in checks),
        checks=checks,
        stats={
            "control_book": CONTROL,
            "filtered_book": FILTERED,
            "control_closed": len(control),
            "filtered_closed": len(filtered),
            "refused": len(excluded),
            "admitted": len(admitted),
            "retention_pct": round(100 * len(admitted) / len(control), 1) if control else None,
            "refused_mean_pnl": round(ex_mean, 4),
            "refused_total_pnl": round(sum(ex_pnl), 2),
            "admitted_mean_pnl": round(ad_mean, 4),
            "admitted_total_pnl": round(sum(ad_pnl), 2),
            "control_mean_pnl": round(statistics.fmean(all_pnl), 4) if all_pnl else None,
            "random_bar_mean_pnl": round(bar, 4) if null else None,
            "random_draws": len(null),
        },
    )


async def judge_live(session: AsyncSession, today: date | None = None) -> Verdict:
    """Read both books and judge. Writes nothing."""
    return judge(
        await _closed(session, CONTROL),
        await _closed(session, FILTERED),
        today=today,
    )
