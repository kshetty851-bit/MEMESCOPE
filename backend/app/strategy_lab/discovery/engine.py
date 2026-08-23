"""Evaluating 1,850 strategies without 1,850 passes over the market. §22.

── THE OPTIMISATION, AND WHY IT IS EXACT ────────────────────────────────────

A fill schedule — *which* rungs fire, *when*, and at *what observed price* — is
determined by the price path and the rule alone. It does not depend on position
size, because every rung is a fraction of the initial quantity and the trigger
is a multiple of the entry price. It does not depend on the wallet, because size
is fixed and a position's own series is all `rules.resolve` reads.

So the schedule is resolved **once per (opportunity x profit x exit)** and reused
across every entry filter, every size and every portfolio control that shares
it. 537 opportunities x 7 profit configs x 8 exit configs = ~30,000 resolutions,
against 1,850 x 537 = ~993,000 if each strategy replayed the market itself.

What is *not* cached is anything size-dependent: execution cost is quadratic in
notional, so proceeds are computed per strategy from the cached fractions. The
cache holds the schedule, never the money.

This is an optimisation, not an assumption about the market — it is the same
property `paper_v2.replay` relies on, stated there as "fills are
position-intrinsic".

── WHAT THE CHRONOLOGICAL WALK STILL DOES PER STRATEGY ──────────────────────

Cash, blocking, concurrency and the portfolio breakers are wallet state and
cannot be cached: they depend on everything the strategy did before. That walk
is O(opportunities) per strategy, which is cheap.

Nothing here writes. It reads frozen opportunities and returns numbers.
"""

from __future__ import annotations

import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from app.strategy_lab import execution
from app.strategy_lab.discovery.space import Candidate, EntryConfig, PortfolioConfig
from app.strategy_lab.opportunities import Opportunity
from app.strategy_lab.rules import (
    FillReason,
    StrategyRules,
    resolve,
    settle_unobserved,
)

_ZERO = Decimal(0)
_ONE = Decimal(1)

STARTING_CAPITAL = Decimal(1000)

#: A position is catastrophic when its pool became untradable, or it lost
#: essentially everything. Matches `strategy_lab.replay.Position`.
_CATASTROPHIC_RETURN_PCT = Decimal(-90)

#: Moonshot levels reported for retention. §19.
MOONSHOT_LEVELS: tuple[Decimal, ...] = (
    Decimal("1.5"),
    Decimal(2),
    Decimal(5),
    Decimal(10),
)


@dataclass(frozen=True, slots=True)
class ScheduledFill:
    """One sale, as a *fraction* of the initial quantity. Size-free."""

    at: datetime
    price_usd: Decimal
    fraction: Decimal
    reason: FillReason
    liquidity_usd: Decimal | None
    rung_indexes: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class Schedule:
    """Everything one (opportunity, profit, exit) triple produces."""

    fills: tuple[ScheduledFill, ...]
    unsettled: bool
    observed_peak_multiple: Decimal
    executable_peak_multiple: Decimal
    closed_at: datetime | None


