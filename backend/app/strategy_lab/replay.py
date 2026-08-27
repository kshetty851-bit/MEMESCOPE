"""One strategy, one $1,000 wallet, one pass through the opportunity stream.

The engine calls `rules.resolve` — the same function forward research will call.
A replay that re-implemented the exit rule would be testing the replay.

── WHAT MAKES THIS HONEST ───────────────────────────────────────────────────

  * **Chronological and capital-constrained.** Opportunities arrive in order.
    An entry the wallet cannot fund is *refused and recorded*, never quietly
    skipped, because "how much did being small cost you" is one of the figures
    under test.
  * **Independent capital.** Each strategy gets its own $1,000. No pooling, no
    lineage, no contact with any wallet's money.
  * **Pool-pinned costs.** Every fill is charged against the depth reported *at
    that fill* by `strategy_lab.execution` — the platform's fee schedule with
    the *exact* constant-product impact rather than its first-order
    approximation. A rug's exit is priced against the drained pool. See that
    module for why the approximation could not be inherited.
  * **No look-ahead.** A position's fills come only from its own forward
    series. `rules.resolve` walks that series once, forward.
  * **Marked to market, not to cost.** Equity is sampled on a fixed grid with
    every open position valued at its most recent observation. Marking open
    exposure at cost — the convention V1's realised curve uses — would report a
    book full of tokens on their way to zero as having no drawdown at all,
    which would corrupt the one risk figure the ranking depends on.

Nothing here writes. It reads observations and returns numbers.
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal

from app.strategy_lab import execution
from app.strategy_lab.opportunities import Opportunity
from app.strategy_lab.rules import (
    Fill,
    FillReason,
    resolve,
    settle_unobserved,
)
from app.strategy_lab.strategies import StrategyDefinition

_ZERO = Decimal(0)

STARTING_CAPITAL = Decimal(1000)

#: How often the equity curve is sampled. Fifteen minutes over a week is ~670
#: points per strategy — enough resolution to catch a drawdown that opens and
#: closes inside an hour, cheap enough to hold in memory for twelve strategies.
EQUITY_SAMPLE = timedelta(minutes=15)


class Refusal:
    """Why an opportunity produced no position. Recorded, never silent."""

    NO_CASH = "INSUFFICIENT_STRATEGY_LAB_CASH"
    AGE_GATE = "BLOCKED_DISCOVERY_AGE"
    UNPRICEABLE = "UNPRICEABLE_ENTRY"


@dataclass(frozen=True, slots=True)
class Missed:
    """One opportunity a strategy did not take, and what it was worth.

    `peak_multiple` is filled in from the series *after the fact*, for reporting
    only. It never reaches the strategy and cannot change a decision — the
    refusal was already made when it is computed.
    """

    mint_address: str
    source_decision_id: str
    at: datetime
    reason: str
    cash_at_refusal: Decimal
    peak_multiple: Decimal | None


@dataclass
class Position:
    """One taken trade and its complete lifecycle."""

    mint_address: str
    source_decision_id: str
    opened_at: datetime
    entry_price: Decimal
    size_usd: Decimal
    initial_quantity: Decimal
    entry_cost: Decimal
    entry_liquidity_usd: Decimal | None
    venue: str | None
    pool_address: str | None
    discovery_age_seconds: Decimal | None
    #: (fill, net proceeds, execution cost)
    fills: list[tuple[Fill, Decimal, Decimal]] = field(default_factory=list)
    observed_peak_multiple: Decimal = _ZERO
    executable_peak_multiple: Decimal = _ZERO
    terminal_multiple: Decimal | None = None
    batch_rung_fills: int = 0
    #: The clock ran out with nothing to settle on. Marked, flagged, and
    #: excluded from every figure that claims to be executable.
    unsettled: bool = False

    @property
    def gross_proceeds(self) -> Decimal:
        return sum((f.gross_proceeds for f, _, _ in self.fills), _ZERO)

    @property
    def net_proceeds(self) -> Decimal:
        return sum((net for _, net, _ in self.fills), _ZERO)

    @property
    def exit_costs(self) -> Decimal:
        return sum((c for _, _, c in self.fills), _ZERO)

    @property
    def gross_pnl(self) -> Decimal:
        """Before any execution cost, either side. Never presented as net."""
        return self.gross_proceeds - self.size_usd

    @property
    def net_pnl(self) -> Decimal:
        """After the venue's fee and price impact on both sides."""
        return self.net_proceeds - self.size_usd

    @property
    def return_pct(self) -> Decimal:
        return self.net_pnl / self.size_usd * 100

    @property
    def closed_at(self) -> datetime | None:
        return self.fills[-1][0].at if self.fills else None

    @property
    def final_reason(self) -> str:
        for f, _, _ in reversed(self.fills):
            if f.reason is not FillReason.TARGET:
                return str(f.reason)
        return str(FillReason.TARGET) if self.fills else "open"

    @property
    def rungs_hit(self) -> int:
        return len({i for f, _, _ in self.fills for i in f.rung_indexes})

    @property
    def banked_before_final(self) -> Decimal:
        """Cash returned by every fill before the last one.

        The question the whole ladder exists to answer: on a token that later
        collapsed, how much came back on the way up.
        """
        return sum((net for _, net, _ in self.fills[:-1]), _ZERO)

    @property
    def is_catastrophic(self) -> bool:
        """Ended in a pool nobody could sell into, or lost almost everything.

        `DATA_UNAVAILABLE` is deliberately excluded. That label means the series
        ran out while the pool still looked healthy — we do not know what
        happened, and counting "we do not know" as a rug would inflate every
        rug figure with the feed's own gaps. Those positions are counted under
        `unsettled` instead, and reported separately.
        """
        if not self.fills:
            return False
        last = self.fills[-1][0]
        if last.reason in (FillReason.DEAD_POOL, FillReason.UNTRADABLE):
            return True
        return not self.unsettled and self.return_pct <= Decimal(-90)


