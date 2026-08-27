"""Whether the market evidence is good enough to commit new capital.

On 2026-08-21 the observation pipeline stopped for 125 minutes. The paper
wallet noticed nothing: it kept its beat, found no new quotes, closed nothing,
and would have opened a position against a price two hours old had one ranked.
When the feed came back, 62 of 106 open positions waited a further 44 minutes
for their first observation, and five positions were settled at the first price
anybody saw after the blackout — each a near-total loss whose whole move
happened inside the blind window.

Nothing in the platform measured any of that, so nothing could refuse to trade
on it. This module is that measurement, and the refusal that follows from it.

── THE ASYMMETRY THIS MODULE EXISTS TO ENFORCE ─────────────────────────────

    Evidence unreliable  →  DO NOT OPEN.       Fail closed for new risk.
    Evidence unreliable  →  KEEP EXITING.      Fail active for risk reduction.

Nothing here is reachable from any exit path, and a test asserts it. A feed
outage must never be able to stop a position reaching its trailing stop: the
exit walk resolves from the stored observation series, so an exit that could
not price today prices correctly whenever the reading arrives. Refusing to
*exit* on bad data would strand capital in exactly the position most likely to
be dying, which is the opposite of what a stop is for.

── WHY "PRICED", EVERYWHERE ────────────────────────────────────────────────

`token_enrichment_state.last_success_at` is not evidence that a price exists.
`record_result` marks a poll successful and increments `consecutive_empty` when
the provider returns nothing, so a token can be polled every fifteen seconds,
report success for days, and carry no usable price the whole time. Nine open
positions were in exactly that state when this was written, with
`consecutive_empty` past 3,200 and their newest priced observation four days
old. Every age in this module is therefore measured against the newest snapshot
**carrying a price**, never against an attempt, a success or a snapshot row.

── WHY UNPRICEABLE IS NOT STALE ────────────────────────────────────────────

94 of the 95 open Generation 5 positions have had no priced observation since
2026-08-17. Their pools are gone. A watchdog that blocked entries on "any stale
open position" would fail closed on a condition that can never clear, and the
wallet would never trade again — a safety mechanism that makes the system
useless is not a safety mechanism.

So a position that has been unpriceable for longer than any recovery could
plausibly fix is counted, named and reported, but does not hold the gate shut.
It is never silently dropped: `unpriceable` is a field on the census and the
mints are listed. A number nobody can see is the failure this module is a
response to.

── PURE, AND THE THRESHOLDS COME IN WITH THE FACTS ─────────────────────────

No clock, no database, no settings. `assess` takes measured evidence, a `now`
and an explicit `Thresholds`, exactly like every other decision module in this
package — the reproducibility of the whole simulation rests on that boundary,
and `test_paper_purity` enforces it.

The thresholds are a parameter rather than a `settings` read *inside* the
function on purpose. A pure function with a hidden global dependency is only
pure by inspection: it would still answer differently in two processes
configured differently, which is the property the boundary exists to prevent.
`PaperRepository.market_health_thresholds()` builds them at the I/O seam, which
is the one place allowed to know what the deployment is configured to do.
"""

from __future__ import annotations

import enum
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


class FeedState(enum.StrEnum):
    """How much the platform's market evidence can currently be trusted.

    Four states, because three of them need different actions. `DEGRADED` is
    the one that earns its place: it is the difference between "slower than
    promised, still usable" and "stopped", and collapsing them would either
    block entries on ordinary jitter or fail to block them on an outage.
    """

    #: The feed is producing priced observations within its promised window.
    HEALTHY = "HEALTHY"
    #: Producing, but later than promised. Entries continue — a slow feed is
    #: still evidence, and the per-candidate freshness gate is what protects
    #: an individual entry.
    DEGRADED = "DEGRADED"
    #: No priced observation recently enough to trust anything. Entries stop.
    STALE = "STALE"
    #: The feed itself is producing again, but the open book has not been
    #: re-primed: at least one managed position that *can* be priced still has
    #: no recent priced observation. Entries stay stopped until it does.
    RECOVERING = "RECOVERING"


#: The wallet-level refusal recorded when the feed, not the candidate, is what
#: stopped an entry. Deliberately shaped like `entry_policy.SECURITY_GATE_REFUSAL`
#: — one canonical aggregate code beside the detailed reason, so the dashboard's
#: refusal counts stay one flat mapping.
MARKET_HEALTH_REFUSAL = "market_data_health"


