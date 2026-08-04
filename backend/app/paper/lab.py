"""The Strategy Lab: one replay engine, many exit rules.

Every strategy sees **the same entries over the same market history**. The only
thing that varies is when a position closes. That is what makes the comparison a
comparison — if entries differed, a strategy could win by having been offered
better tokens.

## The distinction that has to stay visible

The live wallet answers *"what would $1,000 have done?"*, and there cash is a
binding constraint: with $100 trades only ten positions fit at once, so a rule
that exits sooner frees capital sooner and **enters different tokens**.

The lab answers a different question — *"which exit rule handles these
detections best?"* — and to hold entries fixed it replays with **unconstrained
capital**: every detection gets one $100 position, whatever else is open. Return
is therefore an equal-weight per-trade figure, directly comparable to the
"buy every Radar token" benchmark, which is unconstrained in exactly the same
way.

The two numbers are not interchangeable and the API says so on every response.
Reporting a lab return as though it were the wallet's balance would be the
quietest lie available here.

Pure. No I/O, no clock, no randomness — `now` is a parameter. Running the same
rows twice must produce byte-identical results, and a test asserts it.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal

from app.paper import costs, exits
from app.paper.models import ExitReason, Quote

_ZERO = Decimal(0)
_HUNDRED = Decimal(100)

#: Notional per position. Equal weight, and the same for every strategy, so a
#: difference in result is a difference in the exit rule and nothing else.
TRADE_SIZE = Decimal(100)

#: Below this span, an annualised figure is extrapolation rather than
#: measurement — a four-day window scaled to a year magnifies noise by ninety.
#: Published rather than buried: the bar is part of the claim.
MIN_DAYS_TO_ANNUALISE = 90


@dataclass(frozen=True, slots=True)
class Detection:
    """One Radar detection, and the prices observed since.

    The lab's entire input. Built once and handed to every strategy unchanged —
    that sharing is what guarantees identical entries.
    """

    mint_address: str
    symbol: str | None
    detected_at: datetime
    quotes: tuple[Quote, ...]


@dataclass(frozen=True, slots=True)
class Trade:
    """What one rule did with one detection."""

    mint_address: str
    symbol: str | None
    opened_at: datetime
    entry_price: Decimal
    #: `None` while the position never closed inside the observed history.
    closed_at: datetime | None
    exit_price: Decimal | None
    reason: ExitReason | None
    #: Highest price observed while the position was open, up to its exit.
    peak_price: Decimal
    #: Latest observed price, for a position still running.
    mark_price: Decimal | None
    #: Pool depth at entry and at settlement. `None` on bonding-curve pairs,
    #: which report no liquidity — such a trade is excluded from net entirely
    #: rather than costed against a depth nobody observed.
    entry_liquidity: Decimal | None = None
    settle_liquidity: Decimal | None = None

    @property
    def is_open(self) -> bool:
        return self.closed_at is None

    @property
    def settle_price(self) -> Decimal | None:
        """What the position is worth: its exit, or its latest mark."""
        return self.exit_price if self.exit_price is not None else self.mark_price

    @property
    def return_pct(self) -> Decimal | None:
        price = self.settle_price
        if price is None or self.entry_price <= 0:
            return None
        return (price - self.entry_price) / self.entry_price * _HUNDRED

    @property
    def pnl(self) -> Decimal | None:
        pct = self.return_pct
        return None if pct is None else TRADE_SIZE * pct / _HUNDRED

    @property
    def peak_pct(self) -> Decimal | None:
        """How high it got before it exited, as a percent of entry."""
        if self.entry_price <= 0:
            return None
        return (self.peak_price - self.entry_price) / self.entry_price * _HUNDRED

    @property
    def giveback_pct(self) -> Decimal | None:
        """How much of the peak was handed back at the exit.

        The figure that actually explains a rule: a strategy with a high average
        peak and a high giveback is one that was right and did not collect.
        """
        price = self.settle_price
        if price is None or self.peak_price <= 0:
            return None
        return (self.peak_price - price) / self.peak_price * _HUNDRED

    @property
    def execution_costs(self) -> costs.RoundTrip | None:
        """What the venue would have taken, or `None` if depth is unknown."""
        settle = self.settle_price
        if settle is None or self.entry_price <= 0:
            return None
        exit_notional = TRADE_SIZE * settle / self.entry_price
        return costs.round_trip(
            entry_notional=TRADE_SIZE,
            entry_liquidity=self.entry_liquidity,
            exit_notional=exit_notional,
            exit_liquidity=self.settle_liquidity,
        )

    @property
    def net_pnl(self) -> Decimal | None:
        """Profit after fee and price impact on both sides.

        `None` when the trade cannot be costed. The caller excludes it from the
        net aggregate rather than reporting it as costless, which would flatter
        exactly the thin-pool trades most likely to be expensive.
        """
        found = self.execution_costs
        settle = self.settle_price
        if found is None or settle is None or self.entry_price <= 0:
            return None
        exit_notional = TRADE_SIZE * settle / self.entry_price
        return costs.net_proceeds(
            entry_notional=TRADE_SIZE, exit_notional=exit_notional, costs=found
        )

    @property
    def hold_hours(self) -> Decimal | None:
        if self.closed_at is None:
            return None
        return Decimal((self.closed_at - self.opened_at).total_seconds()) / Decimal(3600)


@dataclass(frozen=True, slots=True)
class EquityPoint:
    at: datetime
    equity: Decimal
    drawdown_pct: Decimal


@dataclass(frozen=True, slots=True)
class LabResult:
    """One strategy's measured performance. Nothing here is estimated."""

    strategy_id: str
    trades: tuple[Trade, ...]

    invested: Decimal
    #: Every trade, with open positions marked at the latest observed price.
    total_return_pct: Decimal | None
    #: **Closed trades only.** Reported beside the total because win rate and
    #: profit factor are also closed-only: a rule whose headline return comes
    #: mostly from open marks would otherwise read as though it had earned it.
    realised_return_pct: Decimal | None
    #: Share of trades still open. The number that tells a reader how much of
    #: the total return is a mark rather than a result.
    open_share_pct: Decimal | None
    #: `None` unless the observed history is long enough to annualise honestly.
    annualised_return_pct: Decimal | None
    annualised_unavailable_reason: str | None

    closed_count: int
    open_count: int
    win_rate_pct: Decimal | None
    profit_factor: Decimal | None
    average_win: Decimal | None
    average_loss: Decimal | None
    largest_winner: Decimal | None
    largest_loser: Decimal | None
    max_drawdown_pct: Decimal | None
    average_hold_hours: Decimal | None
    average_peak_pct: Decimal | None
    average_giveback_pct: Decimal | None
    exits_by_reason: dict[str, int]
    #: Return after the venue's fee and the order's price impact, over the
    #: trades that could be costed. `None` when none could.
    net_return_pct: Decimal | None = None
    #: What execution took, in percentage points of the gross figure.
    cost_drag_pct: Decimal | None = None
    #: How many trades the net figure covers, and how many were excluded for
    #: reporting no pool depth. Published so the coverage is checkable.
    costed_trades: int = 0
    uncosted_trades: int = 0
    equity_curve: tuple[EquityPoint, ...] = field(default=())
    #: Per-trade returns, for the distribution chart. Closed trades only.
    return_distribution: tuple[Decimal, ...] = field(default=())
    hold_distribution: tuple[Decimal, ...] = field(default=())


