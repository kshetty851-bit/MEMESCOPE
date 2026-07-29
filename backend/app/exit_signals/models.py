"""Exit Watch domain types.

Pure: dataclasses and enums only. No I/O, no clock.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal


class ExitSignal(enum.StrEnum):
    """One way conviction can deteriorate.

    Persisted inside `radar_snapshots.dimensions` and served by the API, so
    append-only.
    """

    VOLUME_COLLAPSING = "volume_collapsing"
    LIQUIDITY_LEAVING = "liquidity_leaving"
    TECHNICAL_BREAKDOWN = "technical_breakdown"
    MOMENTUM_ROLLING_OVER = "momentum_rolling_over"
    CONFIDENCE_DROPPING = "confidence_dropping"
    SELL_PRESSURE_BUILDING = "sell_pressure_building"
    PRICE_BELOW_DETECTION = "price_below_detection"
    #: Declared, and not detectable without wallet data. See `smart_money.py`.
    SMART_MONEY_DISTRIBUTING = "smart_money_distributing"
    HOLDER_GROWTH_STALLING = "holder_growth_stalling"


class ExitSeverity(enum.StrEnum):
    """How far the deterioration has gone.

    Three levels, not five. A scale finer than the evidence supports invites
    users to read precision that is not there.
    """

    #: Nothing meaningful is deteriorating.
    CLEAR = "clear"
    #: One or two signals. Worth knowing, not worth acting on alone.
    WATCH = "watch"
    #: Several independent signals agree. The reason it was surfaced is gone.
    ELEVATED = "elevated"


@dataclass(frozen=True, slots=True)
class SignalResult:
    """One signal's verdict.

    `triggered` is `False` and `available` is `True` for a signal that was
    checked and did not fire — distinct from one that could not be checked at
    all, which is the distinction the whole platform is built on.
    """

    id: ExitSignal
    available: bool
    triggered: bool
    #: How far past the threshold, 0-1, for ordering. `None` when unavailable.
    magnitude: Decimal | None = None
    raw: dict[str, Decimal | None] = field(default_factory=dict)

    @classmethod
    def unavailable(cls, signal: ExitSignal) -> SignalResult:
        return cls(id=signal, available=False, triggered=False)

    @classmethod
    def clear(cls, signal: ExitSignal, **raw: Decimal | None) -> SignalResult:
        return cls(id=signal, available=True, triggered=False, raw=raw)

    @classmethod
    def fired(
        cls, signal: ExitSignal, magnitude: Decimal, **raw: Decimal | None
    ) -> SignalResult:
        return cls(id=signal, available=True, triggered=True, magnitude=magnitude, raw=raw)


@dataclass(frozen=True, slots=True)
class ExitAssessment:
    """The complete Exit Watch verdict for one token."""

    mint_address: str
    severity: ExitSeverity
    signals: tuple[SignalResult, ...]
    evaluated_at: datetime
    #: Share of declared signals that could be checked, 0-100. Below 100 because
    #: smart-money and holder signals have no data source.
    coverage: Decimal

    @property
    def triggered(self) -> tuple[SignalResult, ...]:
        """Fired signals, most severe first."""
        fired = [signal for signal in self.signals if signal.triggered]
        return tuple(sorted(fired, key=lambda s: s.magnitude or Decimal(0), reverse=True))

    def has(self, signal: ExitSignal) -> bool:
        return any(s.id is signal and s.triggered for s in self.signals)
