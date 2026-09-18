"""Restate the tournament's closed trades under the rules fixed on 2026-09-16.

An audit of the leading arm found three faults in how trades had been booked,
all fixed in the live tick the same day:

* a timed exit took the newest mark there was, however old — five B3 trades
  were closed on a price from before their pool was drained;
* the migration feed's `raydium-cpmm` events for JUP, PENGU and tokenized
  stocks were bought as graduations;
* fees were PumpSwap's flat 25 bps and a 0.002 SOL network fee, where the pool
  charges 30-125 bps by market cap, Jupiter takes 10 more, and the network fee
  is about a twentieth of that.

This walks every closed trade of the current arms and books it as the fixed
tick would have. A trade that was never a graduation is EXCLUDED — kept and
shown, never summed. What a row said before is written to
`grad_paper_restatements`, once; a restated row is not restated again.

Prices come from DexScreener rows only. The socket marks written before the
fix left out the pool's virtual reserve and read up to 2% low, and every
position has DexScreener rows around its exit anyway.

Dry run by default:
`python -m app.labs.graduation restate --opened-before ISO [--apply]`.

A second rule, `onchain-2026-09-18`, re-prices BASE_75k_5m's closed trades off
their pools' own swaps; see `restate_onchain`.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.labs.graduation import config, sources
from app.labs.graduation.backtest import amm_buy, amm_impact
from app.labs.graduation.held_watch import Held
from app.labs.graduation.models import (
    SOURCE_DEXSCREENER,
    GradPaperPosition,
    GradPaperRestatement,
    GradPostgradSample,
)
from app.labs.graduation.paper import _P, _Q, costs
from app.labs.graduation.tournament import (
    ARMS,
    BY_NAME,
    Mark,
    _timed_due,
    exit_mark,
    graduation_pool,
    seen_at,
    settle,
    valued,
)

RULE = "exit-fees-2026-09-16"
NOT_GRADUATION = "not_graduation_pool"
#: A trade whose pool was drained while it was open. Left out of every figure
#: on the operator's instruction (2026-09-16): the board shows what the arm
#: would have made had those tokens never been bought. It is a what-if — no
#: rule here could have avoided them in advance — so each row still shows what
#: it really lost, and the board states the total.
RUGGED = "rugged"
#: The board's arms only. The rug-signal A/B (`F01`, `F14`) is a pre-registered
#: experiment whose judge compares the P&L of the trades its filter refused —
#: leaving its rugs out would decide that verdict, and rewriting its closed
#: trades would change a record its rules were fixed before. Its history is
#: left exactly as it was booked.
BOOKS = tuple(a.name for a in ARMS if not a.ab_experiment)
#: Only these closes are re-timed. A stop fired on the mark in front of it,
#: and a retired arm or an ended series had no later mark to wait for; those
#: keep their exit and are re-charged only.
TIMED = "max_hold"


@dataclass(frozen=True, slots=True)
class Outcome:
    """What one restatement did, for the summary."""

    book: str
    reason: str
    excluded: str | None
    was_pnl_usd: Decimal
    now_pnl_usd: Decimal


def _snapshot(position: GradPaperPosition, *, reason: str,
              seen: datetime | None, source: str | None) -> GradPaperRestatement:
    return GradPaperRestatement(
        position_id=position.id, rule=RULE, reason=reason,
        was_open_fill=position.open_fill, was_tokens=position.tokens,
        was_close_quote=position.close_quote, was_close_fill=position.close_fill,
        was_close_reason=position.close_reason,
        was_liq_close_usd=position.liq_close_usd,
        was_pnl_quote=position.pnl_quote, was_pnl_usd=position.pnl_usd,
        was_net_return=position.net_return, was_closed_at=position.closed_at,
        exit_seen_at=seen, exit_source=source)


def restate_one(position: GradPaperPosition, *, pinned_pair: str | None,
                marks: list[Mark]) -> GradPaperRestatement:
    """Rebook one closed position in place and return what it said before.

    Pure apart from the position it is handed, so it can be tested without a
    database: `marks` are the mint's DexScreener rows around the trade.
    """
    if pinned_pair != graduation_pool(position.mint):
        audit = _snapshot(position, reason=NOT_GRADUATION, seen=None, source=None)
        position.excluded = NOT_GRADUATION
        return audit

    # The exit, re-timed if it was a timed exit. Any other exit keeps its
    # price and time and is only re-charged.
    quote, depth = position.close_quote, position.liq_close_usd
    reason, closed_at = position.close_reason or TIMED, position.closed_at
    seen = source = None
    restated_as = "fees"
    if position.close_reason == TIMED:
        due = position.opened_at + timedelta(minutes=BY_NAME[position.book].hold)
        out = exit_mark(marks, due)
        why = TIMED
        if out is None:
            # Nothing recorded after the exit was due: the newest mark the
            # book had, flagged as exactly that.
            before = [m for m in marks if m.ts is not None and m.ts <= closed_at]
            out = max(before, key=lambda m: m.ts) if before else None
            why = "stale_exit"
        if out is not None:
            quote, collapsed = valued(out, position.open_quote,
                                      position.liq_open_usd)
            depth, reason = out.depth, collapsed or why
            closed_at = max(closed_at, out.ts)
            seen, source = seen_at(out), out.source
            restated_as = reason
    audit = _snapshot(position, reason=restated_as, seen=seen, source=source)

    # The entry, re-charged: same price, the pool's real tier and the router.
    fee_bps = config.pool_fee_bps(position.open_quote)
    leg = costs(position.notional_quote, pool_fee_bps=fee_bps)
    fill = amm_buy(position.open_quote, order_usd=position.notional_usd,
                   liquidity_usd=position.liq_open_usd,
                   fee_fraction=leg.fee_fraction) or leg.buy_price(position.open_quote)
    position.pool_fee_bps = fee_bps
    position.open_fill = fill.quantize(_P)
    position.tokens = (position.notional_quote / fill).quantize(_Q)
    settle(position, quote, depth, reason, closed_at)
    if reason == "pool_collapsed":
        position.excluded = RUGGED
    return audit


async def _marks(session: AsyncSession, mints: list[str], start: datetime,
                 end: datetime) -> dict[str, list[Mark]]:
    out: dict[str, list[Mark]] = defaultdict(list)
    for i in range(0, len(mints), 200):
        for r in (await session.execute(
                select(GradPostgradSample.mint, GradPostgradSample.price_native,
                       GradPostgradSample.liquidity_usd, GradPostgradSample.ts,
                       GradPostgradSample.source)
                .where(GradPostgradSample.mint.in_(mints[i:i + 200]),
                       GradPostgradSample.source == SOURCE_DEXSCREENER,
                       GradPostgradSample.price_native > 0,
                       GradPostgradSample.ts >= start,
                       GradPostgradSample.ts <= end))).all():
            out[r.mint].append(Mark(r.price_native, r.liquidity_usd, r.ts, r.source))
    return out


async def _pinned(session: AsyncSession, mints: list[str]) -> dict[str, str | None]:
    """The pair each mint was priced on: its first DexScreener row's."""
    out: dict[str, str | None] = {}
    for i in range(0, len(mints), 500):
        for mint, pair in (await session.execute(
                select(GradPostgradSample.mint, GradPostgradSample.pair_address)
                .where(GradPostgradSample.mint.in_(mints[i:i + 500]),
                       GradPostgradSample.source == SOURCE_DEXSCREENER,
                       GradPostgradSample.price_native > 0)
                .distinct(GradPostgradSample.mint)
                .order_by(GradPostgradSample.mint, GradPostgradSample.ts))).all():
            out[mint] = pair
    return out