def _quantize(value: Decimal | None, places: str = "0.01") -> Decimal | None:
    return None if value is None else value.quantize(Decimal(places))


def _liquidity_at(quotes: Sequence[Quote], moment: datetime) -> Decimal | None:
    """Pool depth at a given observation, or `None` if that reading had none.

    The exit is costed against the depth observed *when it closed*, not against
    the latest reading — a pool that drained afterwards did not affect a trade
    that had already left it, and one that filled up afterwards did not help it.
    """
    for quote in quotes:
        if quote.captured_at == moment:
            return quote.liquidity_usd
    return None


def replay(detections: Sequence[Detection], strategy: exits.LabStrategy) -> LabResult:
    """Apply one rule set to every detection, in one pass each.

    Deterministic by construction: the only inputs are the stored series and the
    rule, and neither the clock nor the iteration order of anything unordered is
    consulted. Detections are processed in the order given, and the caller sorts
    them, so two runs over the same input produce identical output.
    """
    trades: list[Trade] = []

    for detection in detections:
        if not detection.quotes:
            # Never priced, so never entered. Skipped rather than entered at a
            # price nobody observed.
            continue

        first = detection.quotes[0]
        if first.price_usd <= 0:
            continue

        found, peak = exits.resolve(
            strategy.rules,
            entry_price=first.price_usd,
            opened_at=first.captured_at,
            quotes=detection.quotes[1:],
        )

        trades.append(
            Trade(
                mint_address=detection.mint_address,
                symbol=detection.symbol,
                opened_at=first.captured_at,
                entry_price=first.price_usd,
                closed_at=None if found is None else found.at,
                exit_price=None if found is None else found.price_usd,
                reason=None if found is None else found.reason,
                peak_price=peak,
                mark_price=detection.quotes[-1].price_usd if found is None else None,
                entry_liquidity=first.liquidity_usd,
                settle_liquidity=_liquidity_at(detection.quotes, found.at)
                if found is not None
                else detection.quotes[-1].liquidity_usd,
            )
        )

    return _summarise(strategy.id, tuple(trades))