@dataclass
class Result:
    """One strategy's complete replay."""

    strategy_id: str
    version: str
    definition_hash: str
    starting_capital: Decimal
    entry_size_usd: Decimal
    positions: list[Position]
    missed: list[Missed]
    offered: int
    final_cash: Decimal
    equity_curve: list[tuple[datetime, Decimal]]
    peak_concurrent: int
    concurrency_samples: list[int]

    @property
    def taken(self) -> int:
        return len(self.positions)

    @property
    def blocked(self) -> int:
        return len(self.missed)

    @property
    def blocked_for_cash(self) -> int:
        return sum(1 for m in self.missed if m.reason == Refusal.NO_CASH)

    @property
    def final_equity(self) -> Decimal:
        """Everything settles inside the window, so final equity is final cash."""
        return self.final_cash

    @property
    def net_pnl(self) -> Decimal:
        return self.final_equity - self.starting_capital

    @property
    def gross_pnl(self) -> Decimal:
        return sum((p.gross_pnl for p in self.positions), _ZERO)

    @property
    def total_costs(self) -> Decimal:
        return sum((p.entry_cost + p.exit_costs for p in self.positions), _ZERO)

    @property
    def wallet_return_pct(self) -> Decimal:
        return self.net_pnl / self.starting_capital * 100

    @property
    def capital_deployed(self) -> Decimal:
        return sum((p.size_usd for p in self.positions), _ZERO)

    @property
    def capture_pct(self) -> Decimal:
        return Decimal(self.taken) / Decimal(self.offered) * 100 if self.offered else _ZERO

    @property
    def avg_concurrency(self) -> Decimal:
        if not self.concurrency_samples:
            return _ZERO
        return Decimal(sum(self.concurrency_samples)) / Decimal(len(self.concurrency_samples))

    @property
    def avg_hold(self) -> timedelta | None:
        spans = [p.closed_at - p.opened_at for p in self.positions if p.closed_at is not None]
        if not spans:
            return None
        return sum(spans, timedelta()) / len(spans)


def _mark_index(quotes: Sequence) -> tuple[list[datetime], list[Decimal]]:
    return [q.captured_at for q in quotes], [q.price_usd for q in quotes]


