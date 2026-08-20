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

from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import select

from app.api.deps import DbSession
from app.core.config import settings
from app.models.paper import PaperPosition, PaperTradeAudit
from app.models.paper_research import PaperDecisionSnapshot
from app.paper import audit, benchmark, cadence, eligibility
from app.paper.metrics import WalletMetrics
from app.paper.models import PositionStatus
from app.paper.performance import daily_returns
from app.paper.repository import PaperRepository
from app.paper.schemas import (
    ArchivedWalletOut,
    ArchiveOut,
    AuditEntryOut,
    AuditOut,
    BenchmarkOut,
    DailyReturnOut,
    LastTradeOut,
    LineageOut,
    ManualSellOut,
    ManualSellPreviewOut,
    MetricsOut,
    PerformanceOut,
    PositionOut,
    PositionsOut,
    RuleOut,
    StrategiesOut,
    StrategyOut,
    WaitingOut,
    WalletContextOut,
    WalletOut,
)
from app.paper.service import (
    ManualSellOutcome,
    ManualSellPreview,
    PaperWalletService,
    WalletRead,
)
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

    Retired strategies remain resolvable for archived-wallet records but are
    deliberately not surfaced as selectable/current paper strategies.  The
    product has one active forward experiment, not a menu of stale variants.
    """
    active = _active_strategy()
    return StrategiesOut(
        items=[_to_strategy(active, active_id=active.id)],
        active_id=active.id,
    )


@router.get("/positions", response_model=PositionsOut, summary="Every simulated trade")
async def list_positions(session: DbSession) -> PositionsOut:
    """Open and closed together, newest first. Losers are never filtered out."""
    now = datetime.now(UTC)
    if not settings.FEATURE_PAPER_WALLET_ENABLED:
        return PositionsOut(items=[], enabled=False, observed_at=now)

    read = await PaperWalletService(session).read(now=now)
    audits_by_position_id = await PaperRepository(session).audits_for_position_ids(
        [
            row.id
            for row in read.positions
            if row.status == PositionStatus.CLOSED.value
        ]
    )
    return PositionsOut(
        items=[
            _to_position(row, read, audit_row=audits_by_position_id.get(row.id))
            for row in read.positions
        ],
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


@router.get(
    "/performance",
    response_model=PerformanceOut,
    summary="Completed-trade returns by day",
)
async def get_performance(session: DbSession) -> PerformanceOut:
    """Date-by-date returns from the append-only completed-trade record.

    This intentionally does not group open-position marks into a day. Current
    portfolio return belongs to the wallet summary and remains unknown whenever
    a holding has no fresh price; a historical day is a closed-trade record.
    """
    now = datetime.now(UTC)
    if not settings.FEATURE_PAPER_WALLET_ENABLED:
        return PerformanceOut(
            enabled=False,
            daily=[],
            disclosure=audit.DISCLOSURE,
            observed_at=now,
        )

    repository = PaperRepository(session)
    wallet = await repository.live_wallet()
    if wallet is None:
        return PerformanceOut(
            enabled=True,
            daily=[],
            disclosure=audit.DISCLOSURE,
            observed_at=now,
        )

    rows = await repository.audit_log(wallet.id, limit=None)
    return PerformanceOut(
        enabled=True,
        daily=[
            DailyReturnOut(
                date=row.date,
                completed_trades=row.completed_trades,
                gross_pnl_usd=row.gross_pnl_usd,
                gross_return_pct=row.gross_return_pct,
                net_pnl_usd=row.net_pnl_usd,
                net_return_pct=row.net_return_pct,
                cost_unavailable_trades=row.cost_unavailable_trades,
            )
            for row in daily_returns(rows, starting_balance=wallet.starting_balance)
        ],
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
            pnl_today=Decimal(0),
            disclosure=DISCLOSURE,
            observed_at=now,
        )

    read = await PaperWalletService(session).read(now=now)

    return WalletOut(
        enabled=True,
        strategy=_to_strategy(read.strategy, active_id=read.strategy.id),
        metrics=_to_metrics(read.metrics),
        lineage=LineageOut(
            generations=list(read.lineage.generations),
            strategy_ids=list(read.lineage.strategy_ids),
            base_generation=read.lineage.base_generation,
            base_capital=read.lineage.base_capital,
        ),
        generation=read.wallet.generation,
        started_at=read.wallet.started_at,
        resumed_at=read.wallet.resumed_at,
        last_trade=_last_trade(read),
        next_radar_evaluation_at=cadence.next_evaluation(now),
        audited_trades=read.audit_count,
        pnl_today=read.pnl_today,
        disclosure=DISCLOSURE,
        observed_at=now,
    )


@router.get("/context", response_model=WalletContextOut, summary="Wallet expensive context")
async def get_wallet_context(
    session: DbSession,
    roi_pct: Decimal | None = Query(None, description="Wallet ROI for benchmark comparison"),
) -> WalletContextOut:
    """The expensive background context for the wallet, loaded separately."""
    now = datetime.now(UTC)

    if not settings.FEATURE_PAPER_WALLET_ENABLED:
        return WalletContextOut(
            benchmarks=[],
            benchmark_note=None,
            waiting=None,
            observed_at=now,
        )

    # We only need the context portion. We will refactor PaperWalletService
    # to only calculate what's needed for the context.
    read = await PaperWalletService(session).read_context(now=now)

    return WalletContextOut(
        benchmarks=_benchmarks(read, roi=roi_pct),
        benchmark_note=_benchmark_note(read),
        waiting=_to_waiting(read),
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
        return_usd=Decimal(0),
        open_value=Decimal(0),
        known_partial_equity=starting,
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
        return_usd=summary.return_usd,
        open_value=summary.open_value,
        invested_usd=summary.invested_usd,
        unpriced_positions=summary.unpriced_positions,
        known_partial_equity=summary.known_partial_equity,
        priced_positions=summary.priced_positions,
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


def _to_position(
    row: PaperPosition,
    read: WalletRead,
    *,
    audit_row: PaperTradeAudit | None = None,
) -> PositionOut:
    name, symbol = read.names.get(row.mint_address, (None, None))
    closed = row.status == PositionStatus.CLOSED.value

    # A closed trade is marked at its exit; an open one at the latest reading.
    # Using the live price for a closed trade would restate a finished result
    # every time the token moved, which is the opposite of a permanent record.
    current = row.exit_price if closed else read.prices.get(row.mint_address)
    current_mcap = getattr(row, "exit_market_cap", None) if closed else read.market_caps.get(row.mint_address)
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
        trailing_stop = getattr(row, "trailing_stop_price", None)
        if trailing_stop is None and getattr(row, "trailing_activated_at", None) is not None:
            trailing_stop = row.peak_price * (Decimal(1) - row.trailing_drawdown)

    from app.paper.schemas import PricingStatus
    pricing_status = PricingStatus.PRICED
    if not closed:
        if observed_at is None:
            pricing_status = PricingStatus.NO_DATA
        elif current is None:
            pricing_status = PricingStatus.UNPRICED

    return PositionOut(
        mint_address=row.mint_address,
        name=name,
        symbol=symbol,
        image_url=read.images.get(row.mint_address),
        status=row.status,
        pricing_status=pricing_status,
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
        target_price=getattr(row, "target_price", None),
        stop_price=getattr(row, "stop_price", None),
        expires_at=getattr(row, "expires_at", None),
        trailing_drawdown=row.trailing_drawdown,
        trailing_activation_multiple=getattr(row, "trailing_activation_multiple", None),
        trailing_activated_at=getattr(row, "trailing_activated_at", None),
        trailing_activation_observed_price=getattr(
            row, "trailing_activation_observed_price", None
        ),
        trailing_high_price=(
            row.peak_price if getattr(row, "trailing_activated_at", None) else None
        ),
        trailing_stop_price=trailing_stop,
        trailing_trigger_price=getattr(row, "trailing_trigger_price", None),
        trailing_trigger_observed_price=getattr(row, "trailing_trigger_observed_price", None),
        current_price=current,
        current_market_cap=current_mcap,
        current_pct=_pct_from(row.entry_price, current),
        current_price_at=observed_at,
        last_market_check_at=read.check_times.get(row.mint_address) if not closed else None,
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
        manual_action_at=getattr(row, "manual_action_at", None),
        pnl_usd=pnl,
        gross_pnl_usd=None if audit_row is None else audit_row.gross_return_usd,
        fee_usd=None if audit_row is None else audit_row.fee_usd,
        slippage_usd=None if audit_row is None else audit_row.slippage_usd,
        net_pnl_usd=None if audit_row is None else audit_row.net_return_usd,
        cost_unavailable_reason=(
            None if audit_row is None else audit_row.cost_unavailable_reason
        ),
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


def _benchmarks(read: WalletRead | WalletContextRead, roi: Decimal | None = None) -> list[BenchmarkOut]:
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
    if roi is None and isinstance(read, WalletRead):
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


def _benchmark_note(read: WalletRead | WalletContextRead) -> str | None:
    """Set only while both benchmarks hold the same set of tokens."""
    if len(read.benchmarks) < 2:
        return None
    first, second = read.benchmarks[0], read.benchmarks[1]
    if first.positions == 0 or first.positions != second.positions:
        return None
    return benchmark.COINCIDENCE_NOTE


def _to_waiting(read: WalletRead | WalletContextRead) -> WaitingOut | None:
    """The reason the wallet is doing nothing, when it is doing nothing."""
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


@router.get(
    "/decisions/{mint_address}",
    summary="Why this mint was, or was not, admitted",
)
async def decisions(
    mint_address: str,
    session: DbSession,
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
) -> dict[str, object]:
    """The engine's own per-mint verdict, read back — never recomputed.

    HQ-5 could show DECISION PASSED (a position exists) but never FAILED,
    because `judge()`'s refusals were counted in aggregate and thrown away
    per mint. This serves the rows the review pass now records at the moment
    it decides, so the reason shown is the reason the engine used.

    Nothing here re-runs an eligibility condition. A caller that wanted to
    know "would this mint qualify *now*" is asking a different question, and
    answering it here would put a second copy of §5 behind an endpoint where
    it could silently drift from the one that trades.

    Read-only, and it cannot admit anything.

    LIMITS, STATED RATHER THAN IMPLIED

    Ownership refusals (`already_traded`, `already_held`) are deliberately
    not recorded — see `PaperWalletService._capture_candidate_decisions`.
    An empty list therefore means "no non-ownership verdict on record",
    which is not the same as "never considered"; it is reported as
    UNKNOWN by every consumer rather than as a pass.
    """
    rows = (
        (
            await session.execute(
                select(PaperDecisionSnapshot)
                .where(PaperDecisionSnapshot.mint_address == mint_address)
                .order_by(PaperDecisionSnapshot.decided_at.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return {
        "mint_address": mint_address,
        "items": [
            {
                "decision": row.decision,
                "decided_at": row.decided_at,
                "source": row.decision_source,
                "wallet_code": row.wallet_code,
                "strategy_id": row.strategy_id,
                "strategy_version": row.strategy_version,
                "reason_codes": row.reason_codes,
                # Server-side prose from a stable code, as every other
                # refusal string in the platform is rendered.
                "reason_labels": [
                    eligibility.REFUSAL_LABELS.get(code, code) for code in row.reason_codes
                ],
                # SEC-2 records the entry gate's own classification here, so a
                # reader can tell "we could not check" from "this token failed"
                # without re-deriving it from reason codes.
                "entry_outcome": (row.availability or {}).get("outcome"),
                "security_status": (row.availability or {}).get("security_status"),
                "security_evaluated_at": (row.availability or {}).get("evaluated_at"),
                "security_evaluator_version": (row.availability or {}).get(
                    "evaluator_version"
                ),
            }
            for row in rows
        ],
    }
