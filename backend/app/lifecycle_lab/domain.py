"""Meme Lifecycle Lab — the shared vocabulary.

Every module in this package speaks these types. They are deliberately plain
frozen dataclasses so the pure engines (point-in-time, attention, events,
replay) can be exercised without a database, and so a replay over the same
inputs is byte-for-byte reproducible.

Three timestamps, three different claims — conflating any two of them is how
look-ahead gets into a backtest:

* ``source_timestamp`` — the time the *source* attributes to the data (the
  Wikipedia day, the GDELT 15-minute bucket, the pump.fun poll). Says what
  period the number describes.
* ``observed_at`` — the instant the measurement describes the world *as of*.
  For a windowed count it is the window's end; for a cumulative counter it is
  the moment it was read.
* ``retrieved_at`` — wall-clock time MEMESCOPE actually had the bytes. This is
  the only one that proves knowledge. A Wikipedia day fetched three weeks later
  has an old ``source_timestamp`` and a new ``retrieved_at``.

Forward (authoritative) data is visible at ``T`` only if ``retrieved_at <= T``.
Backfilled (exploratory) data may be shown as-if-known at
``source_timestamp + publication_lag`` — but only in EXPLORATORY mode, never
for metrics that keep accumulating after the fact (engagement), and never
toward the headline verdict.

Pure: no I/O, no clock, no randomness.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Any

#: The Lab never trades. Asserted by test; there is no setting that flips it.
REAL_TRADING = False


class DataClass(StrEnum):
    """Where an observation's knowledge-time came from."""

    #: Collected prospectively by the Lab. Counts toward the headline verdict.
    FORWARD = "forward"
    #: Fetched after the fact about the past. Research and charts only.
    BACKFILL = "backfill"


class ResearchMode(StrEnum):
    #: FORWARD data only, gated on ``retrieved_at``. The only verdict-grade mode.
    AUTHORITATIVE = "authoritative"
    #: FORWARD + BACKFILL. Every output produced in this mode is labelled.
    EXPLORATORY = "exploratory"


class Source(StrEnum):
    PUMPFUN_REPLIES = "pumpfun_replies"
    WIKIPEDIA = "wikipedia"
    GDELT = "gdelt"
    DEXSCREENER = "dexscreener"
    GECKOTERMINAL = "geckoterminal"
    REDDIT = "reddit"
    X = "x"


#: Sources that measure *attention*. DexScreener / GeckoTerminal feed identity
#: and market context, not attention, and are excluded from platform counts.
ATTENTION_SOURCES: frozenset[Source] = frozenset(
    {Source.PUMPFUN_REPLIES, Source.WIKIPEDIA, Source.GDELT, Source.REDDIT, Source.X}
)


class SourceStatus(StrEnum):
    """The outcome of one collection attempt. Absence is never zero."""

    AVAILABLE = "available"
    #: The source exists but could not answer for this subject (no API access,
    #: subject outside the listing the source exposes, no article, ...).
    UNAVAILABLE = "unavailable"
    #: Turned off by configuration (``X_ENABLED=false``).
    DISABLED = "disabled"
    ERROR = "error"
    #: Data was returned but is older than the source's freshness budget.
    STALE = "stale"
    #: Some of the requested subjects/windows answered, some did not.
    PARTIAL = "partial"


class Metric(StrEnum):
    #: Number of posts/articles/mentions inside [window_start, window_end).
    MENTIONS = "mentions"
    #: Page views inside the window (Wikipedia; daily granularity).
    PAGEVIEWS = "pageviews"
    #: Cumulative reply counter read at observed_at (pump.fun).
    REPLIES_TOTAL = "replies_total"
    #: Distinct accounts inside the window.
    UNIQUE_PARTICIPANTS = "unique_participants"
    #: Likes + comments + reposts + upvotes inside the window. Accumulates
    #: after the fact, so BACKFILL rows of this metric are never visible.
    ENGAGEMENT = "engagement"
    #: Token profile facts (socials, websites, pool creation). value=1 marker;
    #: the facts live in ``raw_payload``.
    PROFILE = "profile"


#: Metrics whose value keeps growing after the window closes. A backfilled
#: reading of these describes the present, not the past.
ACCUMULATING_METRICS: frozenset[Metric] = frozenset({Metric.ENGAGEMENT, Metric.REPLIES_TOTAL})


