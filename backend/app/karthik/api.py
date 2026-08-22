"""`/api/v1/karthik` — the Karthik wallet, its positions, and its misses.

**Read-only. Every route here is a GET.** There is no entry endpoint, no exit
endpoint and no activation endpoint: Karthik is started once by an operator
running `python -m app.karthik.activate` against the deployed backend, and every
trade after that is made by the scheduled review. An HTTP route that could
create the wallet would be a route that could create it twice, or create it at
the wrong instant, and `activated_at` is the one value in this experiment that
must never be wrong.

Before activation the wallet reports `activated: false` rather than 404ing or
serving an empty book — "not started here" and "started and traded nothing" are
different facts, and only the second is a result.

Nothing served here is advice.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter

from app.api.deps import DbSession
from app.core.config import settings
from app.karthik import rules
from app.karthik.rules import Decision, ExitReason
from app.karthik.schemas import (
    KarthikMetricsOut,
    KarthikPositionOut,
    KarthikPositionsOut,
    KarthikSkippedListOut,
    KarthikSkippedOut,
    KarthikWalletOut,
)
from app.karthik.service import KarthikService, WalletRead, utcnow
from app.models.karthik import KarthikPosition

router = APIRouter(prefix="/karthik", tags=["karthik"])

STRATEGY = "$10 per new Track Record token · Take Profit 1.25x · No Stop Loss"

DISCLOSURE = (
    "Simulated. No wallet is connected, no order is placed and no transaction is "
    "made. Karthik buys $10 of every token that enters the Track Record after it "
    "was activated, sells the whole position at 1.25x, and otherwise holds — there "
    "is no stop loss and no time exit. Nothing here is advice."
)

_MONEY = Decimal("0.01")
_MULTIPLE = Decimal("0.0001")
_PCT = Decimal("0.01")


def _money(value: Decimal | None) -> str | None:
    return None if value is None else str(value.quantize(_MONEY))


def _seconds(later: datetime | None, earlier: datetime | None) -> int | None:
    if later is None or earlier is None:
        return None
    delta = int((later - earlier).total_seconds())
    return delta if delta >= 0 else None


def _multiple(numerator: Decimal | None, denominator: Decimal) -> str | None:
    if numerator is None or denominator <= 0:
        return None
    return str((numerator / denominator).quantize(_MULTIPLE))


def _position_out(
    position: KarthikPosition, *, mark: Decimal | None, now: datetime
) -> KarthikPositionOut:
    value = None if mark is None else position.quantity * mark
    proceeds = position.exit_proceeds_usd
    return KarthikPositionOut(
        mint_address=position.mint_address,
        symbol=position.symbol,
        token_name=position.token_name,
        detected_at=position.detected_at,
        track_record_at=position.track_record_at,
        opened_at=position.opened_at,
        track_record_delay_seconds=_seconds(position.opened_at, position.track_record_at),
        detection_delay_seconds=_seconds(position.opened_at, position.detected_at),
        entry_price=str(position.entry_price),
        entry_observed_price=str(position.entry_observed_price),
        quantity=str(position.quantity),
        cost_basis=str(position.cost_basis.quantize(_MONEY)),
        decimals=position.decimals,
        target_price=str(position.target_price),
        target_multiple=str(rules.TAKE_PROFIT_MULTIPLE),
        pool_address=position.pool_address,
        entry_liquidity_usd=_money(position.entry_liquidity_usd),
        entry_market_cap=_money(position.entry_market_cap),
        entry_execution_model_version=position.entry_execution_model_version,
        entry_execution_price_impact_pct=(
            None
            if position.entry_execution_price_impact_pct is None
            else str(position.entry_execution_price_impact_pct)
        ),
        entry_execution_route=position.entry_execution_route,
        entry_execution_confidence=position.entry_execution_confidence,
        entry_execution_fallback_reason=position.entry_execution_fallback_reason,
        status=position.status,
        peak_price=str(position.peak_price),
        current_price=None if mark is None else str(mark),
        current_multiple=_multiple(mark, position.entry_price),
        current_value=_money(value),
        unrealized_pnl=(None if value is None else _money(value - position.cost_basis)),
        last_market_check_at=position.last_market_check_at,
        closed_at=position.closed_at,
        exit_price=None if position.exit_price is None else str(position.exit_price),
        exit_observed_price=(
            None if position.exit_observed_price is None else str(position.exit_observed_price)
        ),
        exit_proceeds_usd=_money(proceeds),
        exit_multiple=_multiple(position.exit_price, position.entry_price),
        exit_reason=position.exit_reason,
        exit_execution_route=position.exit_execution_route,
        exit_evidence=position.exit_evidence,
        realized_pnl=(None if proceeds is None else _money(proceeds - position.cost_basis)),
        hold_seconds=_seconds(position.closed_at, position.opened_at),
        age_seconds=int(((position.closed_at or now) - position.opened_at).total_seconds()),
    )


def _metrics(read: WalletRead) -> KarthikMetricsOut:
    wallet = read.wallet
    assert wallet is not None
    closed = list(read.closed_positions)
    wins = [p for p in closed if p.exit_reason == ExitReason.TARGET_1_25X.value]
    dead = [p for p in closed if p.exit_reason == ExitReason.DEAD_ZERO.value]
    holds = [
        (p.closed_at - p.opened_at).total_seconds() for p in closed if p.closed_at is not None
    ]
    entered = read.decisions.get(Decision.ENTERED.value, 0)
    return KarthikMetricsOut(
        starting_capital=str(wallet.starting_capital.quantize(_MONEY)),
        cash=str(read.cash.quantize(_MONEY)),
        full_equity=str(read.equity.quantize(_MONEY)),
        capital_allocated=str(read.allocated.quantize(_MONEY)),
        realized_pnl=str(read.realized_pnl.quantize(_MONEY)),
        unrealized_pnl=str(read.unrealized_pnl.quantize(_MONEY)),
        return_pct=str(
            ((read.equity - wallet.starting_capital) / wallet.starting_capital * 100).quantize(
                _PCT
            )
        ),
        open_positions=len(read.open_positions),
        closed_positions=len(closed),
        wins=len(wins),
        dead_zero=len(dead),
        win_rate_pct=(
            None
            if not closed
            else str((Decimal(len(wins)) / Decimal(len(closed)) * 100).quantize(_PCT))
        ),
        average_hold_seconds=(None if not holds else int(sum(holds) / len(holds))),
        track_record_opportunities=read.admissions,
        entered=entered,
        skipped_insufficient_cash=read.decisions.get(
            Decision.SKIPPED_INSUFFICIENT_CASH.value, 0
        ),
        skipped_no_market=read.decisions.get(Decision.SKIPPED_NO_MARKET.value, 0),
        capture_rate_pct=(
            None
            if read.admissions <= 0
            else str((Decimal(entered) / Decimal(read.admissions) * 100).quantize(_PCT))
        ),
        targets_hit=len(wins),
        dead_zero_count=len(dead),
        # Karthik has no backfill path at all: `undecided_admissions` filters on
        # `first_detected_at > activated_at`, so a token admitted before
        # activation can never be selected. Served as a figure anyway, because
        # "we do not do that" is worth being checkable rather than believed.
        historical_backfill=0,
    )


@router.get("", response_model=KarthikWalletOut)
async def read_wallet(session: DbSession) -> KarthikWalletOut:
    read = await KarthikService(session).read(now=utcnow())
    if read.wallet is None:
        return KarthikWalletOut(
            activated=False,
            strategy=STRATEGY,
            entries_paused=settings.KARTHIK_ENTRIES_PAUSED,
            disclosure=DISCLOSURE,
        )
    return KarthikWalletOut(
        activated=True,
        name=read.wallet.name,
        strategy=STRATEGY,
        entries_paused=settings.KARTHIK_ENTRIES_PAUSED,
        wallet_id=str(read.wallet.id),
        activated_at=read.wallet.activated_at,
        trade_size=str(read.wallet.trade_size.quantize(_MONEY)),
        take_profit_multiple=str(read.wallet.take_profit_multiple.normalize()),
        metrics=_metrics(read),
        disclosure=DISCLOSURE,
    )


@router.get("/positions", response_model=KarthikPositionsOut)
async def read_positions(session: DbSession) -> KarthikPositionsOut:
    now = utcnow()
    read = await KarthikService(session).read(now=now)
    return KarthikPositionsOut(
        items=[
            _position_out(position, mark=read.mark_for(position), now=now)
            for position in [*read.open_positions, *read.closed_positions]
        ]
    )


@router.get("/skipped", response_model=KarthikSkippedListOut)
async def read_skipped(session: DbSession) -> KarthikSkippedListOut:
    """The opportunities Karthik did not take, and why.

    Shown separately rather than folded into the positions table. A missed
    opportunity is not a trade, and an experiment that only displayed its trades
    would report a capture rate the reader could not check.
    """
    read = await KarthikService(session).read(now=utcnow())
    return KarthikSkippedListOut(
        items=[
            KarthikSkippedOut(
                mint_address=item.mint_address,
                track_record_at=item.track_record_at,
                decided_at=item.decided_at,
                reason=item.decision,
            )
            for item in read.skipped
        ]
    )
