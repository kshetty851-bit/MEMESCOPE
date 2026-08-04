"""What it would have cost to actually take these trades.

Sprint 27. Every figure the wallet and the lab published before this assumed a
fill at the observed mid price: no fee, no price impact, infinite depth. On this
market that assumption is not a rounding error. Measured over the live Radar
set, **57 of 85 tokens hold under $5,000 of liquidity** and the median holds
$1,857 — against which a $100 order moves the price about 10.8% on the way in
and again on the way out.

So this module answers a narrower question than "what would you have made": it
answers *"what would the venue have taken"*, from figures already stored.

## What is modelled, and what is refused

**Modelled, deterministically:**

  - **Protocol fee**, a published rate per side.
  - **Price impact**, from the constant-product identity. For a pool holding `Y`
    USD against `X` tokens, buying with `S` USD fills at `(Y+S)/X` against a
    spot of `Y/X` — an impact of exactly `S/Y`, no approximation. `Y` is half of
    `liquidity_usd`, which providers report as the **total** value of both
    sides.

**Refused, because nothing stored supports them:**

  - **Slippage against competing flow.** The gap between the quote and the fill
    caused by other transactions landing in the same block. That needs the
    mempool, and this platform stores snapshots.
  - **Priority-fee competition and MEV.** Same reason.
  - **Impact on bonding-curve pairs.** `liquidity_usd` is 100% null there
    (ADR 0002), so `estimate` returns `None` for them and the caller excludes
    the trade from net rather than inventing a depth.

A cost model that guessed at the refused three would produce a more
comfortable-looking number and a less true one. `None` is the answer when the
rows do not support one.

Pure: no I/O, no clock, no randomness.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

_ZERO = Decimal(0)
_HUNDRED = Decimal(100)


@dataclass(frozen=True, slots=True)
class CostModel:
    """Published execution costs. Rates are configuration, not measurements.

    These are the venue's stated fees, and they are stated here so a reader can
    check a net figure against them rather than take it on trust. They are
    **not** derived from observed fills — this platform records no fills — so a
    change to a protocol's fee schedule is a config change that should be dated,
    not a silent correction.
    """

    #: Protocol fee per side, in basis points. Applied on entry and again on
    #: exit. Verify against the venue before treating a net figure as precise.
    swap_fee_bps: Decimal
    #: Whether `liquidity_usd` reports both sides of the pool. Providers report
    #: the total, so the USD side is half — and getting this backwards doubles
    #: or halves every impact figure, which is why it is explicit rather than
    #: hidden in a constant.
    liquidity_is_both_sides: bool = True

    @property
    def fee_rate(self) -> Decimal:
        return self.swap_fee_bps / Decimal(10_000)

    def usd_side(self, liquidity_usd: Decimal) -> Decimal:
        return liquidity_usd / 2 if self.liquidity_is_both_sides else liquidity_usd


#: The default. 30 bps per side is the order of PumpSwap's published swap fee;
#: it is a configuration default and not a claim about any particular moment in
#: the protocol's history.
DEFAULT = CostModel(swap_fee_bps=Decimal(30))


@dataclass(frozen=True, slots=True)
class SideCost:
    """What one side of a round trip would have cost."""

    notional: Decimal
    fee: Decimal
    impact: Decimal

    @property
    def total(self) -> Decimal:
        return self.fee + self.impact

    @property
    def total_pct(self) -> Decimal | None:
        if self.notional <= 0:
            return None
        return self.total / self.notional * _HUNDRED


@dataclass(frozen=True, slots=True)
class RoundTrip:
    """Entry and exit together, and the net proceeds after both."""

    entry: SideCost
    exit: SideCost

    @property
    def total(self) -> Decimal:
        return self.entry.total + self.exit.total


def side_cost(
    notional: Decimal, liquidity_usd: Decimal | None, *, model: CostModel = DEFAULT
) -> SideCost | None:
    """Fee plus price impact for one order, or `None` when depth is unknown.

    `None` is the whole point of the return type. A bonding-curve pair reports
    no liquidity, and treating that as a deep pool would understate the cost of
    exactly the trades most likely to be expensive.
    """
    if notional <= 0:
        return None
    if liquidity_usd is None or liquidity_usd <= 0:
        return None

    usd_side = model.usd_side(liquidity_usd)
    if usd_side <= 0:
        return None

    fee = notional * model.fee_rate
    # Exact for constant product: an order of `notional` against a `usd_side`
    # reserve fills at an average price `notional / usd_side` worse than spot.
    impact = notional * (notional / usd_side)
    return SideCost(notional=notional, fee=fee, impact=impact)


def round_trip(
    *,
    entry_notional: Decimal,
    entry_liquidity: Decimal | None,
    exit_notional: Decimal,
    exit_liquidity: Decimal | None,
    model: CostModel = DEFAULT,
) -> RoundTrip | None:
    """Both sides, priced against the depth observed at each end.

    The exit is charged on the position's value *at exit*, not on what it cost
    to open: selling a position that tripled is a three-times larger order, and
    charging it as though it were the entry size would understate the cost of
    precisely the winners.

    `None` if either side is unpriceable — a half-costed round trip is worse
    than an uncosted one, because it looks complete.
    """
    entry = side_cost(entry_notional, entry_liquidity, model=model)
    if entry is None:
        return None
    exit_side = side_cost(exit_notional, exit_liquidity, model=model)
    if exit_side is None:
        return None
    return RoundTrip(entry=entry, exit=exit_side)


def net_proceeds(
    *,
    entry_notional: Decimal,
    exit_notional: Decimal,
    costs: RoundTrip,
) -> Decimal:
    """What the position returns after the venue has taken its share."""
    return exit_notional - costs.exit.total - (entry_notional + costs.entry.total)


#: Stated on every surface that shows a net figure. The three refusals are as
#: much a part of the model as the two inclusions.
DISCLOSURE = (
    "Net figures charge the venue's published swap fee on each side plus the "
    "constant-product price impact of the order against the pool depth observed "
    "at that moment. They do NOT include slippage from competing transactions "
    "in the same block, priority-fee competition, or MEV — this platform stores "
    "snapshots, not fills, and modelling those would be guessing. Trades on "
    "bonding-curve pairs report no liquidity and are excluded from net entirely "
    "rather than costed at an invented depth."
)