class ScheduleCache:
    """Resolves each (opportunity, rules) pair once and remembers it."""

    def __init__(self, opportunities: Sequence[Opportunity]) -> None:
        self._opportunities = list(opportunities)
        self._by_mint = {o.mint_address: i for i, o in enumerate(self._opportunities)}
        self._cache: dict[tuple[int, str, str], Schedule] = {}
        self.resolutions = 0

    @property
    def opportunities(self) -> list[Opportunity]:
        return self._opportunities

    def get(
        self, index: int, profit_key: str, exit_key: str, rules: StrategyRules
    ) -> Schedule:
        cache_key = (index, profit_key, exit_key)
        hit = self._cache.get(cache_key)
        if hit is not None:
            return hit
        schedule = self._resolve(self._opportunities[index], rules)
        self._cache[cache_key] = schedule
        self.resolutions += 1
        return schedule

    def _resolve(self, opportunity: Opportunity, rules: StrategyRules) -> Schedule:
        assert opportunity.entry_price is not None
        # Unit quantity: every fill comes back as a fraction of the position,
        # which is exactly what makes the result size-free.
        outcome = resolve(
            rules,
            entry_price=opportunity.entry_price,
            opened_at=opportunity.eligible_at,
            initial_quantity=_ONE,
            quotes=opportunity.quotes,
        )
        fills = list(outcome.fills)
        unsettled = False
        if not outcome.closed and outcome.remaining_quantity > 0:
            tail = settle_unobserved(
                remaining_quantity=outcome.remaining_quantity,
                last_quote=opportunity.quotes[-1] if opportunity.quotes else None,
                at=opportunity.eligible_at + rules.hold_for,
                last_executable_price=outcome.last_executable_price,
            )
            if tail is not None:
                fills.append(tail)
                unsettled = True

        return Schedule(
            fills=tuple(
                ScheduledFill(
                    at=f.at,
                    price_usd=f.price_usd,
                    fraction=f.quantity,
                    reason=f.reason,
                    liquidity_usd=f.liquidity_usd,
                    rung_indexes=f.rung_indexes,
                )
                for f in fills
            ),
            unsettled=unsettled,
            observed_peak_multiple=outcome.observed_peak_multiple,
            executable_peak_multiple=outcome.executable_peak_multiple,
            closed_at=fills[-1].at if fills else None,
        )


# ── Entry admission ─────────────────────────────────────────────────────────


class Refusal:
    NO_CASH = "INSUFFICIENT_CASH"
    ENTRY_FILTER = "ENTRY_FILTER"
    EXPOSURE_CAP = "EXPOSURE_CAP"
    BREAKER = "BREAKER_PAUSED"
    UNPRICEABLE = "UNPRICEABLE"


def _sell_buy(opportunity: Opportunity) -> Decimal | None:
    """Sells divided by buys over 24h, from the two counts.

    Computed rather than inverted from the stored buy/sell ratio so a zero on
    either side is a `None` a caller must handle, not an infinity that silently
    passes every threshold.
    """
    buys, sells = opportunity.buys_24h, opportunity.sells_24h
    if buys is None or sells is None or buys <= 0:
        return None
    return Decimal(sells) / Decimal(buys)


def admits(entry: EntryConfig, opportunity: Opportunity) -> bool:
    """Whether this entry rule takes this opportunity. Point-in-time only.

    A missing feature is a **refusal**, never a pass. A rule that quietly
    admitted every token whose data was absent would be measuring the feed's
    gaps rather than the rule.
    """
    if entry.min_discovery_age is not None:
        age = opportunity.discovery_age_seconds
        if age is None or age < Decimal(entry.min_discovery_age.total_seconds()):
            return False
    if entry.min_liq_to_mcap is not None:
        ratio = opportunity.liq_to_mcap
        if ratio is None or ratio < entry.min_liq_to_mcap:
            return False
    if entry.max_liq_to_mcap is not None:
        ratio = opportunity.liq_to_mcap
        if ratio is None or ratio > entry.max_liq_to_mcap:
            return False
    if entry.min_liquidity_usd is not None:
        liquidity = opportunity.liquidity_usd
        if liquidity is None or liquidity < entry.min_liquidity_usd:
            return False
    if entry.min_sell_buy is not None:
        ratio = _sell_buy(opportunity)
        if ratio is None or ratio < entry.min_sell_buy:
            return False
    if entry.reject_sell_buy_band is not None:
        ratio = _sell_buy(opportunity)
        if ratio is None:
            return False
        lo, hi = entry.reject_sell_buy_band
        if lo <= ratio < hi:
            return False
    return True


# ── One evaluated trade ─────────────────────────────────────────────────────


