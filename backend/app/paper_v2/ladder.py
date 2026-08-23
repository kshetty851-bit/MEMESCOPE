"""Paper Wallet V2's exit rule: a profit ladder and a hard clock. **Pure.**

V1 sells a position once. V2 sells it up to four times, so the resolver returns
a *list* of fills and the quantity still held, rather than one `Exit`.

── THE EXECUTION MODEL, STATED BEFORE IT IS USED ────────────────────────────

Two fill conventions, and they are deliberately different. This is the same
asymmetry `paper.exits` publishes, for the same reason.

  * **A rung fills at its own multiple, never at the observation that crossed
    it.** A reading of 1.80x that crosses 1.25x, 1.50x and 1.75x books three
    fills at 1.25, 1.50 and 1.75 — not three fills at 1.80. A resting limit
    sell fills at the level it asked for; booking the crossing print would
    claim the upside of a gap the wallet never had a chance to take.
  * **The expiry fills at the observed price.** At six hours the position sells
    whatever the market is, however bad. Booking the trigger here would claim
    an escape from a gap down, which is the same error pointing the other way.

Conservative in both directions: never claim a gap's upside, never dodge its
downside.

── EXECUTABILITY ────────────────────────────────────────────────────────────

A rung only fills on a quote the wallet could actually have sold into. A price
printed against a drained pool is a number, not an exit, and letting a rug's
final tick "hit" 1.75x on the way down would manufacture profit out of a
collapse. `Quote.executable` carries that judgement; this module only reads it.

The expiry is not gated the same way, and that is the point of the experiment:
when the pool is dead the position is marked at what the dead pool prints, and
the fill is labelled so the loss is attributable rather than hidden.

── IDEMPOTENCE ──────────────────────────────────────────────────────────────

`already_filled` is passed in and the caller stores it. A rung is a one-time
event, and a resolver that re-derived which rungs had fired from the price
series would fire them all again on every restart. The caller owns the fact.

Pure: no I/O, no clock, no randomness. The replay is only reproducible because
this is.
"""

from __future__ import annotations

import enum
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

_ZERO = Decimal(0)


class FillReason(enum.StrEnum):
    """Why a quantity left the position. One per cause, never inferred later."""

    #: A profit rung was reached and sold into an executable quote.
    TARGET = "target"
    #: The six-hour clock ran out. Sells everything left, at what was printed.
    EXPIRY = "expiry"
    #: Expiry reached with no executable quote — the pool is gone. The quantity
    #: is marked at the last print and flagged; it is not an escape.
    DEAD_POOL = "dead_pool"
    #: Expiry reached and *no* quote exists at or after it. Nothing was
    #: observed, so nothing is claimed; the caller must treat this as unsettled.
    UNTRADABLE = "untradable"


@dataclass(frozen=True, slots=True)
class Quote:
    """One observation. `executable` is the caller's depth judgement."""

    price_usd: Decimal
    captured_at: datetime
    liquidity_usd: Decimal | None = None
    executable: bool = True


@dataclass(frozen=True, slots=True)
class Rung:
    """Sell `fraction` of the **original** quantity when price reaches `multiple`.

    Of the original, not of what is left: three 25% rungs off the original are
    75% of the position, while three 25% rungs off the remainder are 58%. The
    published ladder means the former.
    """

    multiple: Decimal
    fraction: Decimal


@dataclass(frozen=True, slots=True)
class LadderRules:
    """The whole V2 exit contract."""

    rungs: tuple[Rung, ...]
    hold_for: timedelta

    def __post_init__(self) -> None:
        if not self.rungs:
            raise ValueError("a ladder with no rungs is not a ladder")
        multiples = [rung.multiple for rung in self.rungs]
        if multiples != sorted(multiples):
            raise ValueError("rungs must ascend")
        total = sum((rung.fraction for rung in self.rungs), _ZERO)
        if total > Decimal(1):
            raise ValueError(f"rungs sell {total} of the original position")

    @property
    def runner_fraction(self) -> Decimal:
        """What the ladder deliberately does not sell, left for the expiry."""
        return Decimal(1) - sum((rung.fraction for rung in self.rungs), _ZERO)


@dataclass(frozen=True, slots=True)
class Fill:
    """One sale. `price_usd` is what was got; `observed_price` is what printed."""

    at: datetime
    price_usd: Decimal
    quantity: Decimal
    reason: FillReason
    observed_price: Decimal
    liquidity_usd: Decimal | None = None
    #: Index into `LadderRules.rungs`, or `None` for a clock-driven exit.
    rung_index: int | None = None

    @property
    def gross_proceeds(self) -> Decimal:
        return self.quantity * self.price_usd


@dataclass(frozen=True, slots=True)
class LadderOutcome:
    """Everything one pass produced."""

    fills: tuple[Fill, ...]
    remaining_quantity: Decimal
    filled_rungs: frozenset[int]
    #: True once the position is finished and must never be evaluated again.
    closed: bool


