"""The frozen dataset layer. `RESEARCH_ONLY`, and strictly READ-ONLY.

Reads `grad_tokens` and `grad_curve_samples` — the graduation lab's tables, the
only place on this platform where bonding-curve progress exists as a series.
Nothing here writes to them, and this lab owns no collector: if the graduation
lab stops, this lab reports a shorter dataset rather than a wrong one.

## Why the dataset is frozen before anything looks at it

`load()` snapshots the archive at one instant and hands back an immutable
object. Every downstream stage — entries, controls, folds, statistics — reads
that one snapshot. Two stages reading the database independently could see
different data (the collector is still running) and produce a result that no
single state of the world supports.

`dataset_version` is a digest of the actual rows loaded, not of the query. A
re-run that returns the same rows produces the same version and must produce
the same result; a re-run an hour later produces a different version, and the
difference is visible rather than silent.

## A gap in the series means NO ACTIVITY, not no coverage

`grad_curve_samples` is written on CHANGE only (`SAMPLE_ON_CHANGE_ONLY`). A
minute without a row is a minute in which nobody traded, so the price was flat
across it — it is not a minute the collector missed. Every consumer here must
therefore FORWARD-FILL: the last observation stands until the next one
contradicts it. Reading the raw rows as if they were a regular time series
makes a dead token look like a token with no data, and the two have opposite
meanings for an exit rule.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.labs.graduation.models import GradCurveSample, GradToken


@dataclass(frozen=True, slots=True)
class Sample:
    """One curve observation, as recorded. `OBSERVED` throughout."""

    ts: datetime
    progress_pct: Decimal | None
    mcap_quote: Decimal | None
    v_quote: Decimal | None
    v_token: Decimal | None
    complete: bool

    @property
    def price(self) -> Decimal | None:
        """The curve mid, in quote per whole token.

        `None` rather than zero when the reserves cannot express a price: a
        completed curve zeroes its reserves, and a zero here would be read
        downstream as a -100% return on a token that merely migrated.
        """
        if self.v_quote is None or not self.v_token:
            return None
        return self.v_quote / self.v_token


@dataclass(frozen=True, slots=True)
class Token:
    """One mint, with its full observed curve series in time order."""

    mint: str
    first_seen_at: datetime
    samples: tuple[Sample, ...]
    #: Set when the collector stopped polling, and why. This is the field that
    #: decides whether a censored trade was censored for a reason correlated
    #: with its outcome — see `quality.censoring_report`.
    unsubscribe_reason: str | None
    pruned: bool
    migrated_at: datetime | None

    @property
    def graduated(self) -> bool:
        return self.migrated_at is not None or any(s.complete for s in self.samples)

    def at(self, when: datetime) -> Sample | None:
        """The state in force at `when`, FORWARD-FILLED.

        The last sample at or before `when`. Not the nearest, and never one
        after it: a sample later than the decision instant is information the
        decision could not have had.
        """
        found = None
        for s in self.samples:
            if s.ts > when:
                break
            found = s
        return found

    def window(self, start: datetime, end: datetime) -> tuple[Sample, ...]:
        """Samples strictly after `start` and at or before `end`."""
        return tuple(s for s in self.samples if start < s.ts <= end)

    def last_observed_at(self) -> datetime | None:
        return self.samples[-1].ts if self.samples else None


@dataclass(frozen=True, slots=True)
class Dataset:
    """An immutable snapshot of the archive."""

    tokens: tuple[Token, ...]
    loaded_at: datetime
    window_start: datetime
    window_end: datetime
    dataset_version: str

    @property
    def span_hours(self) -> float:
        return (self.window_end - self.window_start).total_seconds() / 3600.0

    def by_mint(self) -> dict[str, Token]:
        return {t.mint: t for t in self.tokens}


async def load(
    session: AsyncSession,
    *,
    now: datetime,
    lookback_hours: int = 24 * 14,
    settle_minutes: int = 45,
) -> Dataset:
    """Snapshot every token whose outcome window has had time to close.

    `settle_minutes` excludes tokens too recent for a 30-minute trade to have
    finished. Including them would count every one of them as censored and
    understate resolution for a reason that is purely the clock.

    Pruned tokens are loaded and FLAGGED, not dropped. Their curve series is
    gone, so they cannot produce a trade — but they are the population the
    24-hour pruner removed, and `quality` has to be able to count them to say
    how much of the archive is survivorship-shaped.
    """
    window_start = now - timedelta(hours=lookback_hours)
    window_end = now - timedelta(minutes=settle_minutes)

    rows = (await session.execute(
        select(GradToken.mint, GradToken.first_seen_at, GradToken.unsubscribe_reason,
               GradToken.pruned_at, GradToken.migrated_at)
        .where(GradToken.first_seen_at >= window_start,
               GradToken.first_seen_at <= window_end)
        .order_by(GradToken.first_seen_at)
    )).all()
    if not rows:
        return Dataset((), now, window_start, window_end, "empty")

    mints = [r.mint for r in rows]
    samples: dict[str, list[Sample]] = {m: [] for m in mints}

    # Chunked: `IN` with tens of thousands of parameters is a query plan nobody
    # wants to debug at 3am, and the chunk size is well under any driver limit.
    for i in range(0, len(mints), 5_000):
        chunk = mints[i:i + 5_000]
        srows = (await session.execute(
            select(GradCurveSample.mint, GradCurveSample.ts,
                   GradCurveSample.progress_pct, GradCurveSample.market_cap_quote,
                   GradCurveSample.v_quote_reserves, GradCurveSample.v_token_reserves,
                   GradCurveSample.complete)
            .where(GradCurveSample.mint.in_(chunk))
            .order_by(GradCurveSample.mint, GradCurveSample.ts)
        )).all()
        for s in srows:
            samples[s.mint].append(Sample(
                ts=s.ts, progress_pct=s.progress_pct, mcap_quote=s.market_cap_quote,
                v_quote=s.v_quote_reserves, v_token=s.v_token_reserves,
                complete=s.complete,
            ))

    tokens = tuple(
        Token(mint=r.mint, first_seen_at=r.first_seen_at,
              samples=tuple(samples[r.mint]),
              unsubscribe_reason=r.unsubscribe_reason,
              pruned=r.pruned_at is not None,
              migrated_at=r.migrated_at)
        for r in rows
    )

    # The digest covers the rows, not the query: it is the identity of the DATA.
    h = hashlib.sha256()
    for t in tokens:
        h.update(t.mint.encode())
        h.update(str(len(t.samples)).encode())
        if t.samples:
            h.update(str(t.samples[-1].ts.timestamp()).encode())
    return Dataset(tokens, now, window_start, window_end, h.hexdigest()[:16])