@dataclass(slots=True)
class Trade:
    mint_address: str
    opened_at: datetime
    closed_at: datetime | None
    size_usd: Decimal
    entry_cost: Decimal
    net_proceeds: Decimal
    gross_proceeds: Decimal
    exit_costs: Decimal
    banked_before_final: Decimal
    final_reason: str
    unsettled: bool
    observed_peak_multiple: Decimal
    executable_peak_multiple: Decimal
    fills: int

    @property
    def net_pnl(self) -> Decimal:
        return self.net_proceeds - self.size_usd

    @property
    def return_pct(self) -> Decimal:
        return self.net_pnl / self.size_usd * 100

    @property
    def is_catastrophic(self) -> bool:
        if self.final_reason in ("dead_pool", "untradable"):
            return True
        return not self.unsettled and self.return_pct <= _CATASTROPHIC_RETURN_PCT


@dataclass(slots=True)
class Evaluation:
    """One strategy over one block of opportunities."""

    strategy_id: str
    block: str
    starting_capital: Decimal
    final_cash: Decimal
    offered: int
    trades: list[Trade]
    refusals: dict[str, int]
    peak_concurrent: int
    equity_curve: list[tuple[datetime, Decimal]]

    # ── headline ────────────────────────────────────────────────────────────
    @property
    def n(self) -> int:
        return len(self.trades)

    @property
    def net_pnl(self) -> Decimal:
        return self.final_cash - self.starting_capital

    @property
    def return_pct(self) -> Decimal:
        return self.net_pnl / self.starting_capital * 100

    @property
    def capture_pct(self) -> Decimal:
        return Decimal(self.n) / Decimal(self.offered) * 100 if self.offered else _ZERO

    @property
    def profit_factor(self) -> Decimal | None:
        gains = sum((t.net_pnl for t in self.trades if t.net_pnl > 0), _ZERO)
        losses = -sum((t.net_pnl for t in self.trades if t.net_pnl < 0), _ZERO)
        return gains / losses if losses > 0 else None

    @property
    def expectancy(self) -> Decimal | None:
        if not self.trades:
            return None
        return sum((t.net_pnl for t in self.trades), _ZERO) / len(self.trades)

    @property
    def win_rate_pct(self) -> Decimal | None:
        if not self.trades:
            return None
        wins = sum(1 for t in self.trades if t.net_pnl > 0)
        return Decimal(wins) / Decimal(len(self.trades)) * 100

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
    def blocked_for_cash(self) -> int:
        return self.refusals.get(Refusal.NO_CASH, 0)

    # ── rug economics, §20 ──────────────────────────────────────────────────
    @property
    def catastrophes(self) -> list[Trade]:
        return [t for t in self.trades if t.is_catastrophic]

    @property
    def rug_loss_usd(self) -> Decimal:
        return -sum((t.net_pnl for t in self.catastrophes), _ZERO)

    @property
    def rug_capital_recovered(self) -> Decimal:
        return sum((t.banked_before_final for t in self.catastrophes), _ZERO)

    def rugs_reaching(self, level: str) -> int:
        target = Decimal(level)
        return sum(1 for t in self.catastrophes if t.executable_peak_multiple >= target)

    # ── moonshot retention, §19 ─────────────────────────────────────────────
    def moonshot(self, level: Decimal) -> dict[str, Decimal | int | None]:
        cohort = [t for t in self.trades if t.executable_peak_multiple >= level]
        opportunity = sum((t.size_usd * t.executable_peak_multiple for t in cohort), _ZERO)
        realised = sum((t.net_proceeds for t in cohort), _ZERO)
        monetised = sum(1 for t in cohort if t.net_proceeds >= t.size_usd * level)
        return {
            "level": level,
            "entered": len(cohort),
            "monetised": monetised,
            "opportunity_usd": opportunity,
            "realised_usd": realised,
            "retention_pct": (realised / opportunity * 100 if opportunity > 0 else None),
        }

    # ── daily consistency, §15 ──────────────────────────────────────────────
    def daily(self) -> dict[str, Decimal]:
        out: dict[str, Decimal] = {}
        for trade in self.trades:
            day = (trade.closed_at or trade.opened_at).date().isoformat()
            out[day] = out.get(day, _ZERO) + trade.net_pnl
        return out

    @property
    def profitable_day_pct(self) -> Decimal | None:
        days = self.daily()
        if not days:
            return None
        good = sum(1 for pnl in days.values() if pnl > 0)
        return Decimal(good) / Decimal(len(days)) * 100

    @property
    def worst_day(self) -> Decimal | None:
        days = self.daily()
        return min(days.values()) if days else None

    @property
    def best_day(self) -> Decimal | None:
        days = self.daily()
        return max(days.values()) if days else None

    @property
    def daily_return_stdev(self) -> Decimal | None:
        days = self.daily()
        if len(days) < 2:
            return None
        return Decimal(str(statistics.pstdev([float(v) for v in days.values()])))

    @property
    def day_concentration_pct(self) -> Decimal | None:
        if not self.trades:
            return None
        by_day: dict[str, int] = {}
        for trade in self.trades:
            key = trade.opened_at.date().isoformat()
            by_day[key] = by_day.get(key, 0) + 1
        return Decimal(max(by_day.values())) / Decimal(len(self.trades)) * 100

    # ── robustness, §14 ─────────────────────────────────────────────────────
    def without(self, best: int = 0, worst: int = 0) -> Decimal:
        """Total net P&L with the top `best` and bottom `worst` trades removed."""
        pnls = sorted((t.net_pnl for t in self.trades), reverse=True)
        kept = pnls[best:] if best else pnls
        if worst:
            kept = kept[: len(kept) - worst] if worst < len(kept) else []
        return sum(kept, _ZERO)

    def top_share_pct(self, k: int) -> Decimal | None:
        pnls = sorted((t.net_pnl for t in self.trades), reverse=True)
        gross_profit = sum((p for p in pnls if p > 0), _ZERO)
        if gross_profit <= 0:
            return None
        return sum(pnls[:k], _ZERO) / gross_profit * 100

    @property
    def outlier_dependent(self) -> bool:
        total = sum((t.net_pnl for t in self.trades), _ZERO)
        return total > 0 and self.without(best=1) <= 0

    @property
    def outlier_dependent_top3(self) -> bool:
        total = sum((t.net_pnl for t in self.trades), _ZERO)
        return total > 0 and self.without(best=3) <= 0

    def entered_mints(self) -> set[str]:
        return {t.mint_address for t in self.trades}


