"""`GET /api/v1/paper` — the wallet, its positions, and the published strategies.

**Three endpoints, none of them POST.** There is no manual entry, so there is
no write endpoint to have. That is not an omission: a button that opened a
position by hand would make the wallet a record of somebody's judgement rather
than of a published rule, and the whole claim here is that no judgement was
applied.

Gated on `FEATURE_PAPER_WALLET_ENABLED`. While off the wallet reports
`enabled: false` rather than 404ing or serving an empty book — "not switched on
here" and "this strategy traded nothing" are different facts, and the second is
a result.

Nothing served here is advice. Every figure describes what a published rule did
over stored history; none of it recommends an entry, an exit or a stop.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import DbSession
from app.core.config import settings
from app.models.paper import PaperPosition
from app.paper import costs, exits, lab
from app.paper.lab_service import load_dataset, replay_all
from app.paper.metrics import WalletMetrics
from app.paper.models import PositionStatus
from app.paper.schemas import (
    BenchmarkOut,
    EquityPointOut,
    LabFindingOut,
    LabOut,
    LabRuleOut,
    LabStrategyOut,
    LabTokensOut,
    MetricsOut,
    PositionOut,
    PositionsOut,
    RuleOut,
    StrategiesOut,
    StrategyOut,
    TokenComparisonOut,
    UnavailableStrategyOut,
    WalletOut,
)
from app.paper.service import PaperWalletService, WalletRead
from app.paper.strategy import FixedSizeStrategy, registry

router = APIRouter(prefix="/paper", tags=["paper"])

#: Repeated on every wallet response rather than left to the page. A client that
#: renders the numbers without this sentence should still be serving it.
DISCLOSURE = (
    "Simulated. No wallet is connected, no order is placed and no transaction "
    "is made. Every position below is a record of what a published rule would "
    "have done over prices this platform already stored. Nothing here is advice."
)

MAX_DRAWDOWN_NOTE = (
    "Measured on the realised equity curve — the value after each close, in the "
    "order they closed. The path between closes is not reconstructed, so the "
    "true intraday drawdown was at least this deep."
)


@router.get("/strategies", response_model=StrategiesOut, summary="The published strategies")
async def list_strategies() -> StrategiesOut:
    """Every declared strategy, and which one trades.

    Declared before `/{...}`-shaped routes for the same reason `radar/api.py`
    orders its literals first.

    Publishing the non-operational ones is deliberate: a reader can see that the
    architecture holds four rule sets and that exactly one is running, rather
    than inferring that one is all there is.
    """
    active = _active_strategy()
    return StrategiesOut(
        items=[_to_strategy(item, active_id=active.id) for item in registry.all()],
        active_id=active.id,
    )


@router.get("/positions", response_model=PositionsOut, summary="Every simulated trade")
async def list_positions(session: DbSession) -> PositionsOut:
    """Open and closed together, newest first. Losers are never filtered out."""
    now = datetime.now(UTC)
    if not settings.FEATURE_PAPER_WALLET_ENABLED:
        return PositionsOut(items=[], enabled=False, observed_at=now)

    read = await PaperWalletService(session).read(now=now)
    return PositionsOut(
        items=[_to_position(row, read) for row in read.positions],
        enabled=True,
        observed_at=now,
    )


@router.get("", response_model=WalletOut, summary="The paper wallet")
async def get_wallet(session: DbSession) -> WalletOut:
    """Balance, equity, every metric, and the benchmarks it is measured against."""
    now = datetime.now(UTC)
    active = _active_strategy()

    if not settings.FEATURE_PAPER_WALLET_ENABLED:
        starting = Decimal(str(settings.PAPER_WALLET_STARTING_BALANCE))
        return WalletOut(
            enabled=False,
            strategy=_to_strategy(active, active_id=active.id),
            metrics=_empty_metrics(starting),
            benchmarks=[],
            pnl_today=Decimal(0),
            disclosure=DISCLOSURE,
            observed_at=now,
        )

    read = await PaperWalletService(session).read(now=now)
    return WalletOut(
        enabled=True,
        strategy=_to_strategy(read.strategy, active_id=read.strategy.id),
        metrics=_to_metrics(read.metrics),
        benchmarks=_benchmarks(read),
        pnl_today=read.pnl_today,
        disclosure=DISCLOSURE,
        observed_at=now,
    )


# --- Rendering ----------------------------------------------------------------


def _active_strategy() -> FixedSizeStrategy:
    return registry.get(settings.PAPER_WALLET_STRATEGY_ID) or registry.default


def _to_strategy(strategy: FixedSizeStrategy, *, active_id: str) -> StrategyOut:
    spec = strategy.describe()
    return StrategyOut(
        id=spec.id,
        name=spec.name,
        version=spec.version,
        summary=spec.summary,
        rules=[RuleOut(label=rule.label, value=rule.value) for rule in spec.rules],
        operational=spec.operational,
        unavailable_reason=spec.unavailable_reason,
        is_active=spec.id == active_id,
    )


def _empty_metrics(starting: Decimal) -> MetricsOut:
    """The shape of a wallet that is not running.

    Cash equals the starting balance because nothing was ever committed; every
    *measured* figure is null, because none of them has a trade behind it.
    """
    return MetricsOut(
        starting_balance=starting,
        cash=starting,
        equity=starting,
        roi_pct=Decimal(0),
        open_value=Decimal(0),
        realised_pnl=Decimal(0),
        max_drawdown_note=MAX_DRAWDOWN_NOTE,
    )


def _to_metrics(summary: WalletMetrics) -> MetricsOut:
    return MetricsOut(
        starting_balance=summary.starting_balance,
        cash=summary.cash,
        equity=summary.equity,
        roi_pct=summary.roi_pct,
        open_value=summary.open_value,
        unpriced_positions=summary.unpriced_positions,
        open_positions=summary.open_positions,
        closed_positions=summary.closed_positions,
        realised_pnl=summary.realised_pnl,
        win_rate_pct=summary.win_rate_pct,
        average_win=summary.average_win,
        average_loss=summary.average_loss,
        profit_factor=summary.profit_factor,
        largest_winner=summary.largest_winner,
        largest_loser=summary.largest_loser,
        max_drawdown_pct=summary.max_drawdown_pct,
        max_drawdown_note=MAX_DRAWDOWN_NOTE,
        average_hold_hours=summary.average_hold_hours,
        exits_by_reason=summary.exits_by_reason,
    )


def _pct_from(entry: Decimal, price: Decimal | None) -> Decimal | None:
    if price is None or entry <= 0:
        return None
    return ((price - entry) / entry * 100).quantize(Decimal("0.01"))


def _to_position(row: PaperPosition, read: WalletRead) -> PositionOut:
    name, symbol = read.names.get(row.mint_address, (None, None))
    closed = row.status == PositionStatus.CLOSED.value

    # A closed trade is marked at its exit; an open one at the latest reading.
    # Using the live price for a closed trade would restate a finished result
    # every time the token moved, which is the opposite of a permanent record.
    current = row.exit_price if closed else read.prices.get(row.mint_address)

    pnl: Decimal | None = None
    if current is not None:
        pnl = (row.quantity * current - row.size_usd).quantize(Decimal("0.01"))

    return PositionOut(
        mint_address=row.mint_address,
        name=name,
        symbol=symbol,
        status=row.status,
        opened_at=row.opened_at,
        entry_rank=row.entry_rank,
        entry_price=row.entry_price,
        size_usd=row.size_usd,
        quantity=row.quantity,
        target_price=row.target_price,
        stop_price=row.stop_price,
        expires_at=row.expires_at,
        current_price=current,
        current_pct=_pct_from(row.entry_price, current),
        peak_pct=_pct_from(row.entry_price, row.peak_price),
        closed_at=row.closed_at,
        exit_price=row.exit_price,
        exit_reason=row.exit_reason,
        pnl_usd=pnl,
    )


def _benchmarks(read: WalletRead) -> list[BenchmarkOut]:
    """What the strategy is measured against.

    Two comparisons, not three. "Buy every Radar token" and "equal-weight Radar"
    are the **same measurement** on this data — the mean `current_multiple`
    across every detection *is* an equal-weight buy-everything portfolio — so it
    is reported once. Printing one number under two labels would be exactly the
    duplication this platform refuses.

    Holding SOL stays unavailable with its reason. The platform records no SOL
    price history, and a comparison against a series it never stored would be
    fabricated.
    """
    roi = read.metrics.roi_pct
    average = read.benchmark.get("average_current_multiple")
    entries = int(read.benchmark.get("entries") or 0)

    equal_weight: Decimal | None = None
    if isinstance(average, Decimal) and entries > 0:
        equal_weight = ((average - 1) * 100).quantize(Decimal("0.01"))

    return [
        BenchmarkOut(
            id="equal_weight_radar",
            label="Buy every Radar token",
            description=(
                f"An equal-weight position in all {entries} tokens the Radar has "
                "ever detected, held from detection to now. No exits, no sizing."
            ),
            return_pct=equal_weight,
            difference_pct=(
                None
                if equal_weight is None or roi is None
                else (roi - equal_weight).quantize(Decimal("0.01"))
            ),
            unavailable_reason=(
                None if equal_weight is not None else "No detection has a measured return yet."
            ),
        ),
        BenchmarkOut(
            id="hold_sol",
            label="Hold SOL",
            description="The same capital left in SOL over the same period.",
            return_pct=None,
            difference_pct=None,
            unavailable_reason=(
                "Not shown. The platform records no SOL price history, so this "
                "comparison would be fabricated rather than measured."
            ),
        ),
    ]


# --- Strategy Lab -------------------------------------------------------------

METHODOLOGY = (
    "Every rule is replayed over the same detections and the same stored prices; "
    "only the exit logic differs. Capital is unconstrained here — each detection "
    "gets one $100 position regardless of what else is open — so entries stay "
    "identical across rules and a difference in result is a difference in the "
    "exit. That makes these returns equal-weight per-trade figures, directly "
    "comparable to 'buy every Radar token'. They are NOT the live wallet's "
    "balance, where $1,000 of cash constrains which tokens can be entered at all."
)


@router.get("/lab", response_model=LabOut, summary="Strategy Lab")
async def get_lab(session: DbSession) -> LabOut:
    """Every published exit rule, replayed over one shared dataset.

    Declared before `/{...}`-shaped routes, matching the ordering rule the rest
    of the API follows.

    The dataset is loaded once and handed to every strategy unchanged. Two
    strategies given separately-loaded datasets could differ because a snapshot
    landed between the loads, and the comparison would be measuring a race.
    """
    now = datetime.now(UTC)
    dataset = await load_dataset(session, now=now)
    results = replay_all(dataset)
    order = lab.rank(results)
    baseline_id = exits.baseline().id
    baseline_return = results[baseline_id].total_return_pct

    strategies = [
        _to_lab_strategy(
            strategy,
            results[strategy.id],
            rank=order.index(strategy.id) + 1,
            baseline_return=baseline_return,
        )
        for strategy in exits.LAB_STRATEGIES
    ]
    strategies.sort(key=lambda item: item.rank)

    span = lab.observed_span(results[baseline_id].trades)
    return LabOut(
        strategies=strategies,
        unavailable=[
            UnavailableStrategyOut(id=sid, name=name, reason=reason)
            for sid, name, reason in exits.UNAVAILABLE_STRATEGIES
        ],
        findings=_findings(results, order, baseline_id),
        baseline_id=baseline_id,
        detections=len(dataset.detections),
        unpriced_detections=dataset.unpriced,
        observed_days=(
            None
            if span is None
            else (Decimal(span.total_seconds()) / Decimal(86_400)).quantize(Decimal("0.1"))
        ),
        methodology=METHODOLOGY,
        cost_disclosure=costs.DISCLOSURE,
        cost_rules=[
            LabRuleOut(
                label="Swap fee",
                value=f"{costs.DEFAULT.swap_fee_bps} bps per side",
            ),
            LabRuleOut(
                label="Price impact",
                value="Constant product against the pool depth observed at each end",
            ),
            LabRuleOut(label="Slippage from competing flow", value="Not modelled"),
            LabRuleOut(label="Priority fees and MEV", value="Not modelled"),
            LabRuleOut(
                label="Bonding-curve pairs",
                value="Excluded — the venue reports no liquidity",
            ),
        ],
        observed_at=now,
    )


@router.get("/lab/tokens", response_model=LabTokensOut, summary="Per-token rule comparison")
async def get_lab_tokens(
    session: DbSession,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> LabTokensOut:
    """How every rule handled each token, and which captured most of its peak."""
    now = datetime.now(UTC)
    dataset = await load_dataset(session, now=now)
    results = replay_all(dataset)

    return LabTokensOut(
        items=[
            TokenComparisonOut(
                mint_address=item.mint_address,
                symbol=item.symbol,
                peak_pct=item.peak_pct,
                returns=item.returns,
                best_strategy_id=item.best_strategy_id,
                best_capture_pct=item.best_capture_pct,
            )
            for item in lab.compare_by_token(results, limit=limit)
        ],
        strategy_ids=[strategy.id for strategy in exits.LAB_STRATEGIES],
        observed_at=now,
    )


def _to_lab_strategy(
    strategy: exits.LabStrategy,
    result: lab.LabResult,
    *,
    rank: int,
    baseline_return: Decimal | None,
) -> LabStrategyOut:
    difference: Decimal | None = None
    if (
        not strategy.is_baseline
        and baseline_return is not None
        and result.total_return_pct is not None
    ):
        difference = (result.total_return_pct - baseline_return).quantize(Decimal("0.01"))

    return LabStrategyOut(
        id=strategy.id,
        name=strategy.name,
        description=strategy.description,
        rules=[
            LabRuleOut(label=label, value=value) for label, value in strategy.published_rules()
        ],
        is_baseline=strategy.is_baseline,
        invested=result.invested,
        total_return_pct=result.total_return_pct,
        realised_return_pct=result.realised_return_pct,
        open_share_pct=result.open_share_pct,
        net_return_pct=result.net_return_pct,
        cost_drag_pct=result.cost_drag_pct,
        costed_trades=result.costed_trades,
        uncosted_trades=result.uncosted_trades,
        baseline_difference_pct=difference,
        annualised_return_pct=result.annualised_return_pct,
        annualised_unavailable_reason=result.annualised_unavailable_reason,
        closed_count=result.closed_count,
        open_count=result.open_count,
        win_rate_pct=result.win_rate_pct,
        profit_factor=result.profit_factor,
        average_win=result.average_win,
        average_loss=result.average_loss,
        largest_winner=result.largest_winner,
        largest_loser=result.largest_loser,
        max_drawdown_pct=result.max_drawdown_pct,
        average_hold_hours=result.average_hold_hours,
        average_peak_pct=result.average_peak_pct,
        average_giveback_pct=result.average_giveback_pct,
        exits_by_reason=result.exits_by_reason,
        rank=rank,
        equity_curve=[
            EquityPointOut(at=point.at, equity=point.equity, drawdown_pct=point.drawdown_pct)
            for point in result.equity_curve
        ],
        return_distribution=list(result.return_distribution),
        hold_distribution=list(result.hold_distribution),
    )


def _findings(
    results: dict[str, lab.LabResult], order: tuple[str, ...], baseline_id: str
) -> list[LabFindingOut]:
    """Conclusions drawn only from the figures, each naming its own metric.

    Deliberately mechanical. Every sentence below is a statement about what the
    replay measured, and none tells a reader what to do — the moment this
    function starts recommending, the lab stops being evidence.

    The baseline's standing is stated whether it won or lost. A lab that only
    narrated the winner would be the hindsight this sprint forbids.
    """
    names = {strategy.id: strategy.name for strategy in exits.LAB_STRATEGIES}
    findings: list[LabFindingOut] = []
    if not order:
        return findings

    best_id, worst_id = order[0], order[-1]
    best, worst = results[best_id], results[worst_id]
    baseline = results[baseline_id]

    if best.total_return_pct is not None:
        findings.append(
            LabFindingOut(
                headline=f"Best measured return: {names[best_id]}",
                detail=(
                    f"{best.total_return_pct}% over {best.closed_count} closed trades, "
                    f"with a {best.max_drawdown_pct}% realised drawdown. Ranked on "
                    "total return alone — the one figure every rule reports."
                ),
                strategy_id=best_id,
            )
        )

    if worst_id != best_id and worst.total_return_pct is not None:
        findings.append(
            LabFindingOut(
                headline=f"Worst measured return: {names[worst_id]}",
                detail=(
                    f"{worst.total_return_pct}% over {worst.closed_count} closed trades, "
                    f"with a {worst.max_drawdown_pct}% realised drawdown."
                ),
                strategy_id=worst_id,
            )
        )

    if baseline.total_return_pct is not None:
        place = order.index(baseline_id) + 1
        findings.append(
            LabFindingOut(
                headline=(f"The benchmark placed {place} of {len(order)}"),
                detail=(
                    f"Equal Weight v1 returned {baseline.total_return_pct}%. It is "
                    "frozen and is not tuned in response to this table — every "
                    "comparison here is drawn against it, so moving it would "
                    "restate all of them."
                ),
                strategy_id=baseline_id,
            )
        )

    # The diagnostic pairing: peak reached against peak handed back. This is what
    # distinguishes "the entries were bad" from "the exits gave it away".
    giveback = [
        (sid, result)
        for sid, result in results.items()
        if result.average_giveback_pct is not None and result.average_peak_pct is not None
    ]
    if giveback:
        worst_giveback = max(
            giveback, key=lambda item: (item[1].average_giveback_pct, item[0])
        )
        sid, result = worst_giveback
        findings.append(
            LabFindingOut(
                headline=f"Largest giveback: {names[sid]}",
                detail=(
                    f"Positions reached {result.average_peak_pct}% above entry on "
                    f"average and handed back {result.average_giveback_pct}% of that "
                    "peak by the exit. A high peak with a high giveback means the "
                    "entries found the move and the exit rule did not collect it."
                ),
                strategy_id=sid,
            )
        )

    # The most important caveat in the table. A rule can lead on marked return
    # while its *closed* trades lost badly — the open positions are carrying it.
    # Ranking uses the marked total, so this divergence has to be stated rather
    # than left to be noticed in a column.
    divergences = [
        (sid, result.total_return_pct - result.realised_return_pct, result)
        for sid, result in results.items()
        if result.total_return_pct is not None and result.realised_return_pct is not None
    ]
    if divergences:
        sid, gap, result = max(divergences, key=lambda item: (item[1], item[0]))
        if gap >= Decimal(20):
            findings.append(
                LabFindingOut(
                    headline=f"{names[sid]}'s return is carried by open positions",
                    detail=(
                        f"Marked total {result.total_return_pct}%, but its "
                        f"{result.closed_count} closed trades returned "
                        f"{result.realised_return_pct}% — a gap of "
                        f"{gap.quantize(Decimal('0.01'))} points, with "
                        f"{result.open_share_pct}% of positions still open. The "
                        "marked figure is a position, not a result."
                    ),
                    strategy_id=sid,
                )
            )

    # Execution cost is **progressive**, and that is the interesting part: the
    # exit is charged on the position's value when it closes, so a rule that
    # doubles a position sells twice the notional and pays twice the impact.
    # The rules that win most pay most to leave.
    costed = [
        (sid, result)
        for sid, result in results.items()
        if result.net_return_pct is not None and result.cost_drag_pct is not None
    ]
    if costed:
        sid, result = max(costed, key=lambda item: (item[1].net_return_pct, item[0]))
        survivors = sum(1 for _, r in costed if (r.net_return_pct or Decimal(0)) > 0)
        drags = [abs(r.cost_drag_pct or Decimal(0)) for _, r in costed]
        findings.append(
            LabFindingOut(
                headline=(
                    f"After execution costs, {survivors} of {len(costed)} rules stay positive"
                ),
                detail=(
                    f"Fee and price impact take between {min(drags)} and "
                    f"{max(drags)} points. The cost is progressive — the exit is "
                    "charged on what the position is worth when it closes, so the "
                    f"rules that win most pay most to leave. {names[sid]} nets "
                    f"{result.net_return_pct}% over {result.costed_trades} costed "
                    f"trades; {result.uncosted_trades} were excluded for reporting "
                    "no pool depth."
                ),
                strategy_id=sid,
            )
        )

    stopped = [
        (sid, result.exits_by_reason.get("stop", 0), result.closed_count)
        for sid, result in results.items()
        if result.closed_count > 0
    ]
    if stopped:
        sid, stops, total = max(stopped, key=lambda item: (item[1] / item[2], item[0]))
        findings.append(
            LabFindingOut(
                headline=f"Most stop-driven: {names[sid]}",
                detail=(
                    f"{stops} of {total} closed trades exited on a stop. Exit-reason "
                    "counts are the mechanism behind the return figure, not a "
                    "separate claim about it."
                ),
                strategy_id=sid,
            )
        )

    return findings
