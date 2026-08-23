"""The exit machinery, as one configurable rule set. **Pure.**

Ten strategies, one resolver. Every difference between S1 and S10 is a value in
`StrategyRules`; none of them is a branch written ten times. That is a
correctness property, not a tidiness one — ten hand-written resolvers would
drift, and a comparison between drifted implementations measures the drift.

── THE EXECUTION MODEL, STATED BEFORE IT IS USED ────────────────────────────

**Every fill books the price that was actually observed.** Not the rung's
level, not the trailing trigger, not the stop. This is the brief's rule (§5):
when the series jumps 1.10x → 1.80x, the rungs at 1.25, 1.50 and 1.75 were
never printed and never executable, so booking three fills at those levels
would invent liquidity at prices nobody could have traded. The position sells
at 1.80x — the first defensible executable observation — and all three rungs
are marked filled by it.

This is a **polling** model: the strategy sees a price and acts on it. It is
deliberately different from a resting-limit model (which fills a 1.25 rung at
1.25 regardless of the crossing print), and it is the right one here because
nothing in this platform rests an order anywhere. `MULTI_TARGET_POLICY` names
it so a reader can find it, and `batch_rung_fills` counts how often it mattered.

**Executability gates every fill except the ones that admit a loss.** A price
printed against a drained pool is a number. Rungs, trailing stops and decay
exits all require an executable quote. The six-hour expiry does not — when the
clock runs out on a dead pool, the position is marked at what the dead pool
prints and labelled, because refusing to mark a rug is how a strategy hides
what it lost.

── ORDERING WITHIN ONE OBSERVATION ──────────────────────────────────────────

Published, and adverse-first: **expiry, decay, trailing stop, rungs, then
arm-and-update**. One snapshot that satisfies several rules means the price
moved further than one reading can distinguish, and the honest reading of an
ambiguous bar is the one that does not book the win.

The last step is what makes profit-activated trailing work. A reading that
first reaches 1.50x sells S7's rung *and* arms its trail, and the trail's
high-water mark starts at that reading — so it cannot also fire on it. A single
snapshot cannot both set a high and fall away from it.

Pure: no I/O, no clock, no randomness. The replay is reproducible only because
this is.
"""

from __future__ import annotations

import enum
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal

_ZERO = Decimal(0)
_ONE = Decimal(1)

#: How a reading that crosses several rungs at once is filled. Named so it can
#: be quoted on every surface that reports a ladder result.
MULTI_TARGET_POLICY = "first_executable_observation"

MULTI_TARGET_POLICY_TEXT = (
    "Every rung at or below an observation's multiple fills at that "
    "observation's OBSERVED price, not at the rung's own level. A series that "
    "jumps 1.10x to 1.80x books one sale at 1.80x covering the 1.25x, 1.50x "
    "and 1.75x rungs, because those three prices were never printed and never "
    "executable. Price impact is charged on the combined order."
)

#: Below this depth a $25 exit moves the price more than 10% against itself, so
#: the print is a number rather than a fill. Derivable, and stated so a reader
#: can check it: constant-product impact is notional / (liquidity / 2), which
#: reaches 10% at $500 for a $25 order. The same floor `paper_v2.replay` uses,
#: restated here rather than imported so a change to V2 cannot silently restate
#: every Strategy Lab result ever published.
EXECUTABLE_FLOOR_USD = Decimal(500)


class FillReason(enum.StrEnum):
    """Why quantity left the position. One per cause, never inferred later."""

    #: A profit rung was reached and sold into an executable quote.
    TARGET = "target"
    #: A trailing stop fired after its activation gate had been passed.
    TRAILING_STOP = "trailing_stop"
    #: A time-decay rule found the position stagnant and freed the capital.
    TIME_DECAY = "time_decay"
    #: The hold clock ran out. Sells everything left, at what was printed.
    EXPIRY = "expiry"
    #: The clock ran out with no executable quote — the pool is gone. Marked at
    #: the collapsed print and flagged. This is not an escape.
    DEAD_POOL = "dead_pool"
    #: The series ended before the clock did and the last thing seen was
    #: already collapsed. Marked there, flagged, and reported separately.
    UNTRADABLE = "untradable"
    #: The series ended before the clock did while the pool still looked
    #: healthy. Nothing is known about the outcome. Marked at the last print
    #: and excluded from any figure that claims to be executable.
    DATA_UNAVAILABLE = "data_unavailable"


