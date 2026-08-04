"""The published strategies.

A strategy is a set of rules a reader can check a trade against. That is the
whole point of the wallet: not "our simulation made 40%", but "this rule, stated
in advance, applied to every token the Radar ranked, produced this". A rule that
lives only in code nobody reads is indistinguishable from a claim.

So every strategy publishes itself — `describe()` returns the rules in the same
words the API serves and the page prints, and a test asserts the published
numbers match the ones the code actually applies. Rewording is a deploy; changing
a threshold is a new **version**, because a strategy whose rules changed
underneath its own track record has no track record.

Pure. No I/O, no clock, no randomness; `now` is a parameter. Strategies are
registered here rather than in a table for the same reason providers are: the
rules *are* the code, and a row that could disagree with the code is a bug
waiting to be believed.

Nothing here recommends anything. A strategy describes what it did, never what a
reader should do.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Protocol

from app.paper.models import Candidate, Entry

#: How many Radar places the default strategy watches. Published because it is
#: half the entry rule: a token that never reaches the top ten is never bought,
#: and a reader comparing the wallet against the Radar needs to know the cut.
DEFAULT_TOP_N = 10


@dataclass(frozen=True, slots=True)
class Rule:
    """One published rule, as a reader sees it."""

    label: str
    value: str


@dataclass(frozen=True, slots=True)
class StrategySpec:
    """A strategy, described for publication.

    `version` is part of the identity. Editing a threshold without bumping it
    would silently re-describe trades that were taken under the old one.
    """

    id: str
    name: str
    version: str
    summary: str
    rules: tuple[Rule, ...]
    #: False when a strategy is declared but not runnable. Published rather than
    #: hidden, so "we have one strategy" and "we have four and run one" are
    #: distinguishable — see `provider_registry`, which does the same.
    operational: bool = True
    unavailable_reason: str | None = None


class Strategy(Protocol):
    """What every strategy must be able to do.

    Deliberately small. A strategy decides **how much to buy** and **where the
    exits sit**; it does not decide *what* to buy, because that is the Radar's
    job and a strategy that re-ranked candidates would be a second, unpublished
    scoring model competing with the one this platform stands behind.
    """

    spec: StrategySpec

    def describe(self) -> StrategySpec: ...

    def entry_for(
        self, candidate: Candidate, *, cash_available: Decimal, now: datetime
    ) -> Entry | None:
        """The position to open, or `None` when this candidate is not eligible."""
        ...


@dataclass(frozen=True, slots=True)
class FixedSizeStrategy:
    """Equal weight: the same dollar amount into every eligible token.

    The default, and the one the numbers on the page describe. Equal weight is
    chosen because it is the only allocation that cannot flatter the Radar — any
    size that varies with score, confidence or base rate would mix a second
    opinion into a result presented as a test of the first.

    Exits are symmetric multiples of the entry price and an elapsed holding
    period, all fixed at entry. Whichever comes first wins; nothing here waits
    for a better price.
    """

    id: str
    name: str
    version: str
    trade_size_usd: Decimal
    take_profit_multiple: Decimal
    stop_loss_multiple: Decimal
    hold_for: timedelta
    top_n: int = DEFAULT_TOP_N
    operational: bool = True
    unavailable_reason: str | None = None

    @property
    def spec(self) -> StrategySpec:
        return self.describe()

    def describe(self) -> StrategySpec:
        """The rules, in the words the API serves and the page prints.

        Derived from the same fields `entry_for` applies, so the published rule
        and the executed rule cannot drift. A test asserts exactly this.
        """
        gain = (self.take_profit_multiple - 1) * 100
        loss = (1 - self.stop_loss_multiple) * 100
        hours = int(self.hold_for.total_seconds() // 3600)
        return StrategySpec(
            id=self.id,
            name=self.name,
            version=self.version,
            summary=(
                f"Buys ${self.trade_size_usd:,.0f} of a token the first time it "
                f"reaches the Radar's top {self.top_n}, and closes it at "
                f"+{gain:.0f}%, -{loss:.0f}%, or after {hours} hours - whichever "
                "happens first."
            ),
            rules=(
                Rule("Allocation", "Equal weight"),
                Rule("Trade size", f"${self.trade_size_usd:,.0f}"),
                Rule("Entry", f"First time a token enters the Radar top {self.top_n}"),
                Rule("Re-entry", "Never. One position per token, ever."),
                Rule("Take profit", f"+{gain:.0f}%"),
                Rule("Stop loss", f"-{loss:.0f}%"),
                Rule("Maximum hold", f"{hours} hours"),
                Rule("Exit priority", "Whichever rule is breached first"),
                Rule("Discretion", "None. No rule is applied by hand."),
            ),
            operational=self.operational,
            unavailable_reason=self.unavailable_reason,
        )

    def entry_for(
        self, candidate: Candidate, *, cash_available: Decimal, now: datetime
    ) -> Entry | None:
        """Size and bound one entry, or decline it.

        Declines rather than part-fills when cash is short. A wallet that
        quietly halved its size would report a return the published rule did not
        produce, and "we ran out of money" is a real, interesting outcome that
        the equity curve should show rather than absorb.
        """
        if not self.operational:
            return None
        if candidate.rank > self.top_n:
            return None
        if candidate.price_usd <= 0:
            # A token with no positive observed price cannot be sized. It is not
            # free; it is unpriced, and the two must never be confused.
            return None
        if cash_available < self.trade_size_usd:
            return None

        quantity = self.trade_size_usd / candidate.price_usd
        return Entry(
            mint_address=candidate.mint_address,
            price_usd=candidate.price_usd,
            size_usd=self.trade_size_usd,
            quantity=quantity,
            target_price=candidate.price_usd * self.take_profit_multiple,
            stop_price=candidate.price_usd * self.stop_loss_multiple,
            expires_at=now + self.hold_for,
            opened_at=now,
        )


#: The default, and the only operational strategy. Its numbers are the ones the
#: brief published: $100 equal weight, +100% / -50%, and a holding period that
#: matches the Opportunity Engine's own fresh-graduation TTL so a position is not
#: still running long after the signal that justified it has lapsed.
EQUAL_WEIGHT_V1 = FixedSizeStrategy(
    id="equal_weight_v1",
    name="Equal Weight v1",
    version="1.0.0",
    trade_size_usd=Decimal(100),
    take_profit_multiple=Decimal(2),
    stop_loss_multiple=Decimal("0.5"),
    hold_for=timedelta(hours=48),
)

#: Declared, not runnable. Registered so the interface is exercised by more than
#: one shape and so the page can say "one of four strategies runs" rather than
#: implying the architecture supports only what it currently does. Each states
#: why it is off; none of them is a recommendation, and none of them trades.
CONSERVATIVE_V1 = FixedSizeStrategy(
    id="conservative_v1",
    name="Conservative v1",
    version="1.0.0",
    trade_size_usd=Decimal(50),
    take_profit_multiple=Decimal("1.5"),
    stop_loss_multiple=Decimal("0.75"),
    hold_for=timedelta(hours=24),
    top_n=5,
    operational=False,
    unavailable_reason=(
        "Declared but not running. Only one strategy trades at a time, so that "
        "the wallet measures the Radar rather than a comparison between rules."
    ),
)

AGGRESSIVE_V1 = FixedSizeStrategy(
    id="aggressive_v1",
    name="Aggressive v1",
    version="1.0.0",
    trade_size_usd=Decimal(200),
    take_profit_multiple=Decimal(4),
    stop_loss_multiple=Decimal("0.4"),
    hold_for=timedelta(hours=72),
    operational=False,
    unavailable_reason=(
        "Declared but not running. Only one strategy trades at a time, so that "
        "the wallet measures the Radar rather than a comparison between rules."
    ),
)

HOLD_UNTIL_EXPIRY_V1 = FixedSizeStrategy(
    id="hold_until_expiry_v1",
    name="Hold Until Exit v1",
    version="1.0.0",
    trade_size_usd=Decimal(100),
    # No take profit and no stop in practice: the bounds are set beyond any
    # move this market produces, so only the holding period can close a trade.
    take_profit_multiple=Decimal(1_000_000),
    stop_loss_multiple=Decimal(0),
    hold_for=timedelta(days=30),
    operational=False,
    unavailable_reason=(
        "Declared but not running. Only one strategy trades at a time, so that "
        "the wallet measures the Radar rather than a comparison between rules."
    ),
)


class StrategyRegistry:
    """Every declared strategy, and the one that actually trades.

    Mirrors `opportunities.providers.registry`: declaration is separate from
    operation, so a strategy that exists and does not run is visible rather than
    absent.
    """

    def __init__(self, strategies: tuple[FixedSizeStrategy, ...], *, default: str) -> None:
        self._by_id = {strategy.id: strategy for strategy in strategies}
        if default not in self._by_id:
            raise ValueError(f"default strategy {default!r} is not registered")
        self._default = default

    def all(self) -> tuple[FixedSizeStrategy, ...]:
        return tuple(self._by_id.values())

    def get(self, strategy_id: str) -> FixedSizeStrategy | None:
        return self._by_id.get(strategy_id)

    @property
    def default(self) -> FixedSizeStrategy:
        return self._by_id[self._default]


registry = StrategyRegistry(
    (EQUAL_WEIGHT_V1, CONSERVATIVE_V1, AGGRESSIVE_V1, HOLD_UNTIL_EXPIRY_V1),
    default=EQUAL_WEIGHT_V1.id,
)
