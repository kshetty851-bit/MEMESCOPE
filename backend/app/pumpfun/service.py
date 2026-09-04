"""Mirror one wallet's trades into a $100 paper book — forward only.

## The watermark, which is the rule that matters

**Nothing the leader did before this lab started is ever actionable.** His
recent history is always in view — the follower returns his last hundred swaps,
which can span days — so without a hard cutoff the first tick would open the
whole book on trades that are already over. Every signal older than the
tournament's `valid_from` is recorded and refused with `before_watch_start`.

A second cutoff sits behind it: `MAX_SIGNAL_AGE_SECONDS`. He holds a median of
8.5 minutes, so copying a trade even an hour old is not copying that trade — it
is opening a fresh position at a price his own buying already moved.

## Recorded, then decided

Every leader trade gets a row whether or not we act, because the refusals are
the evidence. "We copied 40 of his 300 trades" is the finding; a ledger of only
our own fills cannot produce it. `signature` is UNIQUE in the database rather
than checked here, because two ticks can read before either writes.

## Sizing is ours

His median buy is ~$106 against our $100 book. We mirror WHICH token and WHEN,
never how much: a fixed $20, at most five open.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.logging import get_logger
from app.lab import execution
from app.lab.service import LabService
from app.models.lab import (
    LabDecision,
    LabPosition,
    LabStrategy,
    LabTournament,
)
from app.models.market import TokenMarketSnapshot, TradingStatus
from app.models.pumpfun import PumpfunSignal
from app.pumpfun import spec
from app.pumpfun.follower import LeaderTrade, recent_trades

logger = get_logger(__name__)

EXIT_REASON = "leader_sold"


class PumpfunService:
    def __init__(self, session) -> None:
        self._session = session
        self._lab = LabService(session, registry=spec)

    async def _row(self) -> tuple[LabTournament, LabStrategy] | None:
        t = (await self._session.execute(
            select(LabTournament).where(
                LabTournament.spec_version == spec.SPEC_VERSION)
        )).scalars().first()
        if t is None:
            return None
        row = (await self._session.execute(
            select(LabStrategy).where(LabStrategy.tournament_id == t.id)
        )).scalars().first()
        return None if row is None else (t, row)

    async def _seen(self, signature: str) -> bool:
        return (await self._session.execute(
            select(PumpfunSignal.id).where(PumpfunSignal.signature == signature)
        )).scalars().first() is not None

    async def _mark_price(self, mint: str, now: datetime):
        """Latest tradeable print for a mint, or None.

        Deliberately strict: a token we cannot price is one we refuse to buy.
        The leader trades many names our scanner has never seen — only 10% of
        his month had five or more snapshots here — and inventing an entry
        price for the rest would make the whole book fiction.
        """
        snap = (await self._session.execute(
            select(TokenMarketSnapshot)
            .where(TokenMarketSnapshot.mint_address == mint,
                   TokenMarketSnapshot.trading_status == TradingStatus.TRADING,
                   TokenMarketSnapshot.price_usd.isnot(None),
                   TokenMarketSnapshot.suspect.is_(False))
            .order_by(TokenMarketSnapshot.captured_at.desc()).limit(1)
        )).scalars().first()
        if snap is None or not snap.price_usd or not snap.liquidity_usd:
            return None
        age = (now - snap.captured_at).total_seconds()
        if age > execution.STALE_GUARD_SECONDS:
            return None
        return snap

    async def _record(self, t, trade: LeaderTrade, outcome: str, *,
                      acted: bool = False, position_id=None,
                      now: datetime) -> None:
        self._session.add(PumpfunSignal(
            tournament_id=t.id, signature=trade.signature,
            mint_address=trade.mint, side=trade.side,
            leader_sol=(Decimal(str(round(trade.sol_amount, 4)))
                        if trade.sol_amount is not None else None),
            leader_at=trade.at, seen_at=now,
            acted=acted, outcome=outcome, position_id=position_id,
        ))
        try:
            await self._session.flush()
        except IntegrityError:
            # Another tick recorded this signature first. That is the unique
            # constraint doing its job, not an error.
            await self._session.rollback()

    async def _open(self, t, row, trade: LeaderTrade, now: datetime) -> str:
        s = spec.BY_ID[row.strategy_id]
        held = (await self._session.execute(
            select(LabPosition).where(LabPosition.strategy_row_id == row.id,
                                      LabPosition.status == "open")
        )).scalars().all()
        if any(p.mint_address == trade.mint for p in held):
            return "already_held"
        if len(held) >= s.max_concurrent:
            return "max_concurrent"
        if row.cash < s.size_usd:
            return "insufficient_cash"
        snap = await self._mark_price(trade.mint, now)
        if snap is None:
            return "unpriceable"
        qty = execution.buy_quantity(s.size_usd, snap.price_usd, snap.liquidity_usd)
        if qty is None or qty <= 0:
            return "unpriceable"

        # Every Lab position descends from a decision, and this one is no
        # exception — `lab_positions.decision_id` is NOT NULL and that
        # invariant is worth satisfying rather than relaxing. The decision here
        # is his: the checkpoint is the moment he traded, and the features
        # record WHOSE trade and WHICH transaction, so a position can always be
        # traced back to the signature that caused it.
        decision = LabDecision(
            strategy_row_id=row.id, strategy_id=row.strategy_id,
            mint_address=trade.mint, token_id=snap.token_id,
            checkpoint_at=trade.at, checkpoint_minutes=0,
            decided_at=now, eligible=True,
            features={"leader": spec.LEADER_ADDRESS,
                      "leader_label": spec.LEADER_LABEL,
                      "signature": trade.signature,
                      "leader_sol": (round(trade.sol_amount, 4)
                                    if trade.sol_amount is not None else None),
                      "lag_seconds": round((now - trade.at).total_seconds(), 1)},
            requested_size_usd=s.size_usd,
        )
        self._session.add(decision)
        await self._session.flush()

        row.cash -= s.size_usd
        pos = LabPosition(
            decision_id=decision.id,
            strategy_row_id=row.id, strategy_id=row.strategy_id,
            mint_address=trade.mint, token_id=snap.token_id,
            opened_at=now, entry_price=snap.price_usd,
            entry_liquidity_usd=snap.liquidity_usd, size_usd=s.size_usd,
            quantity=qty, quantity_remaining=qty,
            banked_proceeds_usd=Decimal(0), status="open",
            peak_exec_multiple=Decimal(1), last_exec_multiple=Decimal(1),
            last_open_value_usd=s.size_usd, entry_source="pumpfun_copy",
        )
        self._session.add(pos)
        await self._session.flush()
        await self._record(t, trade, "opened", acted=True, position_id=pos.id,
                           now=now)
        return "opened"

    async def _close(self, t, row, trade: LeaderTrade, now: datetime) -> str:
        pos = (await self._session.execute(
            select(LabPosition).where(LabPosition.strategy_row_id == row.id,
                                      LabPosition.mint_address == trade.mint,
                                      LabPosition.status == "open")
        )).scalars().first()
        if pos is None:
            return "not_held"
        out = await self._lab.close_manually(
            position_id=pos.id, now=now, actor="pumpfun_copy",
            reason=EXIT_REASON,
        )
        if not out.get("closed"):
            return out.get("reason", "close_refused")
        await self._record(t, trade, "closed", acted=True, position_id=pos.id,
                           now=now)
        return "closed"

    async def tick(self, *, now: datetime | None = None) -> dict[str, Any]:
        now = now or datetime.now(UTC)
        t = await self._lab.activate(valid_from=now)
        found = await self._row()
        if found is None:
            return {"skipped": "not_activated"}
        _t, row = found

        trades = await recent_trades()
        counts: dict[str, int] = {}
        # Oldest first: his own sequence is the one we replay, and a buy that
        # arrives after its own sell would leave the book holding a position he
        # has already exited.
        for trade in sorted(trades, key=lambda x: x.at):
            if await self._seen(trade.signature):
                continue
            if trade.at < t.valid_from:
                outcome = "before_watch_start"
            elif (now - trade.at).total_seconds() > spec.MAX_SIGNAL_AGE_SECONDS:
                outcome = "stale_signal"
            elif trade.side == "buy":
                outcome = await self._open(t, row, trade, now)
            else:
                outcome = await self._close(t, row, trade, now)
            if outcome not in ("opened", "closed"):
                await self._record(t, trade, outcome, now=now)
            counts[outcome] = counts.get(outcome, 0) + 1

        settled = await self._lab.settle(now=now)
        await self._lab.record_equity(now=now)
        equity = await self._lab.equity(row)
        if counts.get("opened") or counts.get("closed"):
            logger.info("pumpfun_tick", **counts, equity=str(equity))
        return {"signals": counts, "settled": settled, "equity": str(equity),
                "watching_from": t.valid_from.isoformat()}
