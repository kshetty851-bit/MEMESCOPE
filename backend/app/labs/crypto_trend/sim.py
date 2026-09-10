"""A minimal in-memory account for the replay. NOT the platform paper wallet.

Money only: fills at a price with slippage and a taker fee, funding at 8h
boundaries, realised and unrealised P&L. Position logic — trailing, exits,
sizing — lives in `strategy.py`; this file just books what it is told.

Conventions: `cash` moves only by fees, funding and realised P&L, so equity
is `cash + unrealised` and starts at the configured equity. A long buys at
`open x (1 + slippage)` and sells at `open x (1 - slippage)`; a short the
reverse. Funding at rate r on notional N costs a long `r x N` and a short
`-r x N` — positive funding is paid by longs to shorts.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime

from app.labs.crypto_trend.strategy import LONG, Order, Position, StrategyConfig


@dataclass(frozen=True, slots=True)
class Trade:
    symbol: str
    side: str
    qty: float
    entry_price: float
    exit_price: float
    opened_at: datetime
    closed_at: datetime
    bars_held: int
    notional: float
    implied_leverage: float
    #: Entry and exit fees together.
    fees: float
    #: Net funding paid while open (negative = received).
    funding: float
    #: Net of fees and funding.
    pnl_usd: float
    #: `pnl_usd` over `risk_usd` — the dollars the stop could actually lose.
    pnl_r: float
    #: qty x stop_distance at fill: the risk ACTUALLY taken.
    risk_usd: float
    reason: str
    #: RISK_PER_TRADE x equity at the decision: the risk INTENDED. Smaller
    #: than `risk_usd` never; larger whenever the notional cap bound.
    intended_risk_usd: float = 0.0


class SimAccount:
    def __init__(self, cfg: StrategyConfig) -> None:
        self.cfg = cfg
        self.cash = cfg.starting_equity
        self.positions: dict[str, Position] = {}
        self.trades: list[Trade] = []
        self.fees_total = 0.0
        self.funding_total = 0.0

    # --- prices ----------------------------------------------------------------

    def _slip(self) -> float:
        return self.cfg.slippage_bps / 10_000.0

    def entry_price(self, side: str, open_price: float) -> float:
        slip = self._slip()
        return open_price * (1.0 + slip) if side == LONG else open_price * (1.0 - slip)

    def exit_price(self, side: str, open_price: float) -> float:
        slip = self._slip()
        return open_price * (1.0 - slip) if side == LONG else open_price * (1.0 + slip)

    # --- fills -------------------------------------------------------------------

    def fill_open(self, order: Order, open_price: float, now: datetime) -> Position:
        assert order.qty is not None and order.stop_distance is not None
        assert order.atr is not None
        price = self.entry_price(order.side, open_price)
        notional = order.qty * price
        fee = notional * self.cfg.fee_taker
        self.cash -= fee
        self.fees_total += fee
        sign = 1.0 if order.side == LONG else -1.0
        position = Position(
            symbol=order.symbol, side=order.side, qty=order.qty, entry_price=price,
            stop=price - order.stop_distance * sign, stop_distance=order.stop_distance,
            atr_at_entry=order.atr, opened_at=now, bars_held=0, best_close=price,
            trail_stop=None, notional_at_entry=notional,
            implied_leverage=order.implied_leverage or 0.0, fees_paid=fee, funding_paid=0.0,
            reason=order.reason, intended_risk_usd=order.intended_risk_usd or 0.0)
        self.positions[order.symbol] = position
        return position

    def fill_close(self, symbol: str, open_price: float, now: datetime, reason: str) -> Trade:
        p = self.positions.pop(symbol)
        price = self.exit_price(p.side, open_price)
        fee = p.qty * price * self.cfg.fee_taker
        gross = (price - p.entry_price) * p.qty * p.sign
        self.cash += gross - fee
        self.fees_total += fee
        fees = p.fees_paid + fee
        pnl = gross - fees - p.funding_paid
        risk = p.stop_distance * p.qty
        trade = Trade(
            symbol=symbol, side=p.side, qty=p.qty, entry_price=p.entry_price, exit_price=price,
            opened_at=p.opened_at, closed_at=now, bars_held=p.bars_held,
            notional=p.notional_at_entry, implied_leverage=p.implied_leverage, fees=fees,
            funding=p.funding_paid, pnl_usd=pnl, pnl_r=pnl / risk if risk else 0.0,
            risk_usd=risk, reason=reason, intended_risk_usd=p.intended_risk_usd)
        self.trades.append(trade)
        return trade

    # --- carry ---------------------------------------------------------------------

    def charge_funding(self, symbol: str, rate: float, mark: float) -> float:
        """Returns what the position paid (negative = received)."""
        p = self.positions[symbol]
        cost = rate * p.qty * mark * p.sign
        self.cash -= cost
        self.funding_total += cost
        self.positions[symbol] = replace(p, funding_paid=p.funding_paid + cost)
        return cost

    # --- valuation -------------------------------------------------------------------

    def unrealised(self, marks: Mapping[str, float]) -> float:
        return sum(p.unrealised(marks[s]) for s, p in self.positions.items() if s in marks)

    def equity(self, marks: Mapping[str, float]) -> float:
        return self.cash + self.unrealised(marks)