def _summarise(strategy_id: str, trades: tuple[Trade, ...]) -> LabResult:
    closed = [trade for trade in trades if not trade.is_open]
    still_open = [trade for trade in trades if trade.is_open]
    invested = TRADE_SIZE * len(trades)

    pnls = [trade.pnl for trade in trades if trade.pnl is not None]
    total_pnl = sum(pnls, _ZERO)
    total_return = None if invested <= 0 else total_pnl / invested * _HUNDRED

    closed_pnls = [trade.pnl for trade in closed if trade.pnl is not None]
    closed_invested = TRADE_SIZE * len(closed)
    realised_return = (
        None if closed_invested <= 0 else sum(closed_pnls, _ZERO) / closed_invested * _HUNDRED
    )
    wins = [value for value in closed_pnls if value > 0]
    losses = [value for value in closed_pnls if value < 0]
    gross_profit = sum(wins, _ZERO)
    gross_loss = sum((-value for value in losses), _ZERO)

    holds = [trade.hold_hours for trade in closed if trade.hold_hours is not None]
    peaks = [trade.peak_pct for trade in trades if trade.peak_pct is not None]
    givebacks = [trade.giveback_pct for trade in trades if trade.giveback_pct is not None]

    curve = _equity_curve(invested, closed)

    # Net is computed only over trades whose depth was reported. Bonding-curve
    # pairs report none, so they are excluded and counted rather than costed
    # against a depth nobody observed.
    costed = [trade for trade in trades if trade.net_pnl is not None]
    net_invested = TRADE_SIZE * len(costed)
    net_return = (
        None
        if net_invested <= 0
        else sum((trade.net_pnl or _ZERO for trade in costed), _ZERO) / net_invested * _HUNDRED
    )
    # Gross measured over the *same* subset, so the drag compares like with
    # like — differencing net against the all-trades gross would attribute the
    # excluded trades' performance to execution cost.
    gross_on_costed = (
        None
        if net_invested <= 0
        else sum((trade.pnl or _ZERO for trade in costed), _ZERO) / net_invested * _HUNDRED
    )

    return LabResult(
        strategy_id=strategy_id,
        trades=trades,
        invested=invested,
        total_return_pct=_quantize(total_return),
        realised_return_pct=_quantize(realised_return),
        open_share_pct=(
            None
            if not trades
            else _quantize(Decimal(len(still_open)) / Decimal(len(trades)) * _HUNDRED)
        ),
        net_return_pct=_quantize(net_return),
        cost_drag_pct=(
            None
            if net_return is None or gross_on_costed is None
            else _quantize(net_return - gross_on_costed)
        ),
        costed_trades=len(costed),
        uncosted_trades=len(trades) - len(costed),
        annualised_return_pct=_annualised(total_return, trades),
        annualised_unavailable_reason=_annualise_reason(trades),
        closed_count=len(closed),
        open_count=len(still_open),
        win_rate_pct=(
            None
            if not closed_pnls
            else _quantize(Decimal(len(wins)) / Decimal(len(closed_pnls)) * _HUNDRED)
        ),
        # Undefined rather than infinite while nothing has lost: a rule with
        # three wins and no losses has not proven a ratio.
        profit_factor=(None if gross_loss <= 0 else _quantize(gross_profit / gross_loss)),
        average_win=(None if not wins else _quantize(gross_profit / Decimal(len(wins)))),
        average_loss=(None if not losses else _quantize(gross_loss / Decimal(len(losses)))),
        largest_winner=(None if not wins else _quantize(max(wins))),
        largest_loser=(None if not losses else _quantize(min(losses))),
        max_drawdown_pct=(
            None if not curve else _quantize(max(point.drawdown_pct for point in curve))
        ),
        average_hold_hours=(
            None if not holds else _quantize(sum(holds, _ZERO) / Decimal(len(holds)))
        ),
        average_peak_pct=(
            None if not peaks else _quantize(sum(peaks, _ZERO) / Decimal(len(peaks)))
        ),
        average_giveback_pct=(
            None
            if not givebacks
            else _quantize(sum(givebacks, _ZERO) / Decimal(len(givebacks)))
        ),
        exits_by_reason={
            reason.value: sum(1 for trade in closed if trade.reason is reason)
            for reason in ExitReason
        },
        equity_curve=curve,
        return_distribution=tuple(
            value
            for value in (
                _quantize(trade.return_pct) for trade in closed if trade.return_pct is not None
            )
            if value is not None
        ),
        hold_distribution=tuple(
            value for value in (_quantize(hold) for hold in holds) if value is not None
        ),
    )


