"""Read-only routes for the Momentum Lab page. No POST, no PUT, no DELETE.

With `LAB_MOMENTUM_ENABLED` off, every route answers `running: false` without
touching the database.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.labs.momentum import board, config
from app.labs.momentum.arms import ARMS, BY_NAME
from app.labs.momentum.lab import LIVE, sell
from app.labs.momentum.models import MomClose, MomPair, MomPosition, MomSignal

router = APIRouter(prefix="/labs/momentum", tags=["momentum-lab"])


class Status(BaseModel):
    running: bool
    min_age_days: int = config.MIN_AGE_DAYS
    min_liquidity_usd: float = float(config.MIN_LIQUIDITY_USD)
    min_trades_5m: int = config.MIN_TRADES_PER_5M
    start_usd: float = float(config.START_USD)
    ticket_usd: float = float(config.TICKET_USD)
    arms: int = len(ARMS)
    pools_active: int = 0
    pools_sampled_5m: int = 0
    last_sample_at: datetime | None = None
    seconds_since_sample: int | None = None
    last_close: dict[str, datetime] = {}
    signals_24h: int = 0
    open_positions: int = 0
    closed_trades: int = 0
    started_at: datetime | None = None


@router.get("/status", response_model=Status)
async def status(db: AsyncSession = Depends(get_db)) -> Status:
    if not config.enabled():
        return Status(running=False)
    now = datetime.now(UTC)
    active = await db.scalar(select(func.count()).select_from(MomPair)
                             .where(MomPair.status == "active")) or 0
    last = await db.scalar(select(func.max(MomPair.last_sample_at)))
    sampled = await db.scalar(select(func.count()).select_from(MomPair).where(
        MomPair.last_sample_at >= now - timedelta(minutes=5))) or 0
    closes = dict((await db.execute(
        select(MomClose.tf, func.max(MomClose.start)).group_by(MomClose.tf))).all())
    signals = await db.scalar(select(func.count()).select_from(MomSignal)
                              .where(MomSignal.at >= now - timedelta(days=1))) or 0
    # Run 1's book is still in the table; the page counts the arms that exist.
    mine = MomPosition.arm.in_([a.name for a in ARMS])
    by_status = dict((await db.execute(
        select(MomPosition.status, func.count()).where(mine)
        .group_by(MomPosition.status))).all())
    started = await db.scalar(select(func.min(MomPosition.opened_at)).where(mine))
    return Status(
        running=True, pools_active=active, pools_sampled_5m=sampled,
        last_sample_at=last,
        seconds_since_sample=int((now - last).total_seconds()) if last else None,
        last_close=closes, signals_24h=signals,
        open_positions=sum(by_status.get(s, 0) for s in LIVE),
        closed_trades=by_status.get("closed", 0), started_at=started)


class SplitRow(BaseModel):
    split: int
    ticket: float
    end: float
    low: float
    funded: int
    skipped: int


class ArmRow(BaseModel):
    name: str
    family: str
    tf: str
    note: str
    entry: str
    exit: str
    is_control: bool
    vs: str | None
    trades: int
    open: int
    wins: int
    mean_pct: float | None
    median_pct: float | None
    se_pct: float | None
    pf: float | None
    best_pct: float | None
    worst_pct: float | None
    #: The tokens' own move, before costs; the gap to `mean_pct` is the toll.
    gross_pct: float | None
    #: Sum of every trade's dollars at the $100 it was measured at.
    book_usd: float
    unrealised_usd: float
    wallet: SplitRow
    splits: list[SplitRow]
    z_vs: float | None
    verdict: str


class Board(BaseModel):
    running: bool
    generated_at: datetime | None = None
    started_at: datetime | None = None
    arms: list[ArmRow] = []


_CACHE: tuple[datetime, Board] | None = None
_CACHE_TTL = timedelta(seconds=30)


def _pct(v: float | None) -> float | None:
    return None if v is None else round(v * 100, 3)


@router.get("/board", response_model=Board)
async def leaderboard(db: AsyncSession = Depends(get_db)) -> Board:
    """Every strategy, its trades, its wallet at every split. Cached thirty
    seconds: the book moves on a thirty-second tick."""
    global _CACHE
    if not config.enabled():
        return Board(running=False)
    now = datetime.now(UTC)
    if _CACHE is not None and now - _CACHE[0] < _CACHE_TTL:
        return _CACHE[1]
    # ponytail: every closed trade, every 30s the page is open; bound it to
    # a window (as the graduation board does) once the book outgrows a second.
    trades: dict[str, list[board.Trade]] = defaultdict(list)
    gross: dict[str, list[float]] = defaultdict(list)
    for r in (await db.execute(
            select(MomPosition.arm, MomPosition.opened_at, MomPosition.closed_at,
                   MomPosition.net_return, MomPosition.impact_open,
                   MomPosition.impact_close, MomPosition.open_price,
                   MomPosition.close_price)
            .where(MomPosition.status == "closed", MomPosition.net_return.is_not(None),
                   MomPosition.opened_at.is_not(None),
                   MomPosition.arm.in_([a.name for a in ARMS]))
            .order_by(MomPosition.opened_at, MomPosition.id))).all():
        trades[r.arm].append(board.Trade(
            r.opened_at, r.closed_at, float(r.net_return),
            float(r.impact_open or 0), float(r.impact_close or 0)))
        if r.open_price and r.close_price:
            gross[r.arm].append(float(r.close_price / r.open_price - 1))
    open_n: dict[str, int] = defaultdict(int)
    unrealised: dict[str, float] = defaultdict(float)
    for p, price, liq in (await db.execute(
            select(MomPosition, MomPair.last_price, MomPair.liquidity_usd)
            .join(MomPair, MomPair.pair_address == MomPosition.pair_address)
            .where(MomPosition.status.in_(LIVE),
                   MomPosition.arm.in_([a.name for a in ARMS])))).all():
        open_n[p.arm] += 1
        if p.status in ("open", "closing") and price and p.tokens:
            _, proceeds, _ = sell(price, liq, p.fee_bps or config.FEE_BPS, p.tokens)
            unrealised[p.arm] += float(proceeds + (p.scaled_usd or 0) - p.notional_usd)
    per = {a.name: board.stats(trades.get(a.name, [])) for a in ARMS}
    rows = []
    for arm in ARMS:
        s = per[arm.name]
        yardstick = arm.vs or None
        z = board.versus(s, per[yardstick]) if yardstick else None
        walks = [board.walk(trades.get(arm.name, []), n) for n in config.SPLITS]
        split_rows = [SplitRow(split=w.split, ticket=w.ticket, end=round(w.end, 2),
                               low=round(w.low, 2), funded=w.funded, skipped=w.skipped)
                      for w in walks]
        headline = next(r for r in split_rows if r.split == config.HEADLINE_SPLIT)
        g = gross.get(arm.name) or []
        rows.append(ArmRow(
            name=arm.name, family=arm.family, tf=arm.tf, note=arm.note,
            entry=arm.entry_words, exit=arm.exit_words, is_control=arm.is_control,
            vs=yardstick, trades=s.n, open=open_n.get(arm.name, 0), wins=s.wins,
            mean_pct=_pct(s.mean), median_pct=_pct(s.median), se_pct=_pct(s.se),
            pf=None if s.pf is None else round(s.pf, 3),
            best_pct=_pct(s.best), worst_pct=_pct(s.worst),
            gross_pct=_pct(sum(g) / len(g)) if g else None,
            book_usd=round(sum(t.ret for t in trades.get(arm.name, []))
                           * float(config.TICKET_USD), 2),
            unrealised_usd=round(unrealised.get(arm.name, 0.0), 2),
            wallet=headline, splits=split_rows,
            z_vs=None if z is None else round(z, 2),
            verdict=board.verdict(s, z, yardstick, is_control=arm.is_control)))
    started = await db.scalar(select(func.min(MomPosition.opened_at))
                              .where(MomPosition.arm.in_([a.name for a in ARMS])))
    out = Board(running=True, generated_at=now, started_at=started, arms=rows)
    _CACHE = (now, out)
    return out


class TradeRow(BaseModel):
    arm: str
    status: str
    symbol: str | None
    mint: str
    pair_address: str
    dex_id: str | None
    signal_tf: str
    signal_start: datetime
    signal_open: float
    signal_high: float
    signal_low: float
    signal_close: float
    features: dict[str, Any] | None
    decided_at: datetime
    opened_at: datetime | None
    open_price: float | None
    stop_price: float | None
    target_price: float | None
    peak_price: float | None
    closed_at: datetime | None
    close_price: float | None
    exit_reason: str | None
    net_return_pct: float | None
    pnl_usd: float | None
    last_price: float | None


class Trades(BaseModel):
    arm: str
    trades: list[TradeRow]


def _f(v: Any) -> float | None:
    return None if v is None else float(v)


@router.get("/trades", response_model=Trades)
async def arm_trades(arm: str, limit: int = 200,
                     db: AsyncSession = Depends(get_db)) -> Trades:
    """One strategy's positions, newest first, with the candle that opened each."""
    if arm not in BY_NAME:
        raise HTTPException(status_code=404, detail="no such strategy")
    if not config.enabled():
        return Trades(arm=arm, trades=[])
    rows = (await db.execute(
        select(MomPosition, MomPair.last_price)
        .outerjoin(MomPair, MomPair.pair_address == MomPosition.pair_address)
        .where(MomPosition.arm == arm, MomPosition.status != "unfilled")
        .order_by(MomPosition.decided_at.desc())
        .limit(max(1, min(limit, 500))))).all()
    return Trades(arm=arm, trades=[TradeRow(
        arm=p.arm, status=p.status, symbol=p.symbol, mint=p.mint,
        pair_address=p.pair_address, dex_id=p.dex_id, signal_tf=p.signal_tf,
        signal_start=p.signal_start, signal_open=float(p.signal_open),
        signal_high=float(p.signal_high), signal_low=float(p.signal_low),
        signal_close=float(p.signal_close), features=p.features,
        decided_at=p.decided_at, opened_at=p.opened_at, open_price=_f(p.open_price),
        stop_price=_f(p.stop_price), target_price=_f(p.target_price),
        peak_price=_f(p.peak_price), closed_at=p.closed_at,
        close_price=_f(p.close_price), exit_reason=p.exit_reason,
        net_return_pct=None if p.net_return is None else round(float(p.net_return) * 100, 3),
        pnl_usd=_f(p.pnl_usd),
        last_price=_f(last) if p.status in ("open", "closing") else None)
        for p, last in rows])


class SignalRow(BaseModel):
    symbol: str | None
    mint: str
    pair_address: str
    tf: str
    start: datetime
    at: datetime
    arms: list[str]
    features: dict[str, Any]


class Signals(BaseModel):
    signals: list[SignalRow]


@router.get("/signals", response_model=Signals)
async def signals(limit: int = 60, db: AsyncSession = Depends(get_db)) -> Signals:
    """The momentum radar: the newest candles any strategy's rule accepted,
    whether or not it had room to buy."""
    if not config.enabled():
        return Signals(signals=[])
    rows = (await db.scalars(select(MomSignal).order_by(MomSignal.at.desc())
                             .limit(max(1, min(limit, 200))))).all()
    return Signals(signals=[SignalRow(
        symbol=r.symbol, mint=r.mint, pair_address=r.pair_address, tf=r.tf,
        start=r.start, at=r.at, arms=list(r.arms), features=r.features) for r in rows])
