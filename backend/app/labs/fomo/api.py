"""Read-only FOMO Lab board, including the uncopied-signal record."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter
from sqlalchemy import func, select

from app.api.deps import DbSession
from app.core.config import settings
from app.labs.fomo.models import FomoBook, FomoLeader, FomoPosition, FomoSignal
from app.labs.fomo.service import MAX_OPEN, STARTING_USD, TRADE_USD, FomoService

router = APIRouter(prefix="/labs/fomo", tags=["fomo-lab"])


def money(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None


@router.get("/board")
async def board(session: DbSession) -> dict[str, Any]:
    base: dict[str, Any] = {
        "enabled": settings.FEATURE_FOMO_LAB_ENABLED,
        "configured": bool(settings.FOMO_API_KEY.get_secret_value()),
        "source": "fomo.family 24h P&L via FOMO API; Solana swaps from the public RPC node",
        "starting_usd": money(STARTING_USD),
        "trade_usd": money(TRADE_USD),
        "max_open_trades": MAX_OPEN,
        "note": (
            "Forward paper simulation. No real orders. Fills use observed "
            "MEMESCOPE prices and a liquidity/fee model. Missing or stale "
            "prices prevent copying."
        ),
    }
    if not base["enabled"]:
        return {**base, "running": False, "reason": "lab_disabled"}
    if not base["configured"]:
        return {**base, "running": False, "reason": "feed_key_missing"}
    service = FomoService(session)
    book = await service.book()
    if book is None:
        return {**base, "running": False, "reason": "awaiting_first_roster"}

    leaders = (
        await session.execute(
            select(FomoLeader)
            .where(FomoLeader.book_id == book.id, FomoLeader.active.is_(True))
            .order_by(FomoLeader.rank)
        )
    ).scalars().all()
    signals = (
        await session.execute(
            select(FomoSignal)
            .where(FomoSignal.book_id == book.id)
            .order_by(FomoSignal.traded_at.desc())
            .limit(100)
        )
    ).scalars().all()
    consensus = await service.book("consensus")
    crowd = await service.book("crowd")
    return {
        **base,
        "running": True,
        "started_at": book.started_at.isoformat(),
        "roster_at": book.roster_at.isoformat() if book.roster_at else None,
        "source_captured_at": (
            book.source_captured_at.isoformat() if book.source_captured_at else None
        ),
        "feed_at": book.feed_at.isoformat() if book.feed_at else None,
        "feed_error": book.feed_error,
        **await _book_view(session, book),
        "leaders": [
            {
                "rank": row.rank,
                "user_id": row.user_id,
                "handle": row.handle,
                "wallet": row.wallet,
                "pnl_24h_usd": money(row.pnl_24h_usd),
                "follow_from": row.follow_from.isoformat(),
            }
            for row in leaders
        ],
        "signals": [
            {
                "wallet": signal.leader_wallet,
                "mint": signal.mint,
                "signature": signal.signature,
                "side": signal.side,
                "traded_at": signal.traded_at.isoformat(),
                "seen_at": signal.seen_at.isoformat(),
                "outcome": signal.outcome,
                "position_id": str(signal.position_id) if signal.position_id else None,
            }
            for signal in signals
        ],
        # The second book (2026-10-19): only buys a different ranked trader
        # made in the hour before. Same roster, feed and fills.
        "consensus": None if consensus is None else {
            "started_at": consensus.started_at.isoformat(),
            **await _book_view(session, consensus),
            "decisions": dict((await session.execute(
                select(FomoSignal.outcome, func.count()).where(
                    FomoSignal.book_id == consensus.id, FomoSignal.side == "buy")
                .group_by(FomoSignal.outcome))).all()),
        },
        # The Crowd book (2026-10-20): a fresh pump.fun graduation, bought on
        # its second fomo buyer from the app feed, sold 5 minutes later.
        "crowd": None if crowd is None else {
            "started_at": crowd.started_at.isoformat(),
            "feed_at": crowd.feed_at.isoformat() if crowd.feed_at else None,
            "feed_error": crowd.feed_error,
            **await _book_view(session, crowd),
            "decisions": dict((await session.execute(
                select(FomoSignal.outcome, func.count()).where(
                    FomoSignal.book_id == crowd.id, FomoSignal.side == "buy")
                .group_by(FomoSignal.outcome))).all()),
            "coins_seen": await session.scalar(select(func.count(func.distinct(FomoSignal.mint))).where(
                FomoSignal.book_id == crowd.id)),
        },
    }


async def _book_view(session: Any, book: FomoBook) -> dict[str, Any]:
    """One book's money and lots: cash, marks, equity and its recent lots."""
    recent_positions = (
        await session.execute(
            select(FomoPosition)
            .where(FomoPosition.book_id == book.id)
            .order_by(FomoPosition.opened_at.desc())
            .limit(100)
        )
    ).scalars().all()
    open_positions = (
        await session.execute(
            select(FomoPosition).where(
                FomoPosition.book_id == book.id, FomoPosition.status == "open"
            )
        )
    ).scalars().all()
    # An old open lot must not disappear from equity after 100 newer closes.
    positions = sorted(
        {pos.id: pos for pos in [*recent_positions, *open_positions]}.values(),
        key=lambda pos: pos.opened_at,
        reverse=True,
    )
    open_value = sum((pos.last_value_usd or Decimal(0) for pos in open_positions), Decimal(0))
    equity = book.cash_usd + open_value
    stale_marks = sum(
        1
        for pos in open_positions
        if not pos.last_mark_at or (datetime.now(UTC) - pos.last_mark_at).total_seconds() > 900
    )
    return {
        "cash_usd": money(book.cash_usd),
        "open_value_usd": money(open_value),
        "equity_usd": money(equity),
        "pnl_usd": money(equity - STARTING_USD),
        "open_trades": len(open_positions),
        "stale_marks": stale_marks,
        "positions": [
            {
                "id": str(pos.id),
                "wallet": pos.leader_wallet,
                "mint": pos.mint,
                "status": pos.status,
                "opened_at": pos.opened_at.isoformat(),
                "closed_at": pos.closed_at.isoformat() if pos.closed_at else None,
                "spent_usd": money(pos.spent_usd),
                "value_usd": money(pos.last_value_usd),
                "proceeds_usd": money(pos.proceeds_usd),
                "pnl_usd": money(
                    (pos.proceeds_usd - pos.spent_usd)
                    if pos.proceeds_usd is not None
                    else (
                        (pos.last_value_usd - pos.spent_usd)
                        if pos.last_value_usd is not None
                        else None
                    )
                ),
                "last_mark_at": pos.last_mark_at.isoformat() if pos.last_mark_at else None,
            }
            for pos in positions
        ],
    }