def _equity_curve(invested: Decimal, closed: Sequence[Trade]) -> tuple[EquityPoint, ...]:
    """Equity after each close, and the drawdown from its running high.

    Realised only. The platform stores no equity series, so the path *between*
    closes is not reconstructed and the drawdown here is a floor on the true
    figure rather than the intraday number. Every surface says so.

    Ordered by close time with a mint tiebreak, so two runs over the same trades
    produce the same curve whatever order they arrived in.
    """
    if invested <= 0 or not closed:
        return ()

    equity = invested
    peak = invested
    points: list[EquityPoint] = []
    for trade in sorted(
        closed, key=lambda item: (item.closed_at or datetime.min, item.mint_address)
    ):
        if trade.pnl is None or trade.closed_at is None:
            continue
        equity += trade.pnl
        if equity > peak:
            peak = equity
        fall = _ZERO if peak <= 0 else (peak - equity) / peak * _HUNDRED
        points.append(
            EquityPoint(
                at=trade.closed_at,
                equity=equity.quantize(Decimal("0.01")),
                drawdown_pct=fall.quantize(Decimal("0.01")),
            )
        )
    return tuple(points)


def observed_span(trades: Sequence[Trade]) -> timedelta | None:
    """How much wall time the replay actually covers."""
    stamps = [trade.opened_at for trade in trades]
    stamps += [trade.closed_at for trade in trades if trade.closed_at is not None]
    if len(stamps) < 2:
        return None
    return max(stamps) - min(stamps)