class EntryBlockReason(enum.StrEnum):
    """Why new entries are refused. Machine-readable, one per cause."""

    #: No priced observation across the whole feed recently enough.
    MARKET_DATA_STALE = "MARKET_DATA_STALE"
    #: The feed is running but not delivering what it promises, badly enough
    #: that the open book cannot be trusted to be current.
    FEED_UNHEALTHY = "FEED_UNHEALTHY"
    #: The feed recovered but managed open positions have not been re-priced.
    RECOVERY_INCOMPLETE = "RECOVERY_INCOMPLETE"
    #: A managed open position that still has a live market has gone dark.
    OPEN_POSITION_STALE = "OPEN_POSITION_STALE"


@dataclass(frozen=True, slots=True)
class PositionFreshness:
    """One managed open position and the age of its newest priced observation.

    `age_seconds` is `None` when the position has never had a priced
    observation at all. That is not the same as an old one and is not folded
    into it: a position nobody has ever priced and a position that went dark
    an hour ago fail for different reasons.
    """

    mint_address: str
    generation: int
    observed_at: datetime | None
    age_seconds: float | None

    @property
    def unobserved(self) -> bool:
        return self.age_seconds is None


@dataclass(frozen=True, slots=True)
class OpenBookCensus:
    """The watchdog's reading of the managed open book.

    "Managed" means positions the review pass actually walks — see
    `PaperRepository.open_book_freshness`. Counting books whose exits are
    switched off would report a staleness nothing is trying to fix.
    """

    total: int = 0
    fresh: int = 0
    warning: int = 0
    #: Stale **and recoverable**: the token still prices, it just has not been
    #: refreshed. These hold the entry gate shut.
    critical: int = 0
    #: No priced observation for longer than any recovery could fix. Reported,
    #: never hidden, and deliberately excluded from `critical` so a dead pool
    #: cannot block the wallet permanently.
    unpriceable: int = 0
    oldest_age_seconds: float | None = None
    refresh_p50_seconds: float | None = None
    refresh_p95_seconds: float | None = None
    critical_mints: tuple[str, ...] = ()
    unpriceable_mints: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "open_positions_total": self.total,
            "open_positions_fresh": self.fresh,
            "open_positions_warning": self.warning,
            "open_positions_stale": self.critical,
            "open_positions_unpriceable": self.unpriceable,
            "oldest_open_position_snapshot_age": self.oldest_age_seconds,
            "open_position_refresh_p50": self.refresh_p50_seconds,
            "open_position_refresh_p95": self.refresh_p95_seconds,
        }


@dataclass(frozen=True, slots=True)
class Thresholds:
    """Every number the verdict depends on, in one value.

    Defaults are the measured production calibration (18,163 priced-observation
    gaps inside open windows on 2026-08-21: p50 17.3s, p95 41.9s), restated
    here so the pure module is testable without a configuration file. The
    deployment's own values arrive from `settings` at the I/O seam and override
    these; these are what the unit tests pin.
    """

    feed_stale_seconds: float = 300.0
    feed_degraded_seconds: float = 120.0
    feed_min_recent_mints: int = 50
    position_warning_seconds: float = 60.0
    position_critical_seconds: float = 180.0
    position_unpriceable_seconds: float = 21_600.0

    def as_dict(self) -> dict[str, float]:
        return {
            "feed_stale_seconds": self.feed_stale_seconds,
            "feed_degraded_seconds": self.feed_degraded_seconds,
            "feed_min_recent_mints": float(self.feed_min_recent_mints),
            "position_warning_seconds": self.position_warning_seconds,
            "position_critical_seconds": self.position_critical_seconds,
            "position_unpriceable_seconds": self.position_unpriceable_seconds,
        }


DEFAULT_THRESHOLDS = Thresholds()


@dataclass(frozen=True, slots=True)
class FeedEvidence:
    """The system-level facts `assess` judges. Never one token's opinion.

    Deliberately a value object rather than a live session: it makes the whole
    decision testable without a database, and it makes the evidence behind a
    refusal something that can be logged verbatim.
    """

    #: Newest priced observation anywhere in the feed.
    newest_priced_at: datetime | None = None
    #: Priced observations written in the recent throughput window, and how
    #: many distinct mints they covered. Throughput distinguishes "the feed is
    #: alive" from "one token happens to have a fresh row".
    recent_priced_snapshots: int = 0
    recent_priced_mints: int = 0


