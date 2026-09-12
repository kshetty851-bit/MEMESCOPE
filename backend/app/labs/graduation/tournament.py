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

from app.core.logging import get_logger
from app.labs.graduation import config
from app.labs.graduation.backtest import ExitPolicy, ExitState, TakeProfit, Tick, TrailingStop
from app.labs.graduation.models import GradPaperPosition, GradPostgradSample, GradToken
from app.labs.graduation.paper import _P, _Q, _rate, costs, in_hour_window, net_return

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

    async def _latest_prices(self, mints: Sequence[str]) -> dict[str, Decimal]:
        """One price per mint, at or before this tick's clock.

        `DISTINCT ON` rather than a query per position: fifty arms hold the
        same handful of tokens, and pricing each one once is the difference
        between six queries a tick and five hundred.
        """
        if not mints:
            return {}
        rows = (await self._session.execute(
            select(GradPostgradSample.mint, GradPostgradSample.price_native)
            .where(GradPostgradSample.mint.in_(list(mints)),
                   GradPostgradSample.price_native > 0,
                   GradPostgradSample.ts <= self._now)
            .distinct(GradPostgradSample.mint)
            .order_by(GradPostgradSample.mint, GradPostgradSample.ts.desc()))).all()
        return {r.mint: r.price_native for r in rows}

    async def _manage(self) -> int:
        positions = (await self._session.scalars(
            select(GradPaperPosition)
            .where(GradPaperPosition.closed_at.is_(None),
                   GradPaperPosition.notional_usd > 0))).all()
        if not positions:
            return 0
        prices = await self._latest_prices(sorted({p.mint for p in positions}))
        closed = 0
        for position in positions:
            arm = BY_NAME.get(position.book)
            if arm is None:
                continue
            price = prices.get(position.mint)
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
                    self._close(position, price, fired)
                    closed += 1
                    continue
            if age >= arm.hold:
                mark = price if price is not None else position.last_quote
                if mark is not None and mark > 0:
                    self._close(position, mark,
                                "max_hold" if price is not None else "end_of_data")
                    closed += 1
        return closed

    def _close(self, position: GradPaperPosition, quote: Decimal, reason: str) -> None:
        leg = costs(position.notional_quote)
        net = net_return(position, quote, leg) or Decimal(0)
        position.closed_at = self._now
        position.close_quote = quote.quantize(_P)
        position.close_fill = leg.sell_price(quote).quantize(_P)
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
        opens = (select(GradPostgradSample.mint,
                        func.min(GradPostgradSample.ts).label("open_at"))
                 .where(GradPostgradSample.price_native > 0,
                        GradPostgradSample.ts <= self._now)
                 .group_by(GradPostgradSample.mint)
                 .having(func.min(GradPostgradSample.ts) >= cutoff)
                 .order_by(func.min(GradPostgradSample.ts))
                 .limit(64)).subquery()
        return (await self._session.execute(
            select(opens.c.mint, opens.c.open_at,
                   GradPostgradSample.price_native, GradPostgradSample.price_usd,
                   GradPostgradSample.liquidity_usd, GradPostgradSample.fdv,
                   GradPostgradSample.txns_m5_sells, GradToken.symbol,
                   GradToken.first_seen_at)
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
        for row in rows:
            if row.price_native is None or row.price_native <= 0:
                continue
            rate = _rate(row.price_usd, row.price_native)
            if rate is None:
                continue
            notional_quote = (config.PAPER_NOTIONAL_USD / rate).quantize(_Q)
            fill = costs(notional_quote).buy_price(row.price_native)
            if fill <= 0:
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
                    marked_at=self._now))
                counts[arm.name] = counts.get(arm.name, 0) + 1
                taken.add((arm.name, row.mint))
                opened += 1
        if opened:
            logger.info("graduation_tournament_filled", opened=opened,
                        candidates=len(rows))
        return opened
