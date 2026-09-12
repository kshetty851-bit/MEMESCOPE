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
* exit at `PAPER_MAX_HOLD_MINUTES` — which is now the WHOLE strategy, not a
  backstop;
* a trailing stop and a take-profit exist and are both set to zero, because
  replaying 430 recorded graduations found each of them made every hold
  worse at every level tested.

The stop is checked BEFORE the target. Both can be true on one 60-second
sample and minute data cannot say which filled first, so the loss is taken —
the conservative reading, and the same order the backtester uses.

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
from app.labs.graduation.backtest import (
    Costs,
    ExitPolicy,
    ExitState,
    TakeProfit,
    Tick,
    TrailingStop,
)
from app.labs.graduation.models import (
    GradPaperPosition,
    GradPostgradSample,
    GradToken,
)

logger = get_logger(__name__)

_Q = Decimal("0.000000001")
#: Price precision. EIGHTEEN decimals, matching the column.
#:
#: It was eight, and a token quoted below 0.000000005 SOL stored every one of
#: its prices as zero. The realised P&L was still right — it is computed from
#: the unquantised price — but a `close_quote` of zero then tripped the rule
#: that voids a trade closed against a price the column could not represent,
#: so a legitimate trade was dropped on a rounding artefact in a field the
#: P&L never reads.
_P = Decimal("1E-18")


def costs(notional_quote: Decimal | None = None) -> Costs:
    """The book's cost model: the backtester's, at the POSITION's size.

    Pass the real `notional_quote`. The priority fee is flat in SOL, so its
    share of the position is entirely a function of size — 0.21% on $100 and
    2.06% on $10 — and the nominal 0.5 SOL this used to fall back on was not
    "a basis point or two" out, as the docstring here used to claim. It was
    the difference between a book that could win and one that could not.

    The fallback remains only for callers with no position in hand, such as a
    page rendering the headline cost.
    """
    return Costs(notional_quote=notional_quote or config.BACKTEST_NOTIONAL_QUOTE)


def switched_mints():
    """Mints whose recorded price series hops between pools.

    A position is opened against ONE pool and marking it against another is
    not a price move, it is a change of instrument — ORE's series crossed from
    a SOL-quoted pair to a USD-quoted one and "rose" 100x in a minute without
    trading. `postgrad._accept` now pins the pair so this cannot recur, but
    the rows already written still say what they say, so the book refuses to
    count them.

    Derived rather than stamped on the position: it is a property of the
    price series, it can only be known after the fact, and a column would be
    a second copy of something the samples already state.
    """
    return (select(GradPostgradSample.mint)
            .group_by(GradPostgradSample.mint)
            .having(func.count(func.distinct(GradPostgradSample.pair_address)) > 1))


def exit_policy() -> ExitPolicy:
    """The book's exits, in priority order: stop first, then target.

    Built from the backtester's rules rather than reimplemented, so the
    forward run and the replay cannot disagree about when a position leaves.
    """
    rules: list[TrailingStop | TakeProfit] = []
    if config.PAPER_TRAILING_PCT > 0:
        rules.append(TrailingStop(config.PAPER_TRAILING_PCT))
    if config.PAPER_TAKE_PROFIT_X > 1:
        rules.append(TakeProfit(config.PAPER_TAKE_PROFIT_X - 1))
    # An empty policy is a real configuration, not a mistake: it leaves the
    # hold as the only exit, which is what the replay says works.
    return ExitPolicy(tuple(rules))


def _rate(price_usd: Decimal | None, price_native: Decimal | None) -> Decimal | None:
    """SOL/USD, observed from one sample that carries both prices.

    Refused rather than guessed when either side is missing: a position sized
    at an invented rate would report a dollar P&L that never existed.
    """
    if not price_usd or not price_native or price_native <= 0:
        return None
    rate = price_usd / price_native
    return rate if rate > 0 else None