@dataclass(frozen=True, slots=True)
class MarketDataHealth:
    """The verdict, its evidence, and what it permits."""

    state: FeedState
    evidence: FeedEvidence
    census: OpenBookCensus
    observed_at: datetime
    block_reasons: tuple[EntryBlockReason, ...] = ()
    detail: str = ""
    thresholds: dict[str, float] = field(default_factory=dict)

    @property
    def entries_allowed(self) -> bool:
        return not self.block_reasons

    @property
    def primary_reason(self) -> EntryBlockReason | None:
        """The one reason to record when only one fits.

        Ordered by how far upstream the cause is, so a report names the thing
        that has to be fixed rather than the last symptom it produced.
        """
        for reason in (
            EntryBlockReason.MARKET_DATA_STALE,
            EntryBlockReason.FEED_UNHEALTHY,
            EntryBlockReason.RECOVERY_INCOMPLETE,
            EntryBlockReason.OPEN_POSITION_STALE,
        ):
            if reason in self.block_reasons:
                return reason
        return None

    @property
    def feed_age_seconds(self) -> float | None:
        if self.evidence.newest_priced_at is None:
            return None
        return max((self.observed_at - self.evidence.newest_priced_at).total_seconds(), 0.0)

    def as_dict(self) -> dict[str, Any]:
        return {
            "market_data": str(self.state),
            "entry_safety": "ENABLED" if self.entries_allowed else "BLOCKED",
            # Stated as its own line and always true. The whole design claim of
            # this module is that exits do not depend on it.
            "exit_management": "ACTIVE",
            "recovery": "COMPLETE" if self.state is not FeedState.RECOVERING else "INCOMPLETE",
            "block_reasons": [str(reason) for reason in self.block_reasons],
            "detail": self.detail,
            "global_last_priced_snapshot_age": self.feed_age_seconds,
            "recent_priced_snapshots": self.evidence.recent_priced_snapshots,
            "recent_priced_mints": self.evidence.recent_priced_mints,
            **self.census.as_dict(),
            "stale_positions": list(self.census.critical_mints),
            "unpriceable_positions": list(self.census.unpriceable_mints),
        }


def _age_seconds(moment: datetime | None, *, now: datetime) -> float | None:
    if moment is None:
        return None
    # Clock skew between containers can date a row slightly in the future; a
    # negative age would read as impossibly healthy.
    return max((now - moment).total_seconds(), 0.0)