def _annualise_reason(trades: Sequence[Trade]) -> str | None:
    span = observed_span(trades)
    if span is None:
        return "Not enough history to measure a span."
    days = span.total_seconds() / 86_400
    if days < MIN_DAYS_TO_ANNUALISE:
        return (
            f"Not shown. The replay covers {days:.1f} days, below the "
            f"{MIN_DAYS_TO_ANNUALISE} needed to annualise without extrapolating — "
            "scaling a window this short to a year magnifies noise rather than "
            "measuring a rate."
        )
    return None


def _annualised(total_return: Decimal | None, trades: Sequence[Trade]) -> Decimal | None:
    """Annualised return, or nothing.

    Refuses far more often than it answers, and that is correct. Annualising a
    four-day window is the single most misleading figure a backtest can print.
    """
    if total_return is None or _annualise_reason(trades) is not None:
        return None
    span = observed_span(trades)
    if span is None:  # pragma: no cover - guarded by the reason above
        return None
    years = Decimal(span.total_seconds()) / Decimal(365 * 86_400)
    if years <= 0:  # pragma: no cover
        return None
    return (total_return / years).quantize(Decimal("0.01"))


# --- Comparison ----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TokenComparison:
    """How every rule handled one token, and which captured most of the peak."""

    mint_address: str
    symbol: str | None
    peak_pct: Decimal | None
    #: strategy id -> return percent for this token.
    returns: dict[str, Decimal | None]
    #: The rule that captured the largest share of this token's peak move.
    #: `None` when the token never rose, so there was no peak to capture.
    best_strategy_id: str | None
    best_capture_pct: Decimal | None


def compare_by_token(
    results: dict[str, LabResult], *, limit: int | None = None
) -> tuple[TokenComparison, ...]:
    """Per-token, per-strategy returns, and who captured most of the move.

    "Captured" is measured against the peak the token actually reached while the
    position was open — a rule that returned 40% on a token that peaked at 50%
    captured more of the available move than one that returned 60% on a token
    that peaked at 300%.

    A token that never rose above its entry has no peak to capture, and reports
    `None` rather than crowning whichever rule lost least.
    """
    by_mint: dict[str, dict[str, Trade]] = {}
    for strategy_id, result in results.items():
        for trade in result.trades:
            by_mint.setdefault(trade.mint_address, {})[strategy_id] = trade

    comparisons: list[TokenComparison] = []
    for mint, per_strategy in by_mint.items():
        any_trade = next(iter(per_strategy.values()))
        # The peak is a property of the token over the window, so it is the same
        # for every rule that held it; take the largest observed.
        peak = max(
            (trade.peak_pct for trade in per_strategy.values() if trade.peak_pct is not None),
            default=None,
        )

        returns = {
            strategy_id: _quantize(trade.return_pct)
            for strategy_id, trade in per_strategy.items()
        }

        best_id: str | None = None
        best_capture: Decimal | None = None
        if peak is not None and peak > 0:
            for strategy_id, value in sorted(returns.items()):
                if value is None:
                    continue
                capture = value / peak * _HUNDRED
                if best_capture is None or capture > best_capture:
                    best_capture = capture
                    best_id = strategy_id

        comparisons.append(
            TokenComparison(
                mint_address=mint,
                symbol=any_trade.symbol,
                peak_pct=_quantize(peak),
                returns=returns,
                best_strategy_id=best_id,
                best_capture_pct=_quantize(best_capture),
            )
        )

    # Largest peak first, mint as tiebreak — deterministic, and it puts the
    # tokens where the choice of rule mattered most at the top.
    comparisons.sort(key=lambda item: (-(item.peak_pct or _ZERO), item.mint_address))
    return tuple(comparisons if limit is None else comparisons[:limit])


def rank(results: dict[str, LabResult]) -> tuple[str, ...]:
    """Strategy ids ordered by total return, best first.

    Ties broken by id so the order is stable across runs. Ranking on return
    alone is deliberate and stated: it is the one figure every rule reports,
    and a composite score would be an opinion wearing a measurement's clothes.
    """
    return tuple(
        sorted(
            results,
            key=lambda key: (
                -(results[key].total_return_pct or Decimal("-999999")),
                key,
            ),
        )
    )