# ── The chronological walk ──────────────────────────────────────────────────


def evaluate(
    candidate: Candidate,
    cache: ScheduleCache,
    indexes: Sequence[int],
    *,
    block: str,
    starting_capital: Decimal = STARTING_CAPITAL,
) -> Evaluation:
    """Offer `indexes` in time order; take what the rule and the cash allow.

    `indexes` are positions into the cache's opportunity list, so a block is a
    view rather than a copy and every block sees the identical frozen evidence.
    """
    rules = candidate.rules
    size = candidate.size_usd
    portfolio = candidate.portfolio

    ordered = sorted(indexes, key=lambda i: cache.opportunities[i].eligible_at)
    cash = starting_capital
    trades: list[Trade] = []
    refusals: dict[str, int] = {}
    #: (when, cash back, cost basis released, position ordinal)
    pending: list[tuple[datetime, Decimal, Decimal, int]] = []
    deployed: dict[int, Decimal] = {}
    #: Closing times of catastrophic trades, for the breaker.
    catastrophe_times: list[datetime] = []
    curve: list[tuple[datetime, Decimal]] = []
    peak_concurrent = 0

    def refuse(reason: str) -> None:
        refusals[reason] = refusals.get(reason, 0) + 1

    def release(upto: datetime) -> None:
        nonlocal cash
        while pending and pending[0][0] <= upto:
            _, net, basis, ordinal = pending.pop(0)
            cash += net
            left = deployed.get(ordinal, _ZERO) - basis
            if left <= Decimal("0.000001"):
                deployed.pop(ordinal, None)
            else:
                deployed[ordinal] = left

    for index in ordered:
        opportunity = cache.opportunities[index]
        pending.sort(key=lambda row: row[0])
        release(opportunity.eligible_at)
        peak_concurrent = max(peak_concurrent, len(deployed))

        if not admits(candidate.entry, opportunity):
            refuse(Refusal.ENTRY_FILTER)
            continue
        if opportunity.entry_price is None or opportunity.entry_price <= 0:
            refuse(Refusal.UNPRICEABLE)
            continue
        if _breaker_paused(portfolio, catastrophe_times, opportunity.eligible_at):
            refuse(Refusal.BREAKER)
            continue
        if _exposure_blocked(portfolio, deployed, size, starting_capital):
            refuse(Refusal.EXPOSURE_CAP)
            continue
        if cash < size:
            refuse(Refusal.NO_CASH)
            continue

        entry_cost = execution.buy(size, opportunity.liquidity_usd)
        quantity = (size - entry_cost) / opportunity.entry_price
        if quantity <= 0:
            refuse(Refusal.UNPRICEABLE)
            continue

        schedule = cache.get(index, candidate.profit.key, candidate.exit.key, rules)
        cash -= size
        ordinal = len(trades)
        deployed[ordinal] = size

        gross = net = costs = _ZERO
        banked = _ZERO
        for position, fill in enumerate(schedule.fills):
            sold = quantity * fill.fraction
            proceeds, cost = execution.sell(sold, fill.price_usd, fill.liquidity_usd)
            gross += sold * fill.price_usd
            net += proceeds
            costs += cost
            if position < len(schedule.fills) - 1:
                banked += proceeds
            pending.append((fill.at, proceeds, size * fill.fraction, ordinal))

        trades.append(
            Trade(
                mint_address=opportunity.mint_address,
                opened_at=opportunity.eligible_at,
                closed_at=schedule.closed_at,
                size_usd=size,
                entry_cost=entry_cost,
                net_proceeds=net,
                gross_proceeds=gross,
                exit_costs=costs,
                banked_before_final=banked,
                final_reason=_final_reason(schedule),
                unsettled=schedule.unsettled,
                observed_peak_multiple=schedule.observed_peak_multiple,
                executable_peak_multiple=schedule.executable_peak_multiple,
                fills=len(schedule.fills),
            )
        )
        if trades[-1].is_catastrophic and schedule.closed_at is not None:
            catastrophe_times.append(schedule.closed_at)
        curve.append((opportunity.eligible_at, cash + sum(deployed.values(), _ZERO)))

    if ordered:
        pending.sort(key=lambda row: row[0])
        last = cache.opportunities[ordered[-1]].eligible_at
        release(last + timedelta(days=365))
        curve.append((last, cash))

    return Evaluation(
        strategy_id=candidate.strategy_id,
        block=block,
        starting_capital=starting_capital,
        final_cash=cash,
        offered=len(ordered),
        trades=trades,
        refusals=refusals,
        peak_concurrent=peak_concurrent,
        equity_curve=curve,
    )


def _final_reason(schedule: Schedule) -> str:
    for fill in reversed(schedule.fills):
        if fill.reason is not FillReason.TARGET:
            return str(fill.reason)
    return str(FillReason.TARGET) if schedule.fills else "open"


def _breaker_paused(
    portfolio: PortfolioConfig, catastrophes: Sequence[datetime], at: datetime
) -> bool:
    """§9. Pauses **new entries only** — open positions keep exiting.

    The same separation `PAPER_WALLET_ENTRIES_PAUSED` enforces on the live
    wallet, and for the same reason: a control that also stopped exits would
    trap capital in exactly the market that triggered it.
    """
    if portfolio.breaker_losses is None or portfolio.breaker_window is None:
        return False
    since = at - portfolio.breaker_window
    recent = sum(1 for t in catastrophes if since <= t <= at)
    return recent >= portfolio.breaker_losses


def _exposure_blocked(
    portfolio: PortfolioConfig,
    deployed: dict[int, Decimal],
    size: Decimal,
    starting_capital: Decimal,
) -> bool:
    if portfolio.max_exposure_pct is None:
        return False
    cap = starting_capital * portfolio.max_exposure_pct / 100
    return sum(deployed.values(), _ZERO) + size > cap
