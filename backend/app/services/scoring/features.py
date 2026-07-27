"""The engine's input: a windowed, provider-neutral view of one token.

`FeatureSet` holds primitives and `Decimal`s only - no ORM instances, no lazy
relationships, no session. Two consequences, both deliberate:

  * The engine can be exercised without a database, which is why the component
    and engine tests need no fixtures at all.
  * Nothing downstream of `build_feature_set` can accidentally trigger I/O, so
    "the engine performs no I/O" is enforced by the type rather than by
    discipline.

Windowing lives here rather than in the components because every component must
see the same window - a momentum term measured over six hours and a drawdown
measured over one would not compose into a coherent score.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Protocol

from app.core.config import settings
from app.services.market.scheduler import RefreshScheduler, SchedulePolicy

SECONDS_PER_MINUTE = Decimal(60)


class TokenLike(Protocol):
    """The subset of `DiscoveredToken` the engine reads.

    A structural type rather than the ORM class: it documents the real
    dependency, and it lets tests build inputs without importing SQLAlchemy.
    """

    mint_address: str
    block_time: datetime | None
    discovered_at: datetime
    metadata_status: Any


class SnapshotLike(Protocol):
    """The subset of `TokenMarketSnapshot` the engine reads."""

    captured_at: datetime
    price_usd: Decimal | None
    liquidity_usd: Decimal | None
    market_cap: Decimal | None
    fully_diluted_valuation: Decimal | None
    volume_24h: Decimal | None
    volume_1h: Decimal | None
    volume_5m: Decimal | None
    buy_count_24h: int | None
    sell_count_24h: int | None
    trading_status: Any


@dataclass(frozen=True, slots=True)
class Observation:
    """One point in the feature window. Only the fields trends are built from."""

    captured_at: datetime
    price_usd: Decimal | None
    liquidity_usd: Decimal | None


@dataclass(frozen=True, slots=True)
class FeatureSet:
    """Everything `evaluate()` is allowed to see."""

    mint_address: str
    evaluated_at: datetime

    # --- Lifecycle -----------------------------------------------------------
    age_minutes: Decimal
    tier: str
    tier_interval_seconds: int
    history_window_seconds: int
    risk_window_seconds: int
    metadata_resolved: bool

    # --- Latest market state -------------------------------------------------
    latest_snapshot_at: datetime | None = None
    trading_status: str = "unknown"
    price_usd: Decimal | None = None
    liquidity_usd: Decimal | None = None
    market_cap: Decimal | None = None
    fully_diluted_valuation: Decimal | None = None
    volume_24h: Decimal | None = None
    volume_1h: Decimal | None = None
    volume_5m: Decimal | None = None
    buy_count_24h: int | None = None
    sell_count_24h: int | None = None

    # --- Window --------------------------------------------------------------
    #: Newest first, already trimmed to `history_window_seconds` and to K.
    window: tuple[Observation, ...] = ()

    # --- Replay state --------------------------------------------------------
    #: Consecutive prior evaluations that met the Elite gate. Supplied by the
    #: caller from stored history, never accumulated inside the engine - that is
    #: what keeps the streak replay-reproducible rather than path-dependent.
    prior_elite_streak: int = 0

    @property
    def observations(self) -> int:
        return len(self.window)

    @property
    def has_market(self) -> bool:
        """True when a provider has actually indexed a pool for this token."""
        return self.price_usd is not None or self.liquidity_usd is not None

    def liquidity_peak(self, *, within_seconds: int | None = None) -> Decimal | None:
        """Highest observed liquidity in the window, or in a recent slice of it.

        `within_seconds` is what separates a rug in progress from slow decay:
        the same 70% decline is a veto inside the risk window and a soft penalty
        outside it.
        """
        cutoff = (
            None
            if within_seconds is None
            else self.evaluated_at - timedelta(seconds=within_seconds)
        )
        values = [
            observation.liquidity_usd
            for observation in self.window
            if observation.liquidity_usd is not None
            and (cutoff is None or observation.captured_at >= cutoff)
        ]
        return max(values) if values else None

    def priced_observations(self) -> tuple[Observation, ...]:
        """Window entries that carry a price, newest first."""
        return tuple(
            observation for observation in self.window if observation.price_usd is not None
        )

    def mean_spacing_seconds(self) -> Decimal | None:
        """Average gap between observations; `None` with fewer than two."""
        if len(self.window) < 2:
            return None
        newest = self.window[0].captured_at
        oldest = self.window[-1].captured_at
        span = Decimal((newest - oldest).total_seconds())
        return span / Decimal(len(self.window) - 1)


def window_seconds_for(
    age_minutes: Decimal,
    *,
    policy: SchedulePolicy | None = None,
    feature_window: int | None = None,
    minimum_seconds: int | None = None,
    maximum_seconds: int | None = None,
) -> tuple[str, int, int]:
    """Resolve `(tier, tier_interval_seconds, history_window_seconds)`.

    The window is tier-relative because the refresh cadence is. A fixed window
    would starve the slow tiers: at a six-hour refresh interval, a one-hour
    window holds at most one observation, permanently capping evidence for every
    healthy token over a day old.

    The tier is derived from age via the enrichment scheduler's own policy - the
    single source of truth for cadence - rather than read from
    `TokenEnrichmentState.tier`, which is null until a token's first refresh.
    """
    resolved_policy = policy or SchedulePolicy.from_settings()
    window = feature_window or settings.SCORING_FEATURE_WINDOW
    floor = (
        minimum_seconds if minimum_seconds is not None else settings.SCORING_WINDOW_MIN_SECONDS
    )
    ceiling = (
        maximum_seconds if maximum_seconds is not None else settings.SCORING_WINDOW_MAX_SECONDS
    )

    tier = resolved_policy.tier_for_age(float(age_minutes))
    interval = resolved_policy.interval_for_tier(tier)
    history_window = min(max(window * interval, floor), ceiling)
    return str(tier), interval, history_window


def age_minutes_of(token: TokenLike, *, now: datetime) -> Decimal:
    """Token age in minutes, preferring on-chain time over discovery time.

    `block_time` is when the token was created; `discovered_at` is when this
    system first saw it. The former is the truth and the latter is our latency,
    so age uses `block_time` whenever the scanner managed to resolve it.
    """
    origin = token.block_time or token.discovered_at
    elapsed = Decimal((now - origin).total_seconds()) / SECONDS_PER_MINUTE
    return max(Decimal(0), elapsed)


def build_feature_set(
    token: TokenLike,
    snapshots: Sequence[SnapshotLike],
    *,
    now: datetime,
    policy: SchedulePolicy | None = None,
    prior_elite_streak: int = 0,
    feature_window: int | None = None,
    risk_window_seconds: int | None = None,
) -> FeatureSet:
    """Assemble a `FeatureSet` from a token and its recent snapshots.

    `snapshots` may arrive in any order and may extend beyond the window; both
    are normalised here so callers do not have to care. Snapshots newer than
    `now` are kept - a provider clock running slightly ahead is not a reason to
    discard the freshest observation we have.
    """
    age = age_minutes_of(token, now=now)
    tier, interval, history_window = window_seconds_for(
        age, policy=policy, feature_window=feature_window
    )
    rug_window = (
        risk_window_seconds
        if risk_window_seconds is not None
        else settings.SCORING_RUG_WINDOW_SECONDS
    )
    risk_window = min(rug_window, history_window)

    limit = feature_window or settings.SCORING_FEATURE_WINDOW
    cutoff = now - timedelta(seconds=history_window)
    ordered = sorted(
        (snapshot for snapshot in snapshots if snapshot.captured_at >= cutoff),
        key=lambda snapshot: snapshot.captured_at,
        reverse=True,
    )[:limit]

    latest = ordered[0] if ordered else None

    return FeatureSet(
        mint_address=token.mint_address,
        evaluated_at=now,
        age_minutes=age,
        tier=tier,
        tier_interval_seconds=interval,
        history_window_seconds=history_window,
        risk_window_seconds=risk_window,
        metadata_resolved=str(token.metadata_status) == "resolved",
        latest_snapshot_at=latest.captured_at if latest else None,
        trading_status=str(latest.trading_status) if latest else "unknown",
        price_usd=latest.price_usd if latest else None,
        liquidity_usd=latest.liquidity_usd if latest else None,
        market_cap=latest.market_cap if latest else None,
        fully_diluted_valuation=latest.fully_diluted_valuation if latest else None,
        volume_24h=latest.volume_24h if latest else None,
        volume_1h=latest.volume_1h if latest else None,
        volume_5m=latest.volume_5m if latest else None,
        buy_count_24h=latest.buy_count_24h if latest else None,
        sell_count_24h=latest.sell_count_24h if latest else None,
        window=tuple(_to_observations(ordered)),
        prior_elite_streak=prior_elite_streak,
    )


def _to_observations(snapshots: Iterable[SnapshotLike]) -> Iterable[Observation]:
    for snapshot in snapshots:
        yield Observation(
            captured_at=snapshot.captured_at,
            price_usd=snapshot.price_usd,
            liquidity_usd=snapshot.liquidity_usd,
        )


def default_policy() -> SchedulePolicy:
    """The enrichment scheduler's policy, as used for tier resolution."""
    return RefreshScheduler().policy
