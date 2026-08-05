"""`GET /api/v1/paper` — the wallet, its positions, its record, and its archive.

**Nothing here is a POST.** There is no manual entry, so there is no write
endpoint to have. That is not an omission: a button that opened a position by
hand would make the wallet a record of somebody's judgement rather than of a
published rule, and the whole claim here is that no judgement was applied. The
same reasoning removed the strategy selector in Sprint 30 — one strategy is
operational, and choosing between rules after seeing their results is the
hindsight this package exists to prevent.

`/paper/archive` is served for internal historical comparison and is not linked
from the product. It reports retired generations frozen exactly as they were.

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
from app.models.paper import PaperPosition, PaperTradeAudit
from app.paper import audit, benchmark, cadence, costs, eligibility, exits, lab
from app.paper.lab_service import load_dataset, measure_entry_divergence, replay_all
from app.paper.metrics import WalletMetrics
from app.paper.models import PositionStatus
from app.paper.repository import PaperRepository
from app.paper.schemas import (
    ArchivedWalletOut,
    ArchiveOut,
    AuditEntryOut,
    AuditOut,
    BenchmarkOut,
    EntryDivergenceOut,
    EquityPointOut,
    LabFindingOut,
    LabOut,
    LabRuleOut,
    LabStrategyOut,
    LabTokensOut,
    LastTradeOut,
    MetricsOut,
    PositionOut,
    PositionsOut,
    RuleOut,
    StrategiesOut,
    StrategyOut,
    TokenComparisonOut,
    UnavailableStrategyOut,
    WaitingOut,
    WalletOut,
)
from app.paper.service import PaperWalletService, WalletRead
from app.paper.strategy import AnyStrategy, registry

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


@router.get("/audit", response_model=AuditOut, summary="The permanent trade record")
async def get_audit(
    session: DbSession,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> AuditOut:
    """Every completed trade, as it was written down and never rewritten.

    Declared before `/{...}`-shaped routes, matching the ordering rule the rest
    of the API follows.

    This is not a re-derivation of the positions table. Each row was computed at
    the moment its trade closed, from the market data observed at each end —
    including the pool depth the fee and impact were charged against, which
    `token_market_snapshots` will eventually prune.
    """
    now = datetime.now(UTC)
    if not settings.FEATURE_PAPER_WALLET_ENABLED:
        return AuditOut(
            items=[], total=0, enabled=False, disclosure=audit.DISCLOSURE, observed_at=now
        )

    repository = PaperRepository(session)
    wallet = await repository.live_wallet()
    if wallet is None:
        return AuditOut(
            items=[], total=0, enabled=True, disclosure=audit.DISCLOSURE, observed_at=now
        )

    rows = await repository.audit_log(wallet.id, limit=limit, offset=offset)
    return AuditOut(
        items=[_to_audit_entry(row) for row in rows],
        total=await repository.audit_count(wallet.id),
        enabled=True,
        disclosure=audit.DISCLOSURE,
        observed_at=now,
    )


@router.get("/archive", response_model=ArchiveOut, summary="Retired wallets (internal)")
async def get_archive(session: DbSession) -> ArchiveOut:
    """Retired generations, for internal historical comparison.

    Not linked from the product, and deliberately so: Sprint 30 relaunched the
    wallet, and showing two track records side by side invites the reader to
    pick the flattering one. The archive exists so the old figures are not lost,
    not so they can be quoted beside the live ones.
    """
    now = datetime.now(UTC)
    repository = PaperRepository(session)
    items = []
    for wallet in await repository.archived_wallets():
        counts = await repository.position_counts(wallet.id)
        open_count = counts.get(PositionStatus.OPEN.value, 0)
        declared = registry.get(wallet.strategy_id)
        items.append(
            ArchivedWalletOut(
                strategy_id=wallet.strategy_id,
                strategy_name=(declared.name if declared is not None else wallet.strategy_id),
                strategy_version=wallet.strategy_version,
                generation=wallet.generation,
                starting_balance=wallet.starting_balance,
                started_at=wallet.started_at,
                # Non-null by construction: `archived_wallets` filters on it.
                archived_at=wallet.archived_at,
                archive_reason=wallet.archive_reason,
                open_positions=open_count,
                closed_positions=counts.get(PositionStatus.CLOSED.value, 0),
                frozen_note=_frozen_note(open_count),
            )
        )

    return ArchiveOut(items=items, note=ARCHIVE_NOTE, observed_at=now)


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
    benchmarks = _benchmarks(read)
    return WalletOut(
        enabled=True,
        strategy=_to_strategy(read.strategy, active_id=read.strategy.id),
        metrics=_to_metrics(read.metrics),
        benchmarks=benchmarks,
        generation=read.wallet.generation,
        started_at=read.wallet.started_at,
        benchmark_note=_benchmark_note(read),
        waiting=_to_waiting(read),
        last_trade=_last_trade(read),
        next_radar_evaluation_at=cadence.next_evaluation(now),
        audited_trades=read.audit_count,
        pnl_today=read.pnl_today,
        disclosure=DISCLOSURE,
        observed_at=now,
    )


# --- Rendering ----------------------------------------------------------------

ARCHIVE_NOTE = (
    "Retired wallets, kept for internal historical comparison and shown nowhere "
    "in the product. Their figures are frozen at the moment they were archived "
    "and are never mixed into the live wallet's."
)


def _frozen_note(open_positions: int) -> str:
    """What an archived wallet's remaining open positions mean.

    They never settle. Closing them at the price on the day of archival would be
    an exit no published rule chose, and marking them to a later price would let
    a retired wallet's figure keep moving. Both are worse than saying it.
    """
    if open_positions == 0:
        return "Every position in this wallet was closed by its own rule before archival."
    return (
        f"{open_positions} position(s) were still open when this wallet was "
        "archived and are frozen in that state. They will never settle: closing "
        "them would be an exit no published rule chose, and marking them to a "
        "later price would let a retired result keep moving."
    )


def _active_strategy() -> AnyStrategy:
    configured = registry.get(settings.PAPER_WALLET_STRATEGY_ID)
    if configured is None or not configured.operational:
        return registry.default
    return configured


def _to_strategy(strategy: AnyStrategy, *, active_id: str) -> StrategyOut:
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
        invested_usd=Decimal(0),
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
        invested_usd=summary.invested_usd,
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
    # The mark's own timestamp: the exit for a finished trade, the observation
    # for a running one.
    observed_at = row.closed_at if closed else read.price_times.get(row.mint_address)

    pnl: Decimal | None = None
    if current is not None:
        pnl = (row.quantity * current - row.size_usd).quantize(Decimal("0.01"))

    # Where the trailing stop sits right now: the running high less the fixed
    # fraction. Derived here rather than stored, because a stored level would be
    # a second source of truth for the only rule this strategy has.
    trailing_stop: Decimal | None = None
    if row.trailing_drawdown is not None and not closed:
        trailing_stop = row.peak_price * (Decimal(1) - row.trailing_drawdown)

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
        entry_market_cap=row.entry_market_cap,
        entry_liquidity_usd=row.entry_liquidity_usd,
        target_price=row.target_price,
        stop_price=row.stop_price,
        expires_at=row.expires_at,
        trailing_drawdown=row.trailing_drawdown,
        trailing_stop_price=trailing_stop,
        current_price=current,
        current_pct=_pct_from(row.entry_price, current),
        current_price_at=observed_at,
        peak_pct=_pct_from(row.entry_price, row.peak_price),
        closed_at=row.closed_at,
        exit_price=row.exit_price,
        exit_reason=row.exit_reason,
        pnl_usd=pnl,
    )


def _benchmarks(read: WalletRead) -> list[BenchmarkOut]:
    """What the strategy is measured against, over its own period.

    Both comparisons start with the wallet's capital at the wallet's own start
    instant (Sprint 30 §2). They are two genuinely different measurements:
    "buy every Radar token" carries the wallet's cash constraint and no exit
    rule, so the gap against it is what the exit rule did; "equal weight Radar"
    is the unconstrained index, so the gap against it is what the ranking did.
    They coincide while fewer tokens qualify than $1,000 can fund, and
    `benchmark_note` says so rather than passing one number off as two checks.

    Holding SOL stays unavailable with its reason. The platform records no SOL
    price history, and a comparison against a series it never stored would be
    fabricated.
    """
    roi = read.metrics.roi_pct

    out = [
        BenchmarkOut(
            id=result.id,
            label=result.label,
            description=result.description,
            return_pct=result.return_pct,
            difference_pct=(
                None
                if result.return_pct is None or roi is None
                else (roi - result.return_pct).quantize(Decimal("0.01"))
            ),
            unavailable_reason=result.unavailable_reason,
            positions=result.positions,
            unpriced=result.unpriced,
        )
        for result in read.benchmarks
    ]
    out.append(
        BenchmarkOut(
            id="hold_sol",
            label="Hold SOL",
            description="The same capital left in SOL over the same period.",
            return_pct=None,
            difference_pct=None,
            unavailable_reason=benchmark.HOLD_SOL_UNAVAILABLE,
        )
    )
    return out


def _benchmark_note(read: WalletRead) -> str | None:
    """Set only while both benchmarks hold the same set of tokens."""
    if len(read.benchmarks) < 2:
        return None
    first, second = read.benchmarks[0], read.benchmarks[1]
    if first.positions == 0 or first.positions != second.positions:
        return None
    return benchmark.COINCIDENCE_NOTE


def _to_waiting(read: WalletRead) -> WaitingOut | None:
    """The empty state, published only when it is true."""
    state = read.waiting_for
    if state is None:
        return None
    return WaitingOut(
        message=state.message,
        idle_cash=state.idle_cash,
        considered=state.considered,
        refusals=state.refusals,
        # Prose from stable codes, rendered server-side. The client never
        # composes a sentence out of a reason code.
        labels={
            code: eligibility.REFUSAL_LABELS[code]
            for code in state.refusals
            if code in eligibility.REFUSAL_LABELS
        },
    )


def _last_trade(read: WalletRead) -> LastTradeOut | None:
    """The most recent action, whichever kind it was.

    Opens count, not only closes. A wallet that deployed its last dollar an hour
    ago did something; reporting only exits would show it as idle since its last
    close, which on a fully-invested book could be never.
    """
    latest: LastTradeOut | None = None
    at: datetime | None = None

    for row in read.positions:
        _, symbol = read.names.get(row.mint_address, (None, None))
        if row.closed_at is not None and (at is None or row.closed_at > at):
            at = row.closed_at
            latest = LastTradeOut(
                action="closed",
                mint_address=row.mint_address,
                symbol=symbol,
                at=row.closed_at,
                price_usd=row.exit_price,
                exit_reason=row.exit_reason,
                pnl_usd=(
                    None
                    if row.exit_price is None
                    else (row.quantity * row.exit_price - row.size_usd).quantize(
                        Decimal("0.01")
                    )
                ),
            )
        if at is None or row.opened_at > at:
            at = row.opened_at
            latest = LastTradeOut(
                action="opened",
                mint_address=row.mint_address,
                symbol=symbol,
                at=row.opened_at,
                price_usd=row.entry_price,
            )

    return latest


def _to_audit_entry(row: PaperTradeAudit) -> AuditEntryOut:
    hold = (row.exit_at - row.entry_at).total_seconds() / 3600
    return AuditEntryOut(
        mint_address=row.mint_address,
        symbol=row.symbol,
        entry_at=row.entry_at,
        entry_price=row.entry_price,
        entry_market_cap=row.entry_market_cap,
        entry_liquidity_usd=row.entry_liquidity_usd,
        size_usd=row.size_usd,
        quantity=row.quantity,
        exit_at=row.exit_at,
        exit_price=row.exit_price,
        exit_market_cap=row.exit_market_cap,
        exit_liquidity_usd=row.exit_liquidity_usd,
        gross_return_usd=row.gross_return_usd,
        gross_return_pct=row.gross_return_pct,
        fee_usd=row.fee_usd,
        slippage_usd=row.slippage_usd,
        net_return_usd=row.net_return_usd,
        net_return_pct=row.net_return_pct,
        cost_unavailable_reason=row.cost_unavailable_reason,
        exit_reason=row.exit_reason,
        strategy_id=row.strategy_id,
        strategy_version=row.strategy_version,
        wallet_generation=row.wallet_generation,
        hold_hours=Decimal(str(hold)).quantize(Decimal("0.01")),
    )


# --- Strategy Lab -------------------------------------------------------------

ENTRY_DIVERGENCE_NOTE = (
    "The lab enters every detection at its **detection price**. The live wallet "
    "enters when a token first reaches the Radar's top 10 — typically hours "
    "later, and after the move that put it there. The lab's entries are "
    "therefore systematically cheaper, in one direction, so its returns are "
    "optimistic relative to anything the wallet could have achieved. The two "
    "figures answer different questions and must not be compared directly.\n\n"
    "The lab does not replay the wallet's entry rule because it cannot: the "
    "Radar sweep rotates through buckets, so `radar_snapshots` holds a slice of "
    "the universe per sweep rather than the full ranking, and historical top-10 "
    "membership is not reconstructible from stored data. Publishing the gap is "
    "honest; modelling it with a proxy would not be."
)

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
    divergence = await measure_entry_divergence(session, dataset)
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
        entry_divergence=EntryDivergenceOut(
            positions=divergence.positions,
            median_ratio=divergence.median_ratio,
            worst_ratio=divergence.worst_ratio,
            wallet_paid_more=divergence.wallet_paid_more,
            median_lag_hours=divergence.median_lag_hours,
            explanation=ENTRY_DIVERGENCE_NOTE,
        ),
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
