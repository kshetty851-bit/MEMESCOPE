"""Meme Lifecycle Lab — exit evaluation and execution costs.

Six exit rules, evaluated deterministically per position per market reading:
take profit, stop loss, trailing stop, maximum hold, attention collapse and
volume collapse.

**Order within one reading is published and adverse-first**, the same order
``app.paper.exits.resolve`` uses, extended with the two collapse rules:

    max_hold → stop_loss → trailing_stop → attention_collapse
             → volume_collapse → take_profit

A reading that satisfies more than one rule means the world moved further than
one reading can distinguish, and the honest interpretation of an ambiguous bar
is the one that does not book a win the data cannot support. So the target is
always checked last. Order *across* readings is chronological: the earliest
breach wins, and scanning ahead for the best outcome would be hindsight.

Fill rules (the trigger says *when*, the observation says *what*):

* stop loss, trailing stop, maximum hold, attention collapse and volume
  collapse fill at the **observed** price. A stop that gapped through fills at
  the gap, never at the stop level.
* take profit fills at ``min(observed, target)`` — which, because the rule only
  fires when ``observed >= target``, is always the target. A limit order fills
  at the level it asked for; booking the observed price would claim the upside
  of a gap, the same error as a stop filled at its trigger, in the other
  direction. This is the conservative rule from ``app.paper.exits``.

``app.paper.exits.resolve`` itself is not imported: it scans a whole quote
series at once, knows nothing of attention or volume, and its ``ExitReason``
enum is the wallet's, not the Lab's. Its ordering and fill rules are what is
reused, and are restated here so the two cannot be read as different policies.

Absence is never a trigger. An ``Unavailable`` attention or volume reading
(at entry or now) does not fire a collapse; the evaluation records *why* it
could not be checked, so the replay can put that on the trade's timeline.

Costs: ``fee_rate + slippage_rate`` of the notional per side, plus the exact
constant-product price impact when the pool depth is known — computed by
``app.paper.costs.side_cost``, reused as-is. When depth is unknown (bonding
curve, ADR 0002) a flat ``unknown_liquidity_slippage_rate`` replaces impact and
the slippage floor, and the side is labelled ``cost_model="flat"``.

Pure: no I/O, no clock, no randomness.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

from app.lifecycle_lab.config import ExitConfig, PortfolioConfig
from app.lifecycle_lab.domain import ExitReason, MarketPoint, Measured, Unavailable
from app.paper import costs as paper_costs

_ONE = Decimal(1)
_ZERO = Decimal(0)

COST_MODEL_CONSTANT_PRODUCT = "constant_product"
COST_MODEL_FLAT = "flat"

#: Published within-reading order. Asserted by test; the docstring above is the
#: reason for it.
EXIT_ORDER: tuple[ExitReason, ...] = (
    ExitReason.MAX_HOLD,
    ExitReason.STOP_LOSS,
    ExitReason.TRAILING_STOP,
    ExitReason.ATTENTION_COLLAPSE,
    ExitReason.VOLUME_COLLAPSE,
    ExitReason.TAKE_PROFIT,
)


# --------------------------------------------------------------------------
# Costs
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SideCost:
    """What one side of a round trip costs, in USD, and how it was modelled."""

    notional: Decimal
    fee_usd: Decimal
    slippage_usd: Decimal
    impact_usd: Decimal
    cost_model: str

    @property
    def total(self) -> Decimal:
        return self.fee_usd + self.slippage_usd + self.impact_usd


def side_cost(
    notional: Decimal, liquidity_usd: Decimal | None, cfg: PortfolioConfig
) -> SideCost:
    """Fee + slippage floor + constant-product impact, or a flat rate.

    Unlike ``app.paper.costs.side_cost`` this never returns ``None``: the Lab
    always charges something, and says which model it used. Unknown depth is
    charged the deliberately punitive flat rate rather than excluded, because
    excluding exactly the bonding-curve trades would bias the sample.
    """
    if notional <= 0:
        return SideCost(notional, _ZERO, _ZERO, _ZERO, COST_MODEL_FLAT)
    fee = notional * cfg.fee_rate
    if liquidity_usd is not None and liquidity_usd > 0:
        model = paper_costs.CostModel(swap_fee_bps=cfg.fee_rate * Decimal(10_000))
        priced = paper_costs.side_cost(notional, liquidity_usd, model=model)
        if priced is not None:
            return SideCost(
                notional=notional,
                fee_usd=fee,
                slippage_usd=notional * cfg.slippage_rate,
                impact_usd=priced.impact,
                cost_model=COST_MODEL_CONSTANT_PRODUCT,
            )
    return SideCost(
        notional=notional,
        fee_usd=fee,
        slippage_usd=notional * cfg.unknown_liquidity_slippage_rate,
        impact_usd=_ZERO,
        cost_model=COST_MODEL_FLAT,
    )


# --------------------------------------------------------------------------
# Exit evaluation
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PositionExitState:
    """What the exit rules need to know about one open position."""

    entry_at: datetime
    entry_price: Decimal
    #: Running high, carried between evaluations for the trailing stop. Starts
    #: at the entry price: nothing was observed before the position existed.
    peak_price: Decimal
    #: 1h volume at entry; ``Unavailable`` disables the volume-collapse rule.
    entry_volume_1h: Measured
    #: 1h attention (mentions) at entry; ``Unavailable`` disables attention
    #: collapse.
    entry_attention_1h: Measured


@dataclass(frozen=True, slots=True)
class ExitSignal:
    reason: ExitReason
    #: When the reading became known — the earliest moment anyone could act.
    at: datetime
    #: The fill, per the module's fill rules.
    fill_price: Decimal
    observed_price: Decimal
    trigger_price: Decimal | None
    #: Pool depth at the fill reading, for the exit cost.
    liquidity_usd: Decimal | None
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ExitEvaluation:
    signal: ExitSignal | None
    #: Updated running high (only moves when nothing closed on this reading).
    peak_price: Decimal
    #: Stable codes for rules that could not be checked on this reading, e.g.
    #: ``attention_collapse_unavailable:no_source``. Never a trigger.
    notes: tuple[str, ...] = ()


def _unavailable_reason(value: Measured | None) -> str:
    if isinstance(value, Unavailable):
        return value.reason
    return "missing"


def _collapse(
    entry: Measured | None, current: Measured | None, fraction: Decimal
) -> tuple[bool, str | None]:
    """(fired, note). ``note`` explains why the rule could not be checked."""
    if not isinstance(entry, Decimal):
        return False, f"entry_{_unavailable_reason(entry)}"
    if not isinstance(current, Decimal):
        return False, f"current_{_unavailable_reason(current)}"
    if entry <= 0:
        # Nothing to collapse from. A rule measured against zero would fire on
        # nothing (0 < 0 is false) or on everything; neither is an observation.
        return False, "entry_zero"
    return current < entry * fraction, None


def evaluate_exit(
    *,
    position: PositionExitState,
    point: MarketPoint,
    cfg: ExitConfig,
    attention_1h: Measured | None = None,
    attention_as_of: datetime | None = None,
) -> ExitEvaluation:
    """The first rule breached on one reading, in the published order.

    ``attention_1h`` is the meme's 1h attention as of the moment this reading
    is acted on. Pass ``None`` when attention is not being evaluated on this
    reading (between decision ticks) — that is "not checked", which is
    different from ``Unavailable`` ("checked, and no source answered"), and
    only the latter produces a note. ``attention_as_of`` is when that
    attention reading became known; an attention-collapse exit is stamped at
    the later of it and the reading's own ``available_at``, because neither
    fact could be acted on before both were known.

    A reading with no usable price cannot fill anything, including an expired
    hold: the position stays open and the note says why. Booking a fill at a
    price nobody observed is the thing this module exists not to do.
    """
    notes: list[str] = []
    price = point.price_usd
    peak = position.peak_price
    if price is None or price <= 0:
        return ExitEvaluation(signal=None, peak_price=peak, notes=("no_price",))

    def fire(
        reason: ExitReason,
        *,
        fill: Decimal,
        trigger: Decimal | None,
        detail: dict[str, Any] | None = None,
        at: datetime | None = None,
    ) -> ExitEvaluation:
        return ExitEvaluation(
            signal=ExitSignal(
                reason=reason,
                at=point.available_at if at is None else max(at, point.available_at),
                fill_price=fill,
                observed_price=price,
                trigger_price=trigger,
                liquidity_usd=point.liquidity_usd,
                detail={"observed_at": point.observed_at.isoformat(), **(detail or {})},
            ),
            peak_price=peak,
            notes=tuple(notes),
        )

    if cfg.max_hold is not None and point.available_at >= position.entry_at + cfg.max_hold:
        return fire(ExitReason.MAX_HOLD, fill=price, trigger=None)

    if cfg.stop_loss_fraction is not None:
        stop = position.entry_price * cfg.stop_loss_fraction
        if price <= stop:
            return fire(ExitReason.STOP_LOSS, fill=price, trigger=stop)

    if cfg.trailing_stop_fraction is not None:
        # Against the high *before* this reading: one reading cannot both set
        # a new high and fall away from it (app.paper.exits, same rule).
        trigger = peak * (_ONE - cfg.trailing_stop_fraction)
        if price <= trigger:
            return fire(ExitReason.TRAILING_STOP, fill=price, trigger=trigger)

    if cfg.attention_collapse_fraction is not None and attention_1h is not None:
        fired, note = _collapse(
            position.entry_attention_1h, attention_1h, cfg.attention_collapse_fraction
        )
        if note is not None:
            notes.append(f"attention_collapse_unavailable:{note}")
        if fired:
            assert isinstance(position.entry_attention_1h, Decimal)
            return fire(
                ExitReason.ATTENTION_COLLAPSE,
                fill=price,
                trigger=None,
                at=attention_as_of,
                detail={
                    "attention_1h_at_entry": str(position.entry_attention_1h),
                    "attention_1h_now": str(attention_1h),
                },
            )

    if cfg.volume_collapse_fraction is not None:
        current_volume: Measured | None = point.volume_1h
        fired, note = _collapse(
            position.entry_volume_1h,
            current_volume if current_volume is not None else Unavailable("no_volume_1h"),
            cfg.volume_collapse_fraction,
        )
        if note is not None:
            notes.append(f"volume_collapse_unavailable:{note}")
        if fired:
            assert isinstance(position.entry_volume_1h, Decimal)
            return fire(
                ExitReason.VOLUME_COLLAPSE,
                fill=price,
                trigger=None,
                detail={
                    "volume_1h_at_entry": str(position.entry_volume_1h),
                    "volume_1h_now": str(current_volume),
                },
            )

    if cfg.take_profit_multiple is not None:
        target = position.entry_price * cfg.take_profit_multiple
        if price >= target:
            return fire(ExitReason.TAKE_PROFIT, fill=min(price, target), trigger=target)

    if price > peak:
        peak = price
    return ExitEvaluation(signal=None, peak_price=peak, notes=tuple(notes))


def evaluate_attention_collapse(
    *,
    position: PositionExitState,
    point: MarketPoint,
    attention_1h: Measured,
    attention_as_of: datetime,
    cfg: ExitConfig,
) -> ExitEvaluation:
    """Attention collapse alone, filled at ``point`` (the latest visible
    reading).

    For a decision instant with no new market reading since the last one: the
    price rules have already been checked against that reading and must not
    be re-run against a running high that moved since, but attention is new
    information and is checked on its own.
    """
    peak = position.peak_price
    price = point.price_usd
    if cfg.attention_collapse_fraction is None:
        return ExitEvaluation(signal=None, peak_price=peak)
    if price is None or price <= 0:
        return ExitEvaluation(signal=None, peak_price=peak, notes=("no_price",))
    fired, note = _collapse(
        position.entry_attention_1h, attention_1h, cfg.attention_collapse_fraction
    )
    notes = () if note is None else (f"attention_collapse_unavailable:{note}",)
    if not fired:
        return ExitEvaluation(signal=None, peak_price=peak, notes=notes)
    return ExitEvaluation(
        signal=ExitSignal(
            reason=ExitReason.ATTENTION_COLLAPSE,
            at=max(attention_as_of, point.available_at),
            fill_price=price,
            observed_price=price,
            trigger_price=None,
            liquidity_usd=point.liquidity_usd,
            detail={
                "observed_at": point.observed_at.isoformat(),
                "attention_1h_at_entry": str(position.entry_attention_1h),
                "attention_1h_now": str(attention_1h),
            },
        ),
        peak_price=peak,
        notes=notes,
    )