class ValueKind(StrEnum):
    #: Count of events inside [window_start, window_end).
    WINDOW_COUNT = "window_count"
    #: Running total read at observed_at. Deltas need two readings.
    CUMULATIVE = "cumulative"
    #: A fact, not a count (profile metadata).
    SNAPSHOT = "snapshot"


class LinkMethod(StrEnum):
    MANUAL = "manual"
    EXACT_NAME = "exact_name"
    EXACT_SYMBOL = "exact_symbol"
    ALIAS_MATCH = "alias_match"
    WEBSITE_MATCH = "website_match"
    SOCIAL_LINK_MATCH = "social_link_match"


class AliasKind(StrEnum):
    NAME = "name"
    SYMBOL = "symbol"
    HASHTAG = "hashtag"
    PHRASE = "phrase"
    WIKI_TITLE = "wiki_title"
    DOMAIN = "domain"
    SOCIAL_HANDLE = "social_handle"


class EventType(StrEnum):
    ATTENTION_INCREASE = "attention_increase"
    ATTENTION_ACCELERATION = "attention_acceleration"
    MEME_REVIVAL = "meme_revival"
    NEW_ATTENTION_WAVE = "new_attention_wave"
    SECOND_WAVE = "second_wave"
    THIRD_WAVE = "third_wave"
    ATTENTION_DECAY = "attention_decay"
    ATTENTION_PRICE_DIVERGENCE = "attention_price_divergence"
    PRICE_ATTENTION_DIVERGENCE = "price_attention_divergence"
    CROSS_PLATFORM_EXPANSION = "cross_platform_expansion"


class LifecycleState(StrEnum):
    """Descriptive only. No state is a buy or a sell."""

    UNKNOWN = "unknown"
    EMERGING = "emerging"
    ACTIVE = "active"
    ACCELERATING = "accelerating"
    PUMPING = "pumping"
    COOLING = "cooling"
    DORMANT = "dormant"
    REVIVING = "reviving"
    SECOND_WAVE = "second_wave"
    THIRD_WAVE = "third_wave"
    DECAYING = "decaying"
    DEAD = "dead"


class DivergenceCase(StrEnum):
    """Research categories. None is labelled better than another."""

    A_ATTENTION_UP_PRICE_FLAT = "A"
    B_ATTENTION_UP_PRICE_UP = "B"
    C_ATTENTION_UP_PRICE_SURGE = "C"
    D_ATTENTION_DOWN_PRICE_SURGE = "D"
    E_ATTENTION_DOWN_PRICE_DOWN = "E"
    #: Inputs unavailable, or the pair falls in none of A–E.
    NONE = "none"


class AgeBucket(StrEnum):
    M0_5 = "0-5m"
    M5_30 = "5-30m"
    M30_H2 = "30m-2h"
    H2_6 = "2h-6h"
    H6_24 = "6h-24h"
    D1_3 = "1-3d"
    D3_7 = "3-7d"
    D7_PLUS = "7d+"
    UNKNOWN = "unknown"


class Arm(StrEnum):
    """Control architecture. Only BASELINE has a strategy in Phase 1–4."""

    CONTROL_A_EXISTING = "control_a_existing"
    CONTROL_B_MARKET_ONLY = "control_b_market_only"
    CONTROL_C_ATTENTION_ONLY = "control_c_attention_only"
    CONTROL_D_COMBINED = "control_d_combined"
    BASELINE = "baseline_attention_acceleration_market_confirmation"


class SplitSegment(StrEnum):
    TRAIN = "train"
    VALIDATION = "validation"
    TEST = "test"
    ALL = "all"


class ExitReason(StrEnum):
    TAKE_PROFIT = "take_profit"
    STOP_LOSS = "stop_loss"
    TRAILING_STOP = "trailing_stop"
    MAX_HOLD = "max_hold"
    ATTENTION_COLLAPSE = "attention_collapse"
    VOLUME_COLLAPSE = "volume_collapse"
    #: Replay ran out of data with the position still open. Marked, not filled.
    END_OF_DATA = "end_of_data"


#: Outcome horizons for event timeliness. Fixed, so results are comparable.
TIMELINESS_HORIZONS: tuple[timedelta, ...] = (
    timedelta(minutes=5),
    timedelta(minutes=15),
    timedelta(minutes=30),
    timedelta(hours=1),
    timedelta(hours=2),
    timedelta(hours=6),
    timedelta(hours=24),
)

