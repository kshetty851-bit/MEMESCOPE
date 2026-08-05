"""Wallet metrics, derived from positions and nothing else.

Every figure here is a pure function of the trades. Nothing is stored, so
nothing can drift from the rows it claims to summarise — the same reason the
Radar recomputes its dimension breakdown rather than trusting a cached one.

Two figures state their own limits rather than overstating:

  - **Equity** is `None` when an open position's token has no current reading.
    A holding nobody has priced is unmeasured, not worthless, and marking it to
    zero would report a loss the market never delivered.
  - **Maximum drawdown** is measured on the *realised* equity curve — the value
    after each close, in close order. The path between closes is not
    reconstructed, because the platform does not store an equity series. It is
    therefore a floor on the true drawdown, and the API says so.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from app.paper.models import ClosedTrade, ExitReason, OpenPosition

_ZERO = Decimal(0)


@dataclass(frozen=True, slots=True)
class WalletMetrics:
    """Everything the wallet reports about itself.

    `None` never means zero. It means the figure has no rows behind it — no
    closed trade to average, no priced holding to value — and every surface
    renders it as a dash.
    """

    starting_balance: Decimal
    cash: Decimal
    #: Cash plus the value of open holdings. `None` when any holding is unpriced.
    equity: Decimal | None
    #: Equity against starting balance, as a percentage. `None` follows equity.
    roi_pct: Decimal | None
    #: Value of open holdings, and how many could not be priced.
    open_value: Decimal | None
    #: What the open holdings **cost** — the sum of what was committed at entry.
    #: Never `None`: an unpriced holding has an unknown value but a known cost,
    #: and conflating the two would make "invested" disappear when a price does.
    invested_usd: Decimal
    unpriced_positions: int

    open_positions: int
    closed_positions: int

    realised_pnl: Decimal
    win_rate_pct: Decimal | None
    average_win: Decimal | None
    average_loss: Decimal | None
    #: Gross profit over gross loss. `None` when nothing has lost yet — the
    #: ratio is undefined, not infinite, and printing ∞ reads as a claim.
    profit_factor: Decimal | None
    largest_winner: Decimal | None
    largest_loser: Decimal | None
    max_drawdown_pct: Decimal | None
    average_hold_hours: Decimal | None
    exits_by_reason: dict[str, int]


def cash_for(
    starting_balance: Decimal,
    open_positions: Sequence[OpenPosition],
    closed: Sequence[ClosedTrade],
) -> Decimal:
    """Uninvested cash, derived rather than stored.

    A stored balance is a second source of truth that drifts from the positions
    the moment one write lands without the other. This cannot drift: it is the
    starting capital, less what is currently tied up, plus what came back.
    """
    committed = sum((position.size_usd for position in open_positions), _ZERO)
    returned = sum((trade.proceeds for trade in closed), _ZERO)
    spent = sum((trade.size_usd for trade in closed), _ZERO)
    return starting_balance - committed - spent + returned


def max_drawdown_pct(
    starting_balance: Decimal, closed: Sequence[ClosedTrade]
) -> Decimal | None:
    """The deepest peak-to-trough fall of the realised equity curve, as a percent.

    Walks closes in the order they happened, tracking the running high-water
    mark. `None` when nothing has closed — an untested wallet has no measured
    drawdown, and reporting 0% would claim it survived something.
    """
    if not closed:
        return None

    equity = starting_balance
    peak = starting_balance
    worst = _ZERO
    for trade in sorted(closed, key=lambda item: (item.closed_at, item.mint_address)):
        equity += trade.pnl
        if equity > peak:
            peak = equity
        if peak > 0:
            fall = (peak - equity) / peak * 100
            if fall > worst:
                worst = fall
    return worst.quantize(Decimal("0.01"))


def summarise(
    *,
    starting_balance: Decimal,
    open_positions: Sequence[OpenPosition],
    prices: dict[str, Decimal | None],
    closed: Sequence[ClosedTrade],
) -> WalletMetrics:
    """Every reported figure, from the trades alone."""
    cash = cash_for(starting_balance, open_positions, closed)

    open_value: Decimal | None = _ZERO
    unpriced = 0
    for position in open_positions:
        price = prices.get(position.mint_address)
        if price is None:
            unpriced += 1
            open_value = None
            continue
        if open_value is not None:
            open_value += position.quantity * price

    equity = None if open_value is None else cash + open_value
    roi = (
        None
        if equity is None or starting_balance <= 0
        else ((equity - starting_balance) / starting_balance * 100).quantize(Decimal("0.01"))
    )

    wins = [trade for trade in closed if trade.pnl > 0]
    losses = [trade for trade in closed if trade.pnl < 0]
    gross_profit = sum((trade.pnl for trade in wins), _ZERO)
    gross_loss = sum((-trade.pnl for trade in losses), _ZERO)

    hold_hours = [
        Decimal((trade.closed_at - trade.opened_at).total_seconds()) / Decimal(3600)
        for trade in closed
    ]

    return WalletMetrics(
        starting_balance=starting_balance,
        cash=cash.quantize(Decimal("0.01")),
        equity=None if equity is None else equity.quantize(Decimal("0.01")),
        roi_pct=roi,
        open_value=None if open_value is None else open_value.quantize(Decimal("0.01")),
        invested_usd=sum((position.size_usd for position in open_positions), _ZERO).quantize(
            Decimal("0.01")
        ),
        unpriced_positions=unpriced,
        open_positions=len(open_positions),
        closed_positions=len(closed),
        realised_pnl=sum((trade.pnl for trade in closed), _ZERO).quantize(Decimal("0.01")),
        win_rate_pct=(
            None
            if not closed
            else (Decimal(len(wins)) / Decimal(len(closed)) * 100).quantize(Decimal("0.01"))
        ),
        average_win=(
            None if not wins else (gross_profit / Decimal(len(wins))).quantize(Decimal("0.01"))
        ),
        average_loss=(
            None
            if not losses
            else (gross_loss / Decimal(len(losses))).quantize(Decimal("0.01"))
        ),
        # Undefined rather than infinite while nothing has lost. A wallet with
        # three wins and no losses has not proven a ratio.
        profit_factor=(
            None if gross_loss <= 0 else (gross_profit / gross_loss).quantize(Decimal("0.01"))
        ),
        largest_winner=(None if not wins else max(trade.pnl for trade in wins)),
        largest_loser=(None if not losses else min(trade.pnl for trade in losses)),
        max_drawdown_pct=max_drawdown_pct(starting_balance, closed),
        average_hold_hours=(
            None
            if not hold_hours
            else (sum(hold_hours, _ZERO) / Decimal(len(hold_hours))).quantize(Decimal("0.01"))
        ),
        exits_by_reason={
            reason.value: sum(1 for trade in closed if trade.reason is reason)
            for reason in ExitReason
        },
    )


def pnl_since(closed: Sequence[ClosedTrade], *, since: datetime) -> Decimal:
    """Realised profit from trades closed at or after a moment.

    Realised only. An open position's unrealised move is not "today's P/L" in
    any sense a reader can act on, and mixing the two produces a figure that
    changes when nothing was traded.
    """
    realised = sum((trade.pnl for trade in closed if trade.closed_at >= since), _ZERO)
    return realised.quantize(Decimal("0.01"))