async def restate(session: AsyncSession, *, apply: bool,
                  opened_before: datetime) -> dict[str, Any]:
    """Every closed, not yet restated trade of the current arms that was opened
    before `opened_before` — the moment the fixed tick went live. A trade
    opened after it was bought and sold by the fixed rules already."""
    done = select(GradPaperRestatement.position_id)
    positions = (await session.scalars(
        select(GradPaperPosition)
        .where(GradPaperPosition.book.in_(BOOKS),
               GradPaperPosition.opened_at < opened_before,
               GradPaperPosition.closed_at.is_not(None),
               GradPaperPosition.notional_usd > 0,
               GradPaperPosition.close_quote > 0,
               GradPaperPosition.id.not_in(done))
        .order_by(GradPaperPosition.opened_at))).all()
    if not positions:
        return {"rule": RULE, "applied": apply, "restated": 0}
    mints = sorted({p.mint for p in positions})
    pinned = await _pinned(session, mints)
    wait = timedelta(seconds=config.EXIT_MAX_WAIT_S + config.FEED_LAG_S)
    marks = await _marks(session, mints, min(p.opened_at for p in positions),
                         max(p.closed_at for p in positions) + wait)

    outcomes: list[Outcome] = []
    for position in positions:
        was = position.pnl_usd or Decimal(0)
        audit = restate_one(position, pinned_pair=pinned.get(position.mint),
                            marks=marks.get(position.mint, []))
        session.add(audit)
        now = position.pnl_usd or Decimal(0)
        outcomes.append(Outcome(position.book, audit.reason, position.excluded,
                                was, now))
    if apply:
        await session.flush()
    else:
        await session.rollback()

    books: dict[str, dict[str, Any]] = {}
    zero = Decimal(0)
    for o in outcomes:
        b = books.setdefault(o.book, {"trades": 0, "not_graduation": 0,
                                      "rugged": 0, "reasons": {},
                                      "was_usd": zero, "counted_usd": zero,
                                      "rugged_usd": zero})
        b["trades"] += 1
        b["not_graduation"] += o.excluded == NOT_GRADUATION
        b["rugged"] += o.excluded == RUGGED
        b["reasons"][o.reason] = b["reasons"].get(o.reason, 0) + 1
        b["was_usd"] += o.was_pnl_usd
        if o.excluded is None:
            b["counted_usd"] += o.now_pnl_usd
        elif o.excluded == RUGGED:
            b["rugged_usd"] += o.now_pnl_usd
    return {"rule": RULE, "applied": apply, "restated": len(outcomes),
            "books": {k: {**v, **{f: str(v[f]) for f in
                                  ("was_usd", "counted_usd", "rugged_usd")}}
                      for k, v in books.items()}}


