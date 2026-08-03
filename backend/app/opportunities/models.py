"""Opportunity Engine domain types.

Plain dataclasses and enums. No I/O, no clock, no randomness — the same
discipline `app/radar`, `app/analysts` and `services/scoring` already hold, and
for the same reason: a signal that is a pure function of a stored window can be
replayed over history, which is how thresholds get tuned rather than guessed
(ARCHITECTURE_DECISIONS.md AD-04).

Time enters as an explicit `now` wherever it is needed at all.
"""

from __future__ import annotations

import enum
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal


class OpportunityStatus(enum.StrEnum):
    """Where an opportunity sits in its lifecycle.

    Persisted as a string, so append-only. The order below is the order of the
    transitions in AD-01; `lifecycle.py` owns which ones are legal.
    """

    NEW = "new"
    PENDING_CONFIRMATION = "pending_confirmation"
    ACTIVE = "active"
    EXPIRING = "expiring"
    CLOSED = "closed"
    ARCHIVED = "archived"


#: Statuses that occupy a token's live slot. A mint may hold at most one
#: opportunity in one of these at a time, which is what makes "one opportunity
#: per token generation" enforceable as a partial unique index rather than as an
#: application check (AD-09).
LIVE_STATUSES: frozenset[OpportunityStatus] = frozenset(
    {
        OpportunityStatus.NEW,
        OpportunityStatus.PENDING_CONFIRMATION,
        OpportunityStatus.ACTIVE,
        OpportunityStatus.EXPIRING,
    }
)


class SignalStatus(enum.StrEnum):
    """A single signal's own lifecycle, independent of its opportunity."""

    PENDING = "pending"
    ACTIVE = "active"
    EXPIRED = "expired"
    INVALIDATED = "invalidated"
    REALISED = "realised"


#: The signal states that still count towards an opportunity being live.
LIVE_SIGNAL_STATUSES: frozenset[SignalStatus] = frozenset(
    {SignalStatus.PENDING, SignalStatus.ACTIVE}
)


class OpportunityStage(enum.StrEnum):
    """Where the *token* is in its own life. Mutually exclusive.

    Orthogonal to signals: a token has exactly one stage and zero-to-many live
    signals, which is what stops Near Graduation and Pre-Breakout from ever
    duplicating each other (AD-05).

    `UNKNOWN` is the honest default. Stage inference beyond graduation is not
    built yet, and guessing would be worse than declining.
    """

    UNKNOWN = "unknown"
    PRE_GRADUATION = "pre_graduation"
    NEAR_GRADUATION = "near_graduation"
    FRESH_GRADUATION = "fresh_graduation"
    ESTABLISHED = "established"


class OpportunityPriority(enum.StrEnum):
    """Coarse ranking band, derived from the numeric priority.

    A band rather than a raw number at the boundary, because "high" survives a
    weighting change and "73.4" does not.
    """

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class SignalType(enum.StrEnum):
    """What kind of change a signal reports.

    Persisted, so append-only. Declared in full here even though one provider
    exists: the type is the contract between a provider and the engine, and a
    future sprint should add a provider, not an enum member the engine has to
    learn about.
    """

    FRESH_GRADUATION = "fresh_graduation"
    NEAR_GRADUATION = "near_graduation"
    LIQUIDITY_EXPANSION = "liquidity_expansion"
    VOLUME_EXPANSION = "volume_expansion"
    PRE_BREAKOUT = "pre_breakout"
    BREAKOUT = "breakout"
    ACCUMULATION = "accumulation"
    HOLDER_GROWTH = "holder_growth"
    COMMUNITY_SURGE = "community_surge"
    BUILDER_ACTIVITY = "builder_activity"
    WHALE_ACCUMULATION = "whale_accumulation"
    SMART_MONEY_ENTRY = "smart_money_entry"
    NARRATIVE_ACCELERATION = "narrative_acceleration"


class SignalSeverity(enum.StrEnum):
    """How much a signal type matters, independent of how sure we are.

    Severity is a property of the *type*, confidence a property of the
    *observation*. Multiplying them is the ranking (AD-08); collapsing them into
    one number would make a certain-but-trivial signal indistinguishable from an
    uncertain-but-important one.
    """

    INFO = "info"
    NOTABLE = "notable"
    MAJOR = "major"
    CRITICAL = "critical"