#: Fills that mark a position without claiming a trade happened.
NON_EXECUTABLE_REASONS = frozenset(
    {FillReason.DEAD_POOL, FillReason.UNTRADABLE, FillReason.DATA_UNAVAILABLE}
)


@dataclass(frozen=True, slots=True)
class Quote:
    """One observation. `executable` is the caller's depth judgement."""

    price_usd: Decimal
    captured_at: datetime
    liquidity_usd: Decimal | None = None
    executable: bool = True


@dataclass(frozen=True, slots=True)
class Rung:
    """Sell `fraction` of the **original** quantity at `multiple` of entry.

    Of the original, not of what is left: three 25% rungs off the original sell
    75% of the position, while three 25% rungs off the remainder sell 58%. Every
    ladder in the brief means the former.
    """

    multiple: Decimal
    fraction: Decimal


@dataclass(frozen=True, slots=True)
class TrailingRule:
    """A giveback stop, optionally gated on the position having proved itself.

    `activation_multiple=None` means armed from entry with the entry price as
    its first high — the shape the original Paper Wallet runs. A value means the
    position is left entirely alone until it prints that multiple, which is the
    hypothesis S7 and S8 exist to test: do not try to stop a newborn rug, only
    protect a gain that happened.
    """

    drawdown: Decimal
    activation_multiple: Decimal | None = None
    #: Fraction of the **remaining** quantity to sell when it fires. 1 closes.
    fraction: Decimal = _ONE

    def __post_init__(self) -> None:
        if not (_ZERO < self.drawdown < _ONE):
            raise ValueError("trailing drawdown must be a fraction between 0 and 1")
        if not (_ZERO < self.fraction <= _ONE):
            raise ValueError("trailing fraction must be in (0, 1]")


@dataclass(frozen=True, slots=True)
class DecayRule:
    """Free capital from a position that has gone nowhere. Deterministic.

    Read as: at `at` past entry, if the position has never printed an executable
    quote at or above `never_exceeded` **and** is currently at or below
    `at_or_below`, close it.

    The peak it tests is the *executable* peak. A 1.4x print against a $200 pool
    is not a gain the position could have taken, and letting it satisfy "has
    exceeded 1.20x" would keep dead capital alive on the strength of a number.
    """

    at: timedelta
    never_exceeded: Decimal
    at_or_below: Decimal


@dataclass(frozen=True, slots=True)
class StrategyRules:
    """The whole exit contract for one strategy. All fields optional.

    A rule set with no rungs, no trail and no decay is a pure hold to the clock,
    and that is exactly S5 — the control. Nothing special-cases it.
    """

    hold_for: timedelta
    rungs: tuple[Rung, ...] = ()
    trailing: TrailingRule | None = None
    decay: tuple[DecayRule, ...] = ()

    def __post_init__(self) -> None:
        multiples = [rung.multiple for rung in self.rungs]
        if multiples != sorted(multiples):
            raise ValueError("rungs must ascend")
        total = sum((rung.fraction for rung in self.rungs), _ZERO)
        if total > _ONE:
            raise ValueError(f"rungs sell {total} of the original position")
        ats = [rule.at for rule in self.decay]
        if ats != sorted(ats):
            raise ValueError("decay rules must ascend in time")

    @property
    def runner_fraction(self) -> Decimal:
        """What the rungs deliberately do not sell."""
        return _ONE - sum((rung.fraction for rung in self.rungs), _ZERO)


