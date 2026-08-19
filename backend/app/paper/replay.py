"""Replaying V1.0 exits, and pricing them two ways.

V1.1 research, Checkpoint 2. Checkpoint 1 established that the historical record
books every trailing-stop exit at the *trigger level* rather than at the price
that triggered it. On this dataset that is not a rounding convention: 76% of
stop exits were booked above the observed quote, by a median of 16.9%, and the
average stop exit reads -4.5% instead of -45.4%.

That convention is disclosed in `exits.py` and it is not a bug. It is, however,
fatal to exit-rule research, because a tighter rule triggers more often on gaps
and therefore harvests *more* of the synthetic premium — the bias points the
same way as the conclusion.

So this module separates two things the original checkpoint conflated:

**Signal fidelity** — can stored snapshots reproduce *when* and *why* V1.0
exited? This decides whether the paths support rule experiments at all.

**Fill fidelity** — what price was actually available at that moment? This is a
modelling choice, measured rather than assumed, and it is where the two
conventions differ.

## Why `exits.resolve` is reused rather than reimplemented

The signal half must be the *same code* the wallet ran, or a match proves
nothing about the wallet. `resolve` is pure and already returns the triggering
timestamp, so the observed fill is a lookup against that timestamp rather than a
second walk of the series with its own subtly different comparisons.

Nothing here mutates a position. The historical record stays exactly as
published; these are alternative arithmetic over the same rows.

Pure: no I/O, no clock, no randomness.
"""

from __future__ import annotations

import enum
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from app.paper import costs
from app.paper.exits import ExitRules, resolve
from app.paper.models import ExitReason, Quote

#: Disclosed on every observed-fill result. The fill is the first price at which
#: the rule is *known* to have breached — not the trigger level, and not a
#: better price found by searching forward.
OBSERVED_FILL_NOTE = "EXECUTION_AT_FIRST_OBSERVED_BREACH"

#: Disclosed alongside it. Between two observations the price is unobserved, so
#: neither convention can claim to be the true executable price.
RESOLUTION_NOTE = "SNAPSHOT_RESOLUTION_ONLY"

#: Tolerance for calling two prices "the same" during reconciliation. Prices are
#: stored at high precision and the arithmetic differs slightly between the live
#: engine and this replay; a relative epsilon avoids reporting a mismatch that is
#: only a rounding artefact.
_PRICE_EPSILON = Decimal("0.0001")

#: Timestamp equality tolerance in seconds. Exits are stamped with a snapshot's
#: own `captured_at`, so an exact match is expected; the tolerance exists to
#: distinguish "same observation" from "a different observation nearby".
TIMESTAMP_TOLERANCE_SECONDS = 1


class FillModel(enum.StrEnum):
    """How an exit is priced once the rule has breached."""

    #: V1.0's convention: fill at the mathematical trigger. Preserved for
    #: reconciliation and sensitivity only — never for ranking candidates.
    LEGACY_TRIGGER = "legacy_trigger_fill_v1"
    #: The research convention: fill at the observed price of the snapshot that
    #: revealed the breach.
    OBSERVED_SNAPSHOT = "observed_snapshot_v1"


class Mismatch(enum.StrEnum):
    """Why a replayed exit does not correspond to the recorded one."""

    #: Replay found no exit; the recorded position closed anyway.
    NO_REPLAY_EXIT = "no_replay_exit"
    #: Replay closed the position; the record did not.
    UNEXPECTED_REPLAY_EXIT = "unexpected_replay_exit"
    #: Different rule fired.
    RULE_DIFFERS = "rule_differs"
    #: Same rule, different observation.
    TIMESTAMP_DIFFERS = "timestamp_differs"
    #: A human closed the position. Not a strategy signal and never counted as a
    #: replay failure.
    MANUAL_EXIT = "manual_exit"
    #: No usable path inside the holding window.
    MISSING_PATH = "missing_path"
    #: The row cannot be sequenced — see `quality.Reason.EXIT_BEFORE_ENTRY`.
    CORRUPT_TIMESTAMPS = "corrupt_timestamps"
    #: The position carries no rule configuration to replay.
    NO_RULE_CONFIG = "no_rule_config"


