"""Long-watch Lab (Karthik, 2026-10-22: "build all").

The track record showed we stop pricing a graduation after ~2 hours, so the
big multiples were still climbing when we stopped looking, and a coin like
Kimchi (-90%, then 922x eighteen hours later) is invisible. This lab:

  * COLLECTS a DexScreener reading of every graduation every 10 minutes for
    48 hours after it graduates (30 coins per call);
  * RUNNER book: at about 60 minutes after graduating, buys a coin that is
    3x+ its first price with a pool 2x+ its first size and more buyers than
    sellers in the last hour; sells on a 40% fall from its high or after 6 h;
  * SECOND WIND book: buys a coin 2-48 h old that fell 80%+ from its
    first-hour high and has since tripled off its low with $50k+ traded in the
    last hour and more buyers than sellers; sells on a 40% fall from its high
    or after 24 h.

Paper only, $25 a trade on $500 each, fills priced on the reading's pool with
impact and fees. The rules were fixed before any data: judge them forward.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx
from sqlalchemy import delete, func, select, text

from app.core.logging import get_logger
from app.lab import execution
from app.labs.longwatch.models import LongwatchBook, LongwatchPosition, LongwatchReading

logger = get_logger(__name__)

WATCH = timedelta(hours=48)
KEEP = timedelta(days=14)
BATCH = 30
SPACING_S = 0.4
DEX = "https://api.dexscreener.com/tokens/v1/solana/"
START_USD, TRADE_USD, MAX_OPEN = Decimal(500), Decimal(25), 20
#: The pool's swap fee each way, on top of the shared fill model's impact.
POOL_FEE = Decimal("0.0125")
TRAIL = Decimal("0.40")
RUNNER = dict(book="runner", at_min=(55, 80), x=3, pool_x=2, min_pool=5_000, hold=timedelta(hours=6))
SECOND = dict(book="secondwind", age_h=(2, 48), crash=0.2, rebound=3, vol_h1=50_000,
              min_pool=10_000, hold=timedelta(hours=24))
BOOKS = (RUNNER["book"], SECOND["book"])
RUNNER_ON = False


def _d(v: Any) -> Decimal | None:
    try:
        return Decimal(str(v)) if v not in (None, "") else None
    except Exception:
        return None


def pick_pair(pairs: list[dict], mint: str, pool: str | None) -> dict | None:
    """The graduation's own pool when DexScreener lists it, else the deepest
    PumpSwap pair (DexScreener returns every pool in an unstable order)."""
    mine = [p for p in pairs if (p.get("baseToken") or {}).get("address") == mint]
    for p in mine:
        if pool and p.get("pairAddress") == pool:
            return p
    swap = [p for p in mine if p.get("dexId") == "pumpswap"] or mine
    return max(swap, key=lambda p: float((p.get("liquidity") or {}).get("usd") or 0), default=None)


async def collect(session, now: datetime, client: httpx.AsyncClient) -> int:
    """One reading for every coin graduated in the last 48 hours."""
    rows = (await session.execute(text("""
        select distinct on (mint) mint, pool from grad_migrations
        where ts >= :lo and ts < :hi order by mint, ts"""), {"lo": now - WATCH, "hi": now})).all()
    pool_of = {m: p for m, p in rows}
    mints = list(pool_of)
    out = []
    for i in range(0, len(mints), BATCH):
        chunk = mints[i:i + BATCH]
        for attempt in range(3):
            try:
                r = await client.get(DEX + ",".join(chunk), timeout=20)
                if r.status_code == 429:
                    await asyncio.sleep(5 * (attempt + 1))
                    continue
                r.raise_for_status()
                pairs = [p for p in r.json() or [] if isinstance(p, dict)]
                break
            except (httpx.HTTPError, ValueError):
                await asyncio.sleep(2)
        else:
            continue
        by_mint: dict[str, list[dict]] = defaultdict(list)
        for p in pairs:
            by_mint[(p.get("baseToken") or {}).get("address")].append(p)
        for m in chunk:
            p = pick_pair(by_mint.get(m, []), m, pool_of[m])
            if p is None:
                continue
            tx = (p.get("txns") or {}).get("h1") or {}
            out.append(LongwatchReading(
                mint=m, ts=now, pair=p.get("pairAddress"), price_usd=_d(p.get("priceUsd")),
                liquidity_usd=_d((p.get("liquidity") or {}).get("usd")), fdv=_d(p.get("fdv")),
                volume_h1=_d((p.get("volume") or {}).get("h1")), buys_h1=tx.get("buys"), sells_h1=tx.get("sells")))
        await asyncio.sleep(SPACING_S)
    session.add_all(out)
    await session.execute(delete(LongwatchReading).where(LongwatchReading.ts < now - KEEP))
    await session.flush()
    return len(out)


async def _book(session, name: str, now: datetime) -> LongwatchBook:
    b = await session.get(LongwatchBook, name)
    if b is None:
        b = LongwatchBook(book=name, started_at=now, cash_usd=START_USD)
        session.add(b)
        await session.flush()
    return b


def _buy_qty(price: Decimal, liq: Decimal) -> Decimal | None:
    return execution.buy_quantity(TRADE_USD * (1 - POOL_FEE), price, liq)


def _sell(qty: Decimal, price: Decimal, liq: Decimal) -> Decimal:
    return execution.sell_proceeds(qty, price, liq) * (1 - POOL_FEE)


async def _open(session, b: LongwatchBook, mint: str, symbol: str | None, price: Decimal,
                liq: Decimal, now: datetime, trigger: dict) -> str:
    held = await session.scalar(select(func.count()).select_from(LongwatchPosition).where(
        LongwatchPosition.book == b.book, LongwatchPosition.status == "open"))
    if held >= MAX_OPEN:
        return "max_open"
    if b.cash_usd < TRADE_USD:
        return "no_cash"
    if await session.scalar(select(LongwatchPosition.id).where(
            LongwatchPosition.book == b.book, LongwatchPosition.mint == mint)):
        return "already_traded"
    qty = _buy_qty(price, liq)
    if not qty:
        return "unpriceable"
    session.add(LongwatchPosition(book=b.book, mint=mint, symbol=(symbol or "")[:64] or None, opened_at=now,
                                  entry_price=price, quantity=qty, spent_usd=TRADE_USD, peak_price=price,
                                  last_price=price, last_liquidity_usd=liq, status="open", trigger=trigger))
    b.cash_usd -= TRADE_USD
    await session.flush()
    return "opened"


_LATEST = text("""
select distinct on (mint) mint, price_usd, liquidity_usd, volume_h1, buys_h1, sells_h1
from longwatch_readings where ts = :now order by mint""")

_FIRST = text("""
select x.mint,
  (select price_usd from grad_postgrad_samples p where p.mint = x.mint and p.price_usd > 0 order by p.ts limit 1),
  (select liquidity_usd from grad_postgrad_samples p where p.mint = x.mint and p.price_usd > 0 order by p.ts limit 1),
  (select symbol from grad_tokens t where t.mint = x.mint)