# --- onchain-2026-09-18 -----------------------------------------------------
#
# The book bought at DexScreener's FIRST report on each new pool, which can
# predate the pool's first big buy: Bluey (17 Sep) was booked at +1,044% on a
# price 11x under where its pool already traded, and made +4% on-chain. Exits
# missed drains the same way when the feed lagged them. Replayed off the pools'
# own swaps, BASE_75k_5m's +$187 at $20 a trade was -$3. New trades are priced
# off the pool since 2026-09-18; this rebooks the ones before.

ONCHAIN_RULE = "onchain-2026-09-18"
#: The book the real wallet copies. Its $75k floor admits pools DexScreener
#: first reports before their first big buy; the deeper books' first reports
#: come after it. The A/B experiments are never restated (see `BOOKS`).
ONCHAIN_BOOKS = ("BASE_75k_5m",)
ONCHAIN = "onchain"
#: `exit_source` for a price read off the pool's own swaps.
CHAIN = "chain"


def _at(held: Held, reserves: tuple[int, int], sol_usd: Decimal
        ) -> tuple[Decimal, Decimal] | None:
    """Price and depth of `held`'s pool when it held `reserves`."""
    snap = replace(held, base=reserves[0], quote=reserves[1])
    price, depth = snap.price(), snap.depth_usd(sol_usd)
    return (price, depth) if price and depth else None


def restate_one_onchain(position: GradPaperPosition, *, held: Held,
                        entry: tuple[int, int], exit: tuple[int, int],
                        prior: GradPaperRestatement | None
                        ) -> GradPaperRestatement | None:
    """Rebook one closed trade at its pool's own prices: bought at the reserves
    when it was taken, sold at the reserves its first swap at or after the exit
    was due left (the book's own exit rule), by the same arithmetic as a live
    trade. None, and the row untouched, when either reading cannot be priced.

    What the row said FIRST stays in the audit: an earlier rule's row keeps its
    figures and takes this rule's name. A drain found here is counted like any
    other trade — the board's what-if covered drains up to 16 Sep — but a trade
    that rule already left out stays out.
    """
    sol_usd = position.sol_usd_at_open
    bought, sold = _at(held, entry, sol_usd), _at(held, exit, sol_usd)
    if bought is None or sold is None:
        return None
    audit = prior or _snapshot(position, reason=ONCHAIN, seen=None, source=None)

    price, depth = bought
    fee_bps = config.pool_fee_bps(price)
    leg = costs(position.notional_quote, pool_fee_bps=fee_bps)
    fill = amm_buy(price, order_usd=position.notional_usd, liquidity_usd=depth,
                   fee_fraction=leg.fee_fraction) or leg.buy_price(price)
    impact = amm_impact(position.notional_usd, depth)
    position.open_quote = price.quantize(_P)
    position.peak_quote = max(position.peak_quote or position.open_quote,
                              position.open_quote)
    position.pool_fee_bps = fee_bps
    position.open_fill = fill.quantize(_P)
    position.tokens = (position.notional_quote / fill).quantize(_Q)
    position.impact_open = (None if impact is None
                            else impact.quantize(Decimal("0.000001")))

    due = _timed_due(position)
    quote, collapsed = valued(Mark(sold[0], sold[1], due, CHAIN),
                              position.open_quote, position.liq_open_usd)
    settle(position, quote, sold[1], collapsed or TIMED, position.closed_at)

    audit.rule = ONCHAIN_RULE
    audit.reason = "pool_collapsed" if position.excluded == RUGGED else ONCHAIN
    audit.exit_seen_at, audit.exit_source = due, CHAIN
    return audit


