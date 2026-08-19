"""Whether a pool is likely to still be there when the position needs to leave.

V1.1 research, collapse investigation. The Checkpoint 2 finding that reordered
this phase: 38 of 110 reproducible trades ended with an observed price below
-90%, and V1.0 booked those at a median of -7.5% because it fills at the
trigger level rather than at the price that triggered it.

The investigation established what those 38 were, and what they were not:

* **Not an observability failure.** All 38 were still being observed after the
  position closed, with no change of DEX, pool or provider. The pipeline never
  lost the market.
* **Not migration.** Zero pool or venue changes across the cohort.
* **Real liquidity withdrawal.** Median depth at entry was $150,961 and median
  depth at the closing observation was $1,535 — a 99% collapse in the pool
  itself.

So entry depth does not measure exitability. A pool can be deep at entry and
gone an hour later, and the strategy's worst losses come from exactly that.

## What actually separates them

Turnover does. Volume over liquidity — how much trade flows through a pool
relative to how much sits in it — separates the two cohorts almost cleanly, and
it is monotonic across every bucket measured:

    vol/liq      n    collapse rate
    < 0.5        9        56%
    0.5 - 1     34        76%
    1 - 2       15        13%
    2 - 5       10        10%
    5 - 10      16         0%
    > 10        21         0%

Below 1.0, 31 of 43 trades collapsed. At or above it, 3 of 62 did.

The reading is economic rather than statistical: a pool holding $150k that
trades $100k a day is a market. A pool holding $150k that trades $700 a day is
a deposit someone can withdraw, and on this evidence frequently does.

**This is a research gate. It is not wired into the live wallet**, and the
threshold below is a starting point derived from 105 trades — a sample small
enough that the plateau between 1 and 2 matters more than the exact number.

Pure: no I/O, no clock, no randomness. Every input is available at entry.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from decimal import Decimal

#: Turnover at or above which the collapse rate drops from 72% to 4.8% on the
#: studied sample. Chosen at the boundary of a monotonic plateau rather than at
#: the point that maximises in-sample return: 1, 2 and 5 all separate the
#: cohorts, and preferring the loosest keeps the most opportunity.
MIN_VOLUME_TO_LIQUIDITY = Decimal(1)

#: Below this, turnover is not merely low — three quarters of the sample below
#: it lost effectively everything.
CRITICAL_VOLUME_TO_LIQUIDITY = Decimal("0.5")

#: Depth below which a $100 order's own price impact starts to dominate the
#: result regardless of survival. `costs.side_cost` charges `notional²/usd_side`,
#: so at $5,000 total depth a round trip costs about 8%.
MIN_LIQUIDITY_USD = Decimal(5_000)


class Verdict(enum.StrEnum):
    """Whether the pool looks like one a position can leave."""

    # The suppression below is a false positive: ruff's hardcoded-credential
    # check reads the member name `PASS` as a password assignment.
    PASS = "pass"  # noqa: S105
    CAUTION = "caution"
    REJECT = "reject"


class Reason(enum.StrEnum):
    """Machine-readable findings. Stable strings — they are counted and shown."""

    #: Turnover below the level where collapse became the majority outcome.
    TURNOVER_BELOW_FLOOR = "turnover_below_floor"
    #: Turnover in the band where collapse is common but not dominant.
    TURNOVER_MARGINAL = "turnover_marginal"
    #: Pool too shallow for the trade size to round-trip cheaply.
    DEPTH_BELOW_FLOOR = "depth_below_floor"
    #: No depth recorded at all, so neither turnover nor cost can be computed.
    LIQUIDITY_UNKNOWN = "liquidity_unknown"
    #: No volume recorded, so turnover cannot be computed.
    VOLUME_UNKNOWN = "volume_unknown"


@dataclass(frozen=True, slots=True)
class EntryObservation:
    """What was known about a pool at the moment of entry.

    Every field is available at entry by construction. Nothing here may be
    derived from the position's own future — that is the look-ahead rule this
    whole phase is built to respect.
    """

    liquidity_usd: Decimal | None
    volume_24h_usd: Decimal | None
    size_usd: Decimal

    @property
    def turnover(self) -> Decimal | None:
        """Volume over liquidity, or `None` when either side is missing."""
        if self.liquidity_usd is None or self.liquidity_usd <= 0:
            return None
        if self.volume_24h_usd is None or self.volume_24h_usd < 0:
            return None
        return self.volume_24h_usd / self.liquidity_usd

    @property
    def size_to_liquidity(self) -> Decimal | None:
        if self.liquidity_usd is None or self.liquidity_usd <= 0:
            return None
        return self.size_usd / self.liquidity_usd


@dataclass(frozen=True, slots=True)
class Eligibility:
    """The gate's answer, with everything needed to audit it."""

    verdict: Verdict
    reasons: tuple[Reason, ...]
    turnover: Decimal | None
    size_to_liquidity: Decimal | None

    @property
    def accepted(self) -> bool:
        """`CAUTION` is accepted. It marks a trade worth watching, not refusing."""
        return self.verdict is not Verdict.REJECT


def evaluate(
    observation: EntryObservation,
    *,
    min_turnover: Decimal = MIN_VOLUME_TO_LIQUIDITY,
    critical_turnover: Decimal = CRITICAL_VOLUME_TO_LIQUIDITY,
    min_liquidity_usd: Decimal = MIN_LIQUIDITY_USD,
) -> Eligibility:
    """Judge one entry on survivability.

    Thresholds are parameters rather than constants in the body so the
    experiment can sweep them without a second implementation drifting away
    from the one that would eventually run.

    Missing data is `REJECT`, not `PASS`. A pool that cannot be measured is not
    thereby safe, and the alternative — treating unknown depth as adequate — is
    how the 7 uncostable trades entered in the first place.
    """
    reasons: list[Reason] = []

    if observation.liquidity_usd is None or observation.liquidity_usd <= 0:
        reasons.append(Reason.LIQUIDITY_UNKNOWN)
        return Eligibility(
            verdict=Verdict.REJECT,
            reasons=tuple(reasons),
            turnover=None,
            size_to_liquidity=None,
        )

    if observation.volume_24h_usd is None:
        reasons.append(Reason.VOLUME_UNKNOWN)
        return Eligibility(
            verdict=Verdict.REJECT,
            reasons=tuple(reasons),
            turnover=None,
            size_to_liquidity=observation.size_to_liquidity,
        )

    turnover = observation.turnover
    assert turnover is not None  # both operands checked above

    if observation.liquidity_usd < min_liquidity_usd:
        reasons.append(Reason.DEPTH_BELOW_FLOOR)

    verdict = Verdict.PASS
    if turnover < critical_turnover:
        reasons.append(Reason.TURNOVER_BELOW_FLOOR)
        verdict = Verdict.REJECT
    elif turnover < min_turnover:
        reasons.append(Reason.TURNOVER_MARGINAL)
        verdict = Verdict.REJECT
    elif Reason.DEPTH_BELOW_FLOOR in reasons:
        # Turnover is healthy but the pool is thin. Not refused — the studied
        # collapses were deep pools with no flow, not shallow pools with flow —
        # but flagged, because cost rather than survival is the risk here.
        verdict = Verdict.CAUTION

    return Eligibility(
        verdict=verdict,
        reasons=tuple(reasons),
        turnover=turnover,
        size_to_liquidity=observation.size_to_liquidity,
    )