#: How long after the period it describes a source publishes. Used only to
#: place BACKFILL rows on the EXPLORATORY timeline.
PUBLICATION_LAG: dict[Source, timedelta] = {
    Source.WIKIPEDIA: timedelta(hours=24),
    Source.GDELT: timedelta(minutes=15),
    Source.GECKOTERMINAL: timedelta(minutes=1),
    Source.PUMPFUN_REPLIES: timedelta(0),
    Source.DEXSCREENER: timedelta(0),
    Source.REDDIT: timedelta(0),
    Source.X: timedelta(0),
}


# --------------------------------------------------------------------------
# Identity
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Meme:
    id: str
    slug: str
    display_name: str
    #: When forward collection for this meme began. Nothing about this meme
    #: before it is FORWARD data.
    tracking_started_at: datetime
    wikipedia_title: str | None = None
    gdelt_query: str | None = None


@dataclass(frozen=True, slots=True)
class MemeAlias:
    meme_id: str
    alias: str
    kind: AliasKind
    #: When the alias became known. Gated like every other fact.
    added_at: datetime


@dataclass(frozen=True, slots=True)
class MemeTokenLink:
    meme_id: str
    mint_address: str
    method: LinkMethod
    confidence: Decimal
    #: Written once, when the link was made. A link made after a pump does not
    #: exist before it — the single most important look-ahead guard here.
    linked_at: datetime
    unlinked_at: datetime | None = None

    def visible_at(self, t: datetime) -> bool:
        return self.linked_at <= t and (self.unlinked_at is None or self.unlinked_at > t)


@dataclass(frozen=True, slots=True)
class TokenInfo:
    mint_address: str
    name: str | None
    symbol: str | None
    #: Chain/pool creation time when known; None is "unknown", not "new".
    created_at: datetime | None
    discovered_at: datetime | None
    creator_address: str | None = None