def net_return(position: Any, quote: Decimal | None,
               book_costs: Costs | None = None) -> Decimal | None:
    """What the position has returned at `quote`, after the cost of getting out.

    THE one definition, used by the close, by the equity mark and by the API
    row, because three copies of this formula is three chances for the page to
    disagree with the book about what a position is worth.

    Costs come from the POSITION unless a caller supplies them, so the flat
    priority fee is charged against what was actually traded.

    Note what is absent: the SOL/USD rate. The quote cancels — `tokens` was
    bought with `notional_quote` — so this is a pure price ratio, and the
    dollar figure derived from it is `notional_usd * net`. A move in SOL
    therefore cannot rewrite what a trade earned.
    """
    if quote is None or position.notional_quote <= 0:
        return None
    leg = book_costs or costs(position.notional_quote)
    return (position.tokens * leg.sell_price(quote)
            / position.notional_quote - 1)


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
    #: Closed trades refused because their price series crossed pools. Shown,
    #: never summed — a count of what is NOT in the figures above.
    voided: int = 0
    #: Gross profit over gross loss, and the single biggest winner's share of
    #: gross profit. Both are gate terms, so the page can show the run against
    #: the bar it was given rather than against a feeling.
    profit_factor: Decimal | None = None
    top_token_share: Decimal | None = None

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
            "voided": self.voided,
            "profit_factor": (str(self.profit_factor)
                              if self.profit_factor is not None else None),
            "free_slots": self.free_slots,
        }


def in_hour_window(when: datetime, start: int, end: int) -> bool:
    """Is `when` inside [start, end) UTC hours, wrapping midnight?"""
    hour = when.astimezone(UTC).hour
    return (start <= hour < end) if start < end else (hour >= start or hour < end)


async def symbol_reuse(session: AsyncSession, mint: str) -> int | None:
    """How many tokens with this mint's symbol were first seen BEFORE it.

    Strictly earlier, so it is knowable at entry. None when the token has no
    symbol on record — the research treated that as zero reuse and skipped it,
    and so does the filter.
    """
    row = (await session.execute(
        select(GradToken.symbol, GradToken.first_seen_at)
        .where(GradToken.mint == mint))).first()
    if row is None or not row.symbol or not row.symbol.strip():
        return None
    return int(await session.scalar(
        select(func.count()).select_from(GradToken)
        .where(func.lower(GradToken.symbol) == row.symbol.strip().lower(),
               GradToken.first_seen_at < row.first_seen_at,
               GradToken.mint != mint)) or 0)


async def passes_entry_filter(session: AsyncSession, mint: str,
                              open_at: datetime) -> tuple[bool, str]:
    """The filtered book's one extra rule. Returns (verdict, reason).

    Two conditions, both fixed before the book opened a trade: the pool
    opened inside the hour window, and the symbol had been used before.
    """
    if not in_hour_window(open_at, config.PAPER_FILTER_HOUR_START,
                          config.PAPER_FILTER_HOUR_END):
        return False, "hour"
    reuse = await symbol_reuse(session, mint)
    if reuse is None or reuse < config.PAPER_FILTER_MIN_SYMBOL_REUSE:
        return False, "symbol_new"
    return True, "ok"