from unnest(cast(:mints as varchar[])) as x(mint)""")


async def decide(session, now: datetime) -> dict[str, int]:
    """Entries for both books from this tick's readings."""
    counts: dict[str, int] = defaultdict(int)
    latest = {m: (p, liq, vol, b, s) for m, p, liq, vol, b, s in (await session.execute(_LATEST, {"now": now})).all()}
    if not latest:
        return counts
    grads = dict((await session.execute(text("""
        select distinct on (mint) mint, ts from grad_migrations
        where mint = any(:mints) order by mint, ts"""), {"mints": list(latest)})).all())
    runner_lo, runner_hi = (timedelta(minutes=m) for m in RUNNER["at_min"])
    # Karthik, 2026-10-22: "turn off runner". Its backtest since 1 Oct lost
    # $745 over 181 trades (-$4.12 a $25 trade, 177 sold on the trail).
    runners = [m for m, g in grads.items() if runner_lo <= now - g <= runner_hi] if RUNNER_ON else []
    second_lo, second_hi = (timedelta(hours=h) for h in SECOND["age_h"])
    seconds = [m for m, g in grads.items() if second_lo <= now - g <= second_hi
               and (latest[m][2] or 0) >= SECOND["vol_h1"] and (latest[m][1] or 0) >= SECOND["min_pool"]
               and (latest[m][3] or 0) > (latest[m][4] or 0)]
    first = {m: (p, liq, sym) for m, p, liq, sym in (await session.execute(_FIRST, {"mints": runners + seconds})).all()}

    rb = await _book(session, RUNNER["book"], now)
    for m in runners:
        p, liq, vol, buys, sells = latest[m]
        p0, l0, sym = first.get(m, (None, None, None))
        if not (p and liq and p0 and l0) or l0 < RUNNER["min_pool"]:
            continue
        if p >= p0 * RUNNER["x"] and liq >= l0 * RUNNER["pool_x"] and (buys or 0) > (sells or 0):
            counts["runner_" + await _open(session, rb, m, sym, p, liq, now, {
                "x_vs_first": float(p / p0), "pool_x": float(liq / l0), "buys_h1": buys, "sells_h1": sells})] += 1

    sb = await _book(session, SECOND["book"], now)
    for m in seconds:
        p, liq, vol, buys, sells = latest[m]
        g = grads[m]
        hist = (await session.execute(text("""
            select max(price_usd) filter (where ts <= :h1), min(price_usd) filter (where ts > :h1)
            from (select ts, price_usd from grad_postgrad_samples where mint = :m and price_usd > 0
                  union all select ts, price_usd from longwatch_readings where mint = :m and price_usd > 0 and ts < :now) x"""),
            {"m": m, "h1": g + timedelta(hours=1), "now": now})).one()
        hi1, low = hist
        if not (p and hi1 and low) or low > hi1 * Decimal(str(SECOND["crash"])):
            continue
        if p >= low * SECOND["rebound"]:
            counts["secondwind_" + await _open(session, sb, m, first.get(m, (None, None, None))[2], p, liq, now, {
                "first_hour_high": float(hi1), "low": float(low), "x_off_low": float(p / low),
                "volume_h1": float(vol or 0), "buys_h1": buys, "sells_h1": sells})] += 1
    return counts


