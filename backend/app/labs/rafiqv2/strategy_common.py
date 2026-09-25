"""The mechanisms all six books share. Pure: no session, no clock, no I/O.

Each one is built from a book's JSON by `config.py`; the defaults here ARE
the published ladders, and a test holds every book's JSON equal to them.

* `FastRugGate`   the seconds-scale ladder: at each checkpoint the position
                  must be at least this multiple of entry, and the LATEST
                  checkpoint reached governs. Clearing one is never a pass
                  for the next.
* `ProfitLock`    a floor under a winner that follows the peak up and never
                  falls. It owns no sale; the engine sells when it is breached.
* `DeathRateBreaker`  halts entries when too many recent tokens died.
* `EquityRatchet` G1's ratchet, reused rather than re-spelled: the JSON's
                  `equity_ratchet` block is exactly its constructor.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal

from app.labs.rafiqv2.base.equity_ratchet import EquityRatchet

__all__ = ["FRICTION_PCT", "LOCK_GIVEBACK_DEFAULT", "LOCK_LADDER", "RUG_LADDER",
           "DeathRateBreaker", "EquityRatchet", "FastRugGate", "ProfitLock"]

#: Round-trip cost at these sizes. A lock floor is never set below it.
FRICTION_PCT = Decimal("0.01")

#: (after_seconds, min_multiple, label), ascending.
RUG_LADDER: tuple[tuple[int, Decimal, str], ...] = (
    (30, Decimal("0.97"), "rug_30s"),
    (60, Decimal("0.99"), "rug_60s"),
    (120, Decimal("1.0"), "rug_120s"),
    (600, Decimal("1.08"), "abandon_10m"),
    (1200, Decimal("1.15"), "abandon_20m"),
)

#: (peak gain that arms the rung, gain it can never be sold below), ascending.
LOCK_LADDER: tuple[tuple[Decimal, Decimal], ...] = (
    (Decimal("0.03"), Decimal("0.01")),
    (Decimal("0.10"), Decimal("0.04")),
    (Decimal("0.25"), Decimal("0.14")),
    (Decimal("0.50"), Decimal("0.32")),
    (Decimal("1.00"), Decimal("0.70")),
)

#: The learner's starting `lock_giveback`, at which the ladder is exactly as
#: published.
LOCK_GIVEBACK_DEFAULT = Decimal("0.15")


@dataclass(frozen=True)
class FastRugGate:
    """`strictness` is the learner's `rug_strictness`, added to every rung:
    positive cuts more, negative cuts less."""

    ladder: tuple = RUG_LADDER
    strictness: Decimal = Decimal(0)

    def check(self, *, age: timedelta, multiple: Decimal) -> str | None:
        """The label of the governing checkpoint if the position is under it."""
        reached = [(floor, label) for after, floor, label in self.ladder
                   if age.total_seconds() >= after]
        if not reached:
            return None
        floor, label = reached[-1]
        return label if multiple < floor + self.strictness else None


@dataclass
class ProfitLock:
    """Once the peak touches a rung, the position is never sold below it.

    `giveback` is the learner's `lock_giveback`. The published ladder carries
    no such number, so its meaning here is this lab's: each rung may give back
    `giveback - 0.15` more of its own trigger gain than published (less, when
    negative), and no floor goes below friction. At 0.15 the ladder is exactly
    as published; at the 0.40 bound the +25% rung locks +7.75% instead of +14%.
    """

    giveback: Decimal = LOCK_GIVEBACK_DEFAULT
    ladder: tuple = LOCK_LADDER
    floor_multiple: Decimal | None = None

    @property
    def armed(self) -> bool:
        return self.floor_multiple is not None

    def observe(self, peak_multiple: Decimal) -> Decimal | None:
        shift = self.giveback - LOCK_GIVEBACK_DEFAULT
        for trigger, floor in self.ladder:
            if peak_multiple - 1 >= trigger:
                candidate = 1 + max(FRICTION_PCT, floor - shift * trigger)
                if self.floor_multiple is None or candidate > self.floor_multiple:
                    self.floor_multiple = candidate  # never down
        return self.floor_multiple

    def breached(self, multiple: Decimal) -> bool:
        return self.armed and multiple <= self.floor_multiple


@dataclass
class DeathRateBreaker:
    """Halts new entries for `halt_for` once `halt_rate` of the last `window`
    closed trades were deaths, judged from `min_sample` trades on. The
    evidence is cleared when it fires, so an expired halt does not re-fire on
    the deaths that caused it."""

    window: int = 20
    halt_rate: Decimal = Decimal("0.60")
    min_sample: int = 8
    halt_for: timedelta = timedelta(hours=6)
    recent: deque = field(default_factory=deque)
    halted_until: datetime | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        self.recent = deque(self.recent, maxlen=self.window)

    def record(self, *, token_died: bool, now: datetime) -> str | None:
        """One closed trade. Returns the halt reason when this one trips it."""
        self.recent.append(bool(token_died))
        n, deaths = len(self.recent), sum(self.recent)
        if n < self.min_sample or deaths < self.halt_rate * n:
            return None
        self.halted_until = now + self.halt_for
        self.reason = (f"{deaths} of the last {n} tokens died "
                       f"({deaths / n:.0%} >= {self.halt_rate:.0%}) - no new entries "
                       f"until {self.halted_until:%Y-%m-%d %H:%M} UTC")
        self.recent.clear()
        return self.reason

    def check(self, now: datetime) -> tuple[bool, str | None]:
        if self.halted_until is not None and now < self.halted_until:
            return True, self.reason
        return False, None