@dataclass(frozen=True, slots=True)
class Fill:
    """One sale. `price_usd` is what was got — always an observed print."""

    at: datetime
    price_usd: Decimal
    quantity: Decimal
    reason: FillReason
    liquidity_usd: Decimal | None = None
    #: Which rungs this one sale covered. Several when a reading gapped through
    #: more than one; empty for every non-rung reason.
    rung_indexes: tuple[int, ...] = ()
    #: The level that caused it — a rung's multiple, a trailing trigger price.
    #: Recorded so the gap between "what asked" and "what filled" is visible
    #: rather than lost.
    trigger_price: Decimal | None = None

    @property
    def gross_proceeds(self) -> Decimal:
        return self.quantity * self.price_usd

    @property
    def executable(self) -> bool:
        return self.reason not in NON_EXECUTABLE_REASONS


@dataclass(frozen=True, slots=True)
class Outcome:
    """Everything one pass over the series produced."""

    fills: tuple[Fill, ...]
    remaining_quantity: Decimal
    filled_rungs: frozenset[int]
    closed: bool
    #: Highest multiple printed at all, executable or not. What the token did.
    observed_peak_multiple: Decimal
    #: Highest multiple printed against a pool deep enough to sell into. What
    #: the position could actually have taken. The gap between the two is the
    #: difference between a chart and a fill.
    executable_peak_multiple: Decimal
    #: Multiple at the first observation at or after the clock ran out.
    terminal_multiple: Decimal | None
    #: How many fills covered more than one rung. The cost of the polling model,
    #: counted rather than assumed away.
    batch_rung_fills: int
    #: Carried out so a resume can cap its own settlements. See `_settle_at`.
    last_executable_price: Decimal | None


@dataclass(frozen=True, slots=True)
class Resume:
    """Everything a restart must be told rather than allowed to re-derive.

    Forward research evaluates a position many times, each pass seeing only the
    observations that arrived since the last one. Three facts are path-dependent
    and cannot be recovered from a partial series:

      * `filled_rungs` — a rung is a one-time event. Re-deriving it from prices
        would fire every rung again on the next pass.
      * `fired_decay` — same, for a decay deadline.
      * `armed` / `high` — the running high may have been set before the window
        this pass can see.

    The peaks are carried for the same reason: a decay rule tests "has never
    exceeded", which is a claim about the whole life of the position.

    `Resume()` with no arguments is a fresh position, which is exactly what the
    backtest passes — so both modes run the same resolver rather than two that
    have to be kept in agreement.
    """

    remaining_quantity: Decimal | None = None
    filled_rungs: frozenset[int] = frozenset()
    fired_decay: frozenset[int] = frozenset()
    armed: bool = False
    high: Decimal = _ZERO
    observed_peak_multiple: Decimal = _ZERO
    executable_peak_multiple: Decimal = _ZERO
    batch_rung_fills: int = 0
    last_executable_price: Decimal | None = None


@dataclass
class _State:
    """Mutable working state for one pass. Never escapes this module."""

    remaining: Decimal
    filled: set[int] = field(default_factory=set)
    fired_decay: set[int] = field(default_factory=set)
    armed: bool = False
    high: Decimal = _ZERO
    observed_peak: Decimal = _ZERO
    executable_peak: Decimal = _ZERO
    batch_fills: int = 0
    #: The last price printed against a pool deep enough to sell into. The
    #: ceiling for any settlement made after depth vanished — see `_settle_at`.
    last_executable_price: Decimal | None = None


