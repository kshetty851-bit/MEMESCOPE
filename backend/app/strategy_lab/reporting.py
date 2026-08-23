"""Reads persisted books back into `replay.Result`, so metrics has one input.

Both modes store the same shape, so both are reconstructed by the same
function and read by the same `metrics.row`. A separate metric path for the
forward record would be a second implementation of the leaderboard, and the two
would eventually disagree about which one was right.

The reconstruction is faithful in everything the metrics read. The one thing it
does *not* rebuild is the mark-to-market equity curve, which needs a price for
every open position at every instant and is therefore stored on the wallet when
it is computed. `Result.equity_curve` is populated from that stored curve, and
`peak_equity` / `max_drawdown_pct` are maintained as exact running scalars so
the ranking never depends on how much of the curve was kept for the chart.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.strategy_lab import (
    StrategyLabFill,
    StrategyLabOpportunity,
    StrategyLabPosition,
    StrategyLabRefusal,
    StrategyLabRun,
    StrategyLabWallet,
)
from app.strategy_lab import metrics, replay
from app.strategy_lab.rules import Fill, FillReason
from app.strategy_lab.state import LabState
from app.strategy_lab.strategies import BY_ID

_ZERO = Decimal(0)

#: How much of the equity curve is kept for the chart. Six weeks of 15-minute
#: samples. Trimming costs a pixel and never a metric — see the module note.
EQUITY_CURVE_POINTS = 4000


@dataclass(frozen=True, slots=True)
class Book:
    """One wallet's reconstructed result, plus what only the DB knows."""

    wallet: StrategyLabWallet
    result: replay.Result
    row: metrics.Row


def _to_fill(record: StrategyLabFill) -> Fill:
    return Fill(
        at=record.filled_at,
        price_usd=record.price_usd,
        quantity=record.quantity,
        reason=FillReason(record.reason),
        liquidity_usd=record.liquidity_usd,
        rung_indexes=tuple(record.rung_indexes or ()),
        trigger_price=record.trigger_price,
    )


async def load_books(
    session: AsyncSession,
    *,
    mode: str,
    run_id: uuid.UUID | None = None,
    since: datetime | None = None,
) -> list[Book]:
    """Every strategy's book for one mode, ranked-ready.

    `since` filters positions by `opened_at` for the leaderboard windows. A
    window is a filter on the trade set, not a re-simulation — see
    `api.leaderboard`, which states that where a reader will see it.
    """
    query = select(StrategyLabWallet).where(StrategyLabWallet.mode == mode)
    if run_id is not None:
        query = query.where(StrategyLabWallet.run_id == run_id)
    wallets = list((await session.execute(query)).scalars().all())
    if not wallets:
        return []

    wallet_ids = [w.id for w in wallets]

    position_query = select(StrategyLabPosition).where(
        StrategyLabPosition.wallet_id.in_(wallet_ids)
    )
    if since is not None:
        position_query = position_query.where(StrategyLabPosition.opened_at >= since)
    positions = list((await session.execute(position_query)).scalars().all())

    fills_by_position: dict[uuid.UUID, list[StrategyLabFill]] = {}
    if positions:
        records = (
            await session.execute(
                select(StrategyLabFill)
                .where(StrategyLabFill.position_id.in_([p.id for p in positions]))
                .order_by(StrategyLabFill.position_id, StrategyLabFill.sequence)
            )
        ).scalars()
        for record in records:
            fills_by_position.setdefault(record.position_id, []).append(record)

    refusal_query = select(StrategyLabRefusal).where(
        StrategyLabRefusal.wallet_id.in_(wallet_ids)
    )
    if since is not None:
        refusal_query = refusal_query.where(StrategyLabRefusal.refused_at >= since)
    refusals = list((await session.execute(refusal_query)).scalars().all())

    by_wallet_positions: dict[uuid.UUID, list[StrategyLabPosition]] = {}
    for position in positions:
        by_wallet_positions.setdefault(position.wallet_id, []).append(position)
    by_wallet_refusals: dict[uuid.UUID, list[StrategyLabRefusal]] = {}
    for refusal in refusals:
        by_wallet_refusals.setdefault(refusal.wallet_id, []).append(refusal)

    books: list[Book] = []
    for wallet in wallets:
        definition = BY_ID.get(wallet.strategy_id)
        result = _rebuild(
            wallet,
            by_wallet_positions.get(wallet.id, []),
            fills_by_position,
            by_wallet_refusals.get(wallet.id, []),
            windowed=since is not None,
        )
        books.append(
            Book(
                wallet=wallet,
                result=result,
                row=metrics.row(
                    result,
                    name=definition.name if definition else wallet.strategy_id,
                    benchmark=definition.benchmark if definition else False,
                ),
            )
        )
    return books


