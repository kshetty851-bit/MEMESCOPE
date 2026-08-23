"""What a Strategy Lab exit would actually have returned. **Bounded, on purpose.**

Strategy Lab keeps the platform's execution *assumptions* — the venue's swap
fee, and the convention that `liquidity_usd` reports both sides of the pool — and
replaces one formula, because §7 permits inheriting Paper Wallet's model but
forbids inheriting a known-invalid one silently. This is that exception, stated
in full rather than buried.

── THE DEFECT ───────────────────────────────────────────────────────────────

`app.paper.costs.side_cost` prices impact as

    impact = notional * (notional / usd_side)

which is the **first-order approximation** of constant-product impact. It is
accurate while the order is small against the pool, and it is the correct model
for the $25-$100 entries Paper Wallet was built to price.

It has no upper bound. Once `notional > usd_side` the "impact" exceeds the whole
order, and net proceeds go negative: selling $25,000 of a token into a pool
holding $500 is charged $2,500,000, so the model says the seller *pays* $2.47m
to close a position worth $25k. Nothing like that can happen — the worst case
for a seller is receiving almost nothing.

Strategy Lab hits this constantly and Paper Wallet does not, because Lab holds
runners: a $25 position that prints 100x is a $2,500 exit, and the memecoin
pools this platform trades routinely hold less than that. On the first replay
this produced a strategy equity of **-$654 trillion**, which is how the defect
was found.

── WHAT REPLACES IT ─────────────────────────────────────────────────────────

The exact constant-product result rather than its tangent. For a pool holding
`Y` USD against `X` tokens, selling `q` tokens returns

    Y*q / (X + q)

and substituting the spot price `p = Y/X` and the notional-at-spot `g = q·p`:

    proceeds = g * Y / (Y + g)          impact = g^2 / (Y + g)

Three properties, all of which the linear form lacks:

  * **Bounded.** Proceeds are always in `[0, g)` and always below `Y`. You
    cannot take more USD out of a pool than it holds, and you can never pay to
    sell.
  * **Agrees where the old model was valid.** At `g` far below `Y` the two differ in the
    third decimal — $25 into a $2,000 pool costs $0.61 here against $0.63
    there — so this is not a re-tuning of small trades.
  * **Strictly more conservative than "no impact"**, which is what an unbounded
    model degenerates into once a caller clamps it at zero.

The **entry** side keeps the same identity for symmetry, and matters far less:
entries are $25 or $100 by construction and never approach pool depth.

── WHAT IS STILL REFUSED ────────────────────────────────────────────────────

Everything `paper.costs` refuses, for the same reasons and stated again because
a net figure carries them: no slippage against competing flow in the same
block, no priority-fee competition, no MEV. This platform stores snapshots, not
fills. And a pair reporting no depth at all is priced at zero impact and
identifiable by its `None` liquidity, rather than costed at an invented depth.

Pure: no I/O, no clock, no randomness.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.paper import costs

_ZERO = Decimal(0)

#: The fee schedule and the both-sides convention come from the platform's
#: model unchanged. Only the impact identity differs.
MODEL = costs.DEFAULT

EXECUTION_MODEL_ID = "strategy_lab_bounded_constant_product_v1"

DISCLOSURE = (
    "Net figures charge the venue's published swap fee on each side plus the "
    "EXACT constant-product price impact of the order against the pool depth "
    "observed at that moment: proceeds = gross x Y/(Y+gross), where Y is the "
    "pool's USD side. Strategy Lab uses the exact identity rather than the "
    "first-order approximation Paper Wallet uses, because Lab holds runners "
    "whose exits routinely exceed pool depth, where the approximation returns "
    "negative proceeds. Net figures do NOT include slippage from competing "
    "transactions in the same block, priority-fee competition, or MEV - this "
    "platform stores snapshots, not fills. Pairs reporting no depth are "
    "charged no impact and are identifiable by a null liquidity."
)


@dataclass(frozen=True, slots=True)
class SideCost:
    """What one order costs, and what it leaves behind."""

    notional: Decimal
    fee: Decimal
    impact: Decimal
    #: `None` when the pair reports no depth. The cost is then fee-only and the
    #: caller can tell that apart from "deep pool, no impact".
    liquidity_usd: Decimal | None

    @property
    def total(self) -> Decimal:
        return self.fee + self.impact

    @property
    def proceeds(self) -> Decimal:
        """Never negative. That is the whole point of this module."""
        return max(_ZERO, self.notional - self.total)

    @property
    def total_pct(self) -> Decimal | None:
        if self.notional <= 0:
            return None
        return self.total / self.notional * 100


def side_cost(notional: Decimal, liquidity_usd: Decimal | None) -> SideCost | None:
    """Fee plus exact constant-product impact for one order.

    `None` only when the order itself is meaningless — a non-positive notional.
    An unknown depth is *not* `None`: it returns a fee-only cost carrying
    `liquidity_usd=None`, because refusing to cost the trade at all would drop
    it from the result set and quietly change which population was measured.
    """
    if notional <= 0:
        return None

    fee = notional * MODEL.fee_rate
    if liquidity_usd is None:
        # Depth genuinely unknown — a bonding-curve pair reports none. Fee-only,
        # and identifiable afterwards by the null.
        return SideCost(notional=notional, fee=fee, impact=_ZERO, liquidity_usd=None)

    usd_side = MODEL.usd_side(liquidity_usd)
    if usd_side <= 0:
        # **An empty pool is a measurement, not an absence.** There is no USD in
        # the pool, so an order against it returns nothing at all. Charging
        # fee-only here — which is what treating zero like unknown does — would
        # hand a rugged position back most of its notional, and is how a
        # drained pool turns into a profit.
        return SideCost(
            notional=notional, fee=fee, impact=notional - fee, liquidity_usd=liquidity_usd
        )

    # Exact: impact = g^2 / (Y + g). Bounded above by g, so proceeds stay in
    # [0, g) for every order size, however large against the pool.
    impact = notional * notional / (usd_side + notional)
    return SideCost(notional=notional, fee=fee, impact=impact, liquidity_usd=liquidity_usd)


def sell(
    quantity: Decimal, price: Decimal, liquidity_usd: Decimal | None
) -> tuple[Decimal, Decimal]:
    """Net proceeds and cost for one sale, priced against the depth at the fill."""
    gross = quantity * price
    cost = side_cost(gross, liquidity_usd)
    if cost is None:
        return _ZERO, _ZERO
    return cost.proceeds, min(cost.total, gross)


def buy(notional: Decimal, liquidity_usd: Decimal | None) -> Decimal:
    """What one entry costs. Charged on top of the stake, as Paper Wallet does."""
    cost = side_cost(notional, liquidity_usd)
    return cost.total if cost is not None else _ZERO


def demo() -> None:
    """The properties this module exists to guarantee, as runnable assertions."""
    # Bounded: a huge exit against a tiny pool returns something, never negative.
    proceeds, _cost = sell(Decimal(1), Decimal(25_000), Decimal(500))
    assert proceeds > 0, proceeds
    assert proceeds < Decimal(25_000), proceeds
    assert proceeds < MODEL.usd_side(Decimal(500)), "cannot take out more than the pool holds"

    # Agrees with the platform's approximation where that approximation is valid.
    small = side_cost(Decimal(25), Decimal(2_000))
    legacy = costs.side_cost(Decimal(25), Decimal(2_000))
    assert small is not None and legacy is not None
    assert abs(small.total - legacy.total) < Decimal("0.05"), (small.total, legacy.total)

    # Monotone: a bigger order never returns more.
    a, _ = sell(Decimal(1), Decimal(100), Decimal(10_000))
    b, _ = sell(Decimal(2), Decimal(100), Decimal(10_000))
    assert b > a and b < 2 * a, (a, b)

    # Unknown depth is fee-only, and says so.
    unknown = side_cost(Decimal(100), None)
    assert unknown is not None and unknown.impact == _ZERO
    assert unknown.liquidity_usd is None

    # An EMPTY pool returns nothing. Distinct from unknown depth, and the
    # single most important case: it is what a rug looks like.
    empty_proceeds, _ = sell(Decimal(1000), Decimal(50), Decimal(0))
    assert empty_proceeds == _ZERO, empty_proceeds
    empty = side_cost(Decimal(100), Decimal(0))
    assert empty is not None and empty.liquidity_usd == _ZERO
    assert empty.proceeds == _ZERO
    print("strategy_lab.execution: ok")  # noqa: T201


if __name__ == "__main__":
    demo()
