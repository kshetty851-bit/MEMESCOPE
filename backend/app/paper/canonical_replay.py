"""Authoritative historical restatement for the promoted V1.1 paper rules.

This module deliberately does not write a wallet or an audit.
It is a deterministic research projection over immutable observations.  The
forward V1.1 wallet and all earlier research artefacts therefore remain intact.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from app.paper import costs
from app.paper.models import ExitReason, Quote

STARTING_CAPITAL = Decimal("1000")
POSITION_SIZE = Decimal("100")
SURVIVAL_MINIMUM = Decimal("1.25")
TAKE_PROFIT = Decimal("1.30")
HARD_STOP = Decimal("0.75")
EXECUTION_MODEL = "legacy_constant_product_v1"
HISTORICAL_QUOTE_LIMITATION = (
    "No immutable, timestamp-matched Jupiter quote is stored for this historical "
    "decision; the production legacy fallback cost model was used."
)


@dataclass(frozen=True, slots=True)
class Opportunity:
    mint: str
    observed_at: datetime
    rank: int
    price: Decimal
    liquidity: Decimal | None
    volume_24h: Decimal | None
    market_cap: Decimal | None


@dataclass(frozen=True, slots=True)
class ReplayTrade:
    mint: str
    opened_at: datetime
    entry_price: Decimal
    quantity: Decimal
    entry_liquidity: Decimal
    entry_cost: Decimal
    closed_at: datetime | None
    exit_price: Decimal | None
    exit_liquidity: Decimal | None
    exit_cost: Decimal | None
    reason: ExitReason | None
    final_mark: Decimal | None

    @property
    def closed(self) -> bool:
        return self.closed_at is not None

    @property
    def gross_pnl(self) -> Decimal | None:
        if self.exit_price is None:
            return None
        return self.quantity * self.exit_price - POSITION_SIZE

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
class ReplayResult:
    trades: tuple[ReplayTrade, ...]
    accepted: int
    rejected_survival: int
    rejected_insufficient_cash: int
    rejected_missing_data: int
    cash: Decimal
    realized_pnl: Decimal
    unrealized_pnl: Decimal | None
    marked_equity: Decimal | None
    total_costs: Decimal
    max_drawdown_pct: Decimal | None


def _first_breach(
    entry: Opportunity, quotes: Sequence[Quote]
) -> tuple[Quote | None, ExitReason | None]:
    """Return the first *observed* TP/stop breach, never a theoretical fill."""
    for quote in quotes:
        if quote.captured_at < entry.observed_at or quote.price_usd <= 0:
            continue
        if quote.price_usd <= entry.price * HARD_STOP:
            return quote, ExitReason.STOP
        if quote.price_usd >= entry.price * TAKE_PROFIT:
            return quote, ExitReason.TARGET
    return None, None


def _side_cost(notional: Decimal, liquidity: Decimal | None) -> Decimal | None:
    side = costs.side_cost(notional, liquidity)
    return None if side is None else side.total


def replay(
    opportunities: Sequence[Opportunity], histories: Mapping[str, Sequence[Quote]]
) -> ReplayResult:
    """Replay a finite $1,000 portfolio in chronological opportunity order.

    Candidates are only entry *opportunities*.  A future legacy trade outcome
    is never used to decide eligibility; exits are settled only as their
    observed timestamp arrives.  Costable trades use the exact live fallback
    model rather than a separate research formula.  A missing liquidity value
    is refused because a partially costed result would not be authoritative.
    """
    ordered = sorted(opportunities, key=lambda item: (item.observed_at, item.mint))
    cash = STARTING_CAPITAL
    open_trades: list[ReplayTrade] = []
    closed: list[ReplayTrade] = []
    accepted = rejected_survival = rejected_cash = rejected_missing = 0
    seen: set[str] = set()
    equity_path: list[Decimal] = [STARTING_CAPITAL]

    def settle_through(at: datetime) -> None:
        nonlocal cash
        remaining: list[ReplayTrade] = []
        for trade in open_trades:
            history = histories.get(trade.mint, ())
            entry = Opportunity(
                trade.mint,
                trade.opened_at,
                0,
                trade.entry_price,
                trade.entry_liquidity,
                None,
                None,
            )
            breach, reason = _first_breach(entry, history)
            if breach is None or breach.captured_at > at:
                remaining.append(trade)
                continue
            exit_cost = _side_cost(trade.quantity * breach.price_usd, breach.liquidity_usd)
            if exit_cost is None:
                # Historical costs are incomplete: do not manufacture a close.
                remaining.append(trade)
                continue
            settled = ReplayTrade(
                mint=trade.mint,
                opened_at=trade.opened_at,
                entry_price=trade.entry_price,
                quantity=trade.quantity,
                entry_liquidity=trade.entry_liquidity,
                entry_cost=trade.entry_cost,
                closed_at=breach.captured_at,
                exit_price=breach.price_usd,
                exit_liquidity=breach.liquidity_usd,
                exit_cost=exit_cost,
                reason=reason,
                final_mark=None,
            )
            cash += settled.quantity * breach.price_usd - exit_cost
            closed.append(settled)
            equity_path.append(cash + sum(t.quantity * t.entry_price for t in remaining))
        open_trades[:] = remaining

    for opportunity in ordered:
        settle_through(opportunity.observed_at)
        if opportunity.mint in seen:
            continue
        seen.add(opportunity.mint)
        if (
            opportunity.price <= 0
            or opportunity.liquidity is None
            or opportunity.liquidity <= 0
            or opportunity.volume_24h is None
        ):
            rejected_missing += 1
            continue
        if opportunity.volume_24h / opportunity.liquidity < SURVIVAL_MINIMUM:
            rejected_survival += 1
            continue
        entry_cost = _side_cost(POSITION_SIZE, opportunity.liquidity)
        if entry_cost is None:
            rejected_missing += 1
            continue
        # Cost is a real cash obligation.  A $100 notional is never part-filled.
        if cash < POSITION_SIZE + entry_cost:
            rejected_cash += 1
            continue
        cash -= POSITION_SIZE + entry_cost
        accepted += 1
        open_trades.append(
            ReplayTrade(
                mint=opportunity.mint,
                opened_at=opportunity.observed_at,
                entry_price=opportunity.price,
                quantity=POSITION_SIZE / opportunity.price,
                entry_liquidity=opportunity.liquidity,
                entry_cost=entry_cost,
                closed_at=None,
                exit_price=None,
                exit_liquidity=None,
                exit_cost=None,
                reason=None,
                final_mark=None,
            )
        )

    # Dataset end: settle real breaches observed in the complete immutable path,
    # otherwise leave the position open and mark only at its final observation.
    end_at = (
        datetime.max.replace(tzinfo=ordered[-1].observed_at.tzinfo)
        if ordered
        else datetime.max
    )
    settle_through(end_at)
    marked_open: list[ReplayTrade] = []
    for trade in open_trades:
        history = histories.get(trade.mint, ())
        final = history[-1] if history else None
        marked_open.append(
            ReplayTrade(
                mint=trade.mint,
                opened_at=trade.opened_at,
                entry_price=trade.entry_price,
                quantity=trade.quantity,
                entry_liquidity=trade.entry_liquidity,
                entry_cost=trade.entry_cost,
                closed_at=None,
                exit_price=None,
                exit_liquidity=None,
                exit_cost=None,
                reason=None,
                final_mark=final.price_usd if final else None,
            )
        )

    all_trades = tuple(
        sorted([*closed, *marked_open], key=lambda item: (item.opened_at, item.mint))
    )
    realized = sum((trade.net_pnl or Decimal(0) for trade in closed), Decimal(0))
    unrealized_values = [trade.marked_pnl for trade in marked_open]
    unrealized = (
        None
        if any(value is None for value in unrealized_values)
        else sum(unrealized_values, Decimal(0))
    )
    marked_equity = None if unrealized is None else STARTING_CAPITAL + realized + unrealized
    total_costs = sum(
        (trade.entry_cost + (trade.exit_cost or Decimal(0)) for trade in all_trades),
        Decimal(0),
    )
    peak = STARTING_CAPITAL
    drawdown = Decimal(0)
    for value in equity_path:
        peak = max(peak, value)
        if peak > 0:
            drawdown = max(drawdown, (peak - value) / peak * Decimal(100))
    return ReplayResult(
        all_trades,
        accepted,
        rejected_survival,
        rejected_cash,
        rejected_missing,
        cash,
        realized,
        unrealized,
        marked_equity,
        total_costs,
        drawdown,
    )