# --------------------------------------------------------------------------
# Raw observations — the source of truth. Features are derived, never stored
# as truth.
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Observation:
    source: Source
    metric: Metric
    value_kind: ValueKind
    data_class: DataClass
    source_timestamp: datetime
    observed_at: datetime
    retrieved_at: datetime
    raw_value: Decimal
    #: Exactly one of meme_id / mint_address identifies the subject.
    meme_id: str | None = None
    mint_address: str | None = None
    window_start: datetime | None = None
    window_end: datetime | None = None
    #: The alias/article/keyword that produced the reading — provenance.
    query: str | None = None
    source_url: str | None = None
    normalized_value: Decimal | None = None
    #: 0..1. How sure we are this reading is about this subject.
    confidence: Decimal = Decimal("1")
    raw_payload: dict[str, Any] | None = None
    collection_run_id: str | None = None

    def dedupe_key(self) -> str:
        """Idempotency key. First write wins: a later revision of the same
        window is a different claim made at a different time, and the record
        of what was known when is immutable."""
        parts = [
            self.source.value,
            self.metric.value,
            self.data_class.value,
            self.meme_id or "",
            self.mint_address or "",
            self.query or "",
            (self.window_start.isoformat() if self.window_start else ""),
            (self.window_end.isoformat() if self.window_end else ""),
            self.observed_at.isoformat(),
        ]
        return hashlib.sha256("|".join(parts).encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class CollectionRun:
    """One attempt to collect one source. Failures are records, not gaps."""

    id: str
    source: Source
    status: SourceStatus
    started_at: datetime
    finished_at: datetime
    data_class: DataClass
    reason: str | None = None
    meme_id: str | None = None
    mint_address: str | None = None
    observations_written: int = 0
    detail: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class MarketPoint:
    """One market reading. FORWARD rows come from token_market_snapshots
    (available at captured_at); BACKFILL rows from token_market_candles
    (close of bar, available at bar end + publication lag)."""

    mint_address: str
    observed_at: datetime
    available_at: datetime
    data_class: DataClass
    price_usd: Decimal | None
    market_cap: Decimal | None = None
    liquidity_usd: Decimal | None = None
    volume_5m: Decimal | None = None
    volume_1h: Decimal | None = None
    volume_24h: Decimal | None = None
    buy_count_24h: int | None = None
    sell_count_24h: int | None = None
    #: For candles: the bar's own volume and resolution.
    bar_volume: Decimal | None = None
    bar_seconds: int | None = None
    source: str = "token_market_snapshots"


# --------------------------------------------------------------------------
# Derived values. A metric that cannot be computed is ``Unavailable``, never 0.
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Unavailable:
    reason: str

    def __bool__(self) -> bool:  # an Unavailable is never truthy evidence
        return False


Measured = Decimal | Unavailable


def is_available(value: object) -> bool:
    return value is not None and not isinstance(value, Unavailable)


@dataclass(frozen=True, slots=True)
class SourceAvailability:
    source: Source
    status: SourceStatus
    reason: str | None
    last_run_at: datetime | None


@dataclass(frozen=True, slots=True)
class InformationState:
    """Everything MEMESCOPE knew at ``as_of``, and nothing it didn't.

    Produced only by ``pit.information_available_at``. Every downstream engine
    takes one of these rather than raw tables, so the gate exists in exactly
    one place.
    """

    as_of: datetime
    mode: ResearchMode
    meme: Meme
    aliases: tuple[MemeAlias, ...]
    links: tuple[MemeTokenLink, ...]
    tokens: tuple[TokenInfo, ...]
    observations: tuple[Observation, ...]
    market: tuple[MarketPoint, ...]
    sources: tuple[SourceAvailability, ...]
    #: True when any BACKFILL row was admitted. Propagates to every output.
    contains_backfill: bool = False
    #: EXPLORATORY-only escape hatch: links treated as known before linked_at.
    #: Every output carrying it is stamped HINDSIGHT. Refused in AUTHORITATIVE.
    hindsight_links: bool = False


@dataclass(frozen=True, slots=True)
class AttentionFeatures:
    as_of: datetime
    meme_id: str
    mentions_5m: Measured
    mentions_15m: Measured
    mentions_1h: Measured
    mentions_6h: Measured
    mentions_24h: Measured
    #: Rate now ÷ rate in the preceding equal window.
    velocity: Measured
    #: Change in velocity between consecutive windows.
    acceleration: Measured
    #: Current hourly rate ÷ the meme's own trailing baseline rate.
    baseline_multiple: Measured
    unique_participants: Measured
    engagement: Measured
    #: Number of ATTENTION_SOURCES with AVAILABLE data and nonzero activity.
    platform_count: Measured
    per_source: dict[str, dict[str, Measured]] = field(default_factory=dict)
    contains_backfill: bool = False


@dataclass(frozen=True, slots=True)
class MarketFeatures:
    as_of: datetime
    mint_address: str
    price_usd: Measured
    market_cap: Measured
    liquidity_usd: Measured
    volume_1h: Measured
    #: volume over the recent window ÷ the preceding equal window.
    volume_growth: Measured
    #: Price change over the feature window, as a fraction (0.08 = +8%).
    price_change: Measured
    liquidity_change: Measured
    token_age: timedelta | None
    age_bucket: AgeBucket
    #: Seconds between as_of and the newest market point used.
    data_age_seconds: Measured


@dataclass(frozen=True, slots=True)
class MemeEvent:
    meme_id: str
    event_type: EventType
    #: The replay instant at which the detector fired. Written once.
    detected_at: datetime
    mode: ResearchMode
    detector_version: str
    mint_address: str | None = None
    divergence_case: DivergenceCase | None = None
    lifecycle_state: LifecycleState | None = None
    features: dict[str, Any] = field(default_factory=dict)
    contains_backfill: bool = False


@dataclass(frozen=True, slots=True)
class Timeliness:
    detected_at: datetime
    mint_address: str
    price_before_detection: Measured
    price_at_detection: Measured
    #: Horizon (as in TIMELINESS_HORIZONS) → fractional return, or Unavailable.
    returns: dict[timedelta, Measured]
    #: Return over the lookback before detection — how much had already moved.
    run_up_before_detection: Measured


# --------------------------------------------------------------------------
# Spec hashing — shared by experiments and strategies.
# --------------------------------------------------------------------------


def _canonical(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, timedelta):
        return value.total_seconds()
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, dict):
        return {
            str(k): _canonical(v) for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_canonical(v) for v in value]
    return value


def spec_hash(spec: dict[str, Any]) -> str:
    """SHA-256 of the canonical JSON. Any change to a spec is a new spec."""
    payload = json.dumps(_canonical(spec), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()