async def restate_onchain(
    session: AsyncSession, *, rpc: object,
    resolve: Callable[[str, str], Awaitable[Held | None]],
    apply: bool, opened_before: datetime,
) -> dict[str, Any]:
    """Every closed ONCHAIN_BOOKS trade opened before `opened_before` (when the
    tick began pricing entries off the pool) and not yet under this rule.

    `rpc` answers Helius's `getTransactionsForAddress`; `resolve` turns a pool
    into its decoded form (vaults, decimals, virtual reserve). A trade either
    reading misses is left exactly as booked and counted as `unpriced`.
    """
    positions = (await session.scalars(
        select(GradPaperPosition)
        .where(GradPaperPosition.book.in_(ONCHAIN_BOOKS),
               GradPaperPosition.opened_at < opened_before,
               GradPaperPosition.closed_at.is_not(None),
               GradPaperPosition.notional_usd > 0,
               GradPaperPosition.close_quote > 0,
               or_(GradPaperPosition.excluded.is_(None),
                   GradPaperPosition.excluded != NOT_GRADUATION))
        .order_by(GradPaperPosition.opened_at))).all()
    prior = {r.position_id: r for r in (await session.scalars(
        select(GradPaperRestatement).where(
            GradPaperRestatement.position_id.in_([p.id for p in positions])))).all()}
    todo = [p for p in positions
            if p.id not in prior or prior[p.id].rule != ONCHAIN_RULE]
    pinned = await _pinned(session, sorted({p.mint for p in todo}))
    pools: dict[str, Held | None] = {}
    moves: list[tuple[Decimal, str, Decimal, Decimal]] = []
    zero = Decimal(0)
    was = now = was20 = now20 = zero
    unpriced = restated = 0
    for position in todo:
        pool = pinned.get(position.mint)
        if pool is None or pool != graduation_pool(position.mint):
            unpriced += 1
            continue
        if position.mint not in pools:
            try:
                pools[position.mint] = await resolve(position.mint, pool)
            except ConnectionError:
                pools[position.mint] = None
        held = pools[position.mint]
        entry = held and await sources.reserves_at(
            rpc, mint=position.mint, pool=pool, at=position.opened_at)
        due = _timed_due(position)
        exit_ = entry and (
            await sources.reserves_after(rpc, mint=position.mint, pool=pool, at=due,
                                         within_s=config.EXIT_MAX_WAIT_S)
            or await sources.reserves_at(rpc, mint=position.mint, pool=pool, at=due))
        before_usd = position.pnl_usd or zero
        before_ret = position.net_return or zero
        audit = (restate_one_onchain(position, held=held, entry=entry, exit=exit_,
                                     prior=prior.get(position.id))
                 if held and entry and exit_ else None)
        if audit is None:
            unpriced += 1
            continue
        if position.id not in prior:
            session.add(audit)
        restated += 1
        after_ret = position.net_return or zero
        if position.excluded is None:
            was, now = was + before_usd, now + (position.pnl_usd or zero)
            was20, now20 = was20 + 20 * before_ret, now20 + 20 * after_ret
        moves.append((abs(after_ret - before_ret), position.symbol or position.mint[:8],
                      before_ret, after_ret))
    if apply:
        await session.flush()
    else:
        await session.rollback()
    moves.sort(reverse=True)
    return {"rule": ONCHAIN_RULE, "applied": apply, "books": list(ONCHAIN_BOOKS),
            "restated": restated, "unpriced": unpriced,
            "counted_was_usd": str(was), "counted_now_usd": str(now),
            "counted_was_at_20": str(was20.quantize(Decimal("0.01"))),
            "counted_now_at_20": str(now20.quantize(Decimal("0.01"))),
            "biggest_moves": [{"token": t, "was": str(b.quantize(Decimal("0.0001"))),
                               "now": str(a.quantize(Decimal("0.0001")))}
                              for _, t, b, a in moves[:8]]}

