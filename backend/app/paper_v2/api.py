"""Paper Wallet V2's read model. **Its own endpoint, never V1's.**

A separate route rather than a `?variant=v2` parameter on the existing one: a
shared endpoint is one bad branch away from serving V1 numbers under a V2
heading, and this wallet exists to be compared against V1 rather than confused
with it.

Every response carries `experimental: true` and the wallet's mode, so a reader
can never mistake a disabled experiment's empty book for a strategy that simply
has not traded today.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.paper_v2 import ladder
from app.paper_v2.service import (
    STRATEGY_ID,
    STRATEGY_NAME,
    STRATEGY_SUMMARY,
    STRATEGY_VERSION,
    PaperV2Service,
)
from app.repositories.market import MarketSnapshotRepository

router = APIRouter(prefix="/paper-v2", tags=["paper-v2"])


class V2Rung(BaseModel):
    multiple: Decimal
    fraction: Decimal


class V2Strategy(BaseModel):
    id: str
    name: str
    version: str
    summary: str
    rungs: list[V2Rung]
    runner_fraction: Decimal
    hold_hours: int
    trade_size_usd: Decimal | None
    stop_loss: None = None


class V2Metrics(BaseModel):
    starting_balance: Decimal | None = None
    cash: Decimal | None = None
    equity: Decimal | None = None
    open_value: Decimal | None = None
    capital_allocated: Decimal | None = None
    realised_pnl: Decimal | None = None
    unrealised_pnl: Decimal | None = None
    return_usd: Decimal | None = None
    roi_pct: Decimal | None = None
    open_positions: int = 0
    closed_positions: int = 0
    unpriced_positions: int = 0
    win_rate_pct: Decimal | None = None
    profit_factor: Decimal | None = None
    max_drawdown_pct: Decimal | None = None
    capital_utilisation_pct: Decimal | None = None


class V2Fill(BaseModel):
    rung_index: int | None
    reason: str
    filled_at: datetime
    quantity: Decimal
    execution_price: Decimal
    observed_price: Decimal
    gross_proceeds: Decimal
    net_proceeds: Decimal
    fee_usd: Decimal | None
    impact_usd: Decimal | None


class V2Position(BaseModel):
    mint_address: str
    status: str
    opened_at: datetime
    expires_at: datetime
    seconds_to_expiry: int | None
    entry_price: Decimal
    current_price: Decimal | None
    current_multiple: Decimal | None
    initial_notional: Decimal
    initial_quantity: Decimal
    remaining_quantity: Decimal
    remaining_pct: Decimal
    position_value: Decimal | None
    realised_proceeds: Decimal
    unrealised_pnl: Decimal | None
    target_status: list[str]
    runner_pct: Decimal
    final_exit_reason: str | None
    fills: list[V2Fill]


class V2Wallet(BaseModel):
    experimental: bool = True
    mode: str
    started: bool
    strategy: V2Strategy
    metrics: V2Metrics
    positions: list[V2Position]
    disclosure: str
    observed_at: datetime


DISCLOSURE = (
    "Experimental. Paper Wallet V2 is a separate simulation with its own $1,000 "
    "of new simulated capital. It shares no cash, no positions and no history "
    "with the original Paper Wallet. Simulated: no wallet is connected, no "
    "order is placed and no transaction is made."
)


def _strategy(trade_size: Decimal | None) -> V2Strategy:
    rules = ladder.PRIMARY
    return V2Strategy(
        id=STRATEGY_ID,
        name=STRATEGY_NAME,
        version=STRATEGY_VERSION,
        summary=STRATEGY_SUMMARY,
        rungs=[V2Rung(multiple=r.multiple, fraction=r.fraction) for r in rules.rungs],
        runner_fraction=rules.runner_fraction,
        hold_hours=int(rules.hold_for.total_seconds() // 3600),
        trade_size_usd=trade_size,
    )


@router.get("", response_model=V2Wallet, summary="Paper Wallet V2 (experimental)")
async def read_v2(session: AsyncSession = Depends(get_db)) -> V2Wallet:
    now = datetime.now(timezone.utc)
    service = PaperV2Service(session)
    wallet = await service.live_wallet()

    if wallet is None:
        # Disabled, or enabled but never reviewed. Either way it holds nothing,
        # and saying so is more honest than rendering a $1,000 that does not exist.
        return V2Wallet(
            mode=service.mode,
            started=False,
            strategy=_strategy(None),
            metrics=V2Metrics(),
            positions=[],
            disclosure=DISCLOSURE,
            observed_at=now,
        )

    open_rows = await service.open_positions(wallet.id)
    closed_rows = await service.closed_positions(wallet.id)
    fills = await service.fills_for([r.id for r in (*open_rows, *closed_rows)])

    marks = await MarketSnapshotRepository(session).latest_for_mints(
        [r.mint_address for r in open_rows]
    )
    prices: dict[str, Decimal | None] = {
        r.mint_address: (
            marks[r.mint_address].price_usd if r.mint_address in marks else None
        )
        for r in open_rows
    }
    summary = await service.summarise(wallet, prices=prices)
    rungs = ladder.PRIMARY.rungs

    out: list[V2Position] = []
    for row in (*open_rows, *closed_rows):
        row_fills = fills.get(row.id, [])
        done = {f.rung_index for f in row_fills if f.rung_index is not None}
        price = prices.get(row.mint_address) if row.status == "open" else None
        value = row.remaining_quantity * price if price is not None else None
        realised = sum((f.net_proceeds for f in row_fills), Decimal(0))
        basis_left = (
            row.initial_notional * (row.remaining_quantity / row.initial_quantity)
            if row.initial_quantity > 0
            else Decimal(0)
        )
        out.append(
            V2Position(
                mint_address=row.mint_address,
                status=row.status,
                opened_at=row.opened_at,
                expires_at=row.expires_at,
                seconds_to_expiry=(
                    max(0, int((row.expires_at - now).total_seconds()))
                    if row.status == "open"
                    else None
                ),
                entry_price=row.entry_price,
                current_price=price,
                current_multiple=(price / row.entry_price if price else None),
                initial_notional=row.initial_notional,
                initial_quantity=row.initial_quantity,
                remaining_quantity=row.remaining_quantity,
                remaining_pct=(
                    row.remaining_quantity / row.initial_quantity * 100
                    if row.initial_quantity > 0
                    else Decimal(0)
                ),
                position_value=value,
                realised_proceeds=realised,
                unrealised_pnl=(value - basis_left if value is not None else None),
                target_status=[
                    ("filled" if i in done else "pending") for i in range(len(rungs))
                ],
                runner_pct=ladder.PRIMARY.runner_fraction * 100,
                final_exit_reason=row.final_exit_reason,
                fills=[
                    V2Fill(
                        rung_index=f.rung_index,
                        reason=f.reason,
                        filled_at=f.filled_at,
                        quantity=f.quantity,
                        execution_price=f.execution_price,
                        observed_price=f.observed_price,
                        gross_proceeds=f.gross_proceeds,
                        net_proceeds=f.net_proceeds,
                        fee_usd=f.fee_usd,
                        impact_usd=f.impact_usd,
                    )
                    for f in row_fills
                ],
            )
        )

    return V2Wallet(
        mode=service.mode,
        started=True,
        strategy=_strategy(wallet.trade_size_usd),
        metrics=V2Metrics(**vars(summary)),
        positions=out,
        disclosure=DISCLOSURE,
        observed_at=now,
    )
