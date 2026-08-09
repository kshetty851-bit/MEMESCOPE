"""`/api/v1/paper` — the wallet, its positions, its record, and its archive.

Manual writes are limited to paper-only exits. There is still no manual entry
and no real execution path: a user may close an open simulated position at the
latest observed market quote, and that override is recorded as `manual` so it
never contaminates automated V1 evidence.

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

from dataclasses import asdict
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import DbSession
from app.core.config import settings
from app.models.paper import PaperPosition, PaperTradeAudit
from app.paper import audit, benchmark, cadence, costs, eligibility, lab
from app.paper.lab_service import load_dataset, replay_all
from app.paper.metrics import WalletMetrics
from app.paper.models import PositionStatus
from app.paper.repository import PaperRepository
from app.paper.schemas import (
    ArchivedWalletOut,
    ArchiveOut,
    AuditEntryOut,
    AuditOut,
    BenchmarkOut,
    EquityPointOut,
    ExecutionModelPerformanceOut,
    LabDataIntegrityOut,
    LabFindingOut,
    LabOut,
    LabRuleOut,
    LabStrategyOut,
    LabTokensOut,
    LastTradeOut,
    ManualSellOut,
    ManualSellPreviewOut,
    MetricsOut,
    PatternAnalysisOut,
    PositionOut,
    PositionsOut,
    RecommendationOut,
    RejectedIdeaOut,
    RuleOut,
    SegmentRowOut,
    StrategiesOut,
    StrategyOut,
    TokenComparisonOut,
    TradeCardOut,
    WaitingOut,
    WalletOut,
)
from app.paper.service import (
    ManualSellOutcome,
    ManualSellPreview,
    PaperWalletService,
    WalletRead,
)
from app.paper.shadow import ShadowPaperService
from app.paper.strategy import AnyStrategy, registry
from app.repositories.token import TokenRepository

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


@router.get(
    "/positions/{mint_address}/manual-sell",
    response_model=ManualSellPreviewOut,
    summary="Preview a paper-only manual close",
)
async def preview_manual_sell(mint_address: str, session: DbSession) -> ManualSellPreviewOut:
    """Show the exact observed quote and cost model a manual close would use."""
    now = datetime.now(UTC)
    preview = await PaperWalletService(session).manual_sell_preview(mint_address, now=now)
    return _to_manual_preview(preview)


@router.post(
    "/positions/{mint_address}/manual-sell",
    response_model=ManualSellOut,
    summary="Close one open paper position manually",
)
async def manual_sell(mint_address: str, session: DbSession) -> ManualSellOut:
    """Paper-only: no wallet, order, chain transaction or strategy change."""
    now = datetime.now(UTC)
    outcome = await PaperWalletService(session).manual_sell(mint_address, now=now)
    return _to_manual_sell(outcome)


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
    tokens = await TokenRepository(session).get_many_by_mints(
        [row.mint_address for row in rows]
    )
    return AuditOut(
        items=[
            _to_audit_entry(
                row,
                image_url=(
                    tokens[row.mint_address].image_url if row.mint_address in tokens else None
                ),
            )
            for row in rows
        ],
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


@router.get("/strategy-intelligence", summary="Shadow wallet strategy intelligence")
async def get_strategy_intelligence(session: DbSession) -> dict[str, object]:
    """V2-V5 live shadow candidates, isolated from the published V1 wallet."""
    now = datetime.now(UTC)
    if not settings.FEATURE_PAPER_WALLET_ENABLED:
        return {
            "enabled": False,
            "observed_at": now,
            "promotion_rules": {
                "minimum_completed_trades": 100,
                "minimum_profit_factor": "1.20",
                "requires_positive_net_return": True,
                "requires_positive_expectancy": True,
            },
            "wallets": [],
            "missed_opportunities": [],
            "filter_performance": [],
        }
    return await ShadowPaperService(session).intelligence(now=now)


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
        image_url=read.images.get(row.mint_address),
        status=row.status,
        opened_at=row.opened_at,
        entry_rank=row.entry_rank,
        entry_price=row.entry_price,
        entry_observed_price=row.entry_observed_price,
        size_usd=row.size_usd,
        quantity=row.quantity,
        entry_execution_model_version=row.entry_execution_model_version,
        entry_execution_price_impact_pct=row.entry_execution_price_impact_pct,
        entry_execution_fee_usd=row.entry_execution_fee_usd,
        entry_execution_route=row.entry_execution_route,
        entry_execution_quoted_at=row.entry_execution_quoted_at,
        entry_execution_confidence=row.entry_execution_confidence,
        entry_execution_fallback_reason=row.entry_execution_fallback_reason,
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
        exit_observed_price=row.exit_observed_price,
        exit_execution_model_version=row.exit_execution_model_version,
        exit_execution_price_impact_pct=row.exit_execution_price_impact_pct,
        exit_execution_fee_usd=row.exit_execution_fee_usd,
        exit_execution_route=row.exit_execution_route,
        exit_execution_quoted_at=row.exit_execution_quoted_at,
        exit_execution_confidence=row.exit_execution_confidence,
        exit_execution_fallback_reason=row.exit_execution_fallback_reason,
        exit_reason=row.exit_reason,
        manual_action_at=row.manual_action_at,
        pnl_usd=pnl,
    )


def _short_mint(mint_address: str) -> str:
    if len(mint_address) <= 12:
        return mint_address
    return f"{mint_address[:4]}...{mint_address[-4:]}"


def _to_manual_preview(preview: ManualSellPreview) -> ManualSellPreviewOut:
    record = preview.audit
    return ManualSellPreviewOut(
        mint_address=preview.position.mint_address,
        name=preview.name,
        symbol=preview.symbol,
        image_url=preview.image_url,
        short_mint=_short_mint(preview.position.mint_address),
        entry_price=preview.position.entry_price,
        entry_observed_price=preview.position.entry_observed_price,
        latest_price=record.exit_price,
        quote_observed_at=preview.quote.captured_at,
        quote_age_seconds=preview.quote_age_seconds,
        is_stale=preview.is_stale,
        warning=preview.warning,
        entry_market_cap=preview.position.entry_market_cap,
        current_market_cap=preview.quote.market_cap,
        liquidity_usd=preview.quote.liquidity_usd,
        gross_return_usd=record.gross_return_usd,
        gross_return_pct=record.gross_return_pct,
        fee_usd=record.fee_usd,
        slippage_usd=record.slippage_usd,
        net_return_usd=record.net_return_usd,
        net_return_pct=record.net_return_pct,
        cost_unavailable_reason=record.cost_unavailable_reason,
        execution_model_version=record.execution_model_version,
        exit_execution_price_impact_pct=record.exit_execution_price_impact_pct,
        exit_execution_fee_usd=record.exit_execution_fee_usd,
        exit_execution_route=record.exit_execution_route,
        exit_execution_quoted_at=record.exit_execution_quoted_at,
        execution_confidence=record.execution_confidence,
        execution_fallback_reason=record.execution_fallback_reason,
    )


def _to_manual_sell(outcome: ManualSellOutcome) -> ManualSellOut:
    return ManualSellOut(
        closed=True,
        preview=_to_manual_preview(outcome.preview),
        audited=outcome.audited,
        opened=outcome.opened,
        candidates=outcome.candidates,
        candidates_truncated=outcome.candidates_truncated,
        refusals=outcome.refusals,
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
        reason=state.reason,
        message=state.message,
        idle_cash=state.idle_cash,
        trade_size=state.trade_size,
        shortfall=state.shortfall,
        considered=state.considered,
        eligible=state.eligible,
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
                image_url=read.images.get(row.mint_address),
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
                image_url=read.images.get(row.mint_address),
                at=row.opened_at,
                price_usd=row.entry_price,
            )

    return latest


def _to_audit_entry(row: PaperTradeAudit, *, image_url: str | None = None) -> AuditEntryOut:
    hold = (row.exit_at - row.entry_at).total_seconds() / 3600
    return AuditEntryOut(
        mint_address=row.mint_address,
        symbol=row.symbol,
        image_url=image_url,
        entry_at=row.entry_at,
        entry_price=row.entry_price,
        entry_observed_price=row.entry_observed_price,
        entry_market_cap=row.entry_market_cap,
        entry_liquidity_usd=row.entry_liquidity_usd,
        size_usd=row.size_usd,
        quantity=row.quantity,
        exit_at=row.exit_at,
        exit_price=row.exit_price,
        exit_observed_price=row.exit_observed_price,
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
        manual_action_at=row.manual_action_at,
        strategy_id=row.strategy_id,
        strategy_version=row.strategy_version,
        wallet_generation=row.wallet_generation,
        hold_hours=Decimal(str(hold)).quantize(Decimal("0.01")),
        execution_model_version=row.execution_model_version,
        entry_execution_model_version=row.entry_execution_model_version,
        exit_execution_model_version=row.exit_execution_model_version,
        entry_execution_price_impact_pct=row.entry_execution_price_impact_pct,
        exit_execution_price_impact_pct=row.exit_execution_price_impact_pct,
        entry_execution_fee_usd=row.entry_execution_fee_usd,
        exit_execution_fee_usd=row.exit_execution_fee_usd,
        entry_execution_route=row.entry_execution_route,
        exit_execution_route=row.exit_execution_route,
        entry_execution_quoted_at=row.entry_execution_quoted_at,
        exit_execution_quoted_at=row.exit_execution_quoted_at,
        execution_confidence=row.execution_confidence,
        execution_fallback_reason=row.execution_fallback_reason,
    )


# --- Strategy Lab -------------------------------------------------------------

METHODOLOGY = (
    "Strategy Lab V2 is scoped to Generation 2 only: the live "
    "`trailing_stop_25_v1` paper-wallet entries. Generation 1 is archived and "
    "excluded from optimisation metrics. Alternate exits are reconstructed from "
    "chronological market snapshots rather than stored trigger-level exit "
    "prices. Production trading behaviour is not changed by this page."
)


@router.get("/lab", response_model=LabOut, summary="Strategy Lab")
async def get_lab(session: DbSession) -> LabOut:
    now = datetime.now(UTC)
    dataset = await load_dataset(session, now=now)
    results = replay_all(dataset)
    baseline = next(item for item in results if item.id == lab.BASELINE_ID)
    baseline_net = baseline.net_return_pct
    first_open = min((entry.opened_at for entry in dataset.entries), default=None)
    last_quote = max(
        (quote.at for entry in dataset.entries for quote in entry.quotes),
        default=None,
    )
    decision_code, decision = lab.final_decision(results)

    return LabOut(
        strategies=[_to_lab_strategy(item, baseline_net=baseline_net) for item in results],
        unavailable=[],
        findings=_findings(results),
        baseline_id=lab.BASELINE_ID,
        data_integrity=LabDataIntegrityOut(**asdict(dataset.integrity)),
        execution_models=[
            ExecutionModelPerformanceOut(**asdict(row)) for row in dataset.execution_models
        ],
        production_summary=_to_lab_strategy(baseline, baseline_net=baseline_net),
        pattern_analysis=PatternAnalysisOut(
            entry_market_cap=[
                SegmentRowOut(**asdict(row))
                for row in lab.segment(dataset.entries, lab.market_cap_band)
            ],
            liquidity=[
                SegmentRowOut(**asdict(row))
                for row in lab.segment(dataset.entries, lab.liquidity_band)
            ],
            radar_score=[
                SegmentRowOut(**asdict(row))
                for row in lab.segment(dataset.entries, lab.score_band)
            ],
            age=[
                SegmentRowOut(**asdict(row))
                for row in lab.segment(dataset.entries, lab.age_band)
            ],
            holding_time=[
                SegmentRowOut(**asdict(row))
                for row in lab.segment_baseline_trades(dataset.entries, lab.holding_band)
            ],
        ),
        largest_winners=[
            TradeCardOut(**asdict(row))
            for row in lab.largest_cards(dataset.entries, winners=True)
        ],
        largest_losers=[
            TradeCardOut(**asdict(row))
            for row in lab.largest_cards(dataset.entries, winners=False)
        ],
        suggestions=[RecommendationOut(**asdict(row)) for row in lab.recommendations(results)],
        rejected_ideas=[RejectedIdeaOut(**asdict(row)) for row in lab.rejected_ideas(results)],
        final_decision_code=decision_code,
        final_decision=decision,
        detections=len(dataset.entries),
        unpriced_detections=sum(1 for entry in dataset.entries if not entry.quotes),
        observed_days=(
            None
            if first_open is None or last_quote is None
            else (
                Decimal((last_quote - first_open).total_seconds()) / Decimal(86_400)
            ).quantize(Decimal("0.1"))
        ),
        methodology=METHODOLOGY,
        cost_disclosure=costs.DISCLOSURE,
        cost_rules=[
            LabRuleOut(
                label="Swap fee",
                value=f"{costs.DEFAULT.swap_fee_bps} bps per side on legacy rows",
            ),
            LabRuleOut(
                label="Price impact",
                value="Constant product against the pool depth observed at each end",
            ),
            LabRuleOut(
                label="Jupiter execution",
                value=(
                    "Future rows store the quote route, impact and estimated "
                    "USDC received at decision time; historical rows are not re-quoted"
                ),
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
            for item in lab.replay_tokens(results, limit=limit)
        ],
        strategy_ids=[strategy.id for strategy in lab.STRATEGIES],
        observed_at=now,
    )


def _to_lab_strategy(
    result: lab.StrategyResult,
    *,
    baseline_net: Decimal | None,
) -> LabStrategyOut:
    difference: Decimal | None = None
    if (
        not result.is_baseline
        and baseline_net is not None
        and result.net_return_pct is not None
    ):
        difference = (result.net_return_pct - baseline_net).quantize(Decimal("0.01"))

    return LabStrategyOut(
        id=result.id,
        name=result.name,
        description=result.description,
        rules=[LabRuleOut(label=label, value=value) for label, value in result.rules],
        is_baseline=result.is_baseline,
        invested=result.invested,
        total_return_pct=result.total_return_pct,
        realised_return_pct=result.realised_return_pct,
        open_share_pct=(
            None
            if result.closed_count + result.open_count == 0
            else (
                Decimal(result.open_count)
                / Decimal(result.closed_count + result.open_count)
                * Decimal(100)
            ).quantize(Decimal("0.01"))
        ),
        net_return_pct=result.net_return_pct,
        cost_drag_pct=result.cost_drag_pct,
        costed_trades=result.costed_trades,
        uncosted_trades=result.uncosted_trades,
        baseline_difference_pct=difference,
        annualised_return_pct=None,
        annualised_unavailable_reason=(
            "Not shown: the Generation 2 dataset is too short to annualise honestly."
        ),
        closed_count=result.closed_count,
        open_count=result.open_count,
        win_rate_pct=result.win_rate_pct,
        profit_factor=result.profit_factor,
        expectancy=result.expectancy,
        average_win=result.average_winner,
        average_loss=result.average_loser,
        average_winner=result.average_winner,
        average_loser=result.average_loser,
        largest_winner=result.largest_winner,
        largest_loser=result.largest_loser,
        max_drawdown_pct=result.max_drawdown_pct,
        average_hold_hours=result.average_hold_hours,
        average_peak_pct=result.average_peak_pct,
        average_capture_pct=result.average_capture_pct,
        average_giveback_pct=result.average_giveback_pct,
        fees_usd=result.fees_usd,
        slippage_usd=result.slippage_usd,
        average_slippage_usd=result.average_slippage_usd,
        capital_utilization_pct=result.capital_utilization_pct,
        exits_by_reason=result.exits_by_reason,
        rank=result.rank,
        equity_curve=[
            EquityPointOut(at=point.at, equity=point.equity, drawdown_pct=point.drawdown_pct)
            for point in result.equity_curve
        ],
        return_distribution=[
            value
            for value in (trade.gross_return_pct for trade in result.trades)
            if value is not None
        ],
        hold_distribution=[
            value
            for value in (trade.hold_hours for trade in result.trades)
            if value is not None
        ],
    )


def _findings(results: tuple[lab.StrategyResult, ...]) -> list[LabFindingOut]:
    findings: list[LabFindingOut] = []
    if not results:
        return findings
    best = results[0]
    baseline = next(item for item in results if item.id == lab.BASELINE_ID)
    findings.append(
        LabFindingOut(
            headline=f"Best net replay: {best.name}",
            detail=(
                f"Ranked by net return, profit factor, drawdown, and expectancy. "
                f"Net return {best.net_return_pct}%, profit factor {best.profit_factor}, "
                f"drawdown {best.max_drawdown_pct}% over {best.closed_count} closed exits."
            ),
            strategy_id=best.id,
        )
    )
    findings.append(
        LabFindingOut(
            headline=f"Production baseline rank: {baseline.rank} of {len(results)}",
            detail=(
                f"Trailing Stop 25% V1 nets {baseline.net_return_pct}% with "
                f"{baseline.win_rate_pct}% win rate and {baseline.expectancy} expectancy. "
                "Manual exits are permanently distinguishable and Generation 1 is excluded."
            ),
            strategy_id=baseline.id,
        )
    )
    costly = max(results, key=lambda item: abs(item.cost_drag_pct or Decimal(0)))
    findings.append(
        LabFindingOut(
            headline="Execution cost remains part of the result",
            detail=(
                f"The largest measured cost drag is {costly.cost_drag_pct}% on "
                f"{costly.name}. Net figures use the existing fee and AMM impact model."
            ),
            strategy_id=costly.id,
        )
    )
    return findings