def run(
    definition: StrategyDefinition,
    opportunities: Sequence[Opportunity],
    *,
    starting_capital: Decimal = STARTING_CAPITAL,
) -> Result:
    """Offer every usable opportunity in order and take what the wallet can fund."""
    ordered = sorted((o for o in opportunities if o.usable), key=lambda o: o.eligible_at)
    size = definition.entry_size_usd
    cash = starting_capital
    positions: list[Position] = []
    missed: list[Missed] = []
    #: (when, net proceeds, cost basis released, position index)
    pending: list[tuple[datetime, Decimal, Decimal, int]] = []
    #: position index -> cost basis still deployed
    deployed: dict[int, Decimal] = {}
    #: position index -> (times, prices, initial quantity). Never pruned: the
    #: equity curve is rebuilt from it after the pass, and a map emptied as
    #: positions settled would have nothing left to mark.
    marks: dict[int, tuple[list[datetime], list[Decimal], Decimal]] = {}
    concurrency: list[int] = []
    peak_concurrent = 0

    def release(upto: datetime) -> None:
        nonlocal cash
        while pending and pending[0][0] <= upto:
            _, net, basis, index = pending.pop(0)
            cash += net
            left = deployed.get(index, _ZERO) - basis
            if left <= Decimal("0.000001"):
                deployed.pop(index, None)
            else:
                deployed[index] = left

    for opportunity in ordered:
        pending.sort(key=lambda row: row[0])
        release(opportunity.eligible_at)
        concurrency.append(len(deployed))
        peak_concurrent = max(peak_concurrent, len(deployed))

        refusal = _refuse(definition, opportunity, cash, size)
        if refusal is not None:
            missed.append(
                Missed(
                    mint_address=opportunity.mint_address,
                    source_decision_id=opportunity.source_decision_id,
                    at=opportunity.eligible_at,
                    reason=refusal,
                    cash_at_refusal=cash,
                    peak_multiple=_peak_of(opportunity),
                )
            )
            continue

        assert opportunity.entry_price is not None
        entry_cost = execution.buy(size, opportunity.liquidity_usd)
        quantity = (size - entry_cost) / opportunity.entry_price
        if quantity <= 0:
            missed.append(
                Missed(
                    mint_address=opportunity.mint_address,
                    source_decision_id=opportunity.source_decision_id,
                    at=opportunity.eligible_at,
                    reason=Refusal.UNPRICEABLE,
                    cash_at_refusal=cash,
                    peak_multiple=_peak_of(opportunity),
                )
            )
            continue

        cash -= size
        index = len(positions)
        position = Position(
            mint_address=opportunity.mint_address,
            source_decision_id=opportunity.source_decision_id,
            opened_at=opportunity.eligible_at,
            entry_price=opportunity.entry_price,
            size_usd=size,
            initial_quantity=quantity,
            entry_cost=entry_cost,
            entry_liquidity_usd=opportunity.liquidity_usd,
            venue=opportunity.venue,
            pool_address=opportunity.pool_address,
            discovery_age_seconds=opportunity.discovery_age_seconds,
        )
        deployed[index] = size
        times, prices = _mark_index(opportunity.quotes)
        marks[index] = (times, prices, quantity)

        outcome = resolve(
            definition.rules,
            entry_price=opportunity.entry_price,
            opened_at=opportunity.eligible_at,
            initial_quantity=quantity,
            quotes=opportunity.quotes,
        )
        fills = list(outcome.fills)
        if not outcome.closed and outcome.remaining_quantity > 0:
            tail = settle_unobserved(
                remaining_quantity=outcome.remaining_quantity,
                last_quote=opportunity.quotes[-1] if opportunity.quotes else None,
                at=opportunity.eligible_at + definition.rules.hold_for,
                last_executable_price=outcome.last_executable_price,
            )
            if tail is not None:
                fills.append(tail)
                position.unsettled = True

        position.observed_peak_multiple = outcome.observed_peak_multiple
        position.executable_peak_multiple = outcome.executable_peak_multiple
        position.terminal_multiple = outcome.terminal_multiple
        position.batch_rung_fills = outcome.batch_rung_fills

        for fill in fills:
            net, cost = execution.sell(fill.quantity, fill.price_usd, fill.liquidity_usd)
            position.fills.append((fill, net, cost))
            pending.append((fill.at, net, size * (fill.quantity / quantity), index))
        positions.append(position)

    if ordered:
        pending.sort(key=lambda row: row[0])
        release(ordered[-1].eligible_at + timedelta(days=365))

    curve = _equity_curve(positions, marks, ordered, starting_capital, size)
    return Result(
        strategy_id=definition.strategy_id,
        version=definition.version,
        definition_hash=definition.definition_hash,
        starting_capital=starting_capital,
        entry_size_usd=size,
        positions=positions,
        missed=missed,
        offered=len(ordered),
        final_cash=cash,
        equity_curve=curve,
        peak_concurrent=peak_concurrent,
        concurrency_samples=concurrency,
    )