def resolve(
    rules: StrategyRules,
    *,
    entry_price: Decimal,
    opened_at: datetime,
    initial_quantity: Decimal,
    quotes: Sequence[Quote],
    resume: Resume | None = None,
) -> Outcome:
    """Replay one position's forward series and return every fill it produced.

    The series must be the position's own forward observations, in ascending
    time. The caller owns that: this function reads them in the order given and
    never looks past the one it is on, which is what "no look-ahead" means in
    practice.

    `resume` carries the path-dependent state of a position that has been
    evaluated before. Omit it for a fresh position; the backtest always does.
    """
    if entry_price <= 0:
        raise ValueError("entry price must be positive")
    if initial_quantity <= 0:
        raise ValueError("initial quantity must be positive")

    expires_at = opened_at + rules.hold_for
    resume = resume or Resume()
    state = _State(
        remaining=(
            initial_quantity
            if resume.remaining_quantity is None
            else resume.remaining_quantity
        ),
        filled=set(resume.filled_rungs),
        fired_decay=set(resume.fired_decay),
        armed=resume.armed,
        high=resume.high,
        observed_peak=resume.observed_peak_multiple,
        executable_peak=resume.executable_peak_multiple,
        batch_fills=resume.batch_rung_fills,
        last_executable_price=resume.last_executable_price,
    )
    if (
        rules.trailing is not None
        and rules.trailing.activation_multiple is None
        and not state.armed
    ):
        # Armed from entry, with the entry price as its first high — nothing
        # was observed before it.
        state.armed = True
        state.high = entry_price

    fills: list[Fill] = []
    terminal: Decimal | None = None

    for quote in quotes:
        multiple = quote.price_usd / entry_price
        state.observed_peak = max(state.observed_peak, multiple)

        if quote.captured_at >= expires_at:
            if terminal is None:
                terminal = multiple
            if state.remaining > 0:
                executable = quote.executable
                fills.append(
                    Fill(
                        at=quote.captured_at,
                        price_usd=(
                            quote.price_usd
                            if executable
                            else _settle_at(quote, state.last_executable_price)
                        ),
                        quantity=state.remaining,
                        reason=FillReason.EXPIRY if executable else FillReason.DEAD_POOL,
                        liquidity_usd=quote.liquidity_usd,
                    )
                )
                state.remaining = _ZERO
            return _finish(state, fills, closed=True, terminal=terminal)

        if state.remaining <= 0:
            continue

        if not quote.executable:
            # Nothing sells into a pool nobody could sell into. The reading is
            # consumed — it just cannot lift a rung, fire a stop, or count
            # toward the peak a decay rule tests.
            continue

        state.executable_peak = max(state.executable_peak, multiple)
        state.last_executable_price = quote.price_usd
        elapsed = quote.captured_at - opened_at

        decay_fill = _decay(rules, state, quote, multiple, elapsed)
        if decay_fill is not None:
            fills.append(decay_fill)
            state.remaining = _ZERO
            return _finish(state, fills, closed=True, terminal=terminal)

        trail_fill = _trail(rules, state, quote)
        if trail_fill is not None:
            fills.append(trail_fill)
            state.remaining -= trail_fill.quantity
            if state.remaining <= 0:
                return _finish(state, fills, closed=True, terminal=terminal)

        rung_fill = _rungs(rules, state, quote, multiple, initial_quantity)
        if rung_fill is not None:
            fills.append(rung_fill)
            state.remaining -= rung_fill.quantity
            state.filled.update(rung_fill.rung_indexes)
            if len(rung_fill.rung_indexes) > 1:
                state.batch_fills += 1
            if state.remaining <= 0:
                return _finish(state, fills, closed=True, terminal=terminal)

        # Arm and raise the high LAST, so neither can act on the reading that
        # caused it. This is the line that makes profit-activated trailing a
        # protection rather than an instant exit.
        if (
            rules.trailing is not None
            and not state.armed
            and rules.trailing.activation_multiple is not None
            and multiple >= rules.trailing.activation_multiple
        ):
            state.armed = True
            state.high = quote.price_usd
        elif state.armed:
            state.high = max(state.high, quote.price_usd)

    return _finish(state, fills, closed=state.remaining <= 0, terminal=terminal)


def _settle_at(quote: Quote, last_executable: Decimal | None) -> Decimal:
    """The price a settlement against a non-executable pool may claim.

    **A print made after depth vanished is not a price.** The feed keeps
    reporting a number after a pool is drained, and that number is unconstrained
    in both directions: it can read near zero, and it can read 1286x. Booking
    the low one is the mistake §6 names — marking a rug at the last healthy
    price. Booking the high one is the same mistake inverted, and is worse,
    because it turns a total loss into the single largest profit in the result
    set. Both were observed in this dataset.

    So a non-executable settlement is capped at the last price the position
    could actually have sold into. It is never raised — a genuine collapse still
    marks at the collapsed print — only prevented from claiming a level that
    stopped being tradable. The bounded execution model then charges the sale
    against the depth that remains, which for a drained pool returns nothing at
    all. A rug ends at zero, which is what a rug is.
    """
    if last_executable is None:
        return quote.price_usd
    return min(quote.price_usd, last_executable)


