"""`/labs/rafiqv2` — read-only. No POST, PUT, PATCH or DELETE.

Every figure arrives computed, from the same functions the tick uses, so the
page can never apply a second rule of its own. `running` says whether the
flag is on; a book that has not ticked yet is listed with its rules and no
numbers, because "not started" and "started and found nothing" differ.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.labs.rafiqv2 import config
from app.labs.rafiqv2.models import Rafiqv2Adjustment, Rafiqv2Book, Rafiqv2Position
from app.labs.rafiqv2.service import BookState, Rafiqv2Service, lock_floor, value

router = APIRouter(prefix="/labs/rafiqv2", tags=["rafiqv2-lab"])
Db = Annotated[AsyncSession, Depends(get_db)]


class AdjustmentOut(BaseModel):
    at: datetime
    parameter: str
    old_value: str
    new_value: str
    sample_size: int | None
    z_score: str | None
    reason: str


class BookOut(BaseModel):
    code: str
    name: str
    identity: str
    #: The book's JSON without commentary: the rules as published.
    rules: dict
    activated_at: datetime | None = None
    starting_equity: str
    cash: str | None = None
    #: Cash plus what every open position would fetch from its pool.
    equity: str | None = None
    #: Closed trades, plus any scale-out already sold from an open one.
    realised_pnl: str | None = None
    unrealised_pnl: str | None = None
    open_positions: int = 0
    closed_trades: int = 0
    wins: int = 0
    losses: int = 0
    mean_net_per_trade: str | None = None
    #: Why entries are held now. Empty when the book is entering.
    halted: list[str] = []
    ratchet_floor: str | None = None
    ratchet_high_water: str | None = None
    #: The death-rate breaker's current window: deaths out of trades.
    window_deaths: int = 0
    window_trades: int = 0
    #: What the next entry will read: rug_strictness, lock_giveback,
    #: size_multiplier, regime_note, plus how many closes it has heard.
    learning: dict | None = None
    adjustments: list[AdjustmentOut] = []


class StatusOut(BaseModel):
    running: bool
    books: list[BookOut]


class PositionOut(BaseModel):
    book: str
    mint_address: str
    symbol: str | None
    opened_at: datetime
    age_seconds: int
    cost_basis: str
    multiple: str | None
    peak_multiple: str
    #: The multiple the profit lock will not let it be sold below; null until
    #: the peak touches the first rung.
    lock_floor: str | None
    scaled_out: bool
    fraction_open: str
    current_value: str
    unrealised_pnl: str
    rug_strictness: str
    lock_giveback: str
    size_multiplier: str


class TradeOut(BaseModel):
    book: str
    mint_address: str
    symbol: str | None
    opened_at: datetime
    closed_at: datetime
    hold_seconds: int
    cost_basis: str
    proceeds_usd: str
    pnl_usd: str
    return_pct: str
    exit_reason: str
    exit_evidence: str | None
    scaled_out: bool
    died: bool | None
    peak_multiple: str
    #: Best price in the hour after the exit, over entry. Null until measured.
    forward_peak_multiple: str | None
    entry_top10_holder_pct: str | None
    entry_lp_locked: bool | None


def _s(v) -> str | None:
    return None if v is None else str(v)


def _usd(v: Decimal) -> str:
    """Money at the ledger's own precision. Summed first, rounded once, so
    equity less the start is exactly realised plus unrealised."""
    return str(v.quantize(Decimal("0.0001")))


async def _book(session: AsyncSession, svc: Rafiqv2Service, book: config.Book,
                row: Rafiqv2Book | None, now: datetime) -> BookOut:
    out = BookOut(code=book.code, name=book.name, identity=book.identity,
                  rules=book.rules, starting_equity=str(book.starting_equity))
    if row is None:
        return out
    pos = Rafiqv2Position
    pnl = pos.exit_proceeds_usd - pos.cost_basis
    closed = pos.status == "closed"
    n, wins, losses, closed_pnl, learned, awaiting = (await session.execute(
        select(func.count().filter(closed), func.count().filter(closed & (pnl > 0)),
               func.count().filter(closed & (pnl <= 0)),
               func.coalesce(func.sum(case((closed, pnl))), 0),
               func.count(pos.learning_recorded_at),
               func.count().filter(closed & pos.learning_recorded_at.is_(None)))
        .where(pos.book_id == row.id))).one()
    held = await svc.open_positions(row)
    cash = await svc.cash(row)
    equity = cash + sum(map(value, held), Decimal(0))
    st = BookState.load(book, row.state or {})
    params = st.lrn.current_parameters()
    adjustments = (await session.execute(
        select(Rafiqv2Adjustment).where(Rafiqv2Adjustment.book_id == row.id)
        .order_by(Rafiqv2Adjustment.at.desc()).limit(25))).scalars()
    return out.model_copy(update={
        "activated_at": row.activated_at, "cash": _usd(cash), "equity": _usd(equity),
        "realised_pnl": _usd(closed_pnl + sum(
            (p.realised_usd - p.cost_basis * (1 - p.fraction_open) for p in held),
            Decimal(0))),
        "unrealised_pnl": _usd(sum(map(value, held), Decimal(0))
                               - sum((p.cost_basis * p.fraction_open for p in held),
                                     Decimal(0))),
        "open_positions": len(held), "closed_trades": n, "wins": wins, "losses": losses,
        "mean_net_per_trade": str(round(closed_pnl / n, 4)) if n else None,
        "halted": st.halts(equity, now),
        "ratchet_floor": str(st.ratchet.floor),
        "ratchet_high_water": str(st.ratchet.high_water),
        "window_deaths": sum(st.death.recent), "window_trades": len(st.death.recent),
        "learning": {"rug_strictness": params["rug_strictness"],
                     "lock_giveback": params["lock_giveback"],
                     "size_multiplier": params["size_multiplier"],
                     "regime_note": params["regime_note"],
                     "closes_learned": learned, "closes_awaiting_their_hour": awaiting},
        "adjustments": [AdjustmentOut(
            at=a.at, parameter=a.parameter, old_value=str(a.old_value),
            new_value=str(a.new_value), sample_size=a.sample_size,
            z_score=_s(a.z_score), reason=a.reason) for a in adjustments],
    })


@router.get("/status", response_model=StatusOut)
async def status(session: Db) -> StatusOut:
    now = datetime.now(UTC)
    rows = {r.code: r for r in (await session.execute(select(Rafiqv2Book))).scalars()}
    svc = Rafiqv2Service(session)
    return StatusOut(running=config.enabled(),
                     books=[await _book(session, svc, b, rows.get(b.code), now)
                            for b in config.BOOKS])


@router.get("/positions", response_model=list[PositionOut])
async def positions(session: Db) -> list[PositionOut]:
    now = datetime.now(UTC)
    rows = (await session.execute(
        select(Rafiqv2Position, Rafiqv2Book.code)
        .join(Rafiqv2Book, Rafiqv2Book.id == Rafiqv2Position.book_id)
        .where(Rafiqv2Position.status == "open")
        .order_by(Rafiqv2Position.opened_at.desc()))).all()
    out = []
    for p, code in rows:
        worth = value(p)
        out.append(PositionOut(
            book=code, mint_address=p.mint_address, symbol=p.symbol, opened_at=p.opened_at,
            age_seconds=int((now - p.opened_at).total_seconds()),
            cost_basis=str(p.cost_basis),
            multiple=_s(p.last_mark_price / p.entry_price if p.last_mark_price else None),
            peak_multiple=str(p.peak_price / p.entry_price),
            lock_floor=_s(lock_floor(config.BY_CODE[code], p)),
            scaled_out=p.scaled_out, fraction_open=str(p.fraction_open),
            current_value=_usd(worth),
            unrealised_pnl=_usd(worth - p.cost_basis * p.fraction_open),
            rug_strictness=str(p.rug_strictness), lock_giveback=str(p.lock_giveback),
            size_multiplier=str(p.size_multiplier)))
    return out


@router.get("/trades", response_model=list[TradeOut])
async def trades(session: Db,
                 limit: Annotated[int, Query(ge=1, le=1000)] = 300) -> list[TradeOut]:
    rows = (await session.execute(
        select(Rafiqv2Position, Rafiqv2Book.code)
        .join(Rafiqv2Book, Rafiqv2Book.id == Rafiqv2Position.book_id)
        .where(Rafiqv2Position.status == "closed")
        .order_by(Rafiqv2Position.closed_at.desc()).limit(limit))).all()
    return [TradeOut(
        book=code, mint_address=p.mint_address, symbol=p.symbol, opened_at=p.opened_at,
        closed_at=p.closed_at,
        hold_seconds=int((p.closed_at - p.opened_at).total_seconds()),
        cost_basis=str(p.cost_basis), proceeds_usd=str(p.exit_proceeds_usd),
        pnl_usd=str(p.exit_proceeds_usd - p.cost_basis),
        return_pct=str(round((p.exit_proceeds_usd / p.cost_basis - 1) * 100, 2)),
        exit_reason=p.exit_reason, exit_evidence=p.exit_evidence,
        scaled_out=p.scaled_out, died=p.died,
        peak_multiple=str(p.peak_price / p.entry_price),
        forward_peak_multiple=_s(p.forward_peak_multiple),
        entry_top10_holder_pct=_s(p.entry_top10_holder_pct),
        entry_lp_locked=p.entry_lp_locked) for p, code in rows]