def assess(
    evidence: FeedEvidence,
    census: OpenBookCensus,
    *,
    now: datetime,
    thresholds: Thresholds = DEFAULT_THRESHOLDS,
) -> MarketDataHealth:
    """Judge the feed and the open book. Pure — no I/O, no clock of its own.

    Order is deliberate and is the fail-closed rule: **no evidence at all is
    the worst state, not the best.** A feed that has never produced a priced
    observation reports STALE, exactly as `health.classify` reports a stage
    with no output as down. The alternative — treating "nothing measured" as
    "nothing wrong" — is the precise failure that let a 125-minute outage pass
    unremarked.

    Throughput is checked as well as recency because they fail differently. A
    single token with a fresh row proves nothing about a feed serving 1,700
    mints, and a worker wedged on one hot token would otherwise report healthy
    forever.
    """
    stale_after = thresholds.feed_stale_seconds
    degraded_after = thresholds.feed_degraded_seconds
    min_mints = thresholds.feed_min_recent_mints

    age = _age_seconds(evidence.newest_priced_at, now=now)
    reasons: list[EntryBlockReason] = []

    # 1. Has the feed stopped? No evidence counts as stopped.
    if age is None or age >= stale_after:
        detail = (
            "No priced market observation has ever been recorded."
            if age is None
            else f"Newest priced observation is {age:.0f}s old (limit {stale_after:.0f}s)."
        )
        return MarketDataHealth(
            state=FeedState.STALE,
            evidence=evidence,
            census=census,
            observed_at=now,
            block_reasons=(EntryBlockReason.MARKET_DATA_STALE,),
            detail=detail,
            thresholds=thresholds.as_dict(),
        )

    # 2. Is it alive but not actually working? A fresh row on one mint while
    #    the rest of the universe goes unobserved is a wedged worker, not a
    #    healthy feed.
    if evidence.recent_priced_mints < min_mints:
        return MarketDataHealth(
            state=FeedState.STALE,
            evidence=evidence,
            census=census,
            observed_at=now,
            block_reasons=(EntryBlockReason.FEED_UNHEALTHY,),
            detail=(
                f"Only {evidence.recent_priced_mints} distinct mints were priced in the "
                f"throughput window (need {min_mints}); the feed is not making progress."
            ),
            thresholds=thresholds.as_dict(),
        )

    # 3. The feed is working. Is the open book current? A position that can be
    #    priced and has not been is the USMS case, and it blocks new entries
    #    whether or not the outage that caused it is over.
    if census.critical:
        reasons.append(
            EntryBlockReason.RECOVERY_INCOMPLETE
            if age < degraded_after
            else EntryBlockReason.OPEN_POSITION_STALE
        )
        return MarketDataHealth(
            # RECOVERING is precisely "the feed is back, the book is not".
            state=FeedState.RECOVERING,
            evidence=evidence,
            census=census,
            observed_at=now,
            block_reasons=tuple(reasons),
            detail=(
                f"{census.critical} managed open position(s) have no recent priced "
                f"observation: {', '.join(census.critical_mints[:5])}"
                f"{'…' if len(census.critical_mints) > 5 else ''}."
            ),
            thresholds=thresholds.as_dict(),
        )

    state = FeedState.DEGRADED if age >= degraded_after else FeedState.HEALTHY
    detail = f"Newest priced observation is {age:.0f}s old."
    if census.unpriceable:
        # Said out loud on the healthy path too. These positions are the ones
        # most likely to be quietly forgotten, because nothing is failing.
        detail += (
            f" {census.unpriceable} open position(s) have no priceable market and are "
            f"excluded from the entry gate."
        )
    return MarketDataHealth(
        state=state,
        evidence=evidence,
        census=census,
        observed_at=now,
        block_reasons=(),
        detail=detail,
        thresholds=thresholds.as_dict(),
    )


def census_from(
    rows: Sequence[PositionFreshness],
    *,
    thresholds: Thresholds = DEFAULT_THRESHOLDS,
) -> OpenBookCensus:
    """Bucket measured position ages. Pure, so every boundary is unit-testable.

    A position with no priced observation *ever* is classified by how long it
    has been open in the caller's measurement — the caller passes `None` and
    this treats it as unpriceable rather than critical, because there is no
    evidence a refresh would produce anything and permanently blocking on it
    would be the never-clears failure this module refuses to build.
    """
    warning_after = thresholds.position_warning_seconds
    critical_after = thresholds.position_critical_seconds
    unpriceable_after = thresholds.position_unpriceable_seconds

    fresh = warning = critical = 0
    critical_mints: list[str] = []
    unpriceable_mints: list[str] = []
    ages: list[float] = []

    for row in rows:
        if row.age_seconds is None or row.age_seconds >= unpriceable_after:
            unpriceable_mints.append(row.mint_address)
            continue
        ages.append(row.age_seconds)
        if row.age_seconds >= critical_after:
            critical += 1
            critical_mints.append(row.mint_address)
        elif row.age_seconds >= warning_after:
            warning += 1
        else:
            fresh += 1

    return OpenBookCensus(
        total=len(rows),
        fresh=fresh,
        warning=warning,
        critical=critical,
        unpriceable=len(unpriceable_mints),
        oldest_age_seconds=max(ages) if ages else None,
        refresh_p50_seconds=_percentile(ages, 0.50),
        refresh_p95_seconds=_percentile(ages, 0.95),
        critical_mints=tuple(critical_mints),
        unpriceable_mints=tuple(unpriceable_mints),
    )


def _percentile(values: list[float], fraction: float) -> float | None:
    """Nearest-rank percentile.

    Nearest-rank rather than interpolated because these are observed ages and
    the answer should be one of them: an interpolated p95 reports a staleness
    no position actually had.
    """
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, round(fraction * (len(ordered) - 1))))
    return round(ordered[index], 1)
