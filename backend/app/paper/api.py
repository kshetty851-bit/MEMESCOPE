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

from fastapi import APIRouter

from app.api.deps import DbSession
from app.core.config import settings
from app.models.paper import PaperPosition
from app.paper.metrics import WalletMetrics
from app.paper.models import PositionStatus
from app.paper.schemas import (
    BenchmarkOut,
    MetricsOut,
    PositionOut,
    PositionsOut,
    RuleOut,
    StrategiesOut,
    StrategyOut,
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