# --- Provider input ----------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MarketObservation:
    """One market snapshot, reduced to what signal providers read.

    A projection of `token_market_snapshots` rather than the ORM row, so
    providers stay free of SQLAlchemy and can be tested with literals.

    Deliberately *not* `radar.models.Observation`. That type is the Radar's
    input and is consumed by six pure analysts with their own purity tests;
    widening it to carry `dex_name` would change a contract this sprint is meant
    to leave alone.
    """

    captured_at: datetime
    price_usd: Decimal | None = None
    market_cap: Decimal | None = None
    liquidity_usd: Decimal | None = None
    volume_24h: Decimal | None = None
    volume_1h: Decimal | None = None
    buy_count_24h: int | None = None
    sell_count_24h: int | None = None
    #: The venue this observation was taken from. The graduation signal is a
    #: transition in this field and nothing else.
    dex_name: str | None = None
    pool_address: str | None = None
    #: How full the bonding curve was, 0 to 1, read directly from the chain.
    #: `None` when no curve observation covers this moment — which is every
    #: observation until curve collection is switched on. Additive: the field is
    #: optional and no existing provider reads it.
    curve_progress: Decimal | None = None


@dataclass(frozen=True, slots=True)
class ObservationWindow:
    """A token's recent observations, oldest first. A provider's entire input.

    Oldest-first matches `RadarSeries`, so anyone who has read one engine can
    read the other without re-checking the ordering.
    """

    mint_address: str
    observations: Sequence[MarketObservation] = ()
    discovered_at: datetime | None = None

    @property
    def latest(self) -> MarketObservation | None:
        return self.observations[-1] if self.observations else None

    @property
    def previous(self) -> MarketObservation | None:
        """The observation before the latest, if there is one."""
        return self.observations[-2] if len(self.observations) >= 2 else None

    def __len__(self) -> int:
        return len(self.observations)


# --- Provider output ---------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Evidence:
    """One observation behind a signal, as a label and a figure.

    Not a free-form dict, for the same reason `analysts.base.Evidence` is not:
    a named, ordered list is what lets a client render the explanation without
    inventing the sentence, and it keeps the evidence auditable.
    """

    label: str
    value: str
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class SignalCandidate:
    """What a provider emits. Not yet an opportunity.

    A candidate is a claim about a transition. The engine decides whether it
    becomes a signal, whether it needs confirming first, and which opportunity
    it attaches to — a provider never reaches into that.
    """

    mint_address: str
    signal_type: SignalType
    #: 0-100, normalised by the provider. How strong *this* observation was,
    #: not how much we trust it — that is confidence, which the engine derives.
    strength: Decimal
    severity: SignalSeverity
    #: Stable identifiers. Prose is rendered at read time, never stored, so
    #: wording changes never require a migration (AD-07).
    reason_codes: tuple[str, ...] = ()
    evidence: tuple[Evidence, ...] = ()
    #: What the token's stage becomes, when the provider can tell. `None` means
    #: "no opinion" and leaves the stage untouched.
    stage: OpportunityStage | None = None
    #: The observation this claim was made from. Used for freshness, and to
    #: dedupe a re-detection of the same transition from the same snapshot.
    observed_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class ProviderResult:
    """One provider's complete verdict on one window.

    `unavailable_reason` is set exactly when the provider has no data source for
    this subject. Reported rather than omitted: a missing provider is invisible,
    while one that says "I cannot see this" is a fact a reader can weigh. Same
    contract `/smart-money/{mint}` already honours.
    """

    provider_id: str
    candidates: tuple[SignalCandidate, ...] = ()
    unavailable_reason: str | None = None

    @property
    def available(self) -> bool:
        return self.unavailable_reason is None

    @classmethod
    def unavailable(cls, provider_id: str, *, reason: str) -> ProviderResult:
        return cls(provider_id=provider_id, unavailable_reason=reason)

    @classmethod
    def nothing(cls, provider_id: str) -> ProviderResult:
        """Available, but saw no transition. The overwhelmingly common case."""
        return cls(provider_id=provider_id)


@dataclass(frozen=True, slots=True)
class ProviderMeta:
    """What a provider is, published so its role is checkable.

    `operational=False` is how a provider declares that the platform holds no
    data for it at all — the holder, community, whale, builder and narrative
    providers will register this way until a source exists, so the gap stays
    visible in the API surface instead of being an undocumented absence.
    """

    provider_id: str
    name: str
    question: str
    emits: tuple[SignalType, ...]
    operational: bool = True
    unavailable_reason: str | None = None
    required_fields: tuple[str, ...] = field(default_factory=tuple)
