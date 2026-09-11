"""The paper trader: reads the ledger, applies `rules.py`, writes the ledger.

Ten slots of equity/10, entered when an episode transitions into
PRE_BREAKOUT, exited on a trailing stop of `TRAIL_PCT` of the slot. **Paper
only** — its own `bo_*` tables, no key, no signer, no route that could
execute, and a second flag (`BREAKOUT_TRADING_ENABLED`) so the watchlist can
run without the book.

**Decide on one bar, fill on the next.** An entry is taken from a transition
that happened on the PREVIOUS closed bar and filled at the OPEN of the bar
that has just closed. That is the brief's "fill at the next hourly open", and
it needs no pending-order state: by the time a tick runs, the bar after the
decision has closed and its open is a stored number rather than a guess.

Every write is keyed on a bar, so a re-run of the same tick changes nothing.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.labs.breakout import config, rules
from app.labs.breakout.candles import interval
from app.labs.breakout.models import (
    BoAccount,
    BoCandle,
    BoEpisode,
    BoEquity,
    BoPosition,
    BoSetupSnapshot,
    BoTrade,
    BoUniverseMember,
)
from app.labs.breakout.setups import FAILED, PRE_BREAKOUT

logger = get_logger(__name__)


def _d(value: float) -> Decimal:
    return Decimal(str(value))


class BreakoutTrader:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # --- the account --------------------------------------------------------

    async def account(self, now: datetime) -> BoAccount:
        """The one row, created at `STARTING_EQUITY` the first time it is asked
        for. `ON CONFLICT DO NOTHING` rather than a read-then-write, so two
        concurrent first ticks cannot make two accounts."""
        await self._session.execute(
            pg_insert(BoAccount).values(
                scope="default", equity=_d(config.STARTING_EQUITY),
                cash=_d(config.STARTING_EQUITY), peak_equity=_d(config.STARTING_EQUITY),
                halted=False, updated_at=now,
            ).on_conflict_do_nothing(constraint="uq_bo_account_scope")
        )
        return (await self._session.execute(
            select(BoAccount).where(BoAccount.scope == "default"))).scalar_one()

    # --- the tick -----------------------------------------------------------

    async def run(self, now: datetime) -> dict[str, Any]:
        """One pass on the newest closed hourly bar. Exits first, then the kill
        switch, then entries — a slot freed by an exit is available on the same
        bar, and a halt stops entries that the same bar's exits caused."""
        if not config.trading_enabled():
            return {"skipped": "breakout_trading_disabled"}

        bar = await self.latest_bar(now)
        if bar is None:
            return {"phase": "trader", "skipped": "no hourly bar stored"}

        account = await self.account(now)
        marks = await self.marks(bar)
        members = {m.mint: m for m in (await self._session.execute(
            select(BoUniverseMember))).scalars()}

        closed = await self.exits(account, bar, marks, members, now)
        halted = await self.check_halt(account, marks, now)
        opened, skipped = ([], {}) if halted else await self.entries(
            account, bar, marks, members, now)

        equity, cash, unrealised, n = await self.revalue(account, marks, now)
        await self.write_equity(bar, equity, cash, unrealised, n)

        logger.info("breakout_trader_tick", bar=bar.isoformat(), opened=len(opened),
                    closed=len(closed), equity=round(equity, 2), halted=account.halted)
        return {"phase": "trader", "bar": bar.isoformat(), "equity": round(equity, 4),
                "cash": round(cash, 4), "unrealised": round(unrealised, 4),
                "positions": n, "opened": opened, "closed": closed,
                "skipped": skipped, "halted": account.halted}

    async def latest_bar(self, now: datetime) -> datetime | None:
        """The newest stored hourly bar that had CLOSED by `now` — the bar this
        tick acts on.

        Bounded by `now` rather than simply `MAX(close_time)`: a bar that has
        not closed yet must never be traded on, and in a backfilled database
        the table can easily hold bars ahead of the tick being replayed.
        """
        return await self._session.scalar(
            select(func.max(BoCandle.close_time))
            .where(BoCandle.timeframe == "hour", BoCandle.close_time <= now))

    async def marks(self, bar: datetime) -> dict[str, BoCandle]:
        """The bar that closed at `bar`, per mint. A token with no bar at this
        close is simply absent — it is not marked, not exited, and not
        entered, because we have no current price for it."""
        rows = (await self._session.execute(
            select(BoCandle).where(BoCandle.timeframe == "hour",
                                   BoCandle.close_time == bar))).scalars()
        return {c.mint: c for c in rows}

    # --- exits --------------------------------------------------------------

    async def exits(self, account: BoAccount, bar: datetime,
                    marks: dict[str, BoCandle], members: dict[str, BoUniverseMember],
                    now: datetime) -> list[dict[str, Any]]:
        positions = (await self._session.execute(select(BoPosition))).scalars().all()
        closed: list[dict[str, Any]] = []
        for position in positions:
            candle = marks.get(position.mint)
            member = members.get(position.mint)
            in_universe = bool(member and member.active)
            if candle is None:
                if in_universe:
                    continue  # no price this bar; hold and look again next tick
                # Gone AND unpriced: close at the entry, which is the only
                # number we can still defend.
                await self.close_position(position, float(position.entry_price), bar,
                                          rules.FORCED_EXIT, member, now)
                closed.append({"mint": position.mint, "reason": rules.FORCED_EXIT})
                continue

            held = self.as_held(position)
            decision = rules.exit_reason(
                held, low=float(candle.low), high=float(candle.high),
                close=float(candle.close), now=now,
                episode_failed=await self.episode_failed(position),
                in_universe=in_universe,
            )
            if decision is None:
                # Not exiting: ratchet the high-water mark so the stop follows.
                step = rules.trail_step(
                    qty=held.qty, low=float(candle.low), high=float(candle.high),
                    high_water=held.high_water_value,
                    trail=rules.trail_amount(held.slot_size))
                if step.high_water > held.high_water_value:
                    await self._session.execute(
                        update(BoPosition).where(BoPosition.id == position.id)
                        .values(high_water_value=_d(step.high_water)))
                continue

            reason, price = decision
            await self.close_position(position, price, bar, reason, member, now)
            closed.append({"mint": position.mint, "reason": reason,
                           "price": round(price, 12)})
        return closed

    async def episode_failed(self, position: BoPosition) -> bool:
        if position.episode_id is None:
            return False
        reason = await self._session.scalar(
            select(BoEpisode.close_reason).where(BoEpisode.id == position.episode_id))
        return reason == FAILED

    def as_held(self, position: BoPosition) -> rules.Held:
        return rules.Held(
            mint=position.mint, qty=float(position.qty),
            entry_price=float(position.entry_price),
            slot_size=float(position.slot_size),
            high_water_value=float(position.high_water_value),
            opened_at=position.opened_at,
        )

    async def close_position(self, position: BoPosition, price: float, bar: datetime,
                             reason: str, member: BoUniverseMember | None,
                             now: datetime) -> None:
        """Sell at `price` with slippage and fee, write the trade, return the
        proceeds to cash, and delete the position. Idempotent: the trade's
        unique key is `(mint, entry_bar)`."""
        fill = rules.close_fill(float(position.qty), price)
        entry_notional = float(position.qty) * float(position.entry_price)
        fees = float(position.entry_fees) + fill.fees
        net, pct = rules.pnl(entry_notional, fill.notional, fees)

        await self._session.execute(pg_insert(BoTrade).values(
            mint=position.mint, symbol=member.symbol if member else None,
            episode_id=position.episode_id, qty=position.qty,
            entry_price=position.entry_price, exit_price=_d(fill.price),
            slot_size=position.slot_size, pnl_usd=_d(net), pnl_pct=_d(pct),
            fees_usd=_d(fees), opened_at=position.opened_at, closed_at=now,
            entry_bar=position.entry_bar, exit_bar=bar, exit_reason=reason,
        ).on_conflict_do_nothing(constraint="uq_bo_trades_mint_entry_bar"))

        await self._session.execute(
            update(BoAccount).where(BoAccount.id.in_(select(BoAccount.id)))
            .values(cash=BoAccount.cash + _d(fill.notional - fill.fees),
                    updated_at=now))
        await self._session.execute(
            delete(BoPosition).where(BoPosition.id == position.id))
        logger.info("breakout_position_closed", mint=position.mint, reason=reason,
                    pnl_usd=round(net, 4), pnl_pct=round(pct, 2))

    # --- the kill switch ----------------------------------------------------

    async def check_halt(self, account: BoAccount, marks: dict[str, BoCandle],
                         now: datetime) -> bool:
        """Trip on drawdown from peak, close everything, and stay tripped until
        a human runs `trader reset-halt --yes`."""
        if account.halted:
            return True
        equity, *_ = await self.compute_equity(account, marks)
        if not rules.should_halt(equity, float(account.peak_equity)):
            return False

        drawdown = rules.drawdown_pct(equity, float(account.peak_equity))
        logger.warning("breakout_kill_switch", equity=round(equity, 2),
                       peak=float(account.peak_equity), drawdown_pct=round(drawdown, 2))
        bar = await self.latest_bar(now)
        members = {m.mint: m for m in (await self._session.execute(
            select(BoUniverseMember))).scalars()}
        for position in (await self._session.execute(select(BoPosition))).scalars().all():
            candle = marks.get(position.mint)
            price = float(candle.close) if candle else float(position.entry_price)
            await self.close_position(position, price, bar or now, rules.HALT,
                                      members.get(position.mint), now)
        await self._session.execute(
            update(BoAccount).where(BoAccount.id == account.id).values(
                halted=True, halted_at=now,
                halted_reason=f"drawdown {drawdown:.1f}% > {config.MAX_DRAWDOWN_PCT}%",
                updated_at=now))
        account.halted = True
        return True

    async def reset_halt(self, now: datetime) -> dict[str, Any]:
        """Clear the halt AND re-base the peak to current equity. Leaving the
        old peak would re-trip the switch on the next tick, which is not a
        reset, it is a loop."""
        account = await self.account(now)
        equity, *_ = await self.compute_equity(account, await self.marks(
            await self.latest_bar(now) or now))
        await self._session.execute(
            update(BoAccount).where(BoAccount.id == account.id).values(
                halted=False, halted_at=None, halted_reason=None,
                peak_equity=_d(equity), updated_at=now))
        return {"halted": False, "peak_equity": round(equity, 4)}

    async def flatten(self, now: datetime) -> dict[str, Any]:
        """Close every position at the last mark. An operator command."""
        bar = await self.latest_bar(now)
        marks = await self.marks(bar) if bar else {}
        members = {m.mint: m for m in (await self._session.execute(
            select(BoUniverseMember))).scalars()}
        closed = []
        for position in (await self._session.execute(select(BoPosition))).scalars().all():
            candle = marks.get(position.mint)
            price = float(candle.close) if candle else float(position.entry_price)
            await self.close_position(position, price, bar or now, rules.FLATTEN,
                                      members.get(position.mint), now)
            closed.append(position.mint)
        await self.revalue(await self.account(now), marks, now)
        return {"flattened": closed}

    # --- entries ------------------------------------------------------------

    async def candidates(self, bar: datetime, marks: dict[str, BoCandle],
                         members: dict[str, BoUniverseMember]) -> list[rules.Candidate]:
        """Episodes that TRANSITIONED into PRE_BREAKOUT on the previous bar.

        A transition, not a state: a token that has been sitting in
        PRE_BREAKOUT for six hours is not a fresh signal, and entering it every
        hour would be a different strategy from the one being recorded.
        """
        step = interval("hour")
        decision_bar, before = bar - step, bar - 2 * step
        entering = (await self._session.execute(
            select(BoSetupSnapshot).where(BoSetupSnapshot.bar_close_time == decision_bar,
                                          BoSetupSnapshot.state == PRE_BREAKOUT)
        )).scalars().all()
        if not entering:
            return []
        previous = {s.mint: s.state for s in (await self._session.execute(
            select(BoSetupSnapshot).where(
                BoSetupSnapshot.bar_close_time == before,
                BoSetupSnapshot.mint.in_([s.mint for s in entering]))
        )).scalars()}
        open_episodes = {e.mint: e.id for e in (await self._session.execute(
            select(BoEpisode).where(BoEpisode.closed_at.is_(None)))).scalars()}

        found = []
        for snapshot in entering:
            if previous.get(snapshot.mint) == PRE_BREAKOUT:
                continue  # already in the state: not a transition
            candle = marks.get(snapshot.mint)
            member = members.get(snapshot.mint)
            if candle is None or member is None or not member.active:
                continue
            found.append(rules.Candidate(
                mint=snapshot.mint, episode_id=open_episodes.get(snapshot.mint),
                score=snapshot.score,
                liquidity_usd=(None if member.liquidity_usd is None
                               else float(member.liquidity_usd)),
                volume_24h_usd=(None if member.volume_24h_usd is None
                                else float(member.volume_24h_usd)),
                # THE NEXT BAR'S OPEN — the fill the brief asks for, and a
                # stored number rather than the close we decided on.
                fill_open=float(candle.open),
            ))
        return found

    async def entries(self, account: BoAccount, bar: datetime,
                      marks: dict[str, BoCandle], members: dict[str, BoUniverseMember],
                      now: datetime) -> tuple[list[dict[str, Any]], dict[str, str]]:
        held = {p.mint for p in (await self._session.execute(
            select(BoPosition))).scalars()}
        free = config.SLOTS - len(held)
        candidates = await self.candidates(bar, marks, members)
        if not candidates:
            return [], {}

        equity, *_ = await self.compute_equity(account, marks)
        chosen, skipped = rules.choose_entries(
            candidates, equity=equity, held=frozenset(held), free_slots=free,
            halted=account.halted)

        opened = []
        for candidate, fill in chosen:
            cost = fill.notional + fill.fees
            if float(account.cash) < cost:
                skipped[candidate.mint] = "no_cash"
                continue
            await self._session.execute(pg_insert(BoPosition).values(
                mint=candidate.mint, episode_id=candidate.episode_id,
                qty=_d(fill.qty), entry_price=_d(fill.price),
                slot_size=_d(rules.slot_size(equity)),
                high_water_value=_d(fill.notional), entry_fees=_d(fill.fees),
                opened_at=now, entry_bar=bar,
            ).on_conflict_do_nothing(constraint="uq_bo_positions_mint"))
            await self._session.execute(
                update(BoAccount).where(BoAccount.id == account.id)
                .values(cash=BoAccount.cash - _d(cost), updated_at=now))
            await self._session.refresh(account, ["cash"])
            opened.append({"mint": candidate.mint, "score": candidate.score,
                           "price": round(fill.price, 12),
                           "notional": round(fill.notional, 4)})
            logger.info("breakout_position_opened", mint=candidate.mint,
                        score=candidate.score, notional=round(fill.notional, 2))
        return opened, skipped

    # --- valuation ----------------------------------------------------------

    async def compute_equity(self, account: BoAccount, marks: dict[str, BoCandle],
                             ) -> tuple[float, float, float, int]:
        """`(equity, cash, unrealised, n)`. A position with no mark this bar is
        held at its entry, which is neither a gain nor a loss we can prove."""
        positions = (await self._session.execute(select(BoPosition))).scalars().all()
        cash = float(account.cash)
        value = unrealised = 0.0
        for position in positions:
            candle = marks.get(position.mint)
            price = float(candle.close) if candle else float(position.entry_price)
            mark = float(position.qty) * price
            value += mark
            unrealised += mark - float(position.qty) * float(position.entry_price)
        return cash + value, cash, unrealised, len(positions)

    async def revalue(self, account: BoAccount, marks: dict[str, BoCandle],
                      now: datetime) -> tuple[float, float, float, int]:
        await self._session.refresh(account, ["cash"])
        equity, cash, unrealised, n = await self.compute_equity(account, marks)
        await self._session.execute(
            update(BoAccount).where(BoAccount.id == account.id).values(
                equity=_d(equity), peak_equity=func.greatest(
                    BoAccount.peak_equity, _d(equity)), updated_at=now))
        return equity, cash, unrealised, n

    async def write_equity(self, bar: datetime, equity: float, cash: float,
                           unrealised: float, n: int) -> None:
        """One row per bar, upserted — a re-run of the same tick rewrites it."""
        stmt = pg_insert(BoEquity).values(
            bar_close_time=bar, equity=_d(equity), cash=_d(cash),
            unrealised=_d(unrealised), positions=n)
        await self._session.execute(stmt.on_conflict_do_update(
            constraint="uq_bo_equity_bar",
            set_={k: getattr(stmt.excluded, k)
                  for k in ("equity", "cash", "unrealised", "positions")}))
        await self._session.execute(delete(BoEquity).where(
            BoEquity.bar_close_time
            < bar - timedelta(hours=config.EQUITY_HISTORY_HOURS)))


def utcnow() -> datetime:
    return datetime.now(UTC)
