"""Exit rules, as data rather than as code.

Exit rules are data rather than duplicated control flow. The varying rule is
a value that can be enumerated, not a function that has to be written repeatedly.

**Equal Weight v1's behaviour is frozen.** It is the permanent benchmark, and a
benchmark that moved when the code was refactored would silently restate every
comparison drawn against it. `BASELINE` below is the same bracket the live
wallet has always applied, and `test_paper_exits.py` asserts this module agrees
with the original `engine.resolve_exit` across the whole space of orderings.

Pure. No I/O, no clock, no randomness — the replay is only reproducible because
this is.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from app.paper.models import Exit, ExitReason, Quote

#: A trailing stop needs a running high, and the high a position carries into a
#: replay is its entry price — nothing was observed before it.
_NO_TRAIL = None


@dataclass(frozen=True, slots=True)
class ExitRules:
    """When a position closes. Every field optional; absent means "no such rule".

    Four independent rules, checked in a published order. Every strategy in the
    lab is one of these, and the *only* thing that differs between them.

    A rule set with nothing set at all never closes a position. That is legal
    and it is measurable: the position stays open and the replay reports it as
    open rather than inventing a close.
    """

    #: Multiple of entry at which to take profit. 2 means +100%.
    take_profit_multiple: Decimal | None = None
    #: Multiple of entry at which to stop out. 0.5 means -50%.
    stop_loss_multiple: Decimal | None = None
    #: Fraction below the running high at which to stop out. 0.25 means "exit
    #: once the price has given back a quarter of its best level".
    trailing_drawdown: Decimal | None = None
    #: How long a position may stay open before it closes at the next reading.
    hold_for: timedelta | None = None

    def target_price(self, entry: Decimal) -> Decimal | None:
        if self.take_profit_multiple is None:
            return None
        return entry * self.take_profit_multiple

    def stop_price(self, entry: Decimal) -> Decimal | None:
        if self.stop_loss_multiple is None:
            return None
        return entry * self.stop_loss_multiple


def resolve(
    rules: ExitRules,
    *,
    entry_price: Decimal,
    opened_at: datetime,
    quotes: Sequence[Quote],
    peak: Decimal | None = _NO_TRAIL,
) -> tuple[Exit | None, Decimal]:
    """The first rule breached, and the running high, from one pass of the series.

    Returns `(exit_or_none, peak)`. The peak is returned even when nothing
    closed, because a trailing stop needs it carried into the next evaluation
    and because "how high did this get before it exited" is one of the figures
    that actually explains why a rule wins or loses.

    **Order within a single reading is published and adverse-first**: expiry,
    then the fixed stop, then the trailing stop, then the target. A snapshot
    that satisfies more than one bound means the price moved further than one
    reading can distinguish, and the honest reading of an ambiguous bar is the
    one that does not book a win the data cannot support.

    Order *across* readings is chronological, and that is the whole algorithm:
    the earliest breach wins, so a token that hit its stop on Tuesday and its
    target on Wednesday is a loss. Scanning for the best outcome instead would
    be hindsight.

    Expiry is measured against each observation's own timestamp, never against
    a wall clock, so a position that should have closed at noon closes at noon's
    price however late it was evaluated.
    """
    running = entry_price if peak is None else peak
    expires_at = None if rules.hold_for is None else opened_at + rules.hold_for
    target = rules.target_price(entry_price)
    stop = rules.stop_price(entry_price)

    for quote in quotes:
        if expires_at is not None and quote.captured_at >= expires_at:
            return (
                Exit(
                    price_usd=quote.price_usd,
                    at=quote.captured_at,
                    reason=ExitReason.EXPIRY,
                ),
                running,
            )

        if stop is not None and quote.price_usd <= stop:
            # Fills at the observed price, not at the stop. `quote.price_usd`
            # is at or below `stop` by the condition above, so this is never
            # better than the market and is usually identical — it only
            # diverges when the price gapped through, which is exactly the
            # case that used to book a fill nobody could have got.
            return (
                Exit(
                    price_usd=quote.price_usd,
                    at=quote.captured_at,
                    reason=ExitReason.STOP,
                    trigger_price=stop,
                ),
                running,
            )

        if rules.trailing_drawdown is not None:
            # Measured against the high *before* this reading. A single snapshot
            # cannot both set a new high and fall away from it, and treating it
            # as though it could would book an exit at a level never observed.
            trigger = running * (Decimal(1) - rules.trailing_drawdown)
            if quote.price_usd <= trigger:
                # Same rule as the fixed stop: the trigger says *when*, the
                # observation says *what*. This is the line that produced the
                # gap-through overstatement.
                return (
                    Exit(
                        price_usd=quote.price_usd,
                        at=quote.captured_at,
                        reason=ExitReason.STOP,
                        trigger_price=trigger,
                    ),
                    running,
                )

        if target is not None and quote.price_usd >= target:
            # The target is correct here and deliberately unchanged. A
            # take-profit limit fills at the level it asked for; booking the
            # observed price would claim the *upside* of a gap, which is the
            # same error in the opposite direction.
            return (
                Exit(
                    price_usd=target,
                    at=quote.captured_at,
                    reason=ExitReason.TARGET,
                    trigger_price=target,
                ),
                running,
            )

        if quote.price_usd > running:
            running = quote.price_usd

    return None, running


# --- The published rule sets ---------------------------------------------------

#: **Frozen.** The live wallet's bracket, and the permanent benchmark every
#: other rule is measured against. Changing these numbers would restate every
#: comparison ever drawn against it, so they are not tuning parameters.
BASELINE = ExitRules(
    take_profit_multiple=Decimal(2),
    stop_loss_multiple=Decimal("0.5"),
    hold_for=timedelta(hours=48),
)


@dataclass(frozen=True, slots=True)
class LabStrategy:
    """One published rule set, named and described for the lab.

    `is_baseline` marks the one every other is compared against. Exactly one
    strategy carries it, asserted by test — a comparison table with two
    baselines, or none, is not a comparison.
    """

    id: str
    name: str
    description: str
    rules: ExitRules
    is_baseline: bool = False

    def published_rules(self) -> tuple[tuple[str, str], ...]:
        """The rules as label/value pairs, rendered from the values applied.

        Derived from `rules` rather than written out beside it, so the published
        description and the executed rule cannot drift.
        """
        out: list[tuple[str, str]] = []
        if self.rules.take_profit_multiple is not None:
            gain = (self.rules.take_profit_multiple - 1) * 100
            out.append(("Take profit", f"+{gain:.0f}%"))
        else:
            out.append(("Take profit", "None"))

        if self.rules.stop_loss_multiple is not None:
            loss = (1 - self.rules.stop_loss_multiple) * 100
            out.append(("Stop loss", f"-{loss:.0f}%"))
        else:
            out.append(("Stop loss", "None"))

        if self.rules.trailing_drawdown is not None:
            out.append(
                ("Trailing stop", f"-{self.rules.trailing_drawdown * 100:.0f}% from high")
            )
        else:
            out.append(("Trailing stop", "None"))

        if self.rules.hold_for is not None:
            total = int(self.rules.hold_for.total_seconds())
            out.append(
                (
                    "Maximum hold",
                    f"{total // 86_400} days"
                    if total >= 86_400
                    else f"{total // 3_600} hours",
                )
            )
        else:
            out.append(("Maximum hold", "None"))

        out.append(("Exit priority", "Expiry, stop, trailing stop, then target"))
        return tuple(out)


LAB_STRATEGIES: tuple[LabStrategy, ...] = (
    LabStrategy(
        id="equal_weight_v1",
        name="Equal Weight v1",
        description=(
            "The live wallet's **exit** rule, and the permanent benchmark. "
            "Frozen: its numbers are never tuned, because every comparison here "
            "is drawn against them. It is not the wallet's *entry* rule — see "
            "the entry note above, which is why this figure and the wallet's "
            "ROI are not the same number and must not be compared directly."
        ),
        rules=BASELINE,
        is_baseline=True,
    ),
    LabStrategy(
        id="hold_until_expiry",
        name="Hold Until Expiry",
        description=(
            "No target and no stop. Isolates how much of the baseline's result "
            "the exits themselves cause, rather than the entries."
        ),
        rules=ExitRules(hold_for=timedelta(hours=48)),
    ),
    LabStrategy(
        id="no_stop_loss",
        name="No Stop Loss",
        description="The baseline's target and holding period, with the stop removed.",
        rules=ExitRules(take_profit_multiple=Decimal(2), hold_for=timedelta(hours=48)),
    ),
    LabStrategy(
        id="take_profit_only",
        name="Take Profit Only",
        description=(
            "Target alone: no stop and no time limit. A position that never "
            "doubles is reported as still open rather than closed at a price "
            "no rule chose."
        ),
        rules=ExitRules(take_profit_multiple=Decimal(2)),
    ),
    LabStrategy(
        id="trailing_25",
        name="Trailing Stop 25%",
        description="Exits once the price has given back a quarter of its best level.",
        rules=ExitRules(trailing_drawdown=Decimal("0.25"), hold_for=timedelta(hours=48)),
    ),
    LabStrategy(
        id="trailing_40",
        name="Trailing Stop 40%",
        description="Exits once the price has given back two fifths of its best level.",
        rules=ExitRules(trailing_drawdown=Decimal("0.40"), hold_for=timedelta(hours=48)),
    ),
    LabStrategy(
        id="time_24h",
        name="Time Exit 24h",
        description="Closes at the first reading past 24 hours, whatever the price.",
        rules=ExitRules(hold_for=timedelta(hours=24)),
    ),
    LabStrategy(
        id="time_72h",
        name="Time Exit 72h",
        description="Closes at the first reading past 72 hours, whatever the price.",
        rules=ExitRules(hold_for=timedelta(hours=72)),
    ),
    LabStrategy(
        id="time_7d",
        name="Time Exit 7d",
        description="Closes at the first reading past seven days, whatever the price.",
        rules=ExitRules(hold_for=timedelta(days=7)),
    ),
)

#: Declared and **not implemented**, with the reason. An ATR trailing stop needs
#: a true range, which needs a high and a low per period. `token_market_snapshots`
#: stores one price per observation and no OHLC, so an ATR computed here would be
#: a proxy wearing ATR's name — and a lab whose rules are not what they claim is
#: worse than a lab with fewer rules.
UNAVAILABLE_STRATEGIES: tuple[tuple[str, str, str], ...] = (
    (
        "atr_trailing",
        "ATR Trailing Stop",
        "Not implemented. An ATR needs a true range — a high and a low per "
        "period — and this platform stores a single price per observation with "
        "no OHLC. Any ATR computed from it would be a proxy under ATR's name.",
    ),
)


def baseline() -> LabStrategy:
    for strategy in LAB_STRATEGIES:
        if strategy.is_baseline:
            return strategy
    raise RuntimeError("no baseline strategy is registered")  # pragma: no cover