@dataclass(frozen=True, slots=True)
class Fill:
    """One exit, priced under one convention."""

    model: FillModel
    price_usd: Decimal
    gross_return_pct: Decimal
    #: `None` when depth was never recorded, exactly as `costs.round_trip`
    #: refuses rather than inventing a pool.
    net_return_pct: Decimal | None
    round_trip_cost_pct: Decimal | None


@dataclass(frozen=True, slots=True)
class ReplayedExit:
    """What the rules did, and what both conventions say it cost."""

    reason: ExitReason
    at: datetime
    peak_price: Decimal
    legacy: Fill
    observed: Fill
    #: How much better the trigger fill was than the observed one, as a
    #: percentage of the observed price:
    #:
    #:     legacy_price / observed_price - 1
    #:
    #: For a **sell**, a positive value means V1.0 booked a higher price than
    #: the market showed — a synthetic advantage. Negative means the observed
    #: quote was above the trigger, which happens when a rule fires on a
    #: reading that overshot upward.
    synthetic_fill_advantage_pct: Decimal | None
    #: Seconds between the previous observation and the triggering one. Large
    #: gaps are where the two conventions diverge most.
    seconds_since_previous_observation: int | None
    fill_note: str = OBSERVED_FILL_NOTE
    resolution_note: str = RESOLUTION_NOTE


@dataclass(frozen=True, slots=True)
class Reconciliation:
    """Recorded versus replayed, for one position."""

    matched: bool
    rule_match: bool
    timestamp_match: bool
    peak_match: bool
    #: Whether the replayed *legacy* price reproduces the recorded exit price.
    #: The observed price is deliberately not required to match — that
    #: difference is the modelling convention, not an error.
    legacy_price_match: bool
    timestamp_delta_seconds: int | None
    mismatch: Mismatch | None


def _pct(entry: Decimal, price: Decimal) -> Decimal:
    return (price / entry - Decimal(1)) * Decimal(100)


def _close(a: Decimal, b: Decimal) -> bool:
    if a == b:
        return True
    scale = max(abs(a), abs(b))
    if scale == 0:
        return True
    return abs(a - b) / scale <= _PRICE_EPSILON


def _price_and_gap(quotes: Sequence[Quote], at: datetime) -> tuple[Decimal | None, int | None]:
    """The observed price at `at`, and the gap since the previous observation.

    Matches the **first** quote carrying that timestamp. `resolve` stops at the
    first breaching observation, so the first match is the one it saw; taking a
    later duplicate would be searching forward for a different price.
    """
    for index, quote in enumerate(quotes):
        if quote.captured_at == at:
            gap = (
                None
                if index == 0
                else int((quote.captured_at - quotes[index - 1].captured_at).total_seconds())
            )
            return quote.price_usd, gap
    return None, None


def _fill(
    *,
    model: FillModel,
    price: Decimal,
    entry_price: Decimal,
    size_usd: Decimal,
    entry_liquidity: Decimal | None,
) -> Fill:
    """Price one exit and charge it, under one convention."""
    gross = _pct(entry_price, price)
    exit_notional = size_usd * (price / entry_price)

    # Exit-side depth is not stored per position, so entry depth stands in for
    # both sides. That understates the cost of a winner (a larger sell into the
    # same pool) and is disclosed rather than silently assumed.
    trip = costs.round_trip(
        entry_notional=size_usd,
        entry_liquidity=entry_liquidity,
        exit_notional=exit_notional,
        exit_liquidity=entry_liquidity,
    )
    if trip is None:
        return Fill(
            model=model,
            price_usd=price,
            gross_return_pct=gross,
            net_return_pct=None,
            round_trip_cost_pct=None,
        )

    net_usd = costs.net_proceeds(
        entry_notional=size_usd, exit_notional=exit_notional, costs=trip
    )
    return Fill(
        model=model,
        price_usd=price,
        gross_return_pct=gross,
        net_return_pct=net_usd / size_usd * Decimal(100),
        round_trip_cost_pct=trip.total / size_usd * Decimal(100),
    )