async def manage(session, now: datetime) -> int:
    """Mark every open lot to this tick's reading; sell on the trail or the clock."""
    latest = {m: (p, liq) for m, p, liq, *_ in (await session.execute(_LATEST, {"now": now})).all()}
    closed = 0
    for pos in (await session.scalars(select(LongwatchPosition).where(LongwatchPosition.status == "open"))).all():
        hold = RUNNER["hold"] if pos.book == RUNNER["book"] else SECOND["hold"]
        p, liq = latest.get(pos.mint, (None, None))
        if p and liq:
            pos.last_price, pos.last_liquidity_usd = p, liq
            pos.peak_price = max(pos.peak_price, p)
        reason = None
        if p and p <= pos.peak_price * (1 - TRAIL):
            reason = "trailing_stop"
        elif now - pos.opened_at >= hold:
            reason = "time"
        if reason is None or not pos.last_price or not pos.last_liquidity_usd:
            continue
        proceeds = _sell(pos.quantity, pos.last_price, pos.last_liquidity_usd)
        pos.status, pos.closed_at, pos.exit_price = "closed", now, pos.last_price
        pos.proceeds_usd, pos.reason = proceeds, reason
        b = await session.get(LongwatchBook, pos.book)
        b.cash_usd += proceeds
        closed += 1
    await session.flush()
    return closed


async def board(session, now: datetime) -> dict[str, Any]:
    out: dict[str, Any] = {"note": "Paper only. Rules fixed on 22 Oct 2026 before any data; judge them forward."}
    stats = (await session.execute(text("""
        select count(distinct mint) filter (where ts >= :since), count(*) filter (where ts >= :day), max(ts)
        from longwatch_readings"""), {"since": now - timedelta(minutes=15), "day": now - timedelta(days=1)})).one()
    out["collector"] = {"coins_now": stats[0], "readings_24h": stats[1],
                        "last_at": stats[2].isoformat() if stats[2] else None}
    books = []
    for name, rule in ((RUNNER["book"], RUNNER), (SECOND["book"], SECOND)):
        b = await session.get(LongwatchBook, name)
        rows = (await session.scalars(select(LongwatchPosition).where(LongwatchPosition.book == name)
                                      .order_by(LongwatchPosition.opened_at.desc()).limit(60))).all()
        all_closed = (await session.execute(select(func.count(), func.coalesce(func.sum(LongwatchPosition.proceeds_usd - LongwatchPosition.spent_usd), 0),
                                                   func.count().filter(LongwatchPosition.proceeds_usd > LongwatchPosition.spent_usd))
                                            .where(LongwatchPosition.book == name, LongwatchPosition.status == "closed"))).one()
        open_rows = [r for r in rows if r.status == "open"]
        open_value = sum((_sell(r.quantity, r.last_price, r.last_liquidity_usd) for r in open_rows
                          if r.last_price and r.last_liquidity_usd), Decimal(0))
        cash = b.cash_usd if b else START_USD
        books.append({
            "book": name, "started_at": b.started_at.isoformat() if b else None,
            "cash_usd": float(cash), "open_value_usd": float(open_value),
            "equity_usd": float(cash + open_value), "pnl_usd": float(cash + open_value - START_USD),
            "closed": all_closed[0], "closed_pnl_usd": float(all_closed[1]), "wins": all_closed[2],
            "open": len(open_rows), "max_open": MAX_OPEN, "trade_usd": float(TRADE_USD),
            "positions": [{
                "mint": r.mint, "symbol": r.symbol, "status": r.status, "opened_at": r.opened_at.isoformat(),
                "closed_at": r.closed_at.isoformat() if r.closed_at else None, "reason": r.reason,
                "x": float((r.exit_price or r.last_price or r.entry_price) / r.entry_price),
                "peak_x": float(r.peak_price / r.entry_price),
                "pnl_usd": float((r.proceeds_usd if r.proceeds_usd is not None else
                                  (_sell(r.quantity, r.last_price, r.last_liquidity_usd) if r.last_price and r.last_liquidity_usd else r.spent_usd))
                                 - r.spent_usd),
                "trigger": r.trigger} for r in rows],
        })
    out["books"] = books
    return out
