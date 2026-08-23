"""Capital-constrained replay of a V2 ladder against stored observations.

The engine the backtest runs is `ladder.resolve` — the same function the live
V2 service calls. A replay that re-implemented the rule would be testing the
replay.

── WHAT MAKES THIS HONEST ───────────────────────────────────────────────────

  * **Chronological and capital-constrained.** Candidates are offered in the
    order they arrived. An entry is refused when the wallet cannot fund it, and
    the refusal is counted rather than quietly skipped, because "capture rate"
    is one of the figures being measured.
  * **Pool-pinned.** Every fill is costed against the depth reported *at that
    fill*, not at entry. A rug's exit is priced against the drained pool.
  * **No look-ahead.** A position's fills come from its own forward series
    only. The wallet never sees a price before its timestamp.
  * **Fills are position-intrinsic.** Size is fixed, so a position's fill
    schedule does not depend on what else the wallet holds. That is what lets
    the schedule be computed once and then walked chronologically against
    cash — it is an optimisation, not an assumption about the market.
  * **Costs are the platform's existing model.** `paper.costs` prices fee and
    constant-product impact per order. A $25 exit and a $100 exit are charged
    differently because impact is quadratic in notional, which is a large part
    of what this experiment is testing.

Nothing here writes. It reads observations and returns numbers.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal

from app.paper import costs, exits
from app.paper_v2.ladder import Fill, FillReason, LadderRules, Quote, resolve, settle_unobserved

_ZERO = Decimal(0)

#: Below this depth a $25 exit moves the price more than 10% against itself, so
#: a print here is a number rather than a fill. Stated as a rule so a reader can
#: check it: impact/notional = notional/(liquidity/2), which reaches 10% at
#: $500 for a $25 order. Rungs will not lift on a quote under it; the expiry
#: still settles there, labelled `DEAD_POOL`, because refusing to mark a dead
#: pool is how a strategy hides what it lost.
EXECUTABLE_FLOOR_USD = Decimal(500)


@dataclass(frozen=True, slots=True)
class Candidate:
    """One eligible opportunity, exactly as the live wallet received it."""

    mint_address: str
    offered_at: datetime
    entry_price: Decimal
    entry_liquidity_usd: Decimal | None
    entry_market_cap: Decimal | None
    quotes: tuple[Quote, ...]


@dataclass
class ReplayPosition:
    """One taken trade and everything that happened to it."""

    mint_address: str
    opened_at: datetime
    entry_price: Decimal
    size_usd: Decimal
    initial_quantity: Decimal
    entry_cost: Decimal
    entry_liquidity_usd: Decimal | None
    fills: list[tuple[Fill, Decimal, Decimal]] = field(default_factory=list)  # fill, net, cost
    unsettled: bool = False
    #: Highest multiple of entry **observed while held**, from the whole series
    #: and not merely from the fills. Reading it off the fills would report a
    #: position that never sold as having never risen.
    observed_peak_multiple: Decimal = _ZERO
    #: Lowest multiple observed at or after the expiry — what the token was
    #: actually worth when the clock ran out.
    terminal_multiple: Decimal = _ZERO

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
    def realised_pnl(self) -> Decimal:
        """Net of both sides. Entry cost is a real cost of having taken it."""
        return self.net_proceeds - self.size_usd

    @property
    def return_pct(self) -> Decimal:
        return self.realised_pnl / self.size_usd * 100

    @property
    def rungs_hit(self) -> int:
        return len({f.rung_index for f, _, _ in self.fills if f.rung_index is not None})

    @property
    def final_reason(self) -> str:
        for f, _, _ in reversed(self.fills):
            if f.reason is not FillReason.TARGET:
                return str(f.reason)
        return "unsettled" if self.unsettled else str(FillReason.TARGET)

    @property
    def profit_taken_before_final(self) -> Decimal:
        """Cash the ladder banked before the position's last, worst fill.

        The whole question behind the ladder: on a token that later collapsed,
        how much came back on the way up.
        """
        return sum(
            (net for f, net, _ in self.fills if f.reason is FillReason.TARGET), _ZERO
        )


@dataclass
class ReplayResult:
    label: str
    starting_capital: Decimal
    size_usd: Decimal
    positions: list[ReplayPosition]
    offered: int
    blocked: int
    peak_concurrent: int
    concurrency_samples: list[int]
    final_cash: Decimal
    equity_curve: list[tuple[datetime, Decimal]]

    @property
    def taken(self) -> int:
        return len(self.positions)

    @property
    def final_equity(self) -> Decimal:
        return self.final_cash

    @property
    def total_pnl(self) -> Decimal:
        return self.final_equity - self.starting_capital

    @property
    def wallet_return_pct(self) -> Decimal:
        return self.total_pnl / self.starting_capital * 100

    @property
    def profit_factor(self) -> Decimal | None:
        gains = sum((p.realised_pnl for p in self.positions if p.realised_pnl > 0), _ZERO)
        losses = -sum((p.realised_pnl for p in self.positions if p.realised_pnl < 0), _ZERO)
        return gains / losses if losses > 0 else None

    @property
    def expectancy(self) -> Decimal | None:
        if not self.positions:
            return None
        return sum((p.realised_pnl for p in self.positions), _ZERO) / len(self.positions)

    @property
    def max_drawdown_pct(self) -> Decimal:
        peak = self.starting_capital
        worst = _ZERO
        for _, equity in self.equity_curve:
            peak = max(peak, equity)
            if peak > 0:
                worst = max(worst, (peak - equity) / peak * 100)
        return worst

    @property
    def capture_pct(self) -> Decimal:
        return Decimal(self.taken) / Decimal(self.offered) * 100 if self.offered else _ZERO


def _executable(liquidity: Decimal | None) -> bool:
    return liquidity is not None and liquidity >= EXECUTABLE_FLOOR_USD


def _sell(quantity: Decimal, price: Decimal, liquidity: Decimal | None) -> tuple[Decimal, Decimal]:
    """Net proceeds and cost for one sale, priced against the depth at the fill."""
    gross = quantity * price
    cost = costs.side_cost(gross, liquidity)
    charge = cost.total if cost is not None else _ZERO
    return gross - charge, charge


def _ladder_fills(rules: LadderRules, c: Candidate, quantity: Decimal) -> tuple[list[Fill], bool]:
    outcome = resolve(
        rules,
        entry_price=c.entry_price,
        opened_at=c.offered_at,
        initial_quantity=quantity,
        remaining_quantity=quantity,
        quotes=c.quotes,
        already_filled=frozenset(),
    )
    fills = list(outcome.fills)
    unsettled = False
    if not outcome.closed and outcome.remaining_quantity > 0:
        last = c.quotes[-1] if c.quotes else None
        tail = settle_unobserved(
            remaining_quantity=outcome.remaining_quantity,
            last_quote=last,
            at=c.offered_at + rules.hold_for,
        )
        if tail is not None:
            fills.append(tail)
            unsettled = True
    return fills, unsettled


def _trailing_fills(c: Candidate, quantity: Decimal, *, drawdown: Decimal,
                    hold_for: timedelta | None) -> tuple[list[Fill], bool]:
    """Variant A: the live V1 rule, run through the same replay machinery.

    Uses `paper.exits` unchanged, so A is the shipped V1 contract and not a
    restatement of it.
    """
    found, _peak = exits.resolve(
        exits.ExitRules(trailing_drawdown=drawdown, hold_for=hold_for),
        entry_price=c.entry_price,
        opened_at=c.offered_at,
        quotes=[
            exits.Quote(price_usd=q.price_usd, captured_at=q.captured_at)  # type: ignore[attr-defined]
            for q in c.quotes
        ],
        peak=None,
    )
    if found is None:
        last = c.quotes[-1] if c.quotes else None
        tail = settle_unobserved(
            remaining_quantity=quantity,
            last_quote=last,
            at=c.offered_at + (hold_for or timedelta(hours=6)),
        )
        return ([tail] if tail else []), True
    liq = next((q.liquidity_usd for q in c.quotes if q.captured_at == found.at), None)
    reason = FillReason.EXPIRY if _executable(liq) else FillReason.DEAD_POOL
    return [
        Fill(
            at=found.at,
            price_usd=found.price_usd,
            quantity=quantity,
            reason=reason,
            observed_price=found.price_usd,
            liquidity_usd=liq,
        )
    ], False


def run(
    candidates: Sequence[Candidate],
    *,
    label: str,
    size_usd: Decimal,
    starting_capital: Decimal = Decimal(1000),
    rules: LadderRules | None = None,
    trailing_drawdown: Decimal | None = None,
    hold_for: timedelta | None = None,
) -> ReplayResult:
    """Offer every candidate in order; take what the wallet can fund.

    Equity marks open exposure **at cost**, which is the convention V1's
    realised curve already uses: a position that has not returned cash is
    neither a gain nor a loss until it does. Marking it to market would need a
    price for every instant, which these rows do not support.
    """
    ordered = sorted(candidates, key=lambda c: c.offered_at)
    cash = starting_capital
    taken: list[ReplayPosition] = []
    #: (fill_time, net_proceeds, cost_basis_released, position)
    pending: list[tuple[datetime, Decimal, Decimal, ReplayPosition]] = []
    outstanding: dict[int, Decimal] = {}
    blocked = 0
    curve: list[tuple[datetime, Decimal]] = []
    concurrency: list[int] = []
    peak_concurrent = 0

    def equity() -> Decimal:
        return cash + sum(outstanding.values(), _ZERO)

    def release(upto: datetime) -> None:
        nonlocal cash
        pending.sort(key=lambda row: row[0])
        while pending and pending[0][0] <= upto:
            at, net, basis, pos = pending.pop(0)
            cash += net
            key = id(pos)
            outstanding[key] = max(_ZERO, outstanding.get(key, _ZERO) - basis)
            if outstanding.get(key, _ZERO) <= 0:
                outstanding.pop(key, None)
            curve.append((at, equity()))

    for c in ordered:
        release(c.offered_at)
        open_now = len(outstanding)
        concurrency.append(open_now)
        peak_concurrent = max(peak_concurrent, open_now)

        if cash < size_usd or not c.quotes:
            blocked += 1
            continue

        entry_cost_obj = costs.side_cost(size_usd, c.entry_liquidity_usd)
        entry_cost = entry_cost_obj.total if entry_cost_obj else _ZERO
        quantity = (size_usd - entry_cost) / c.entry_price
        if quantity <= 0:
            blocked += 1
            continue

        cash -= size_usd
        pos = ReplayPosition(
            mint_address=c.mint_address,
            opened_at=c.offered_at,
            entry_price=c.entry_price,
            size_usd=size_usd,
            initial_quantity=quantity,
            entry_cost=entry_cost,
            entry_liquidity_usd=c.entry_liquidity_usd,
        )
        outstanding[id(pos)] = size_usd

        if rules is not None:
            fills, unsettled = _ladder_fills(rules, c, quantity)
        else:
            assert trailing_drawdown is not None
            fills, unsettled = _trailing_fills(
                c, quantity, drawdown=trailing_drawdown, hold_for=hold_for
            )
        pos.unsettled = unsettled
        pos.observed_peak_multiple = max(
            (q.price_usd / c.entry_price for q in c.quotes), default=_ZERO
        )
        terminal = [
            q for q in c.quotes if q.captured_at >= c.offered_at + (
                rules.hold_for if rules is not None else (hold_for or timedelta(hours=6))
            )
        ]
        pos.terminal_multiple = (
            terminal[0].price_usd / c.entry_price if terminal
            else (c.quotes[-1].price_usd / c.entry_price if c.quotes else _ZERO)
        )
        for f in fills:
            net, cost = _sell(f.quantity, f.price_usd, f.liquidity_usd)
            pos.fills.append((f, net, cost))
            basis = size_usd * (f.quantity / quantity)
            pending.append((f.at, net, basis, pos))
        taken.append(pos)
        curve.append((c.offered_at, equity()))

    if ordered:
        release(ordered[-1].offered_at + timedelta(days=365))
        curve.append((ordered[-1].offered_at, equity()))

    return ReplayResult(
        label=label,
        starting_capital=starting_capital,
        size_usd=size_usd,
        positions=taken,
        offered=len(ordered),
        blocked=blocked,
        peak_concurrent=peak_concurrent,
        concurrency_samples=concurrency,
        final_cash=cash,
        equity_curve=curve,
    )
