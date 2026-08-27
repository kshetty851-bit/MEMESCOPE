"""Real exits: the trigger decides *when*, an executable quote decides *at what*.

## The distinction this module exists to keep

Paper's `app.paper.exits.resolve` already draws it correctly — a stop fills at
the observed market price that breached it, never at the level itself, because
a stop decides when to sell and does not conjure a buyer at the trigger. The
one way for a real wallet to contradict its own paper track record is to assume
the stop level *is* the fill.

So the trigger is not reimplemented here. `resolve` is imported and called with
the same `ExitRules`, the same published adverse-first ordering, and the same
observation series. That is the whole of the "when". Reimplementing it would
produce two exit engines whose disagreement nobody would notice until a real
position closed at a price the paper record says was impossible.

What is added is only the second half, which paper does not need: once a trigger
fires, a real exit is worth nothing without a route. This turns the trigger into
an *executable* decision, or into an explicit named failure.

## Why a failure is a state and not a retry

`NO_ROUTE`, `QUOTE_STALE` and `PRICE_IMPACT_EXCEEDED` are outcomes, not errors
to swallow. A position whose stop fired and whose exit could not execute is the
single most important thing this system can tell an operator, and a silent
retry loop is how that fact gets hidden. The caller records the state and the
position stays open with a fired trigger — visible, not resolved.

Small real slippage is expected and accepted: the executable price is compared
against the trigger only to *report* the divergence, never to refuse the exit.
Refusing to sell because the market moved is how a stop becomes unbounded.

Nothing here signs, submits, or holds a signer. Pure apart from the quote
callback the caller supplies.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from app.paper.exits import ExitRules, resolve
from app.paper.models import Exit, ExitReason, Quote


class ExitFailure(StrEnum):
    """Why a fired trigger could not become an executable exit."""

    NO_ROUTE = "EXIT_NO_ROUTE"
    QUOTE_STALE = "EXIT_QUOTE_STALE"
    QUOTE_UNAVAILABLE = "EXIT_QUOTE_UNAVAILABLE"
    PRICE_IMPACT_EXCEEDED = "EXIT_PRICE_IMPACT_EXCEEDED"
    SLIPPAGE_ABOVE_POLICY = "EXIT_SLIPPAGE_ABOVE_POLICY"
    QUANTITY_NOT_CONFIRMED = "EXIT_QUANTITY_NOT_CONFIRMED"


@dataclass(frozen=True, slots=True)
class ExecutableQuote:
    """A sell quote fresh enough to act on, as the caller measured it."""

    quoted_at: datetime
    #: Raw base units the route would return for the whole position.
    output_amount_raw: int
    #: Price per token implied by the route, in the output mint's unit.
    executable_price: Decimal | None
    price_impact_pct: Decimal | None
    slippage_bps: int
    has_route: bool


@dataclass(frozen=True, slots=True)
class ExitPolicy:
    """Freshness and impact bounds a real exit quote must satisfy."""

    max_quote_age_seconds: int
    max_price_impact_pct: Decimal
    max_slippage_bps: int


@dataclass(frozen=True, slots=True)
class ExitDecision:
    """What the trigger said, and whether it can actually be executed."""

    #: `None` when no rule was breached — the position simply stays open.
    triggered: Exit | None
    #: The running high, carried into the next evaluation for the trailing stop.
    peak: Decimal
    executable: bool
    reason_codes: tuple[str, ...]
    #: The price the exit would actually fill at, from the route — never the
    #: trigger level. `None` whenever the exit is not executable.
    executable_price: Decimal | None = None
    #: Trigger minus executable, as a fraction of the trigger. Reported, never
    #: enforced: real slippage on a real exit is expected.
    observed_slippage_pct: Decimal | None = None

    @property
    def reason(self) -> ExitReason | None:
        return None if self.triggered is None else self.triggered.reason


def decide(
    rules: ExitRules,
    *,
    entry_price: Decimal,
    opened_at: datetime,
    quotes: Sequence[Quote],
    peak: Decimal | None = None,
    quote: ExecutableQuote | None,
    policy: ExitPolicy,
    now: datetime,
    quantity_confirmed: bool = True,
) -> ExitDecision:
    """Resolve the trigger with paper's rules, then price it with a real route.

    `quote` is `None` when the caller could not obtain one at all — an
    availability failure, reported as `QUOTE_UNAVAILABLE` rather than treated
    as "no exit needed".
    """
    triggered, running = resolve(
        rules, entry_price=entry_price, opened_at=opened_at, quotes=quotes, peak=peak
    )
    if triggered is None:
        return ExitDecision(None, running, executable=False, reason_codes=())

    reasons: list[str] = []
    # A sell must offer the exact confirmed on-chain quantity, for the same
    # reason `order_evidence` insists on it: an exit sized from an assumed
    # balance fails on chain after the fee has already been paid.
    if not quantity_confirmed:
        reasons.append(ExitFailure.QUANTITY_NOT_CONFIRMED)
    if quote is None:
        reasons.append(ExitFailure.QUOTE_UNAVAILABLE)
        return ExitDecision(triggered, running, False, tuple(reasons))

    if not quote.has_route or quote.output_amount_raw <= 0:
        reasons.append(ExitFailure.NO_ROUTE)
    age = (now - quote.quoted_at).total_seconds()
    if age < 0 or age > policy.max_quote_age_seconds:
        reasons.append(ExitFailure.QUOTE_STALE)
    if quote.slippage_bps < 0 or quote.slippage_bps > policy.max_slippage_bps:
        reasons.append(ExitFailure.SLIPPAGE_ABOVE_POLICY)
    # Jupiter reports a fraction; the policy is written in percent. A missing
    # impact figure is not treated as zero impact — it is simply not this
    # check's business, and `NO_ROUTE` below catches an unusable quote.
    if (
        quote.price_impact_pct is not None
        and abs(quote.price_impact_pct) * 100 > policy.max_price_impact_pct
    ):
        reasons.append(ExitFailure.PRICE_IMPACT_EXCEEDED)
    if quote.executable_price is None or quote.executable_price <= 0:
        reasons.append(ExitFailure.NO_ROUTE)

    if reasons:
        return ExitDecision(triggered, running, False, tuple(dict.fromkeys(reasons)))

    executable_price = quote.executable_price
    assert executable_price is not None
    trigger_level = triggered.trigger_price or triggered.price_usd
    divergence = (
        None if trigger_level <= 0 else (trigger_level - executable_price) / trigger_level
    )
    return ExitDecision(
        triggered=triggered,
        peak=running,
        executable=True,
        reason_codes=(),
        executable_price=executable_price,
        observed_slippage_pct=divergence,
    )


def emergency_exit(*, at: datetime, quote: ExecutableQuote | None) -> ExitDecision:
    """A manual override, priced by the same route rules as an automated exit.

    Deliberately still requires an executable quote. "Emergency" changes who
    decided to sell; it does not change whether anybody is buying.
    """
    triggered = Exit(
        price_usd=Decimal(0) if quote is None else (quote.executable_price or Decimal(0)),
        at=at,
        reason=ExitReason.MANUAL,
    )
    if quote is None or not quote.has_route or not quote.executable_price:
        return ExitDecision(triggered, Decimal(0), False, (ExitFailure.NO_ROUTE,))
    return ExitDecision(
        triggered=triggered,
        peak=Decimal(0),
        executable=True,
        reason_codes=(),
        executable_price=quote.executable_price,
    )