class PaperBook:
    """One tick: mark and manage what is open, then fill what it can.

    `book` selects which of the two books this instance is. They share every
    rule and every line of code; the filtered one adds a single check before
    opening a position. That is the whole experiment, and it is why the two
    are one class rather than two.
    """

    def __init__(self, session: AsyncSession, *, book: str = "control",
                 now: datetime | None = None) -> None:
        if book not in config.PAPER_BOOKS:
            raise ValueError(f"unknown paper book {book!r}")
        self._session = session
        self._book = book
        self._now = now or datetime.now(UTC)
        self._costs = costs()

    @property
    def book(self) -> str:
        return self._book

    async def tick(self) -> dict[str, Any]:
        if not config.paper_enabled():
            return {"skipped": "graduation_paper_disabled"}
        closed = await self._manage()
        opened = await self._fill()
        account = await self.account()
        return {"book": self._book, "opened": opened, "closed": closed,
                **account.as_dict()}

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
            .where(GradPaperPosition.book == self._book,
                   GradPaperPosition.closed_at.is_(None),
                   # Rows written before the book was denominated in dollars
                   # carry no size and cannot be marked. They are excluded
                   # rather than counted as zero-value positions.
                   GradPaperPosition.notional_usd > 0))).all()
        rule = exit_policy()
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
                    # The EXACT fill, not the 8-decimal column: on a token
                    # quoted at 0.00000048 the stored figure is two
                    # significant digits, and the take-profit is a comparison
                    # against it. The tokens bought were priced at this.
                    entry_price=position.notional_quote / position.tokens,
                    tick=Tick(ts=self._now, price=price, source="paper"),
                    peak=position.peak_quote)
                if (fired := rule.fires(state)) is not None:
                    self._close(position, price, fired)
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
        leg = costs(position.notional_quote)
        fill = leg.sell_price(quote)
        net = net_return(position, quote, leg) or Decimal(0)
        position.closed_at = self._now
        position.close_quote = quote.quantize(_P)
        position.close_fill = fill.quantize(_P)
        position.close_reason = reason
        position.pnl_quote = (position.notional_quote * net).quantize(_Q)
        position.net_return = net.quantize(Decimal("0.00000001"))
        # Dollars come from the size and the return, both of which are exact.
        # Re-converting the SOL proceeds at today's rate would let a move in
        # SOL rewrite what a closed trade earned.
        position.pnl_usd = (position.notional_usd * net).quantize(Decimal("0.01"))
        logger.info("graduation_paper_closed", book=self._book,
                    mint=position.mint, reason=reason,
                    net=float(position.net_return))

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

        traded = (select(GradPaperPosition.mint)
                  .where(GradPaperPosition.book == self._book))
        cutoff = self._now - timedelta(minutes=config.PAPER_ENTRY_GRACE_MINUTES)
        opens = (select(GradPostgradSample.mint,
                        func.min(GradPostgradSample.ts).label("open_at"))
                 .where(GradPostgradSample.price_native > 0,
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
            if self._book == "filtered":
                ok, why = await passes_entry_filter(
                    self._session, row.mint, row.open_at)
                if not ok:
                    logger.info("graduation_paper_filtered_out",
                                mint=row.mint, reason=why)
                    continue
            rate = _rate(row.price_usd, row.price_native)
            if rate is None:
                # No observed SOL/USD for this token. Sizing it at an invented
                # rate would report a dollar P&L that never existed.
                logger.warning("graduation_paper_no_rate", mint=row.mint)
                continue
            notional_quote = (config.PAPER_NOTIONAL_USD / rate).quantize(_Q)
            # Priced at THIS position's size, so the flat priority fee is a
            # share of what is actually being traded.
            fill = costs(notional_quote).buy_price(row.price_native)
            if fill <= 0:
                continue
            self._session.add(GradPaperPosition(
                book=self._book,
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
            logger.info("graduation_paper_opened", book=self._book,
                        mint=row.mint, usd=float(config.PAPER_NOTIONAL_USD))
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
                   # > 0, not just NOT NULL: a zero here is a price too small
                   # for the column that held it, and marking against it
                   # closes a live position at -100%.
                   GradPostgradSample.price_native > 0,
                   GradPostgradSample.ts <= self._now)
            .order_by(GradPostgradSample.ts.desc()).limit(1))

    async def account(self) -> Account:
        bad = switched_mints()
        #: Applies to every position, open or closed.
        sound = (GradPaperPosition.book == self._book,
                 GradPaperPosition.notional_usd > 0,
                 GradPaperPosition.mint.not_in(bad))
        #: A CLOSED position must also have exited at a real price. A zero or
        #: NULL `close_quote` means the exit was marked against a price the
        #: old eight-decimal column could not represent — 0076 turned those
        #: zeros into NULLs, so both spellings have to be refused or the
        #: fabricated -100% exits walk straight back into the book.
        banked = (*sound, GradPaperPosition.close_quote > 0)
        realised = await self._session.scalar(
            select(func.coalesce(func.sum(GradPaperPosition.pnl_usd), 0))
            .where(GradPaperPosition.closed_at.is_not(None), *banked))
        closed = await self._session.scalar(
            select(func.count()).select_from(GradPaperPosition)
            .where(GradPaperPosition.closed_at.is_not(None), *banked))
        wins = await self._session.scalar(
            select(func.count()).select_from(GradPaperPosition)
            .where(GradPaperPosition.closed_at.is_not(None),
                   GradPaperPosition.pnl_usd > 0, *banked))
        voided = await self._session.scalar(
            select(func.count()).select_from(GradPaperPosition)
            .where(GradPaperPosition.book == self._book,
                   GradPaperPosition.closed_at.is_not(None),
                   GradPaperPosition.notional_usd > 0,
                   GradPaperPosition.mint.in_(bad)
                   | GradPaperPosition.close_quote.is_(None)
                   | (GradPaperPosition.close_quote <= 0)))
        # The gate terms come from the realised trades themselves, so they
        # cannot disagree with the list the page renders.
        banked = (await self._session.scalars(
            select(GradPaperPosition.pnl_usd)
            .where(GradPaperPosition.closed_at.is_not(None),
                   GradPaperPosition.pnl_usd.is_not(None), *banked))).all()
        up = sum((p for p in banked if p > 0), Decimal(0))
        down = -sum((p for p in banked if p < 0), Decimal(0))
        pf = (up / down) if down > 0 else None
        share = (max(banked) / up) if up > 0 else None

        open_rows = (await self._session.scalars(
            select(GradPaperPosition)
            .where(GradPaperPosition.closed_at.is_(None), *sound))).all()

        unrealised = Decimal(0)
        for position in open_rows:
            net = net_return(position, position.last_quote)
            if net is not None:
                unrealised += position.notional_usd * net

        return Account(
            starting=config.PAPER_CAPITAL_USD,
            realised=Decimal(realised or 0),
            unrealised=unrealised,
            open_positions=len(open_rows),
            closed_positions=int(closed or 0),
            wins=int(wins or 0),
            voided=int(voided or 0),
            profit_factor=(pf.quantize(Decimal("0.01")) if pf is not None else None),
            top_token_share=(share.quantize(Decimal("0.0001"))
                             if share is not None else None),
        )


async def positions(session: AsyncSession, *, book: str = "control",
                    limit: int | None = None
                    ) -> tuple[Sequence[Any], Sequence[Any]]:
    """Open and closed, separately.

    They answer different questions — what the book is exposed to now, versus
    what it has actually banked — and a single list buries the closed ones
    behind the open ones as soon as there are a few of each.

    Joined to `grad_tokens` for a name, because `GradPaperPosition.symbol` was
    never populated by the filler. Joining fixes every row that already exists;
    writing the symbol at fill time would only fix the ones opened from here on.
    """

    bad = switched_mints()

    def rows(closed: bool):
        return (select(GradPaperPosition, GradToken.symbol, GradToken.name,
                       (GradPaperPosition.mint.in_(bad)
                        | (GradPaperPosition.closed_at.is_not(None)
                           & GradPaperPosition.close_quote.is_(None))
                        | (GradPaperPosition.close_quote <= 0)).label("voided"))
                .outerjoin(GradToken, GradToken.mint == GradPaperPosition.mint)
                .where(GradPaperPosition.book == book,
                       GradPaperPosition.notional_usd > 0,
                       GradPaperPosition.closed_at.is_not(None) if closed
                       else GradPaperPosition.closed_at.is_(None)))

    closed = rows(True).order_by(GradPaperPosition.closed_at.desc())
    # Open needs no limit: the slot count caps it.
    return (
        (await session.execute(
            rows(False).order_by(GradPaperPosition.opened_at.desc()))).all(),
        (await session.execute(
            closed.limit(limit) if limit else closed)).all(),
    )
