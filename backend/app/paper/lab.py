"""Generation-2 Strategy Lab replay engine.

This module is research-only. It never opens, closes, mutates, allocates, or
changes a paper-wallet position. Its input is the already-written Generation 2
paper trade record plus immutable market snapshots; its output is descriptive
evidence about exit rules and entry-time patterns.

Generation 1 is intentionally excluded from optimisation metrics. It remains
historical archive data, but the Sprint 30 relaunch made Generation 2
(`trailing_stop_25_v1`) the only comparable production baseline.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import UUID

from app.paper import costs

_ZERO = Decimal(0)
_HUNDRED = Decimal(100)
_TRADE_SIZE = Decimal(100)

BASELINE_ID = "trailing_25_baseline"
GENERATION = 2
STRATEGY_ID = "trailing_stop_25_v1"


@dataclass(frozen=True, slots=True)
class QuotePoint:
    at: datetime
    price: Decimal
    market_cap: Decimal | None = None
    liquidity_usd: Decimal | None = None
    volume_24h: Decimal | None = None


@dataclass(frozen=True, slots=True)
class TradeInput:
    position_id: UUID
    mint_address: str
    symbol: str | None
    opened_at: datetime
    entry_price: Decimal
    size_usd: Decimal
    quantity: Decimal
    entry_market_cap: Decimal | None
    entry_liquidity_usd: Decimal | None
    entry_rank: int
    status: str
    actual_closed_at: datetime | None
    actual_exit_reason: str | None
    manual: bool
    peak_price: Decimal
    first_detected_at: datetime | None = None
    radar_score: Decimal | None = None
    confidence: Decimal | None = None
    category: str | None = None
    entry_volume_24h: Decimal | None = None
    quotes: tuple[QuotePoint, ...] = field(default_factory=tuple)

    @property
    def age_hours_at_entry(self) -> Decimal | None:
        if self.first_detected_at is None:
            return None
        return Decimal((self.opened_at - self.first_detected_at).total_seconds()) / Decimal(
            3600
        )


@dataclass(frozen=True, slots=True)
class StrategySpec:
    id: str
    name: str
    description: str
    rules: tuple[tuple[str, str], ...]
    is_baseline: bool = False
    trailing_pct: Decimal | None = None
    time_exit: timedelta | None = None
    break_even_at_pct: Decimal | None = None
    adaptive: bool = False


@dataclass(frozen=True, slots=True)
class ReplayTrade:
    mint_address: str
    symbol: str | None
    opened_at: datetime
    entry_price: Decimal
    closed_at: datetime | None
    exit_price: Decimal | None
    exit_reason: str | None
    peak_price: Decimal
    mark_price: Decimal | None
    entry_liquidity_usd: Decimal | None
    exit_liquidity_usd: Decimal | None

    @property
    def settled_price(self) -> Decimal | None:
        return self.exit_price if self.exit_price is not None else self.mark_price

    @property
    def gross_return_pct(self) -> Decimal | None:
        price = self.settled_price
        if price is None or self.entry_price <= 0:
            return None
        return (price - self.entry_price) / self.entry_price * _HUNDRED

    @property
    def gross_return_usd(self) -> Decimal | None:
        pct = self.gross_return_pct
        return None if pct is None else _TRADE_SIZE * pct / _HUNDRED

    @property
    def hold_hours(self) -> Decimal | None:
        if self.closed_at is None:
            return None
        return Decimal((self.closed_at - self.opened_at).total_seconds()) / Decimal(3600)

    @property
    def peak_pct(self) -> Decimal | None:
        if self.entry_price <= 0:
            return None
        return (self.peak_price - self.entry_price) / self.entry_price * _HUNDRED

    @property
    def capture_pct(self) -> Decimal | None:
        peak = self.peak_pct
        gross = self.gross_return_pct
        if peak is None or peak <= 0 or gross is None:
            return None
        return gross / peak * _HUNDRED

    @property
    def giveback_pct(self) -> Decimal | None:
        price = self.settled_price
        if price is None or self.peak_price <= 0:
            return None
        return (self.peak_price - price) / self.peak_price * _HUNDRED

    @property
    def round_trip_cost(self) -> costs.RoundTrip | None:
        price = self.settled_price
        if price is None or self.entry_price <= 0:
            return None
        exit_notional = _TRADE_SIZE * price / self.entry_price
        return costs.round_trip(
            entry_notional=_TRADE_SIZE,
            entry_liquidity=self.entry_liquidity_usd,
            exit_notional=exit_notional,
            exit_liquidity=self.exit_liquidity_usd,
        )

    @property
    def net_return_usd(self) -> Decimal | None:
        price = self.settled_price
        round_trip = self.round_trip_cost
        if price is None or self.entry_price <= 0 or round_trip is None:
            return None
        exit_notional = _TRADE_SIZE * price / self.entry_price
        return costs.net_proceeds(
            entry_notional=_TRADE_SIZE,
            exit_notional=exit_notional,
            costs=round_trip,
        )


@dataclass(frozen=True, slots=True)
class EquityPoint:
    at: datetime
    equity: Decimal
    drawdown_pct: Decimal


@dataclass(frozen=True, slots=True)
class StrategyResult:
    id: str
    name: str
    description: str
    rules: tuple[tuple[str, str], ...]
    is_baseline: bool
    rank: int
    trades: tuple[ReplayTrade, ...]
    invested: Decimal
    total_return_pct: Decimal | None
    realised_return_pct: Decimal | None
    net_return_pct: Decimal | None
    cost_drag_pct: Decimal | None
    closed_count: int
    open_count: int
    costed_trades: int
    uncosted_trades: int
    win_rate_pct: Decimal | None
    profit_factor: Decimal | None
    expectancy: Decimal | None
    average_winner: Decimal | None
    average_loser: Decimal | None
    largest_winner: Decimal | None
    largest_loser: Decimal | None
    max_drawdown_pct: Decimal | None
    average_hold_hours: Decimal | None
    average_peak_pct: Decimal | None
    average_capture_pct: Decimal | None
    average_giveback_pct: Decimal | None
    fees_usd: Decimal | None
    slippage_usd: Decimal | None
    average_slippage_usd: Decimal | None
    capital_utilization_pct: Decimal | None
    exits_by_reason: dict[str, int]
    equity_curve: tuple[EquityPoint, ...]


@dataclass(frozen=True, slots=True)
class SegmentRow:
    name: str
    n: int
    net_return_pct: Decimal | None
    win_rate_pct: Decimal | None
    profit_factor: Decimal | None
    average_return_pct: Decimal | None
    slippage_drag_pct: Decimal | None


@dataclass(frozen=True, slots=True)
class TradeCard:
    mint_address: str
    symbol: str | None
    net_return_pct: Decimal | None
    gross_return_pct: Decimal | None
    entry_market_cap: Decimal | None
    entry_liquidity_usd: Decimal | None
    radar_score: Decimal | None
    confidence: Decimal | None
    category: str | None
    age_hours_at_entry: Decimal | None
    hold_hours: Decimal | None
    exit_reason: str | None


@dataclass(frozen=True, slots=True)
class DataIntegrity:
    scoped_generation: int
    scoped_strategy_id: str
    positions: int
    open_positions: int
    closed_positions: int
    audited_closed_positions: int
    missing_audit_rows: int
    manual_overrides: int
    archived_generation_positions: int
    archived_missing_audit_rows: int
    verdict: str


@dataclass(frozen=True, slots=True)
class Recommendation:
    title: str
    confidence: str
    sample_size: int
    expected_improvement: str
    trade_offs: str


@dataclass(frozen=True, slots=True)
class RejectedIdea:
    strategy_id: str
    reason: str
    sample_size: int


@dataclass(frozen=True, slots=True)
class TokenComparison:
    mint_address: str
    symbol: str | None
    peak_pct: Decimal | None
    returns: dict[str, Decimal | None]
    best_strategy_id: str | None
    best_capture_pct: Decimal | None


STRATEGIES: tuple[StrategySpec, ...] = (
    StrategySpec(
        id=BASELINE_ID,
        name="Trailing Stop 25% — production baseline",
        description="Generation 2 baseline replayed from immutable market snapshots.",
        rules=(("Exit", "Trail 25% from the observed high"),),
        is_baseline=True,
        trailing_pct=Decimal("25"),
    ),
    StrategySpec(
        id="trailing_15",
        name="Trailing Stop 15%",
        description="Tighter trailing stop. Tests faster profit protection.",
        rules=(("Exit", "Trail 15% from the observed high"),),
        trailing_pct=Decimal("15"),
    ),
    StrategySpec(
        id="trailing_20",
        name="Trailing Stop 20%",
        description="Moderately tighter trailing stop.",
        rules=(("Exit", "Trail 20% from the observed high"),),
        trailing_pct=Decimal("20"),
    ),
    StrategySpec(
        id="trailing_30",
        name="Trailing Stop 30%",
        description="Looser than production, allowing wider pullbacks.",
        rules=(("Exit", "Trail 30% from the observed high"),),
        trailing_pct=Decimal("30"),
    ),
    StrategySpec(
        id="trailing_35",
        name="Trailing Stop 35%",
        description="Looser trailing stop for high-volatility moves.",
        rules=(("Exit", "Trail 35% from the observed high"),),
        trailing_pct=Decimal("35"),
    ),
    StrategySpec(
        id="trailing_40",
        name="Trailing Stop 40%",
        description="Wide trailing stop; tests whether winners need room.",
        rules=(("Exit", "Trail 40% from the observed high"),),
        trailing_pct=Decimal("40"),
    ),
    StrategySpec(
        id="breakeven_25_trailing_25",
        name="Break-even at +25%, then Trailing 25%",
        description="Once price reaches +25%, the stop cannot fall below entry.",
        rules=(("Protection", "At +25%, stop is at least entry"), ("Exit", "Then trail 25%")),
        trailing_pct=Decimal("25"),
        break_even_at_pct=Decimal("25"),
    ),
    StrategySpec(
        id="adaptive_trailing",
        name="Adaptive trailing schedule",
        description="Pre-declared tightening schedule for large winners.",
        rules=(
            ("+25%", "Stop cannot fall below entry"),
            ("+100%", "25% trailing"),
            ("+300%", "20% trailing"),
            ("+700%", "15% trailing"),
            ("+1500%", "10% trailing"),
        ),
        adaptive=True,
    ),
    StrategySpec(
        id="time_exit_24h",
        name="Time Exit 24h",
        description="Exit at the first observed quote after 24 hours.",
        rules=(("Exit", "First quote at or after 24h"),),
        time_exit=timedelta(hours=24),
    ),
    StrategySpec(
        id="time_exit_48h",
        name="Time Exit 48h",
        description="Exit at the first observed quote after 48 hours.",
        rules=(("Exit", "First quote at or after 48h"),),
        time_exit=timedelta(hours=48),
    ),
    StrategySpec(
        id="time_exit_72h",
        name="Time Exit 72h",
        description="Exit at the first observed quote after 72 hours.",
        rules=(("Exit", "First quote at or after 72h"),),
        time_exit=timedelta(hours=72),
    ),
    StrategySpec(
        id="hybrid_25_trail_48h",
        name="Hybrid: Trailing 25% or 48h",
        description="Production trail, with a 48-hour max holding period.",
        rules=(("Exit", "First of 25% trailing stop or 48h time exit"),),
        trailing_pct=Decimal("25"),
        time_exit=timedelta(hours=48),
    ),
    StrategySpec(
        id="hold_until_latest",
        name="Hold until latest observation",
        description="No stop. Mark at latest stored market quote.",
        rules=(("Exit", "No rule inside observed history"),),
    ),
)


def replay_all(entries: Sequence[TradeInput]) -> tuple[StrategyResult, ...]:
    raw = [_summarise(strategy, _replay(entries, strategy), rank=0) for strategy in STRATEGIES]
    ordered_ids = rank({item.id: item for item in raw})
    by_id = {item.id: item for item in raw}
    return tuple(
        _replace_rank(by_id[strategy_id], index + 1)
        for index, strategy_id in enumerate(ordered_ids)
    )


def replay_tokens(
    results: Sequence[StrategyResult], *, limit: int
) -> tuple[TokenComparison, ...]:
    by_mint: dict[str, dict[str, ReplayTrade]] = {}
    for result in results:
        for trade in result.trades:
            by_mint.setdefault(trade.mint_address, {})[result.id] = trade

    rows: list[TokenComparison] = []
    for mint, per_strategy in by_mint.items():
        any_trade = next(iter(per_strategy.values()))
        peak = max(
            (trade.peak_pct for trade in per_strategy.values() if trade.peak_pct is not None),
            default=None,
        )
        returns = {
            strategy_id: _q(trade.gross_return_pct)
            for strategy_id, trade in per_strategy.items()
        }
        best_id: str | None = None
        best_capture: Decimal | None = None
        if peak is not None and peak > 0:
            for strategy_id, trade in per_strategy.items():
                capture = trade.capture_pct
                if capture is not None and (best_capture is None or capture > best_capture):
                    best_capture = capture
                    best_id = strategy_id
        rows.append(
            TokenComparison(
                mint_address=mint,
                symbol=any_trade.symbol,
                peak_pct=_q(peak),
                returns=returns,
                best_strategy_id=best_id,
                best_capture_pct=_q(best_capture),
            )
        )
    rows.sort(key=lambda item: (-(item.peak_pct or _ZERO), item.mint_address))
    return tuple(rows[:limit])


def segment(
    entries: Sequence[TradeInput], key: Callable[[TradeInput], str]
) -> tuple[SegmentRow, ...]:
    rows: dict[str, list[ReplayTrade]] = {}
    entry_by_mint = {entry.mint_address: entry for entry in entries}
    baseline = next(result for result in replay_all(entries) if result.id == BASELINE_ID)
    for trade in baseline.trades:
        source = entry_by_mint[trade.mint_address]
        rows.setdefault(key(source), []).append(trade)
    return tuple(_segment_row(name, trades) for name, trades in sorted(rows.items()))


def segment_baseline_trades(
    entries: Sequence[TradeInput], key: Callable[[ReplayTrade], str]
) -> tuple[SegmentRow, ...]:
    rows: dict[str, list[ReplayTrade]] = {}
    baseline = next(result for result in replay_all(entries) if result.id == BASELINE_ID)
    for trade in baseline.trades:
        rows.setdefault(key(trade), []).append(trade)
    return tuple(_segment_row(name, trades) for name, trades in sorted(rows.items()))


def market_cap_band(entry: TradeInput) -> str:
    value = entry.entry_market_cap
    if value is None:
        return "Unknown"
    bands = (
        (Decimal("25000"), "< $25K"),
        (Decimal("50000"), "$25K-$50K"),
        (Decimal("100000"), "$50K-$100K"),
        (Decimal("250000"), "$100K-$250K"),
        (Decimal("500000"), "$250K-$500K"),
        (Decimal("1000000"), "$500K-$1M"),
        (Decimal("5000000"), "$1M-$5M"),
    )
    for limit, label in bands:
        if value < limit:
            return label
    return "> $5M"


def liquidity_band(entry: TradeInput) -> str:
    value = entry.entry_liquidity_usd
    if value is None:
        return "Unknown"
    if value < Decimal("1000"):
        return "< $1K"
    if value < Decimal("5000"):
        return "$1K-$5K"
    if value < Decimal("10000"):
        return "$5K-$10K"
    if value < Decimal("25000"):
        return "$10K-$25K"
    return "> $25K"


def score_band(entry: TradeInput) -> str:
    value = entry.radar_score
    if value is None:
        return "Unknown"
    if value < Decimal("60"):
        return "< 60"
    if value < Decimal("70"):
        return "60-69"
    if value < Decimal("80"):
        return "70-79"
    if value < Decimal("90"):
        return "80-89"
    return "90+"


def age_band(entry: TradeInput) -> str:
    value = entry.age_hours_at_entry
    if value is None:
        return "Unknown"
    if value < Decimal("1"):
        return "<1h"
    if value < Decimal("6"):
        return "1-6h"
    if value < Decimal("12"):
        return "6-12h"
    if value < Decimal("24"):
        return "12-24h"
    if value < Decimal("48"):
        return "24-48h"
    return "48h+"


def holding_band(trade: ReplayTrade) -> str:
    value = trade.hold_hours
    if value is None:
        return "Open/marked"
    if value < Decimal("1"):
        return "<1h"
    if value < Decimal("6"):
        return "1-6h"
    if value < Decimal("12"):
        return "6-12h"
    if value < Decimal("24"):
        return "12-24h"
    if value < Decimal("48"):
        return "24-48h"
    return "48h+"


def largest_cards(
    entries: Sequence[TradeInput], *, winners: bool, limit: int = 8
) -> tuple[TradeCard, ...]:
    entry_by_mint = {entry.mint_address: entry for entry in entries}
    baseline = next(result for result in replay_all(entries) if result.id == BASELINE_ID)
    trades = [
        trade
        for trade in baseline.trades
        if trade.net_return_usd is not None and (trade.net_return_usd > 0) is winners
    ]
    trades.sort(key=lambda trade: trade.net_return_usd or _ZERO, reverse=winners)
    return tuple(_card(entry_by_mint[trade.mint_address], trade) for trade in trades[:limit])


def rejected_ideas(results: Sequence[StrategyResult]) -> tuple[RejectedIdea, ...]:
    baseline = next(item for item in results if item.id == BASELINE_ID)
    rejected: list[RejectedIdea] = []
    for item in results:
        if item.id == BASELINE_ID:
            continue
        if item.net_return_pct is None or baseline.net_return_pct is None:
            rejected.append(
                RejectedIdea(
                    item.id,
                    "Net return could not be costed for comparison.",
                    item.closed_count,
                )
            )
        elif item.net_return_pct < baseline.net_return_pct:
            reason = (
                f"Net return {item.net_return_pct}% did not beat baseline "
                f"{baseline.net_return_pct}%."
            )
            rejected.append(
                RejectedIdea(
                    item.id,
                    reason,
                    item.closed_count,
                )
            )
        elif (
            item.max_drawdown_pct is not None
            and baseline.max_drawdown_pct is not None
            and item.max_drawdown_pct > baseline.max_drawdown_pct + Decimal("10")
        ):
            rejected.append(
                RejectedIdea(
                    item.id,
                    "Higher net came with materially worse realised drawdown.",
                    item.closed_count,
                )
            )
    return tuple(rejected)


def recommendations(results: Sequence[StrategyResult]) -> tuple[Recommendation, ...]:
    baseline = next(item for item in results if item.id == BASELINE_ID)
    winner = results[0] if results else baseline
    if (
        winner.id == baseline.id
        or winner.net_return_pct is None
        or baseline.net_return_pct is None
        or winner.closed_count < 30
        or winner.net_return_pct <= 0
        or winner.net_return_pct <= baseline.net_return_pct
    ):
        return (
            Recommendation(
                title="Keep V1 as production baseline",
                confidence="medium",
                sample_size=baseline.closed_count,
                expected_improvement=(
                    "No production improvement is proven by the Generation 2 record."
                ),
                trade_offs=(
                    "Small sample and short market regime; avoid fitting exits "
                    "to a few extreme tokens."
                ),
            ),
        )
    improvement = winner.net_return_pct - baseline.net_return_pct
    return (
        Recommendation(
            title=f"Research {winner.name} as a V2 candidate",
            confidence="low" if winner.closed_count < 50 else "medium",
            sample_size=winner.closed_count,
            expected_improvement=(
                f"+{improvement.quantize(Decimal('0.01'))} net points versus "
                "V1 in scoped replay."
            ),
            trade_offs=(
                "Promising only as research; must run in parallel before replacing production."
            ),
        ),
    )


def final_decision(results: Sequence[StrategyResult]) -> tuple[str, str]:
    baseline = next(item for item in results if item.id == BASELINE_ID)
    winner = results[0] if results else baseline
    if winner.id == baseline.id:
        return (
            "A",
            "KEEP V1 — the production baseline ranks first under the published ranking.",
        )
    if winner.net_return_pct is None or winner.net_return_pct <= 0:
        return (
            "A",
            "KEEP V1 — the best replay reduces losses but does not prove "
            "positive net expectancy.",
        )
    if winner.closed_count < 30:
        return (
            "A",
            "KEEP V1 — the best replay has too few closed trades to justify "
            "a production change.",
        )
    return (
        "C",
        "BUILD V2 — evidence is research-promising, but production execution "
        "remains unchanged.",
    )


def rank(results: dict[str, StrategyResult]) -> tuple[str, ...]:
    return tuple(
        sorted(
            results,
            key=lambda key: (
                -(results[key].net_return_pct or Decimal("-999999")),
                -(results[key].profit_factor or Decimal("-999999")),
                results[key].max_drawdown_pct or Decimal("999999"),
                -(results[key].expectancy or Decimal("-999999")),
                key,
            ),
        )
    )


def _replay(entries: Sequence[TradeInput], strategy: StrategySpec) -> tuple[ReplayTrade, ...]:
    return tuple(_replay_one(entry, strategy) for entry in entries if entry.entry_price > 0)


def _replay_one(entry: TradeInput, strategy: StrategySpec) -> ReplayTrade:
    peak = entry.entry_price
    latest: QuotePoint | None = None
    close: QuotePoint | None = None
    reason: str | None = None
    deadline = entry.opened_at + strategy.time_exit if strategy.time_exit is not None else None

    for quote in entry.quotes:
        if quote.price <= 0 or quote.at < entry.opened_at:
            continue
        latest = quote
        if quote.price > peak:
            peak = quote.price

        stop_price = _stop_price(strategy, entry.entry_price, peak)
        if deadline is not None and quote.at >= deadline:
            close, reason = quote, "expiry"
            break
        if stop_price is not None and quote.at > entry.opened_at and quote.price <= stop_price:
            close, reason = quote, "stop"
            break

    if close is not None:
        return ReplayTrade(
            mint_address=entry.mint_address,
            symbol=entry.symbol,
            opened_at=entry.opened_at,
            entry_price=entry.entry_price,
            closed_at=close.at,
            exit_price=close.price,
            exit_reason=reason,
            peak_price=peak,
            mark_price=None,
            entry_liquidity_usd=entry.entry_liquidity_usd,
            exit_liquidity_usd=close.liquidity_usd,
        )
    mark = latest.price if latest is not None else None
    return ReplayTrade(
        mint_address=entry.mint_address,
        symbol=entry.symbol,
        opened_at=entry.opened_at,
        entry_price=entry.entry_price,
        closed_at=None,
        exit_price=None,
        exit_reason=None,
        peak_price=max(peak, mark or peak),
        mark_price=mark,
        entry_liquidity_usd=entry.entry_liquidity_usd,
        exit_liquidity_usd=None if latest is None else latest.liquidity_usd,
    )


def _stop_price(strategy: StrategySpec, entry_price: Decimal, peak: Decimal) -> Decimal | None:
    gain_pct = (peak - entry_price) / entry_price * _HUNDRED if entry_price > 0 else _ZERO
    trailing = strategy.trailing_pct
    floor: Decimal | None = None
    if strategy.break_even_at_pct is not None and gain_pct >= strategy.break_even_at_pct:
        floor = entry_price
    if strategy.adaptive:
        if gain_pct >= Decimal("1500"):
            trailing = Decimal("10")
        elif gain_pct >= Decimal("700"):
            trailing = Decimal("15")
        elif gain_pct >= Decimal("300"):
            trailing = Decimal("20")
        elif gain_pct >= Decimal("100"):
            trailing = Decimal("25")
        elif gain_pct >= Decimal("25"):
            trailing = Decimal("25")
            floor = entry_price
        else:
            trailing = Decimal("25")
    if trailing is None:
        return None
    stop = peak * (Decimal(1) - trailing / _HUNDRED)
    return max(stop, floor) if floor is not None else stop


def _summarise(
    strategy: StrategySpec, trades: tuple[ReplayTrade, ...], *, rank: int
) -> StrategyResult:
    closed = [trade for trade in trades if trade.closed_at is not None]
    opened = [trade for trade in trades if trade.closed_at is None]
    invested = _TRADE_SIZE * len(trades)
    gross = [trade.gross_return_usd for trade in trades if trade.gross_return_usd is not None]
    closed_gross = [
        trade.gross_return_usd for trade in closed if trade.gross_return_usd is not None
    ]
    net = [trade.net_return_usd for trade in trades if trade.net_return_usd is not None]
    closed_net = [trade.net_return_usd for trade in closed if trade.net_return_usd is not None]
    wins = [value for value in closed_net if value > 0]
    losses = [value for value in closed_net if value < 0]
    gross_profit = sum(wins, _ZERO)
    gross_loss = sum((-value for value in losses), _ZERO)
    total_fee = sum(
        (
            trade.round_trip_cost.entry.fee + trade.round_trip_cost.exit.fee
            for trade in trades
            if trade.round_trip_cost is not None
        ),
        _ZERO,
    )
    total_slippage = sum(
        (
            trade.round_trip_cost.entry.impact + trade.round_trip_cost.exit.impact
            for trade in trades
            if trade.round_trip_cost is not None
        ),
        _ZERO,
    )
    curve = _equity_curve(closed)
    realised_invested = _TRADE_SIZE * len(closed)
    net_invested = _TRADE_SIZE * len(net)
    gross_costed = [
        trade.gross_return_usd
        for trade in trades
        if trade.net_return_usd is not None and trade.gross_return_usd is not None
    ]
    gross_costed_return = _return_pct(gross_costed, net_invested)
    net_return = _return_pct(net, net_invested)
    return StrategyResult(
        id=strategy.id,
        name=strategy.name,
        description=strategy.description,
        rules=strategy.rules,
        is_baseline=strategy.is_baseline,
        rank=rank,
        trades=trades,
        invested=invested,
        total_return_pct=_return_pct(gross, invested),
        realised_return_pct=_return_pct(closed_gross, realised_invested),
        net_return_pct=net_return,
        cost_drag_pct=(
            None
            if net_return is None or gross_costed_return is None
            else _q(net_return - gross_costed_return)
        ),
        closed_count=len(closed),
        open_count=len(opened),
        costed_trades=len(net),
        uncosted_trades=len(trades) - len(net),
        win_rate_pct=None
        if not closed_net
        else _q(Decimal(len(wins)) / Decimal(len(closed_net)) * _HUNDRED),
        profit_factor=None if gross_loss <= 0 else _q(gross_profit / gross_loss),
        expectancy=None
        if not closed_net
        else _q(sum(closed_net, _ZERO) / Decimal(len(closed_net))),
        average_winner=None if not wins else _q(gross_profit / Decimal(len(wins))),
        average_loser=None if not losses else _q(sum(losses, _ZERO) / Decimal(len(losses))),
        largest_winner=None if not wins else _q(max(wins)),
        largest_loser=None if not losses else _q(min(losses)),
        max_drawdown_pct=None if not curve else _q(max(point.drawdown_pct for point in curve)),
        average_hold_hours=_avg([trade.hold_hours for trade in closed]),
        average_peak_pct=_avg([trade.peak_pct for trade in trades]),
        average_capture_pct=_avg([trade.capture_pct for trade in trades]),
        average_giveback_pct=_avg([trade.giveback_pct for trade in trades]),
        fees_usd=None if not net else _q(total_fee),
        slippage_usd=None if not net else _q(total_slippage),
        average_slippage_usd=None if not net else _q(total_slippage / Decimal(len(net))),
        capital_utilization_pct=_capital_utilization(trades),
        exits_by_reason=dict(Counter(trade.exit_reason or "open" for trade in trades)),
        equity_curve=curve,
    )


def _replace_rank(result: StrategyResult, rank: int) -> StrategyResult:
    return replace(result, rank=rank)


def _segment_row(name: str, trades: Sequence[ReplayTrade]) -> SegmentRow:
    net = [trade.net_return_usd for trade in trades if trade.net_return_usd is not None]
    returns = [
        trade.gross_return_pct for trade in trades if trade.gross_return_pct is not None
    ]
    wins = [value for value in net if value > 0]
    losses = [value for value in net if value < 0]
    loss_abs = sum((-value for value in losses), _ZERO)
    slippage = sum(
        (trade.round_trip_cost.entry.impact + trade.round_trip_cost.exit.impact)
        for trade in trades
        if trade.round_trip_cost is not None
    )
    return SegmentRow(
        name=name,
        n=len(trades),
        net_return_pct=_return_pct(net, _TRADE_SIZE * len(net)),
        win_rate_pct=None
        if not net
        else _q(Decimal(len(wins)) / Decimal(len(net)) * _HUNDRED),
        profit_factor=None if loss_abs <= 0 else _q(sum(wins, _ZERO) / loss_abs),
        average_return_pct=_avg(returns),
        slippage_drag_pct=None
        if not trades
        else _q(slippage / (_TRADE_SIZE * len(trades)) * _HUNDRED),
    )


def _card(entry: TradeInput, trade: ReplayTrade) -> TradeCard:
    return TradeCard(
        mint_address=entry.mint_address,
        symbol=entry.symbol,
        net_return_pct=None
        if trade.net_return_usd is None
        else _q(trade.net_return_usd / _TRADE_SIZE * _HUNDRED),
        gross_return_pct=_q(trade.gross_return_pct),
        entry_market_cap=entry.entry_market_cap,
        entry_liquidity_usd=entry.entry_liquidity_usd,
        radar_score=entry.radar_score,
        confidence=entry.confidence,
        category=entry.category,
        age_hours_at_entry=_q(entry.age_hours_at_entry),
        hold_hours=_q(trade.hold_hours),
        exit_reason=trade.exit_reason,
    )


def _equity_curve(closed: Sequence[ReplayTrade]) -> tuple[EquityPoint, ...]:
    equity = Decimal(1000)
    peak = equity
    points: list[EquityPoint] = []
    for trade in sorted(
        closed, key=lambda item: (item.closed_at or datetime.min, item.mint_address)
    ):
        net = trade.net_return_usd
        if net is None or trade.closed_at is None:
            continue
        equity += net
        peak = max(peak, equity)
        drawdown = _ZERO if peak <= 0 else (peak - equity) / peak * _HUNDRED
        points.append(
            EquityPoint(
                trade.closed_at,
                equity.quantize(Decimal("0.01")),
                drawdown.quantize(Decimal("0.01")),
            )
        )
    return tuple(points)


def _capital_utilization(trades: Sequence[ReplayTrade]) -> Decimal | None:
    events: list[tuple[datetime, int]] = []
    for trade in trades:
        events.append((trade.opened_at, 1))
        if trade.closed_at is not None:
            events.append((trade.closed_at, -1))
    if len(events) < 2:
        return None
    events.sort()
    weighted = Decimal(0)
    active = 0
    start = events[0][0]
    last = start
    for at, change in events:
        if at > last:
            weighted += Decimal(active) * Decimal((at - last).total_seconds())
        active += change
        last = at
    span = Decimal((events[-1][0] - start).total_seconds())
    if span <= 0:
        return None
    avg_positions = weighted / span
    return _q(avg_positions * _TRADE_SIZE / Decimal(1000) * _HUNDRED)


def _return_pct(values: Sequence[Decimal | None], invested: Decimal) -> Decimal | None:
    clean = [value for value in values if value is not None]
    if invested <= 0 or not clean:
        return None
    return _q(sum(clean, _ZERO) / invested * _HUNDRED)


def _avg(values: Sequence[Decimal | None]) -> Decimal | None:
    clean = [value for value in values if value is not None]
    return None if not clean else _q(sum(clean, _ZERO) / Decimal(len(clean)))


def _q(value: Decimal | None, places: str = "0.01") -> Decimal | None:
    return None if value is None else value.quantize(Decimal(places))
