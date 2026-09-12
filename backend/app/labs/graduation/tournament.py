"""Fifty paper strategies on the same graduations, and eight of them are noise.

## Why eight of them are noise on purpose

Run fifty strategies for a day and one of them leads. That is arithmetic, not
evidence — fifty coin-flippers also produce a leader, and the more arms there
are the better that leader looks. The only way a leaderboard means anything is
if it contains arms that CANNOT have an edge, so the question becomes "did the
leader beat what chance alone produced?" rather than "who is on top?".

So eight arms (`R1`-`R8`) decide by hashing the mint. They see the same
graduations, pay the same costs, and are indistinguishable from a real arm
except that their rule is provably meaningless. `control_band` reports the best
of them, and the page refuses to call a winner that has not cleared it.

## Everything else is shared

Every arm uses the same fills, the same cost model, the same `net_return`, the
same clock, in the same tick. They differ in exactly two places: which
graduations they accept (`entry`) and when they leave (`hold`, `tp`, `trail`).
A difference anywhere else would mean the tournament measures that instead.

## One tick, six queries

Fifty arms times ten slots is five hundred positions to mark. Doing that
per-arm is fifty times the work for the same answer, so the tick reads every
open position once, prices every distinct mint once, and writes once. The cost
of the tournament is therefore flat in the number of arms, which is what makes
fifty of them affordable at a fifteen-second tick.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.logging import get_logger
from app.labs.graduation import config
from app.labs.graduation.backtest import (
    ExitPolicy,
    ExitState,
    TakeProfit,
    Tick,
    TrailingStop,
    amm_buy,
    amm_impact,
    amm_sell,
)
from app.labs.graduation.models import GradPaperPosition, GradPostgradSample, GradToken
from app.labs.graduation.paper import _P, _Q, _rate, costs, in_hour_window

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class Arm:
    """One strategy. Frozen: the tournament is only evidence if no arm changes
    while it runs."""

    name: str
    entry: str
    hold: int
    tp: Decimal | None = None
    trail: Decimal | None = None
    note: str = ""

    @property
    def is_control(self) -> bool:
        return self.entry.startswith("rand")

    @property
    def entry_rule(self) -> str:
        """Buy when — in the words the page prints."""
        return ENTRY_RULES.get(self.entry, self.entry)

    @property
    def exit_rule(self) -> str:
        """Sell when. The hold is always present because the price series ends
        an hour after the open: past it there is no mark and no exit price, so
        every arm needs a backstop whatever else it carries."""
        parts = []
        if self.trail:
            parts.append(f"{self.trail * 100:.0f}% off the running peak")
        if self.tp:
            parts.append(f"{self.tp:g}x the price paid")
        parts.append(f"{self.hold} minute{'s' if self.hold != 1 else ''}")
        if len(parts) == 1:
            return f"at {parts[0]}"
        return "whichever comes first: " + ", or ".join(parts)

    def policy(self) -> ExitPolicy:
        rules: list[Any] = []
        if self.trail:
            rules.append(TrailingStop(self.trail))
        if self.tp:
            rules.append(TakeProfit(self.tp - 1))
        return ExitPolicy(tuple(rules))


def _coin(arm: str, mint: str, pct: int) -> bool:
    """A decision that depends on nothing. Hashed rather than `random` so it is
    the same on every tick, every restart and every replay — a control that
    changed its mind between ticks would be a different rule each time."""
    digest = hashlib.blake2b(f"{arm}:{mint}".encode(), digest_size=8).digest()
    return int.from_bytes(digest, "big") % 100 < pct


#: What each entry key MEANS, in the words the page prints.
#:
#: Kept beside `accepts` rather than in the frontend so the description cannot
#: drift from the rule it describes — `test_every_entry_filter_is_described`
#: fails if a filter gains a branch and loses its sentence, or vice versa.
ENTRY_RULES: dict[str, str] = {
    "all": "every graduation, no filter",
    "sym": "the token's symbol had been used by at least one earlier token",
    "sym3": "the symbol had been used by at least three earlier tokens",
    "newsym": "the symbol had never been seen before (the rug side of the split)",
    "night": "the pool opened between 18:00 and 06:00 UTC",
    "day": "the pool opened between 06:00 and 18:00 UTC",
    "sym_night": "symbol used before AND the pool opened 18:00-06:00 UTC",
    "deep": "the pool held at least $100,000 at the open",
    "shallow": "the pool held under $30,000 at the open",
    "nosell": "no sells had printed in the first five minutes of flow",
    "hassell": "at least one sell had already printed",
    "bigcap": "market cap at the open was at least $1,000,000",
    "smallcap": "market cap at the open was under $200,000",
    "sym_deep": "symbol used before AND the pool held at least $100,000",
    "sym_nosell": "symbol used before AND no sells had printed",
    "rand25": "a hash of the token address, taking a quarter of them — CONTROL",
    "rand50": "a hash of the token address, taking half of them — CONTROL",
    "rand75": "a hash of the token address, taking three quarters — CONTROL",
}

#: Candidate features, measured at the pool open. Every one was chosen before
#: the tournament opened a position; none is tuned to a result.
def accepts(arm: Arm, *, mint: str, open_at: datetime, liquidity: Decimal | None,
            fdv: Decimal | None, sells: int | None, reuse: int | None) -> bool:
    e = arm.entry
    if e == "all":
        return True
    if e == "sym":
        return (reuse or 0) >= 1
    if e == "night":
        return in_hour_window(open_at, 18, 6)
    if e == "day":
        return not in_hour_window(open_at, 18, 6)
    if e == "sym_night":
        return (reuse or 0) >= 1 and in_hour_window(open_at, 18, 6)
    if e == "sym3":
        return (reuse or 0) >= 3
    if e == "newsym":
        return (reuse or 0) == 0
    if e == "deep":
        return liquidity is not None and liquidity >= 100_000
    if e == "shallow":
        return liquidity is not None and liquidity < 30_000
    if e == "nosell":
        return sells is not None and sells == 0
    if e == "hassell":
        return sells is not None and sells > 0
    if e == "bigcap":
        return fdv is not None and fdv >= 1_000_000
    if e == "smallcap":
        return fdv is not None and 0 < fdv < 200_000
    if e == "sym_deep":
        return (reuse or 0) >= 1 and liquidity is not None and liquidity >= 100_000
    if e == "sym_nosell":
        return (reuse or 0) >= 1 and sells is not None and sells == 0
    if e.startswith("rand"):
        return _coin(arm.name, mint, int(e[4:]))
    raise ValueError(f"unknown entry filter {e!r}")


D = Decimal
#: The fifty. Named so the leaderboard reads as a grid rather than a list:
#: E = exit only, F = entry filter, C = combination, R = random control.
ARMS: tuple[Arm, ...] = (
    # --- E: the exit, on every graduation. The live book is E05. ------------
    Arm("E01_hold_1m", "all", 1, note="everything, out at 1 minute"),
    Arm("E02_hold_2m", "all", 2, note="everything, out at 2 minutes"),
    Arm("E03_hold_3m", "all", 3, note="everything, out at 3 minutes"),
    Arm("E05_hold_5m", "all", 5, note="the live book's rule"),
    Arm("E10_hold_10m", "all", 10, note="everything, out at 10 minutes"),
    Arm("E15_hold_15m", "all", 15, note="everything, out at 15 minutes"),
    Arm("E30_hold_30m", "all", 30, note="everything, out at 30 minutes"),
    Arm("E60_hold_60m", "all", 60, note="held to the end of the series"),
    # --- X: exit rules layered on the 5m and 15m holds -----------------------
    Arm("X01_tp_1_5x_15m", "all", 15, tp=D("1.5"), note="1.5x target, 15m cap"),
    Arm("X02_tp_2x_15m", "all", 15, tp=D("2"), note="2x target, 15m cap"),
    Arm("X03_tp_3x_60m", "all", 60, tp=D("3"), note="3x target, hour cap"),
    Arm("X04_trail_20_15m", "all", 15, trail=D("0.20"), note="20% trailing stop"),
    Arm("X05_trail_30_60m", "all", 60, trail=D("0.30"), note="30% trailing, hour cap"),
    Arm("X06_trail_50_60m", "all", 60, trail=D("0.50"), note="50% trailing, hour cap"),
    Arm("X07_tp2_trail30", "all", 60, tp=D("2"), trail=D("0.30"), note="2x or -30% off peak"),
    # --- F: one entry filter each, all at the 5-minute exit ------------------
    Arm("F01_sym_5m", "sym", 5, note="symbol used before"),
    Arm("F02_sym3_5m", "sym3", 5, note="symbol used 3+ times before"),
    Arm("F03_newsym_5m", "newsym", 5, note="symbol never seen (the rug side)"),
    Arm("F04_night_5m", "night", 5, note="pool opened 18:00-06:00 UTC"),
    Arm("F05_day_5m", "day", 5, note="pool opened 06:00-18:00 UTC"),
    Arm("F06_deep_5m", "deep", 5, note="liquidity >= $100k"),
    Arm("F07_shallow_5m", "shallow", 5, note="liquidity < $30k"),
    Arm("F08_nosell_5m", "nosell", 5, note="no sells in the first 5m of flow"),
    Arm("F09_hassell_5m", "hassell", 5, note="some sells already"),
    Arm("F10_bigcap_5m", "bigcap", 5, note="market cap >= $1M"),
    Arm("F11_smallcap_5m", "smallcap", 5, note="market cap < $200k"),
    # --- C: the combinations, and the same filters at other holds ------------
    Arm("C01_symnight_5m", "sym_night", 5, note="symbol reused AND night — the A/B arm"),
    Arm("C02_symnight_2m", "sym_night", 2, note="same filter, out at 2 minutes"),
    Arm("C03_symnight_10m", "sym_night", 10, note="same filter, out at 10 minutes"),
    Arm("C04_symnight_15m", "sym_night", 15, note="same filter, out at 15 minutes"),
    Arm("C05_symnight_tp2", "sym_night", 15, tp=D("2"), note="filter + 2x target"),
    Arm("C06_symdeep_5m", "sym_deep", 5, note="symbol reused AND deep pool"),
    Arm("C07_symnosell_5m", "sym_nosell", 5, note="symbol reused AND no sells"),
    Arm("C08_sym_2m", "sym", 2, note="symbol reused, out at 2 minutes"),
    Arm("C09_sym_15m", "sym", 15, note="symbol reused, out at 15 minutes"),
    Arm("C10_night_2m", "night", 2, note="night, out at 2 minutes"),
    Arm("C11_night_15m", "night", 15, note="night, out at 15 minutes"),
    Arm("C12_deep_2m", "deep", 2, note="deep pool, out at 2 minutes"),
    Arm("C13_deep_15m", "deep", 15, note="deep pool, out at 15 minutes"),
    Arm("C14_nosell_2m", "nosell", 2, note="no sells, out at 2 minutes"),
    Arm("C15_smallcap_60m", "smallcap", 60, trail=D("0.30"),
        note="small caps held for the tail, 30% trailing"),
    Arm("C16_bigcap_15m", "bigcap", 15, note="big caps, out at 15 minutes"),
    # --- R: the controls. These cannot have an edge. -------------------------
    Arm("R1_coin50_5m", "rand50", 5, note="CONTROL — half the tokens, by coin flip"),
    Arm("R2_coin50_5m", "rand50", 5, note="CONTROL — different coin, same rule"),
    Arm("R3_coin50_2m", "rand50", 2, note="CONTROL — coin flip, 2m exit"),
    Arm("R4_coin50_15m", "rand50", 15, note="CONTROL — coin flip, 15m exit"),
    Arm("R5_coin25_5m", "rand25", 5, note="CONTROL — a quarter of the tokens"),
    Arm("R6_coin25_15m", "rand25", 15, note="CONTROL — a quarter, 15m exit"),
    Arm("R7_coin75_5m", "rand75", 5, note="CONTROL — three quarters"),
    Arm("R8_coin75_60m", "rand75", 60, note="CONTROL — three quarters, hour hold"),
)

BY_NAME: dict[str, Arm] = {a.name: a for a in ARMS}
CONTROLS: tuple[Arm, ...] = tuple(a for a in ARMS if a.is_control)
assert len(ARMS) == 50, f"the tournament is fifty arms, not {len(ARMS)}"
assert len(CONTROLS) == 8
assert len({a.name for a in ARMS}) == 50, "arm names must be unique"
assert all(len(a.name) <= 32 for a in ARMS), "arm name must fit the column"
assert {a.entry for a in ARMS} <= set(ENTRY_RULES), (
    "every entry filter an arm uses must be described: "
    f"{ {a.entry for a in ARMS} - set(ENTRY_RULES) }")


class Tournament:
    """Every arm, one tick, six queries."""

    def __init__(self, session: AsyncSession, *, now: datetime | None = None) -> None:
        self._session = session
        self._now = now or datetime.now(UTC)

    async def tick(self) -> dict[str, Any]:
        if not config.paper_enabled():
            return {"skipped": "graduation_paper_disabled"}
        closed = await self._manage()
        opened = await self._fill()
        return {"arms": len(ARMS), "opened": opened, "closed": closed}

    # --- marking -------------------------------------------------------------

    async def _latest_prices(
        self, mints: Sequence[str]
    ) -> dict[str, tuple[Decimal, Decimal | None]]:
        """Price AND pool depth per mint, at or before this tick's clock.

        The depth comes back with the price because an exit is priced against
        it: a position that ran is a larger order into the same pool, and
        selling it at the quote is the mistake this whole change exists to
        stop.

        `DISTINCT ON` rather than a query per position: fifty arms hold the
        same handful of tokens, and pricing each one once is the difference
        between six queries a tick and five hundred.
        """
        if not mints:
            return {}
        rows = (await self._session.execute(
            select(GradPostgradSample.mint, GradPostgradSample.price_native,
                   GradPostgradSample.liquidity_usd)
            .where(GradPostgradSample.mint.in_(list(mints)),
                   GradPostgradSample.price_native > 0,
                   GradPostgradSample.ts <= self._now)
            .distinct(GradPostgradSample.mint)
            .order_by(GradPostgradSample.mint, GradPostgradSample.ts.desc()))).all()
        return {r.mint: (r.price_native, r.liquidity_usd) for r in rows}

    async def _manage(self) -> int:
        positions = (await self._session.scalars(
            select(GradPaperPosition)
            .where(GradPaperPosition.closed_at.is_(None),
                   GradPaperPosition.notional_usd > 0))).all()
        if not positions:
            return 0
        marks = await self._latest_prices(sorted({p.mint for p in positions}))
        closed = 0
        for position in positions:
            arm = BY_NAME.get(position.book)
            if arm is None:
                continue
            price, depth = marks.get(position.mint, (None, None))
            age = (self._now - position.opened_at).total_seconds() / 60
            if price is not None:
                position.peak_quote = max(position.peak_quote, price)
                position.last_quote = price
                position.marked_at = self._now
                fired = arm.policy().fires(ExitState(
                    clock_at=position.opened_at,
                    entry_price=position.notional_quote / position.tokens,
                    tick=Tick(ts=self._now, price=price, source="paper"),
                    peak=position.peak_quote))
                if fired is not None:
                    self._close(position, price, depth, fired)
                    closed += 1
                    continue
            if age >= arm.hold:
                mark = price if price is not None else position.last_quote
                if mark is not None and mark > 0:
                    self._close(position, mark, depth,
                                "max_hold" if price is not None else "end_of_data")
                    closed += 1
        return closed

    def _close(self, position: GradPaperPosition, quote: Decimal,
               depth: Decimal | None, reason: str) -> None:
        """Exit at what the pool would actually pay for this position.

        The order size on the way out is the position's CURRENT value, not
        what it cost: a token that ran 878% is ten times the order it was, into
        a pool that is usually no deeper. Pricing the exit at the quote is what
        turned a $21 pool into $878 of paper profit.

        With no recorded depth the exit is still taken — the position has to
        leave — but at the spot price with fees only, and `impact_close` stays
        NULL so the row shows the fill was never verified.
        """
        leg = costs(position.notional_quote)
        # Value at the quote, before impact: the size of the sell order.
        value_usd = position.notional_usd * (quote / (
            position.notional_quote / position.tokens))
        fill = amm_sell(quote, value_usd=value_usd, liquidity_usd=depth,
                        fee_fraction=leg.fee_fraction)
        if fill is None:
            fill = leg.sell_price(quote)
        else:
            position.impact_close = (amm_impact(value_usd, depth) or Decimal(0)
                                     ).quantize(Decimal("0.000001"))
        position.liq_close_usd = depth
        proceeds = position.tokens * fill
        net = (proceeds / position.notional_quote - 1
               if position.notional_quote > 0 else Decimal(0))
        position.closed_at = self._now
        position.close_quote = quote.quantize(_P)
        position.close_fill = fill.quantize(_P)
        position.close_reason = reason
        position.pnl_quote = (position.notional_quote * net).quantize(_Q)
        position.net_return = net.quantize(Decimal("0.00000001"))
        position.pnl_usd = (position.notional_usd * net).quantize(Decimal("0.01"))

    # --- filling -------------------------------------------------------------

    async def _open_counts(self) -> dict[str, int]:
        rows = (await self._session.execute(
            select(GradPaperPosition.book, func.count())
            .where(GradPaperPosition.closed_at.is_(None),
                   GradPaperPosition.notional_usd > 0)
            .group_by(GradPaperPosition.book))).all()
        return {r[0]: r[1] for r in rows}

    async def _candidates(self) -> Sequence[Any]:
        """Pool opens inside the entry grace window, with everything each arm
        needs to decide, in one read."""
        cutoff = self._now - timedelta(minutes=config.PAPER_ENTRY_GRACE_MINUTES)
        # Written to stay flat as the sample table grows, not to read well.
        #
        # The obvious form — GROUP BY mint HAVING min(ts) >= cutoff — asks
        # every mint that ever existed when its first sample was, so Postgres
        # scans the whole table: measured at 211 ms against 56,000 rows, on a
        # table growing 130,000 a day, inside a tick that runs every fifteen
        # seconds. This asks the same question backwards. A pool that opened
        # inside the window HAS a sample inside the window and NO sample
        # before it, and both of those are index lookups: 23 ms, and the first
        # step only ever touches the last few minutes of rows however large
        # the table gets.
        earlier = aliased(GradPostgradSample)
        recent = (select(GradPostgradSample.mint)
                  .where(GradPostgradSample.ts >= cutoff,
                         GradPostgradSample.ts <= self._now,
                         GradPostgradSample.price_native > 0)
                  .distinct()).subquery()
        fresh = (select(recent.c.mint)
                 .where(~select(1).select_from(earlier)
                        .where(earlier.mint == recent.c.mint,
                               earlier.ts < cutoff,
                               earlier.price_native > 0)
                        .exists())).subquery()
        opens = (select(GradPostgradSample.mint,
                        func.min(GradPostgradSample.ts).label("open_at"))
                 .join(fresh, fresh.c.mint == GradPostgradSample.mint)
                 .where(GradPostgradSample.price_native > 0)
                 .group_by(GradPostgradSample.mint)
                 .order_by(func.min(GradPostgradSample.ts))
                 .limit(64)).subquery()
        return (await self._session.execute(
            select(opens.c.mint, opens.c.open_at,
                   GradPostgradSample.price_native, GradPostgradSample.price_usd,
                   GradPostgradSample.liquidity_usd, GradPostgradSample.fdv,
                   GradPostgradSample.txns_m5_sells,
                   GradToken.symbol, GradToken.first_seen_at)
            .join(GradPostgradSample,
                  (GradPostgradSample.mint == opens.c.mint)
                  & (GradPostgradSample.ts == opens.c.open_at))
            .outerjoin(GradToken, GradToken.mint == opens.c.mint))).all()

    async def _symbol_reuse(self, rows: Sequence[Any]) -> dict[str, int]:
        """How many tokens carried each candidate's symbol BEFORE it existed.

        Counted in Python from one flat read rather than a correlated
        subquery: the candidates are a handful, the answer has to be "strictly
        earlier than THIS token", and a join that expresses that is harder to
        read than it is to verify.
        """
        wanted = {(r.symbol or "").strip().lower() for r in rows if r.symbol}
        wanted.discard("")
        if not wanted:
            return {}
        seen: dict[str, list[datetime]] = {}
        for symbol, first_seen in (await self._session.execute(
                select(GradToken.symbol, GradToken.first_seen_at)
                .where(func.lower(func.trim(GradToken.symbol)).in_(wanted)))).all():
            seen.setdefault((symbol or "").strip().lower(), []).append(first_seen)
        out: dict[str, int] = {}
        for r in rows:
            key = (r.symbol or "").strip().lower()
            if not key or r.first_seen_at is None:
                continue
            out[r.mint] = sum(1 for t in seen.get(key, []) if t < r.first_seen_at)
        return out

    async def _fill(self) -> int:
        rows = await self._candidates()
        if not rows:
            return 0
        reuse = await self._symbol_reuse(rows)
        mints = [r.mint for r in rows]
        taken = {(b, m) for b, m in (await self._session.execute(
            select(GradPaperPosition.book, GradPaperPosition.mint)
            .where(GradPaperPosition.mint.in_(mints)))).all()}
        counts = await self._open_counts()
        opened = 0
        refused = 0
        for row in rows:
            if row.price_native is None or row.price_native <= 0:
                continue
            rate = _rate(row.price_usd, row.price_native)
            if rate is None:
                continue
            # Could a real wallet have filled this at all? A transaction whose
            # price move exceeds the slippage tolerance REVERTS — it does not
            # fill badly, it does not fill. Refusing here is the difference
            # between a book that informs a real wallet and one that cannot.
            impact = amm_impact(config.PAPER_NOTIONAL_USD, row.liquidity_usd)
            if impact is None or impact > config.PAPER_MAX_IMPACT:
                refused += 1
                logger.info("graduation_tournament_unfillable", mint=row.mint,
                            liquidity=float(row.liquidity_usd or 0),
                            impact=float(impact) if impact is not None else None)
                continue
            notional_quote = (config.PAPER_NOTIONAL_USD / rate).quantize(_Q)
            leg = costs(notional_quote)
            fill = amm_buy(row.price_native, order_usd=config.PAPER_NOTIONAL_USD,
                           liquidity_usd=row.liquidity_usd,
                           fee_fraction=leg.fee_fraction)
            if fill is None or fill <= 0:
                continue
            for arm in ARMS:
                if (arm.name, row.mint) in taken:
                    continue
                if counts.get(arm.name, 0) >= config.PAPER_MAX_SLOTS:
                    continue
                if not accepts(arm, mint=row.mint, open_at=row.open_at,
                               liquidity=row.liquidity_usd, fdv=row.fdv,
                               sells=row.txns_m5_sells,
                               reuse=reuse.get(row.mint)):
                    continue
                self._session.add(GradPaperPosition(
                    book=arm.name, mint=row.mint, symbol=row.symbol,
                    opened_at=row.open_at,
                    open_quote=row.price_native.quantize(_P),
                    open_fill=fill.quantize(_P),
                    notional_usd=config.PAPER_NOTIONAL_USD,
                    sol_usd_at_open=rate.quantize(Decimal("0.000001")),
                    notional_quote=notional_quote,
                    tokens=(notional_quote / fill).quantize(_Q),
                    peak_quote=row.price_native.quantize(_P),
                    last_quote=row.price_native.quantize(_P),
                    liq_open_usd=row.liquidity_usd,
                    impact_open=impact.quantize(Decimal("0.000001")),
                    marked_at=self._now))
                counts[arm.name] = counts.get(arm.name, 0) + 1
                taken.add((arm.name, row.mint))
                opened += 1
        if opened or refused:
            logger.info("graduation_tournament_filled", opened=opened,
                        refused_unfillable=refused, candidates=len(rows))
        return opened