def replay(
    *,
    rules: ExitRules,
    entry_price: Decimal,
    opened_at: datetime,
    quotes: Sequence[Quote],
    size_usd: Decimal,
    entry_liquidity: Decimal | None,
    peak: Decimal | None = None,
) -> tuple[ReplayedExit | None, Decimal]:
    """Replay one position and price its exit under both conventions.

    Returns `(exit_or_none, peak)`. `None` means the rules never fired over the
    supplied path, which is a real outcome and not a failure.

    The signal comes from `exits.resolve` — the same function the live wallet
    runs — so a reproduced timestamp is evidence about the wallet rather than
    about this module.
    """
    exit_, running_peak = resolve(
        rules, entry_price=entry_price, opened_at=opened_at, quotes=quotes, peak=peak
    )
    if exit_ is None:
        return None, running_peak

    observed_price, gap = _price_and_gap(quotes, exit_.at)
    # `resolve` stamps its exit with a quote's own `captured_at`, so a miss here
    # means the caller passed a different series than the one replayed.
    if observed_price is None:
        observed_price = exit_.price_usd

    legacy = _fill(
        model=FillModel.LEGACY_TRIGGER,
        price=exit_.price_usd,
        entry_price=entry_price,
        size_usd=size_usd,
        entry_liquidity=entry_liquidity,
    )
    observed = _fill(
        model=FillModel.OBSERVED_SNAPSHOT,
        price=observed_price,
        entry_price=entry_price,
        size_usd=size_usd,
        entry_liquidity=entry_liquidity,
    )

    advantage = (
        None
        if observed_price <= 0
        else (exit_.price_usd / observed_price - Decimal(1)) * Decimal(100)
    )

    return (
        ReplayedExit(
            reason=exit_.reason,
            at=exit_.at,
            peak_price=running_peak,
            legacy=legacy,
            observed=observed,
            synthetic_fill_advantage_pct=advantage,
            seconds_since_previous_observation=gap,
        ),
        running_peak,
    )


def reconcile(
    *,
    replayed: ReplayedExit | None,
    recorded_reason: str | None,
    recorded_at: datetime | None,
    recorded_exit_price: Decimal | None,
    recorded_peak: Decimal | None,
    had_path: bool,
) -> Reconciliation:
    """Compare a replayed exit against what the wallet recorded.

    Manual exits are classified, never failed: a human override is not a signal
    the strategy produced and counting it as a replay miss would understate
    fidelity for a reason that has nothing to do with the data.
    """
    if recorded_reason == ExitReason.MANUAL.value:
        return Reconciliation(
            matched=False,
            rule_match=False,
            timestamp_match=False,
            peak_match=False,
            legacy_price_match=False,
            timestamp_delta_seconds=None,
            mismatch=Mismatch.MANUAL_EXIT,
        )

    if not had_path:
        return Reconciliation(
            matched=False,
            rule_match=False,
            timestamp_match=False,
            peak_match=False,
            legacy_price_match=False,
            timestamp_delta_seconds=None,
            mismatch=Mismatch.MISSING_PATH,
        )

    if replayed is None:
        return Reconciliation(
            matched=False,
            rule_match=False,
            timestamp_match=False,
            peak_match=False,
            legacy_price_match=False,
            timestamp_delta_seconds=None,
            mismatch=Mismatch.NO_REPLAY_EXIT,
        )

    rule_match = recorded_reason == replayed.reason.value

    delta: int | None = None
    timestamp_match = False
    if recorded_at is not None:
        delta = int((replayed.at - recorded_at).total_seconds())
        timestamp_match = abs(delta) <= TIMESTAMP_TOLERANCE_SECONDS

    peak_match = recorded_peak is not None and _close(replayed.peak_price, recorded_peak)
    price_match = recorded_exit_price is not None and _close(
        replayed.legacy.price_usd, recorded_exit_price
    )

    mismatch: Mismatch | None = None
    if not rule_match:
        mismatch = Mismatch.RULE_DIFFERS
    elif not timestamp_match:
        mismatch = Mismatch.TIMESTAMP_DIFFERS

    return Reconciliation(
        matched=rule_match and timestamp_match,
        rule_match=rule_match,
        timestamp_match=timestamp_match,
        peak_match=peak_match,
        legacy_price_match=price_match,
        timestamp_delta_seconds=delta,
        mismatch=mismatch,
    )