def _refuse(
    definition: StrategyDefinition,
    opportunity: Opportunity,
    cash: Decimal,
    size: Decimal,
) -> str | None:
    """The entry decision, in the order the reasons should be reported.

    The age gate is checked before cash so an S9 refusal is attributed to the
    gate rather than to whatever the wallet happened to be holding — the gate is
    the hypothesis, and a refusal miscredited to cash would hide it.
    """
    if definition.min_discovery_age is not None:
        age = opportunity.discovery_age_seconds
        if age is None or age < Decimal(definition.min_discovery_age.total_seconds()):
            return Refusal.AGE_GATE
    if opportunity.entry_price is None or opportunity.entry_price <= 0:
        return Refusal.UNPRICEABLE
    if cash < size:
        return Refusal.NO_CASH
    return None


def _peak_of(opportunity: Opportunity) -> Decimal | None:
    if not opportunity.quotes or not opportunity.entry_price:
        return None
    return max(q.price_usd for q in opportunity.quotes) / opportunity.entry_price


def _equity_curve(
    positions: Sequence[Position],
    marks: dict[int, tuple[list[datetime], list[Decimal], Decimal]],
    ordered: Sequence[Opportunity],
    starting_capital: Decimal,
    size: Decimal,
) -> list[tuple[datetime, Decimal]]:
    """Cash plus mark-to-market open value, sampled on a fixed grid.

    Rebuilt in a second pass rather than accumulated in the first, because
    marking a position requires knowing its whole fill schedule and the first
    pass discovers those as it goes. The two passes see the same events; this
    one just also asks "and what was everything else worth at that instant".
    """
    if not positions or not ordered:
        return []

    #: (when, cash delta, quantity sold, index). `sold is None` marks the entry
    #: event — a sentinel rather than "sold == 0", because a zero-quantity fill
    #: would otherwise reopen the position at its full size.
    schedule: list[tuple[datetime, Decimal, Decimal | None, int]] = []
    for index, position in enumerate(positions):
        schedule.append((position.opened_at, -position.size_usd, None, index))
        for fill, net, _ in position.fills:
            schedule.append((fill.at, net, fill.quantity, index))
    schedule.sort(key=lambda row: (row[0], row[2] is not None))

    start = ordered[0].eligible_at
    end = max(row[0] for row in schedule)
    held: dict[int, Decimal] = {}
    cash = starting_capital
    curve: list[tuple[datetime, Decimal]] = []
    cursor = 0
    t = start

    def mark(at: datetime) -> Decimal:
        total = _ZERO
        for index, quantity in held.items():
            if quantity <= 0:
                continue
            times, prices, _ = marks.get(index, ([], [], _ZERO))
            pos = bisect_right(times, at) - 1
            if pos >= 0:
                total += quantity * prices[pos]
        return total

    while t <= end + EQUITY_SAMPLE:
        while cursor < len(schedule) and schedule[cursor][0] <= t:
            _, delta, sold, index = schedule[cursor]
            cash += delta
            if sold is None:
                held[index] = marks[index][2]
            else:
                held[index] = held.get(index, _ZERO) - sold
                if held[index] <= 0:
                    held.pop(index, None)
            cursor += 1
        curve.append((t, cash + mark(t)))
        t += EQUITY_SAMPLE
    return curve
