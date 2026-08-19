"""Frozen V1.2 progressive-profit-lock research replay.

Research-only.  It imports the canonical opportunity/cost primitives but never
writes a wallet or alters the promoted V1.1 rule.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from app.paper import costs
from app.paper.canonical_replay import (
    POSITION_SIZE,
    STARTING_CAPITAL,
    SURVIVAL_MINIMUM,
    Opportunity,
)
from app.paper.models import Quote

INITIAL_STOP = Decimal("-0.15")
LOCKS: tuple[tuple[Decimal, Decimal], ...] = (
    (Decimal("0.15"), Decimal("0")),
    (Decimal("0.25"), Decimal("0.10")),
    (Decimal("0.40"), Decimal("0.20")),
    (Decimal("0.60"), Decimal("0.35")),
    (Decimal("1.00"), Decimal("0.60")),
)


@dataclass(frozen=True, slots=True)
class Trade:
    mint: str
    opened_at: datetime
    entry_price: Decimal
    quantity: Decimal
    entry_cost: Decimal
    closed_at: datetime | None
    exit_price: Decimal | None
    exit_cost: Decimal | None
    exit_kind: str | None
    final_mark: Decimal | None
    reached: tuple[Decimal, ...]

    @property
    def final_price(self) -> Decimal | None:
        return self.exit_price if self.exit_price is not None else self.final_mark

    @property
    def gross_return_pct(self) -> Decimal | None:
        price = self.final_price
        return None if price is None else (price / self.entry_price - 1) * 100

    @property
    def net_pnl(self) -> Decimal | None:
        if self.exit_price is None or self.exit_cost is None:
            return None
        return (
            self.quantity * self.exit_price - POSITION_SIZE - self.entry_cost - self.exit_cost
        )

    @property
    def marked_pnl(self) -> Decimal | None:
        if self.final_mark is None:
            return None
        return self.quantity * self.final_mark - POSITION_SIZE - self.entry_cost


@dataclass(frozen=True, slots=True)
class Result:
    trades: tuple[Trade, ...]
    accepted: int
    rejected_survival: int
    rejected_cash: int
    rejected_missing: int
    cash: Decimal
    realized_pnl: Decimal
    unrealized_pnl: Decimal | None
    equity: Decimal | None
    costs: Decimal
    max_drawdown_pct: Decimal


def _cost(notional: Decimal, liquidity: Decimal | None) -> Decimal | None:
    side = costs.side_cost(notional, liquidity)
    return None if side is None else side.total


def _exit(
    entry: Trade, quotes: Sequence[Quote]
) -> tuple[Quote | None, str | None, tuple[Decimal, ...]]:
    floor = INITIAL_STOP
    peak = Decimal(0)
    reached: list[Decimal] = []
    for quote in quotes:
        if quote.captured_at < entry.opened_at or quote.price_usd <= 0:
            continue
        returned = quote.price_usd / entry.entry_price - 1
        # The floor available before this observation is tested first. A quote
        # cannot both discover a new high and be exited at a floor it just set.
        if returned <= floor:
            return (
                quote,
                "initial_stop" if floor == INITIAL_STOP else "profit_floor",
                tuple(reached),
            )
        if returned > peak:
            peak = returned
            for threshold, protected in LOCKS:
                if peak >= threshold and threshold not in reached:
                    reached.append(threshold)
                    floor = max(floor, protected)
            if peak >= Decimal(1):
                floor = max(floor, peak * Decimal("0.60"))
    return None, None, tuple(reached)


def replay(
    opportunities: Sequence[Opportunity], histories: Mapping[str, Sequence[Quote]]
) -> Result:
    ordered = sorted(opportunities, key=lambda row: (row.observed_at, row.mint))
    cash = STARTING_CAPITAL
    open_trades: list[Trade] = []
    closed: list[Trade] = []
    accepted = rejected_survival = rejected_cash = rejected_missing = 0
    seen: set[str] = set()
    path = [STARTING_CAPITAL]

    def settle(through: datetime) -> None:
        nonlocal cash
        keep: list[Trade] = []
        for trade in open_trades:
            breach, kind, reached = _exit(trade, histories.get(trade.mint, ()))
            if breach is None or breach.captured_at > through:
                keep.append(trade)
                continue
            exit_cost = _cost(trade.quantity * breach.price_usd, breach.liquidity_usd)
            if exit_cost is None:
                keep.append(trade)
                continue
            settled = Trade(
                trade.mint,
                trade.opened_at,
                trade.entry_price,
                trade.quantity,
                trade.entry_cost,
                breach.captured_at,
                breach.price_usd,
                exit_cost,
                kind,
                None,
                reached,
            )
            cash += settled.quantity * breach.price_usd - exit_cost
            closed.append(settled)
            path.append(cash + sum(row.quantity * row.entry_price for row in keep))
        open_trades[:] = keep

    for candidate in ordered:
        settle(candidate.observed_at)
        if candidate.mint in seen:
            continue
        seen.add(candidate.mint)
        if (
            candidate.price <= 0
            or candidate.liquidity is None
            or candidate.liquidity <= 0
            or candidate.volume_24h is None
        ):
            rejected_missing += 1
            continue
        if candidate.volume_24h / candidate.liquidity < SURVIVAL_MINIMUM:
            rejected_survival += 1
            continue
        entry_cost = _cost(POSITION_SIZE, candidate.liquidity)
        if entry_cost is None:
            rejected_missing += 1
            continue
        if cash < POSITION_SIZE + entry_cost:
            rejected_cash += 1
            continue
        cash -= POSITION_SIZE + entry_cost
        accepted += 1
        open_trades.append(
            Trade(
                candidate.mint,
                candidate.observed_at,
                candidate.price,
                POSITION_SIZE / candidate.price,
                entry_cost,
                None,
                None,
                None,
                None,
                None,
                (),
            )
        )

    end = (
        datetime.max.replace(tzinfo=ordered[-1].observed_at.tzinfo)
        if ordered
        else datetime.max
    )
    settle(end)
    marked: list[Trade] = []
    for trade in open_trades:
        history = histories.get(trade.mint, ())
        final = history[-1] if history else None
        _, _, reached = _exit(trade, history)
        marked.append(
            Trade(
                trade.mint,
                trade.opened_at,
                trade.entry_price,
                trade.quantity,
                trade.entry_cost,
                None,
                None,
                None,
                None,
                final.price_usd if final else None,
                reached,
            )
        )
    all_trades = tuple(sorted([*closed, *marked], key=lambda row: (row.opened_at, row.mint)))
    realized = sum((row.net_pnl or Decimal(0) for row in closed), Decimal(0))
    unrealizeds = [row.marked_pnl for row in marked]
    unrealized = (
        None if any(value is None for value in unrealizeds) else sum(unrealizeds, Decimal(0))
    )
    equity = None if unrealized is None else STARTING_CAPITAL + realized + unrealized
    total_cost = sum(
        (row.entry_cost + (row.exit_cost or Decimal(0)) for row in all_trades), Decimal(0)
    )
    peak = STARTING_CAPITAL
    max_drawdown = Decimal(0)
    for equity_point in path:
        peak = max(peak, equity_point)
        if peak:
            max_drawdown = max(max_drawdown, (peak - equity_point) / peak * 100)
    return Result(
        all_trades,
        accepted,
        rejected_survival,
        rejected_cash,
        rejected_missing,
        cash,
        realized,
        unrealized,
        equity,
        total_cost,
        max_drawdown,
    )
