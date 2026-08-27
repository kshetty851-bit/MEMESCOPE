"""Chronological splits and walk-forward folds. **The anti-overfit machinery.**

§11 calls this the most important requirement, and it is the part of a search
engine that is easiest to get subtly, invisibly wrong. Three rules are enforced
here rather than remembered:

  1. **Chronological, never random.** A random split leaks the future into the
     past through market regime: two tokens from the same hour are not
     independent observations.
  2. **No boundary splits a group.** The split point is snapped to a calendar
     boundary, so no single day — or, when days are unavailable, no single
     hour — has its tokens spread across discovery and holdout.
  3. **The holdout is untouchable.** It is a separate object that the discovery
     and validation code paths never receive. `Split.holdout` is not reachable
     from `Split.for_selection()`, which is what selection is given.

── THE GRANULARITY IS CHOSEN, AND REPORTED ──────────────────────────────────

§11 prefers day boundaries and says so; it also says calendar boundaries matter
more than exact percentages, and that a short history should use walk-forward
rather than pretend to have a holdout. `diagnose` decides which case applies and
records it, so a reader is never left to assume the split was better than the
data allowed. On the current set it will report HOUR granularity and a warning:
the Radar's decision audit covers three calendar days, one of which carries
over 90% of the opportunities.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.strategy_lab.opportunities import Opportunity

#: Below this many calendar days with a meaningful share of the sample, a
#: day-boundary split cannot produce three independent blocks and the engine
#: falls back to hours — loudly.
MIN_DAYS_FOR_DAY_SPLIT = 6

#: A day must hold at least this share of the sample to count as usable
#: independent evidence rather than a fragment.
MIN_DAY_SHARE_PCT = 5.0

#: Default proportions. §11's 50/25/25.
DISCOVERY_SHARE = 0.50
VALIDATION_SHARE = 0.25


class Granularity:
    DAY = "DAY"
    HOUR = "HOUR"


@dataclass(frozen=True, slots=True)
class Diagnosis:
    """What the data actually supports, stated before any split is used."""

    total: int
    calendar_days: int
    substantial_days: int
    largest_day_share_pct: float
    granularity: str
    warnings: tuple[str, ...]

    @property
    def day_split_possible(self) -> bool:
        return self.granularity == Granularity.DAY


def diagnose(opportunities: Sequence[Opportunity]) -> Diagnosis:
    """Decide the split granularity from the sample, and say why."""
    if not opportunities:
        return Diagnosis(0, 0, 0, 0.0, Granularity.HOUR, ("no opportunities",))

    by_day: dict[str, int] = {}
    for o in opportunities:
        key = o.eligible_at.date().isoformat()
        by_day[key] = by_day.get(key, 0) + 1

    total = len(opportunities)
    shares = {d: n / total * 100 for d, n in by_day.items()}
    substantial = sum(1 for pct in shares.values() if pct >= MIN_DAY_SHARE_PCT)
    largest = max(shares.values())

    warnings: list[str] = []
    granularity = Granularity.DAY
    if substantial < MIN_DAYS_FOR_DAY_SPLIT:
        granularity = Granularity.HOUR
        warnings.append(
            f"only {substantial} calendar day(s) carry >= {MIN_DAY_SHARE_PCT:g}% of the "
            f"sample, against the {MIN_DAYS_FOR_DAY_SPLIT} needed for a day-boundary "
            f"split; falling back to HOUR boundaries"
        )
    if largest >= 60:
        warnings.append(
            f"one calendar day carries {largest:.0f}% of the sample — the split "
            f"separates hours within a regime, NOT independent market regimes"
        )
    return Diagnosis(
        total=total,
        calendar_days=len(by_day),
        substantial_days=substantial,
        largest_day_share_pct=largest,
        granularity=granularity,
        warnings=tuple(warnings),
    )


def _bucket(at: datetime, granularity: str) -> datetime:
    if granularity == Granularity.DAY:
        return at.replace(hour=0, minute=0, second=0, microsecond=0)
    return at.replace(minute=0, second=0, microsecond=0)


@dataclass
class Split:
    """Three chronological blocks. The holdout is deliberately awkward to reach."""

    diagnosis: Diagnosis
    granularity: str
    discovery: list[Opportunity]
    validation: list[Opportunity]
    #: **Sacred.** Read exactly once, after candidate selection is frozen.
    holdout: list[Opportunity]
    discovery_to: datetime | None
    validation_to: datetime | None

    def for_selection(self) -> tuple[list[Opportunity], list[Opportunity]]:
        """Everything selection is allowed to see. The holdout is not in it.

        Returned as a pair rather than exposing `self` so a caller that only
        ever calls this cannot reach the holdout by accident — and so a reviewer
        can see, from the call site alone, that it did not.
        """
        return self.discovery, self.validation

    def sizes(self) -> dict[str, int]:
        return {
            "discovery": len(self.discovery),
            "validation": len(self.validation),
            "holdout": len(self.holdout),
        }

    def bounds(self) -> dict[str, Any]:
        def span(rows: Sequence[Opportunity]) -> dict[str, str | None]:
            if not rows:
                return {"from": None, "to": None}
            return {
                "from": min(o.eligible_at for o in rows).isoformat(),
                "to": max(o.eligible_at for o in rows).isoformat(),
            }

        return {
            "granularity": self.granularity,
            "discovery": span(self.discovery),
            "validation": span(self.validation),
            "holdout": span(self.holdout),
        }


def chronological(
    opportunities: Sequence[Opportunity],
    *,
    discovery_share: float = DISCOVERY_SHARE,
    validation_share: float = VALIDATION_SHARE,
) -> Split:
    """Split in time, snapping the cuts to calendar boundaries.

    The shares are targets, not guarantees: the cut moves to the nearest
    boundary that does not divide a bucket, so a block may end up larger or
    smaller than asked. §11 is explicit that boundaries matter more than exact
    percentages, and a split that severed a day would leak that day's regime
    into every block that received a piece of it.
    """
    ordered = sorted(opportunities, key=lambda o: o.eligible_at)
    diagnosis = diagnose(ordered)
    granularity = diagnosis.granularity
    if not ordered:
        return Split(diagnosis, granularity, [], [], [], None, None)

    buckets: list[datetime] = []
    for o in ordered:
        bucket = _bucket(o.eligible_at, granularity)
        if not buckets or buckets[-1] != bucket:
            buckets.append(bucket)

    counts = dict.fromkeys(buckets, 0)
    for o in ordered:
        counts[_bucket(o.eligible_at, granularity)] += 1

    total = len(ordered)
    discovery_target = total * discovery_share
    validation_target = total * (discovery_share + validation_share)

    running = 0
    discovery_cut: datetime | None = None
    validation_cut: datetime | None = None
    for bucket in buckets:
        running += counts[bucket]
        if discovery_cut is None and running >= discovery_target:
            discovery_cut = bucket
            continue
        if (
            discovery_cut is not None
            and validation_cut is None
            and running >= validation_target
        ):
            validation_cut = bucket

    # Degenerate inputs (one bucket, or a bucket holding most of the sample)
    # can leave a cut unset. Falling back to the last bucket keeps the blocks
    # non-overlapping and simply makes one of them empty, which `diagnose`
    # already warned about — better than silently rebalancing.
    if discovery_cut is None:
        discovery_cut = buckets[-1]
    if validation_cut is None:
        validation_cut = buckets[-1]

    discovery = [o for o in ordered if _bucket(o.eligible_at, granularity) <= discovery_cut]
    validation = [
        o
        for o in ordered
        if discovery_cut < _bucket(o.eligible_at, granularity) <= validation_cut
    ]
    holdout = [o for o in ordered if _bucket(o.eligible_at, granularity) > validation_cut]

    return Split(
        diagnosis=diagnosis,
        granularity=granularity,
        discovery=discovery,
        validation=validation,
        holdout=holdout,
        discovery_to=discovery_cut,
        validation_to=validation_cut,
    )


@dataclass(frozen=True, slots=True)
class Fold:
    """One walk-forward step: fit on the past, measure on the next block only."""

    index: int
    train_from: datetime
    train_to: datetime
    test_from: datetime
    test_to: datetime
    train: list[Opportunity] = field(repr=False, default_factory=list)
    test: list[Opportunity] = field(repr=False, default_factory=list)

    @property
    def label(self) -> str:
        return f"fold{self.index}: test {self.test_from:%Y-%m-%d %H:%M}"


def walk_forward(
    opportunities: Sequence[Opportunity],
    *,
    train_buckets: int = 5,
    step: int = 1,
    granularity: str | None = None,
) -> list[Fold]:
    """Rolling train/test blocks in time order. §12.

    The definitions under test are predetermined, so nothing is *fitted* on the
    training block — it exists to establish that the test block is strictly
    later, and to give the search the same shape it would need if a future
    strategy family did fit parameters. What is aggregated is the **test**
    blocks only, and they never overlap.
    """
    ordered = sorted(opportunities, key=lambda o: o.eligible_at)
    if not ordered:
        return []
    granularity = granularity or diagnose(ordered).granularity

    grouped: dict[datetime, list[Opportunity]] = {}
    for o in ordered:
        grouped.setdefault(_bucket(o.eligible_at, granularity), []).append(o)
    buckets = sorted(grouped)
    if len(buckets) <= train_buckets:
        return []

    folds: list[Fold] = []
    index = 0
    start = 0
    while start + train_buckets < len(buckets):
        train_slice = buckets[start : start + train_buckets]
        test_slice = buckets[start + train_buckets : start + train_buckets + step]
        if not test_slice:
            break
        index += 1
        train = [o for b in train_slice for o in grouped[b]]
        test = [o for b in test_slice for o in grouped[b]]
        folds.append(
            Fold(
                index=index,
                train_from=train_slice[0],
                train_to=train_slice[-1],
                test_from=test_slice[0],
                test_to=test_slice[-1],
                train=train,
                test=test,
            )
        )
        start += step
    return folds
