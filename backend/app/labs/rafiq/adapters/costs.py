"""`earlysignal.execution.costs` — what a round trip actually costs at a depth.

THE FORMULA, stated rather than implied
---------------------------------------
Two terms, both per side:

    fee_pct    = swap_fee_bps / 100
    impact_pct = 100 * notional / (depth + notional)
    depth      = (liquidity_usd / 2) / IMPACT_DIVISOR

`impact_pct` is the constant-product result. Selling `q` tokens worth `n` USD
into a pool of depth `d` returns `n / (1 + n/d)`, so the fraction given up is
`1 - 1/(1 + n/d)`, which is `n / (d + n)`. Entry pays the same shape.

`IMPACT_DIVISOR = 12` and `swap_fee_bps = 30` are MEMESCOPE's own calibration,
measured against 320 live Jupiter quotes: a real fill moves the price about
twelve times more than naive `notional / (liquidity/2)` predicts, because the
reported "liquidity" figure is both sides of the pool and the tradable depth
near the mark is a fraction of it. **These are not EarlySignal's constants**,
and Strategy C's docstring cites EarlySignal's figures (~1.6% round trip at
$10k, ~0.8% at $100k) — those describe his cost model, not this one. What both
models agree on, and the only thing C's logic actually depends on, is the
direction: a thinner pool costs more to round-trip than a deeper one.

No `Decimal ** float` anywhere. Every operation below is Decimal-on-Decimal or
Decimal-on-int, which are the only exponent and arithmetic pairs Python defines
for Decimal.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

#: Effective depth is (liquidity/2)/12. See the module docstring.
IMPACT_DIVISOR = Decimal(12)


@dataclass(frozen=True, slots=True)
class CostModel:
    """The swap fee, in basis points. 30 bps = 0.30% a side."""

    swap_fee_bps: Decimal = Decimal(30)

    @property
    def fee_pct(self) -> Decimal:
        return self.swap_fee_bps / 100


@dataclass(frozen=True, slots=True)
class SideCost:
    """One leg's cost, split so a reader can see what each part contributed."""

    fee_pct: Decimal
    impact_pct: Decimal

    @property
    def total_pct(self) -> Decimal:
        return self.fee_pct + self.impact_pct


def effective_depth(liquidity_usd: Decimal) -> Decimal:
    """Tradable depth near the mark, from the reported pool figure."""
    return (liquidity_usd / 2) / IMPACT_DIVISOR


def side_cost(notional: Decimal, liquidity_usd: Decimal | None, *,
              model: CostModel) -> SideCost | None:
    """Cost of ONE leg, or None when the pool cannot be priced at all.

    None is never a zero and never a default: a caller that cannot price a leg
    must decline the trade, not assume it is free.
    """
    if liquidity_usd is None or liquidity_usd <= 0 or notional <= 0:
        return None
    depth = effective_depth(liquidity_usd)
    return SideCost(fee_pct=model.fee_pct,
                    impact_pct=Decimal(100) * notional / (depth + notional))


def buy_quantity(size_usd: Decimal, price: Decimal,
                 liquidity_usd: Decimal | None) -> Decimal | None:
    """Tokens `size_usd` actually buys, after fee and impact.

    None when the market cannot be priced at all — never a naive
    `size_usd / price`, which is the number that makes a paper book look
    executable when it is not.
    """
    if liquidity_usd is None or liquidity_usd <= 0 or size_usd <= 0 or price <= 0:
        return None
    spend = size_usd * (1 - CostModel().fee_pct / 100)
    return spend / (price * (1 + spend / effective_depth(liquidity_usd)))


def sell_proceeds(quantity: Decimal, price: Decimal,
                  liquidity_usd: Decimal | None) -> Decimal:
    """USD a sale actually returns, after impact and fee.

    Zero when there is no priceable market, and zero is the claim: nothing
    could be sold.
    """
    if liquidity_usd is None or liquidity_usd <= 0 or quantity <= 0 or price <= 0:
        return Decimal(0)
    gross = quantity * price
    net = gross / (1 + gross / effective_depth(liquidity_usd))
    return net * (1 - CostModel().fee_pct / 100)
