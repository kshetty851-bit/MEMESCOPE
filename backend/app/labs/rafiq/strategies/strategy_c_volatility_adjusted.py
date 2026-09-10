"""STRATEGY C — VOLATILITY_ADJUSTED_RISK

Fixes a defect that is invisible in Karthik's summary stats but visible the
moment you look at its trade-level prices: one fixed stop/size pair applied
to tokens with wildly different liquidity depth is wrong for almost all of
them.

THE EVIDENCE THIS RESPONDS TO
------------------------------
Karthik's own closed-trade table prices span from $8628 down to
$0.0000001033 per token — many orders of magnitude of scale, which is a proxy
for how differently these pools behave. A $10 order into a deep pool barely
moves the price; the same $10 into a shallow one can BE the move, so a fixed
percentage stop is, in the shallow case, often just "noise" and gets clipped
constantly, while in the deep case it may be far looser than the token's
actual risk warrants.

`execution/costs.py`'s own model makes this precise: round-trip cost for a
fixed order against a $10,000 pool is ~1.6%; against $100,000, ~0.8%. A stop
set without reference to that difference is either too tight to survive normal
noise in a thin pool, or too loose to protect capital in one that is.

THE FIX
-------
Stop distance and position size are DERIVED from the pool's liquidity depth at
entry, not fixed. Deeper pools get a tighter stop (their price is a more
reliable signal, less noise) and can support a larger clean size; shallow
pools get more room in percentage terms(to avoid being clipped by cost-driven
noise) but a correspondingly SMALLER position, so the dollar risk stays
bounded even though the percentage stop is wider.

This does not eliminate the need for a hard floor stop — it sits on top of one.
`min_stop_pct` / `max_stop_pct` bound how far the liquidity-derived number is
allowed to drift in either direction, so a pathological input never produces
an unbounded stop.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.labs.rafiq.adapters.costs import CostModel, side_cost

MODEL = CostModel(swap_fee_bps=Decimal(30))


@dataclass(frozen=True)
class VolatilityAdjustedPolicy:
    """Provisional. Every constant here is a hypothesis, not a validated fit."""

    #: Baseline stop at the reference liquidity depth below.
    base_stop_pct: Decimal = Decimal(12)
    #: The liquidity level `base_stop_pct` was calibrated against.
    reference_liquidity_usd: Decimal = Decimal(100_000)
    #: Bounds so a pathological input cannot produce a useless stop.
    min_stop_pct: Decimal = Decimal(8)
    max_stop_pct: Decimal = Decimal(25)
    #: How strongly stop distance reacts to liquidity being thinner/deeper
    #: than the reference. 0.5 = square-root scaling (moderate reaction);
    #: 1.0 would scale linearly with the liquidity ratio.
    sensitivity: Decimal = Decimal("0.5")


def stop_distance_for(liquidity_usd: Decimal | None, *,
                      policy: VolatilityAdjustedPolicy = VolatilityAdjustedPolicy()
                      ) -> Decimal | None:
    """Percent stop distance for this pool's depth, or None if depth is
    unknown — NEVER a guessed default. An unpriceable pool gets no stop
    distance here, which the caller must treat as "cannot size this trade",
    not as "use some fallback number"."""
    if liquidity_usd is None or liquidity_usd <= 0:
        return None
    ratio = policy.reference_liquidity_usd / liquidity_usd
    # ratio > 1 means this pool is thinner than reference -> widen the stop.
    # ratio < 1 means it is deeper -> tighten the stop. Square-root damps the
    # effect so a 100x thinner pool does not demand a 100x wider stop.
    #
    # `Decimal ** float` raises TypeError — Python only defines Decimal
    # exponentiation against another Decimal or an int. `sensitivity` is a
    # configured Decimal (default 0.5, i.e. square root), so the general case
    # goes through Decimal's own `.sqrt()` for 0.5 and falls back to float
    # math (then back to Decimal) for any other configured exponent, rather
    # than silently crashing every time this function is called.
    if policy.sensitivity == Decimal("0.5"):
        factor = ratio.sqrt()
    else:
        factor = Decimal(str(float(ratio) ** float(policy.sensitivity)))
    scaled = policy.base_stop_pct * factor
    bounded = max(policy.min_stop_pct, min(policy.max_stop_pct, scaled))
    return bounded


def sized_for_liquidity(equity: Decimal, liquidity_usd: Decimal | None, *,
                        stop_pct: Decimal, risk_per_trade: Decimal = Decimal("0.01"),
                        max_notional_usd: Decimal = Decimal(50)) -> Decimal:
    """Position size consistent with the SAME risk budget regardless of which
    pool it lands in — a wider stop must mean a smaller size, or the risk
    budget this function exists to enforce is fiction."""
    if liquidity_usd is None or liquidity_usd <= 0 or stop_pct <= 0:
        return Decimal(0)
    risk_budget = equity * risk_per_trade
    size = risk_budget / (stop_pct / 100)
    return min(size, max_notional_usd)


def round_trip_cost_pct(notional: Decimal, liquidity_usd: Decimal | None) -> Decimal | None:
    """What this specific order would actually cost at this specific depth —
    the number that justifies treating pools differently in the first place."""
    if liquidity_usd is None or liquidity_usd <= 0:
        return None
    c = side_cost(notional, liquidity_usd, model=MODEL)
    if c is None or c.total_pct is None:
        return None
    return c.total_pct * 2  # entry + exit, same depth assumption both legs