def _decay(
    rules: StrategyRules,
    state: _State,
    quote: Quote,
    multiple: Decimal,
    elapsed: timedelta,
) -> Fill | None:
    for index, rule in enumerate(rules.decay):
        if index in state.fired_decay or elapsed < rule.at:
            continue
        state.fired_decay.add(index)
        if state.executable_peak < rule.never_exceeded and multiple <= rule.at_or_below:
            return Fill(
                at=quote.captured_at,
                price_usd=quote.price_usd,
                quantity=state.remaining,
                reason=FillReason.TIME_DECAY,
                liquidity_usd=quote.liquidity_usd,
            )
    return None


def _trail(rules: StrategyRules, state: _State, quote: Quote) -> Fill | None:
    if rules.trailing is None or not state.armed:
        return None
    trigger = state.high * (_ONE - rules.trailing.drawdown)
    if quote.price_usd > trigger:
        return None
    quantity = min(state.remaining, state.remaining * rules.trailing.fraction)
    if quantity <= 0:
        return None
    return Fill(
        at=quote.captured_at,
        price_usd=quote.price_usd,
        quantity=quantity,
        reason=FillReason.TRAILING_STOP,
        liquidity_usd=quote.liquidity_usd,
        trigger_price=trigger,
    )


def _rungs(
    rules: StrategyRules,
    state: _State,
    quote: Quote,
    multiple: Decimal,
    initial_quantity: Decimal,
) -> Fill | None:
    """Every unfilled rung this reading reached, as **one** sale at its price.

    One sale rather than several: they happen at the same instant against the
    same pool, so charging them as separate orders would understate the impact
    of the combined size. The rungs they cover are recorded on the fill.
    """
    hit = [
        index
        for index, rung in enumerate(rules.rungs)
        if index not in state.filled and rung.multiple <= multiple
    ]
    if not hit:
        return None
    wanted = sum((rules.rungs[i].fraction for i in hit), _ZERO) * initial_quantity
    quantity = min(state.remaining, wanted)
    if quantity <= 0:
        return None
    return Fill(
        at=quote.captured_at,
        price_usd=quote.price_usd,
        quantity=quantity,
        reason=FillReason.TARGET,
        liquidity_usd=quote.liquidity_usd,
        rung_indexes=tuple(hit),
        trigger_price=rules.rungs[hit[-1]].multiple * (quote.price_usd / multiple),
    )


def _finish(
    state: _State, fills: list[Fill], *, closed: bool, terminal: Decimal | None
) -> Outcome:
    return Outcome(
        fills=tuple(fills),
        remaining_quantity=state.remaining,
        filled_rungs=frozenset(state.filled),
        closed=closed,
        observed_peak_multiple=state.observed_peak,
        executable_peak_multiple=state.executable_peak,
        terminal_multiple=terminal,
        batch_rung_fills=state.batch_fills,
        last_executable_price=state.last_executable_price,
    )


def settle_unobserved(
    *,
    remaining_quantity: Decimal,
    last_quote: Quote | None,
    at: datetime,
    last_executable_price: Decimal | None = None,
) -> Fill | None:
    """Mark a position whose clock ran out with no observation to close it on.

    Separate from `resolve` because it is not a rule the market triggered — it
    is the caller admitting the series ran out. The two labels matter and are
    not interchangeable: a last print against a collapsed pool is a real loss
    (`UNTRADABLE`), while a last print against a healthy pool tells us nothing
    at all about what happened next (`DATA_UNAVAILABLE`) and must never be
    counted as a successful exit at that price.
    """
    if remaining_quantity <= 0 or last_quote is None:
        return None
    executable = last_quote.executable
    reason = FillReason.DATA_UNAVAILABLE if executable else FillReason.UNTRADABLE
    return Fill(
        at=at,
        price_usd=(
            last_quote.price_usd
            if executable
            else _settle_at(last_quote, last_executable_price)
        ),
        quantity=remaining_quantity,
        reason=reason,
        liquidity_usd=last_quote.liquidity_usd,
    )