def resolve(
    rules: LadderRules,
    *,
    entry_price: Decimal,
    opened_at: datetime,
    initial_quantity: Decimal,
    remaining_quantity: Decimal,
    quotes: Sequence[Quote],
    already_filled: frozenset[int] = frozenset(),
) -> LadderOutcome:
    """Every fill this series produces, in order, and what is left after them.

    Order within a single reading is published and adverse-first, matching
    `paper.exits`: **expiry, then rungs**. A quote at or past the cutoff closes
    the position at that quote and books no rung from it, because a reading
    that is simultaneously "past six hours" and "up 25%" cannot be resolved
    into an ordering by one snapshot, and the honest reading of an ambiguous
    bar is the one that does not book the win.
    """
    if entry_price <= 0:
        raise ValueError("entry price must be positive")

    expires_at = opened_at + rules.hold_for
    filled = set(already_filled)
    left = remaining_quantity
    fills: list[Fill] = []

    for quote in quotes:
        if left <= 0:
            break

        if quote.captured_at >= expires_at:
            reason = FillReason.EXPIRY if quote.executable else FillReason.DEAD_POOL
            fills.append(
                Fill(
                    at=quote.captured_at,
                    price_usd=quote.price_usd,
                    quantity=left,
                    reason=reason,
                    observed_price=quote.price_usd,
                    liquidity_usd=quote.liquidity_usd,
                )
            )
            return LadderOutcome(tuple(fills), _ZERO, frozenset(filled), True)

        if not quote.executable:
            # Nothing sells into a pool nobody could sell into. The reading is
            # still consumed — it simply cannot lift a rung.
            continue

        multiple = quote.price_usd / entry_price
        for index, rung in enumerate(rules.rungs):
            if index in filled or rung.multiple > multiple:
                continue
            quantity = min(left, initial_quantity * rung.fraction)
            if quantity <= 0:
                continue
            fills.append(
                Fill(
                    at=quote.captured_at,
                    # The rung's own level, not the crossing print.
                    price_usd=entry_price * rung.multiple,
                    quantity=quantity,
                    reason=FillReason.TARGET,
                    observed_price=quote.price_usd,
                    liquidity_usd=quote.liquidity_usd,
                    rung_index=index,
                )
            )
            filled.add(index)
            left -= quantity

    return LadderOutcome(tuple(fills), left, frozenset(filled), False)


def settle_unobserved(
    *, remaining_quantity: Decimal, last_quote: Quote | None, at: datetime
) -> Fill | None:
    """Close a position whose expiry passed with no observation to close it on.

    Separate from `resolve` because it is not a rule the market triggered — it
    is the caller admitting the series ran out. The quantity is marked at the
    last thing seen and labelled `UNTRADABLE`, so it can be excluded from any
    figure that claims to be executable.
    """
    if remaining_quantity <= 0 or last_quote is None:
        return None
    return Fill(
        at=at,
        price_usd=last_quote.price_usd,
        quantity=remaining_quantity,
        reason=FillReason.UNTRADABLE,
        observed_price=last_quote.price_usd,
        liquidity_usd=last_quote.liquidity_usd,
    )


#: ── VARIANT NAMES ───────────────────────────────────────────────────────────
#:
#: The brief names the primary ladder "Variant C" in its strategy section and
#: "B" in its backtest table. The backtest table wins, because that is the
#: comparison being reported. So: **B is the primary V2 strategy** — three
#: rungs and a runner — and the collision is written down here rather than left
#: for a reader to trip over.
#:
#: Written in code rather than read from configuration for the reason V1
#: freezes its bracket: a ladder re-read after the fact could be re-read
#: favourably.

#: **B — the published V2 ladder.** 25% at each of three rungs, and a quarter
#: left running to the six-hour clock.
VARIANT_B = LadderRules(
    rungs=(
        Rung(multiple=Decimal("1.25"), fraction=Decimal("0.25")),
        Rung(multiple=Decimal("1.50"), fraction=Decimal("0.25")),
        Rung(multiple=Decimal("1.75"), fraction=Decimal("0.25")),
    ),
    hold_for=timedelta(hours=6),
)

#: C — the same three rungs with **no runner**: the last quarter sells at 2x if
#: it gets there, and otherwise still meets the clock.
VARIANT_C = LadderRules(
    rungs=(
        Rung(multiple=Decimal("1.25"), fraction=Decimal("0.25")),
        Rung(multiple=Decimal("1.50"), fraction=Decimal("0.25")),
        Rung(multiple=Decimal("1.75"), fraction=Decimal("0.25")),
        Rung(multiple=Decimal("2.00"), fraction=Decimal("0.25")),
    ),
    hold_for=timedelta(hours=6),
)

#: D — a wider third rung at 2x, runner kept.
VARIANT_D = LadderRules(
    rungs=(
        Rung(multiple=Decimal("1.25"), fraction=Decimal("0.25")),
        Rung(multiple=Decimal("1.50"), fraction=Decimal("0.25")),
        Rung(multiple=Decimal("2.00"), fraction=Decimal("0.25")),
    ),
    hold_for=timedelta(hours=6),
)

#: What the live V2 service runs if it is ever activated.
PRIMARY = VARIANT_B
