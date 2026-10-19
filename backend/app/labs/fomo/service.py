"""One shared $500 paper book: each fresh leader buy spends $50, each sell exits one lot."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.lab import execution
from app.labs.fomo.models import FomoBook, FomoLeader, FomoPosition, FomoSignal
from app.labs.fomo.source import Leader
from app.models.market import LANE_DISPLAY, TokenMarketSnapshot, TradingStatus
from app.pumpfun.follower import LeaderTrade
from app.repositories.token import TokenRepository
from app.services.market.providers.registry import get_provider
from app.services.market.service import MarketEnrichmentService

STARTING_USD = Decimal("500")
#: Karthik, 2026-10-19: 20 lots of $25 instead of 10 of $50 (177 buys in the
#: first day were skipped for want of cash), and one lot per coin.
TRADE_USD = Decimal("25")
MAX_OPEN = 20
#: The consensus book buys only when ANOTHER ranked trader bought the same coin
#: in this window before (walk-forward lead, 19 Oct: 13 trades, unproven).
CONSENSUS_WINDOW = timedelta(minutes=60)
MAX_SIGNAL_AGE_SECONDS = 300
#: Hourly, not every 30 minutes: the free FOMO API plan is 250,000 credits a
#: month at 250 a call (1,000 calls); half-hourly reads would run it dry by
#: about day 20 and stale-roster pauses would stop every buy (2026-10-18).
ROSTER_REFRESH = timedelta(minutes=60)
MAX_ROSTER_AGE = timedelta(hours=2)


class FomoService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def book(self, kind: str = "main") -> FomoBook | None:
        return (
            await self.session.execute(select(FomoBook).where(FomoBook.kind == kind)
                                       .order_by(FomoBook.started_at).limit(1))
        ).scalar_one_or_none()

    async def consensus_book(self, now: datetime) -> FomoBook:
        """The second book, opened the first time it is asked for: its record
        starts then, never earlier."""
        book = await self.book("consensus")
        if book is None:
            book = FomoBook(started_at=now, cash_usd=STARTING_USD, kind="consensus")
            self.session.add(book)
            await self.session.flush()
        return book

    async def other_buyer_before(self, main: FomoBook, wallet: str,
                                 trade: LeaderTrade) -> bool:
        """Did a DIFFERENT followed trader buy this coin in the hour before?"""
        return (await self.session.execute(
            select(FomoSignal.id).where(
                FomoSignal.book_id == main.id, FomoSignal.side == "buy",
                FomoSignal.mint == trade.mint, FomoSignal.leader_wallet != wallet,
                FomoSignal.outcome.not_in(("not_ranked_at_trade", "before_start")),
                FomoSignal.traded_at >= trade.at - CONSENSUS_WINDOW,
                FomoSignal.traded_at < trade.at).limit(1))).scalar_one_or_none() is not None

    async def roster(self, book: FomoBook, leaders: list[Leader], now: datetime) -> None:
        """Update membership, never rewrite the instant a wallet first became actionable."""
        rows = (
            (
                await self.session.execute(
                    select(FomoLeader).where(FomoLeader.book_id == book.id)
                )
            )
            .scalars()
            .all()
        )
        by_id = {row.user_id: row for row in rows}
        incoming = {leader.user_id for leader in leaders}
        for row in rows:
            if row.user_id not in incoming:
                row.active = False
        for leader in leaders:
            row = by_id.get(leader.user_id)
            if row is None:
                self.session.add(
                    FomoLeader(
                        book_id=book.id,
                        user_id=leader.user_id,
                        handle=leader.handle,
                        wallet=leader.wallet,
                        rank=leader.rank,
                        pnl_24h_usd=leader.pnl_usd,
                        active=True,
                        follow_from=now,
                        ranked_at=now,
                    )
                )
            else:
                if not row.active or row.wallet != leader.wallet:
                    row.follow_from = now
                row.handle, row.wallet, row.rank = leader.handle, leader.wallet, leader.rank
                row.pnl_24h_usd, row.active, row.ranked_at = leader.pnl_usd, True, now
        book.roster_at = now
        await self.session.flush()

    async def wallets_to_poll(self, book: FomoBook, *also: FomoBook) -> list[str]:
        active = (
            (
                await self.session.execute(
                    select(FomoLeader.wallet).where(
                        FomoLeader.book_id == book.id, FomoLeader.active.is_(True)
                    )
                )
            )
            .scalars()
            .all()
        )
        held = (
            (
                await self.session.execute(
                    select(FomoPosition.leader_wallet).where(
                        FomoPosition.book_id.in_([book.id, *(b.id for b in also)]),
                        FomoPosition.status == "open",
                    )
                )
            )
            .scalars()
            .all()
        )
        return sorted(set(active) | set(held))

    async def cursors(self, book: FomoBook) -> dict[str, str | None]:
        """Each polled wallet's bookmark: the newest one any of its rows holds."""
        rows = (await self.session.execute(
            select(FomoLeader.wallet, FomoLeader.last_signature, FomoLeader.ranked_at)
            .where(FomoLeader.book_id == book.id)
            .order_by(FomoLeader.ranked_at))).all()
        out: dict[str, str | None] = {}
        for wallet, sig, _ in rows:
            out[wallet] = sig or out.get(wallet)
        return out

    async def set_cursors(self, book: FomoBook, marks: dict[str, str]) -> None:
        for row in (await self.session.execute(
                select(FomoLeader).where(FomoLeader.book_id == book.id,
                                         FomoLeader.wallet.in_(list(marks))))).scalars():
            row.last_signature = marks[row.wallet]
        await self.session.flush()

    async def price(self, mint: str, now: datetime) -> TokenMarketSnapshot | None:
        snap = (
            await self.session.execute(
                select(TokenMarketSnapshot)
                .where(
                    TokenMarketSnapshot.mint_address == mint,
                    TokenMarketSnapshot.trading_status == TradingStatus.TRADING,
                    TokenMarketSnapshot.suspect.is_(False),
                    TokenMarketSnapshot.price_usd.is_not(None),
                    TokenMarketSnapshot.liquidity_usd.is_not(None),
                )
                .order_by(TokenMarketSnapshot.captured_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if (
            snap is None
            or not snap.price_usd
            or not snap.liquidity_usd
            or execution.is_stale(snap.captured_at, now)
        ):
            return None
        return snap

    async def quote_now(
        self, trade: LeaderTrade, now: datetime
    ) -> tuple[TokenMarketSnapshot | None, str]:
        """Enrol and quote through the existing market pipeline, not a private fill."""
        tokens = TokenRepository(self.session)
        token = await tokens.get_by_mint(trade.mint)
        if token is None:
            token = await tokens.insert_if_absent(
                {
                    "mint_address": trade.mint,
                    "signature": trade.signature,
                    "slot": trade.slot,
                    "discovered_at": now,
                    "block_time": trade.at,
                    "source_program": "fomo_copy",
                }
            )
            if token is None:
                token = await tokens.get_by_mint(trade.mint)
        if token is None:
            return None, "enrol_failed"

        provider = get_provider()
        await provider.start()
        try:
            enrichment = MarketEnrichmentService(self.session, provider)
            state = await enrichment.states.ensure_state(
                token_id=token.id,
                mint_address=trade.mint,
                next_refresh_at=now,
                priority=LANE_DISPLAY,
            )
            if state is None:
                state = await enrichment.states.get_by_mint(trade.mint)
            if state is None:
                return None, "enrol_failed"
            outcome = await enrichment.enrich([state])
            if outcome.without_market:
                return None, "no_market"
            if outcome.deferred or outcome.failed or outcome.snapshots_written == 0:
                return None, "quote_unavailable"
            snap = await self.price(trade.mint, now)
            return snap, "quoted" if snap is not None else "unpriceable"
        finally:
            await provider.close()

    async def _open(
        self, book: FomoBook, wallet: str, trade: LeaderTrade, now: datetime
    ) -> tuple[str, FomoPosition | None]:
        open_count = len(
            (
                await self.session.execute(
                    select(FomoPosition.id).where(
                        FomoPosition.book_id == book.id, FomoPosition.status == "open"
                    )
                )
            ).all()
        )
        if open_count >= MAX_OPEN:
            return "max_open_trades", None
        held = (await self.session.execute(
            select(FomoPosition.id).where(
                FomoPosition.book_id == book.id, FomoPosition.mint == trade.mint,
                FomoPosition.status == "open").limit(1))).scalar_one_or_none()
        if held is not None:
            return "already_held", None
        if book.cash_usd < TRADE_USD:
            return "insufficient_cash", None
        snap = await self.price(trade.mint, now)
        if snap is None:
            snap, reason = await self.quote_now(trade, now)
            if snap is None:
                return reason, None
        qty = execution.buy_quantity(TRADE_USD, snap.price_usd, snap.liquidity_usd)
        if qty is None or qty <= 0:
            return "unpriceable", None
        pos = FomoPosition(
            book_id=book.id,
            leader_wallet=wallet,
            mint=trade.mint,
            buy_signature=trade.signature,
            leader_bought_at=trade.at,
            opened_at=now,
            entry_price_usd=snap.price_usd,
            quantity=qty,
            spent_usd=TRADE_USD,
            status="open",
            last_value_usd=execution.sell_proceeds(qty, snap.price_usd, snap.liquidity_usd),
            last_mark_at=now,
        )
        self.session.add(pos)
        book.cash_usd -= TRADE_USD
        await self.session.flush()
        return "opened", pos

    async def _close(
        self,
        book: FomoBook,
        wallet: str,
        trade: LeaderTrade,
        now: datetime,
        *,
        expected_position_id: uuid.UUID | None = None,
    ) -> tuple[str, FomoPosition | None]:
        positions = (
            (
                await self.session.execute(
                    select(FomoPosition)
                    .where(
                        FomoPosition.book_id == book.id,
                        FomoPosition.leader_wallet == wallet,
                        FomoPosition.mint == trade.mint,
                        FomoPosition.status == "open",
                    )
                    # Chain order: lots copied in one tick share `opened_at`.
                    .order_by(FomoPosition.leader_bought_at, FomoPosition.opened_at,
                              FomoPosition.id)
                )
            )
            .scalars()
            .all()
        )
        if expected_position_id is None:
            pending_ids = set(
                (
                    await self.session.execute(
                        select(FomoSignal.position_id).where(
                            FomoSignal.book_id == book.id,
                            FomoSignal.leader_wallet == wallet,
                            FomoSignal.mint == trade.mint,
                            FomoSignal.outcome == "pending_price",
                        )
                    )
                )
                .scalars()
                .all()
            )
            pos = next(
                (
                    p
                    for p in positions
                    if p.id not in pending_ids and p.leader_bought_at <= trade.at
                ),
                None,
            )
        else:
            pos = next(
                (
                    p
                    for p in positions
                    if p.id == expected_position_id and p.leader_bought_at <= trade.at
                ),
                None,
            )
        if pos is None:
            if expected_position_id is not None:
                return "position_already_closed", None
            if positions and all(p.leader_bought_at > trade.at for p in positions):
                return "before_buy", None
            return ("sell_already_pending" if positions else "not_held"), None
        snap = await self.price(trade.mint, now)
        if snap is None:
            snap, _ = await self.quote_now(trade, now)
            if snap is None:
                return "pending_price", pos
        proceeds = execution.sell_proceeds(pos.quantity, snap.price_usd, snap.liquidity_usd)
        pos.status, pos.closed_at = "closed", now
        pos.exit_price_usd, pos.proceeds_usd = snap.price_usd, proceeds
        pos.last_value_usd, pos.last_mark_at = proceeds, now
        book.cash_usd += proceeds
        # Sessions do not autoflush: without this the lot still reads "open" to
        # the next sell in the same tick, which would close it and pay it twice.
        await self.session.flush()
        return "closed", pos

    async def apply(
        self, book: FomoBook, observations: list[tuple[str, LeaderTrade]], now: datetime,
        *, roster_book: FomoBook | None = None,
        gate: Callable[[str, LeaderTrade], Awaitable[bool]] | None = None,
    ) -> dict[str, int]:
        """`roster_book` lends its roster to a book that keeps none (the
        consensus book); `gate` is a further test a buy must pass."""
        source = roster_book or book
        roster = (
            (
                await self.session.execute(
                    select(FomoLeader).where(
                        FomoLeader.book_id == source.id, FomoLeader.active.is_(True)
                    )
                )
            )
            .scalars()
            .all()
        )
        active = {row.wallet: row for row in roster}
        roster_fresh = (
            source.source_captured_at is not None
            and now - source.source_captured_at <= MAX_ROSTER_AGE
        )
        counts: dict[str, int] = {}
        seen_this_tick: set[tuple[str, str, str]] = set()
        for wallet, trade in observations:
            key = (wallet, trade.signature, trade.mint)
            if key in seen_this_tick:
                continue
            seen_this_tick.add(key)
            old = (
                await self.session.execute(
                    select(FomoSignal.id)
                    .where(
                        FomoSignal.book_id == book.id,
                        FomoSignal.leader_wallet == wallet,
                        FomoSignal.signature == trade.signature,
                        FomoSignal.mint == trade.mint,
                    )
                    .limit(1)
                )
            ).scalar_one_or_none()
            if old is not None:
                continue
            row = active.get(wallet)
            if trade.at < book.started_at:
                outcome, pos = "before_start", None
            elif trade.side == "buy" and not roster_fresh:
                outcome, pos = "roster_stale", None
            elif trade.side == "buy" and (row is None or trade.at < row.follow_from):
                outcome, pos = "not_ranked_at_trade", None
            elif (
                trade.side == "buy"
                and (now - trade.at).total_seconds() > MAX_SIGNAL_AGE_SECONDS
            ):
                outcome, pos = "stale_signal", None
            elif trade.side == "buy" and gate is not None and not await gate(wallet, trade):
                outcome, pos = "no_consensus", None
            elif trade.side == "buy":
                outcome, pos = await self._open(book, wallet, trade, now)
            else:
                outcome, pos = await self._close(book, wallet, trade, now)
            self.session.add(
                FomoSignal(
                    book_id=book.id,
                    leader_wallet=wallet,
                    signature=trade.signature,
                    mint=trade.mint,
                    side=trade.side,
                    traded_at=trade.at,
                    seen_at=now,
                    outcome=outcome,
                    position_id=pos.id if pos else None,
                )
            )
            if outcome == "pending_price":
                await self.session.flush()
            counts[outcome] = counts.get(outcome, 0) + 1
        await self.session.flush()
        return counts

    async def retry_sells(self, book: FomoBook, now: datetime) -> None:
        pending = (
            (
                await self.session.execute(
                    select(FomoSignal)
                    .where(
                        FomoSignal.book_id == book.id, FomoSignal.outcome == "pending_price"
                    )
                    .order_by(FomoSignal.traded_at)
                )
            )
            .scalars()
            .all()
        )
        unavailable: set[str] = set()
        for signal in pending:
            if signal.mint in unavailable:
                continue
            if signal.position_id is None:
                signal.outcome = "not_held"
                continue
            trade = LeaderTrade(
                signal.signature, 0, signal.mint, "sell", None, signal.traded_at
            )
            outcome, pos = await self._close(
                book,
                signal.leader_wallet,
                trade,
                now,
                expected_position_id=signal.position_id,
            )
            if outcome == "pending_price":
                unavailable.add(signal.mint)
            if outcome != "pending_price":
                signal.outcome = outcome
                signal.position_id = pos.id if pos else None
        # Resolved before `apply` runs, so its sells do not read them as pending.
        await self.session.flush()

    async def mark(self, book: FomoBook, now: datetime) -> None:
        positions = (
            (
                await self.session.execute(
                    select(FomoPosition).where(
                        FomoPosition.book_id == book.id, FomoPosition.status == "open"
                    )
                )
            )
            .scalars()
            .all()
        )
        prices: dict[str, TokenMarketSnapshot | None] = {}
        for pos in positions:
            if pos.mint not in prices:
                prices[pos.mint] = await self.price(pos.mint, now)
            snap = prices[pos.mint]
            if snap is not None:
                pos.last_value_usd = execution.sell_proceeds(
                    pos.quantity, snap.price_usd, snap.liquidity_usd
                )
                pos.last_mark_at = now
