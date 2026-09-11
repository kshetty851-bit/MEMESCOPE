"""The forward paper book. Rules fixed in advance, outcomes recorded as they land.

**Paper only.** No key, no signer, no route to a real wallet. `test_isolation`
fails if this package ever imports one.

## Why a forward run at all, when the backtest already says no

Because it is the one test that cannot be curve-fitted. A hundred exit-rule
variants were searched over a single week of recorded data and every one of
them lost — best profit factor 0.59 — and if one HAD come back at 2.4 it would
have been noise, because searching a hundred variants against sixty-eight
trades produces a winner by chance. A forward book has no search in it: the
rules are written down, and then the market answers.

So this book is evidence in a way the sweep was not, and it is worth exactly
as much whether it wins or loses.

## The rules, frozen

* enter at the POOL OPEN — the first post-graduation price, which is the
  earliest price anything could actually have been bought at, and the only
  entry available while the curve's SOL side is unresolved;
* `PAPER_NOTIONAL_QUOTE` per position, `PAPER_MAX_SLOTS` at once, a signal
  arriving with every slot full is SKIPPED and never queued;
* exit on a `PAPER_TRAILING_PCT` trailing stop off the RUNNING peak;
* exit at `PAPER_MAX_HOLD_MINUTES` regardless.

That last one is not a strategy choice. The post-graduation price series ends
`POST_MIGRATION_SECONDS` after the open, so past it there is no mark and no
exit price — a position left open would simply hang, unpriceable. It is a
property of the data.

## Costs are the backtester's, not a second opinion

`Costs` and the exit rules are imported from `backtest.py` rather than
reimplemented, so the paper book and the replay agree by construction. Two
cost models that drifted apart would make the forward run and the backtest
incomparable, which is the only reason to run both.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.labs.graduation import config
from app.labs.graduation.backtest import Costs, ExitState, Tick, TrailingStop
from app.labs.graduation.models import (
    GradPaperPosition,
    GradPostgradSample,
)

logger = get_logger(__name__)

_Q = Decimal("0.000000001")
_P = Decimal("0.00000001")


def costs(notional_quote: Decimal | None = None) -> Costs:
    """The book's cost model: the backtester's, at the book's position size.

    The flat priority fee is a fraction of the position, so it needs a quote
    size. A nominal one is fine — it moves the fee by a basis point or two,
    not the shape of anything.
    """
    return Costs(notional_quote=notional_quote or Decimal("0.5"))


def _rate(price_usd: Decimal | None, price_native: Decimal | None) -> Decimal | None:
    """SOL/USD, observed from one sample that carries both prices.

    Refused rather than guessed when either side is missing: a position sized
    at an invented rate would report a dollar P&L that never existed.
    """
    if not price_usd or not price_native or price_native <= 0:
        return None
    rate = price_usd / price_native
    return rate if rate > 0 else None


@dataclass(frozen=True, slots=True)
class Account:
    """Derived, never stored. Storing equity would be a second source of truth
    for something the positions already say."""

    starting: Decimal
    realised: Decimal
    unrealised: Decimal
    open_positions: int
    closed_positions: int
    wins: int

    @property
    def equity(self) -> Decimal:
        return self.starting + self.realised + self.unrealised

    @property
    def pnl(self) -> Decimal:
        return self.realised + self.unrealised

    @property
    def return_pct(self) -> Decimal:
        if self.starting <= 0:
            return Decimal(0)
        return (self.pnl / self.starting).quantize(Decimal("0.0001"))

    @property
    def free_slots(self) -> int:
        return max(0, config.PAPER_MAX_SLOTS - self.open_positions)

    def as_dict(self) -> dict[str, Any]:
        """All USD. The book was specified in dollars and reports in them."""
        cents = Decimal("0.01")
        return {
            "starting_usd": str(self.starting.quantize(cents)),
            "realised_usd": str(self.realised.quantize(cents)),
            "unrealised_usd": str(self.unrealised.quantize(cents)),
            "equity_usd": str(self.equity.quantize(cents)),
            "pnl_usd": str(self.pnl.quantize(cents)),
            "return_pct": str(self.return_pct),
            "open_positions": self.open_positions,
            "closed_positions": self.closed_positions,
            "wins": self.wins,
            "free_slots": self.free_slots,
        }


class PaperBook:
    """One tick: mark and manage what is open, then fill what it can."""

    def __init__(self, session: AsyncSession, *,
                 now: datetime | None = None) -> None:
        self._session = session
        self._now = now or datetime.now(UTC)
        self._costs = costs()

    async def tick(self) -> dict[str, Any]:
        if not config.paper_enabled():
            return {"skipped": "graduation_paper_disabled"}
        closed = await self._manage()
        opened = await self._fill()
        account = await self.account()
        return {"opened": opened, "closed": closed, **account.as_dict()}

    # --- managing what is open ----------------------------------------------

    async def _manage(self) -> int:
        """Mark every open position, then close the ones whose rule fired.

        The peak is updated BEFORE the stop is evaluated and is stored, so it
        survives a restart. A trailing stop that reset its peak on every
        process restart would be a different, much looser rule than the one
        written down.
        """
        positions = (await self._session.scalars(
            select(GradPaperPosition)
            .where(GradPaperPosition.closed_at.is_(None),
                   # Rows written before the book was denominated in dollars
                   # carry no size and cannot be marked. They are excluded
                   # rather than counted as zero-value positions.
                   GradPaperPosition.notional_usd > 0))).all()
        rule = TrailingStop(config.PAPER_TRAILING_PCT)
        closed = 0

        for position in positions:
            price = await self._latest_price(position.mint)
            age = (self._now - position.opened_at).total_seconds() / 60

            if price is not None:
                position.peak_quote = max(position.peak_quote, price)
                position.last_quote = price
                position.marked_at = self._now
                state = ExitState(
                    clock_at=position.opened_at,
                    entry_price=position.open_fill,
                    tick=Tick(ts=self._now, price=price, source="paper"),
                    peak=position.peak_quote)
                if rule.fires(state):
                    self._close(position, price, "trailing_stop")
                    closed += 1
                    continue

            if age >= config.PAPER_MAX_HOLD_MINUTES:
                # The series has ended; mark at the last price there was.
                mark = price if price is not None else position.last_quote
                if mark is not None:
                    self._close(position, mark,
                                "max_hold" if price is not None else "end_of_data")
                    closed += 1
        return closed

    def _close(self, position: GradPaperPosition, quote: Decimal,
               reason: str) -> None:
        fill = self._costs.sell_price(quote)
        proceeds = position.tokens * fill
        position.closed_at = self._now
        position.close_quote = quote.quantize(_P)
        position.close_fill = fill.quantize(_P)
        position.close_reason = reason
        position.pnl_quote = (proceeds - position.notional_quote).quantize(_Q)
        net = ((proceeds / position.notional_quote - 1)
               if position.notional_quote > 0 else Decimal(0))
        position.net_return = net.quantize(Decimal("0.00000001"))
        # Dollars come from the size and the return, both of which are exact.
        # Re-converting the SOL proceeds at today's rate would let a move in
        # SOL rewrite what a closed trade earned.
        position.pnl_usd = (position.notional_usd * net).quantize(Decimal("0.01"))
        logger.info("graduation_paper_closed", mint=position.mint,
                    reason=reason, net=float(position.net_return))

    # --- filling free slots -------------------------------------------------

    async def _fill(self) -> int:
        """Open a position on every fresh pool open, up to the slot limit.

        A candidate arriving with every slot full is SKIPPED, never queued: a
        book that queued them would be assuming capital it did not have, which
        is the same mistake as having no slot limit.
        """
        account = await self.account()
        if account.free_slots <= 0:
            return 0

        traded = select(GradPaperPosition.mint)
        cutoff = self._now - timedelta(minutes=config.PAPER_ENTRY_GRACE_MINUTES)
        opens = (select(GradPostgradSample.mint,
                        func.min(GradPostgradSample.ts).label("open_at"))
                 .where(GradPostgradSample.price_native.is_not(None),
                        GradPostgradSample.ts <= self._now,
                        GradPostgradSample.mint.not_in(traded))
                 .group_by(GradPostgradSample.mint)
                 .having(func.min(GradPostgradSample.ts) >= cutoff)
                 .order_by(func.min(GradPostgradSample.ts))
                 .limit(account.free_slots)).subquery()

        rows = (await self._session.execute(
            select(opens.c.mint, opens.c.open_at,
                   GradPostgradSample.price_native, GradPostgradSample.price_usd)
            .join(GradPostgradSample,
                  (GradPostgradSample.mint == opens.c.mint)
                  & (GradPostgradSample.ts == opens.c.open_at)))).all()

        opened = 0
        for row in rows:
            if row.price_native is None or row.price_native <= 0:
                continue
            rate = _rate(row.price_usd, row.price_native)
            if rate is None:
                # No observed SOL/USD for this token. Sizing it at an invented
                # rate would report a dollar P&L that never existed.
                logger.warning("graduation_paper_no_rate", mint=row.mint)
                continue
            fill = self._costs.buy_price(row.price_native)
            if fill <= 0:
                continue
            notional_quote = (config.PAPER_NOTIONAL_USD / rate).quantize(_Q)
            self._session.add(GradPaperPosition(
                mint=row.mint,
                opened_at=row.open_at,
                open_quote=row.price_native.quantize(_P),
                open_fill=fill.quantize(_P),
                notional_usd=config.PAPER_NOTIONAL_USD,
                sol_usd_at_open=rate.quantize(Decimal("0.000001")),
                notional_quote=notional_quote,
                tokens=(notional_quote / fill).quantize(_Q),
                peak_quote=row.price_native.quantize(_P),
                last_quote=row.price_native.quantize(_P),
                marked_at=self._now,
            ))
            opened += 1
            logger.info("graduation_paper_opened", mint=row.mint,
                        usd=float(config.PAPER_NOTIONAL_USD))
        return opened

    # --- reads ---------------------------------------------------------------

    async def _latest_price(self, mint: str) -> Decimal | None:
        """The last price AT OR BEFORE this tick's clock.

        The `ts <= now` bound is not decoration. Without it the book reads the
        newest row in the table, which during any replay or backfill is a
        price from the future — the running peak would then be the window's
        eventual high and the trailing stop would fire on information nothing
        could have had. Live it happens to be harmless because later rows do
        not exist yet; that is luck, not a guarantee.
        """
        return await self._session.scalar(
            select(GradPostgradSample.price_native)
            .where(GradPostgradSample.mint == mint,
                   GradPostgradSample.price_native.is_not(None),
                   GradPostgradSample.ts <= self._now)
            .order_by(GradPostgradSample.ts.desc()).limit(1))

    async def account(self) -> Account:
        realised = await self._session.scalar(
            select(func.coalesce(func.sum(GradPaperPosition.pnl_usd), 0))
            .where(GradPaperPosition.closed_at.is_not(None)))
        closed = await self._session.scalar(
            select(func.count()).select_from(GradPaperPosition)
            .where(GradPaperPosition.closed_at.is_not(None),
                   GradPaperPosition.notional_usd > 0))
        wins = await self._session.scalar(
            select(func.count()).select_from(GradPaperPosition)
            .where(GradPaperPosition.pnl_usd > 0))
        open_rows = (await self._session.scalars(
            select(GradPaperPosition)
            .where(GradPaperPosition.closed_at.is_(None),
                   GradPaperPosition.notional_usd > 0))).all()

        unrealised = Decimal(0)
        for position in open_rows:
            if position.last_quote is None or position.notional_quote <= 0:
                continue
            value = position.tokens * self._costs.sell_price(position.last_quote)
            # The unrealised move is a RATIO, so it converts to dollars with
            # the position's own entry rate and needs no live SOL/USD.
            unrealised += position.notional_usd * (
                value / position.notional_quote - 1)

        return Account(
            starting=config.PAPER_CAPITAL_USD,
            realised=Decimal(realised or 0),
            unrealised=unrealised,
            open_positions=len(open_rows),
            closed_positions=int(closed or 0),
            wins=int(wins or 0),
        )


async def positions(session: AsyncSession, *, limit: int = 25
                    ) -> Sequence[GradPaperPosition]:
    """Open first, then the most recently closed."""
    return (await session.scalars(
        select(GradPaperPosition)
        .order_by(GradPaperPosition.closed_at.is_not(None),
                  GradPaperPosition.opened_at.desc())
        .limit(limit))).all()
