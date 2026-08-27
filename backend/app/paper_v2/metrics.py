"""V2 wallet figures, derived from its own rows and nothing else. **Pure.**

Same rule as V1: nothing is stored that can be computed, so no reported figure
can drift from the trades behind it. What differs is that a V2 position returns
cash *several times*, so cash is a function of fills rather than of closes.

`None` never means zero. It means the figure has no rows behind it.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

_ZERO = Decimal(0)


@dataclass(frozen=True, slots=True)
class OpenLeg:
    """What is still held of one position."""

    mint_address: str
    initial_notional: Decimal
    initial_quantity: Decimal
    remaining_quantity: Decimal

    @property
    def cost_basis_remaining(self) -> Decimal:
        """The share of the original notional still deployed.

        Pro-rata on quantity, not on count: selling a quarter of the tokens
        releases a quarter of the cost, whatever price it fetched. The profit
        or loss on that quarter is already in `net_proceeds`.
        """
        if self.initial_quantity <= 0:
            return _ZERO
        return self.initial_notional * (self.remaining_quantity / self.initial_quantity)


@dataclass(frozen=True, slots=True)
class ClosedLeg:
    """One finished position, reduced to the figures the metrics read."""

    mint_address: str
    initial_notional: Decimal
    net_proceeds: Decimal
    #: Used only to order the realised curve. Drawdown is a path, so the order
    #: has to be the order the closes happened in.
    closed_at: datetime | None = None

    @property
    def pnl(self) -> Decimal:
        return self.net_proceeds - self.initial_notional


@dataclass(frozen=True, slots=True)
class V2Metrics:
    starting_balance: Decimal
    cash: Decimal
    equity: Decimal | None
    open_value: Decimal | None
    capital_allocated: Decimal
    unrealised_pnl: Decimal | None
    realised_pnl: Decimal
    return_usd: Decimal | None
    roi_pct: Decimal | None
    open_positions: int
    closed_positions: int
    unpriced_positions: int
    win_rate_pct: Decimal | None
    profit_factor: Decimal | None
    max_drawdown_pct: Decimal | None
    capital_utilisation_pct: Decimal


def cash_for(
    starting_balance: Decimal,
    *,
    spent: Decimal,
    returned: Decimal,
) -> Decimal:
    """Uninvested cash. `spent` is every notional committed, `returned` every
    net fill proceed — including partial ones, which is the whole difference
    from V1: a quarter sold at 1.25x is spendable the moment it fills."""
    return starting_balance - spent + returned


def summarise(
    *,
    starting_balance: Decimal,
    open_legs: Sequence[OpenLeg],
    closed_legs: Sequence[ClosedLeg],
    partial_proceeds: Decimal,
    prices: dict[str, Decimal | None],
    realised_curve: Sequence[Decimal] = (),
) -> V2Metrics:
    """Every figure V2 reports.

    `partial_proceeds` is net cash already returned by fills on positions that
    are still open. It is passed in rather than derived here so this module
    stays free of the fill rows.
    """
    spent = sum((leg.initial_notional for leg in open_legs), _ZERO) + sum(
        (leg.initial_notional for leg in closed_legs), _ZERO
    )
    returned = sum((leg.net_proceeds for leg in closed_legs), _ZERO) + partial_proceeds
    cash = cash_for(starting_balance, spent=spent, returned=returned)

    allocated = sum((leg.cost_basis_remaining for leg in open_legs), _ZERO)

    open_value: Decimal | None = _ZERO
    unpriced = 0
    for leg in open_legs:
        price = prices.get(leg.mint_address)
        if price is None:
            unpriced += 1
            open_value = None
            continue
        if open_value is not None:
            open_value += leg.remaining_quantity * price

    equity = None if open_value is None else cash + open_value
    unrealised = None if open_value is None else open_value - allocated
    realised = sum((leg.pnl for leg in closed_legs), _ZERO)

    wins = [leg for leg in closed_legs if leg.pnl > 0]
    gross_win = sum((leg.pnl for leg in wins), _ZERO)
    gross_loss = -sum((leg.pnl for leg in closed_legs if leg.pnl < 0), _ZERO)

    peak = starting_balance
    worst = _ZERO
    for equity_point in realised_curve:
        peak = max(peak, equity_point)
        if peak > 0:
            worst = max(worst, (peak - equity_point) / peak * 100)

    return V2Metrics(
        starting_balance=starting_balance,
        cash=cash,
        equity=equity,
        open_value=open_value,
        capital_allocated=allocated,
        unrealised_pnl=unrealised,
        realised_pnl=realised,
        return_usd=None if equity is None else equity - starting_balance,
        roi_pct=(
            None
            if equity is None or starting_balance <= 0
            else (equity - starting_balance) / starting_balance * 100
        ),
        open_positions=len(open_legs),
        closed_positions=len(closed_legs),
        unpriced_positions=unpriced,
        win_rate_pct=(
            Decimal(len(wins)) / Decimal(len(closed_legs)) * 100 if closed_legs else None
        ),
        profit_factor=gross_win / gross_loss if gross_loss > 0 else None,
        max_drawdown_pct=worst.quantize(Decimal("0.01")) if realised_curve else None,
        capital_utilisation_pct=(
            allocated / starting_balance * 100 if starting_balance > 0 else _ZERO
        ),
    )