def _rebuild(
    wallet: StrategyLabWallet,
    records: Sequence[StrategyLabPosition],
    fills_by_position: dict[uuid.UUID, list[StrategyLabFill]],
    refusals: Sequence[StrategyLabRefusal],
    *,
    windowed: bool,
) -> replay.Result:
    positions: list[replay.Position] = []
    for record in sorted(records, key=lambda r: r.opened_at):
        position = replay.Position(
            mint_address=record.mint_address,
            source_decision_id=str(record.opportunity_id),
            opened_at=record.opened_at,
            entry_price=record.entry_price,
            size_usd=record.size_usd,
            initial_quantity=record.initial_quantity,
            entry_cost=record.entry_cost,
            entry_liquidity_usd=record.entry_liquidity_usd,
            venue=record.venue,
            pool_address=record.pool_address,
            discovery_age_seconds=None,
        )
        position.observed_peak_multiple = record.observed_peak_multiple or _ZERO
        position.executable_peak_multiple = record.executable_peak_multiple or _ZERO
        position.terminal_multiple = record.terminal_multiple
        position.batch_rung_fills = record.batch_rung_fills
        position.unsettled = record.unsettled
        for fill in fills_by_position.get(record.id, []):
            position.fills.append((_to_fill(fill), fill.net_proceeds, fill.execution_cost))
        positions.append(position)

    missed = [
        replay.Missed(
            mint_address=r.mint_address,
            source_decision_id=str(r.opportunity_id),
            at=r.refused_at,
            reason=r.reason,
            cash_at_refusal=r.cash_at_refusal,
            peak_multiple=r.peak_multiple,
        )
        for r in refusals
    ]

    # A windowed view cannot claim the wallet's real final cash — the wallet
    # holds the whole history and the window holds part of it. Equity is
    # restated as "what this slice of trades did to a fresh $1,000", and
    # labelled as such by the API rather than passed off as a balance.
    if windowed:
        final_cash = wallet.starting_balance + sum((p.net_pnl for p in positions), _ZERO)
        curve: list[tuple[datetime, Decimal]] = []
        running = wallet.starting_balance
        for position in sorted(
            (p for p in positions if p.closed_at is not None),
            key=lambda p: p.closed_at,  # type: ignore[arg-type,return-value]
        ):
            running += position.net_pnl
            curve.append((position.closed_at, running))  # type: ignore[arg-type]
    else:
        final_cash = wallet.cash
        curve = [
            (datetime.fromisoformat(at), Decimal(str(value)))
            for at, value in (wallet.equity_curve or [])
        ]

    concurrency = _concurrency(positions)
    return replay.Result(
        strategy_id=wallet.strategy_id,
        version=wallet.version,
        definition_hash=wallet.definition_hash,
        starting_capital=wallet.starting_balance,
        entry_size_usd=wallet.entry_size_usd,
        positions=positions,
        missed=missed,
        offered=len(positions) + len(missed),
        final_cash=final_cash,
        equity_curve=curve,
        peak_concurrent=max(concurrency, default=0),
        concurrency_samples=concurrency,
    )


def _concurrency(positions: Sequence[replay.Position]) -> list[int]:
    """How many positions were open at each entry. A sweep, not a nested loop."""
    events: list[tuple[datetime, int]] = []
    for position in positions:
        events.append((position.opened_at, 1))
        if position.closed_at is not None:
            events.append((position.closed_at, -1))
    events.sort()
    samples: list[int] = []
    open_now = 0
    for _, delta in events:
        open_now += delta
        if delta == 1:
            samples.append(open_now)
    return samples


def trim_curve(
    curve: Sequence[tuple[datetime, Decimal]],
) -> list[list]:
    """Serialise a curve for storage, keeping the most recent points."""
    tail = list(curve)[-EQUITY_CURVE_POINTS:]
    return [[at.isoformat(), str(value)] for at, value in tail]


def advance_drawdown(
    *, peak: Decimal, worst_pct: Decimal, equity: Decimal
) -> tuple[Decimal, Decimal]:
    """Fold one equity reading into the running peak and worst drawdown.

    Exact and incremental, so the ranking's risk term never depends on how much
    of the chart was kept.
    """
    new_peak = max(peak, equity)
    if new_peak <= 0:
        return new_peak, worst_pct
    return new_peak, max(worst_pct, (new_peak - equity) / new_peak * 100)


async def latest_run(session: AsyncSession) -> StrategyLabRun | None:
    return (
        await session.execute(
            select(StrategyLabRun)
            .where(
                StrategyLabRun.mode == LabState.BACKTEST.value,
                StrategyLabRun.finished_at.is_not(None),
            )
            .order_by(StrategyLabRun.finished_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def opportunity_by_mint(
    session: AsyncSession, mint: str
) -> StrategyLabOpportunity | None:
    return (
        await session.execute(
            select(StrategyLabOpportunity).where(StrategyLabOpportunity.mint_address == mint)
        )
    ).scalar_one_or_none()
