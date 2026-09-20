"""The real wallet's money-source checks, applied to the lab's own buys, so no
book trades a coin the wallet would refuse (Karthik, 2026-09-19). Before this
the board counted trades the wallet could never have taken.

The wallet's two checks, as the wallet applies them:
- the addresses blocked for good (`app.core.rug_money`), each from the moment
  it went live;
- the wallets and funders behind any trade that lost `REAL_WALLET_RUG_RETURN`
  or worse and closed in the last `REAL_WALLET_SOURCE_BLOCK_HOURS`.

A coin's addresses are the ones `_fill_fast` read for it (`grad_operators.ids`):
every wallet holding 1% or more and the first funder of each. The wallet
traces only the two biggest; this is the same people plus any bundle wallets.
A coin with nothing recorded cannot be checked and is not refused: the wallet
traces every coin itself, the lab records only pools over $50k.

The lab adds one check of its own (Karthik, 2026-09-20): an address already
seen on `REPEAT_MIN_COINS` coins with `REPEAT_MIN_RUG_RATE` of them rugged
BEFORE this buy refuses the coin. Three of the four rugs that cost the fresh
$75k book came from wallets nobody had seen, so blocking addresses by hand is
always one rug late; this refuses the next repeat operator on its own record.
Only labels already written count, so nothing here is decided with hindsight.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.rug_money import BLOCKED_SINCE
from app.labs.graduation import config
from app.labs.graduation.models import GradOperator, GradPaperPosition

#: What `excluded` says on a trade the wallet's checks would have refused.
EXCLUDED = "wallet_blocked"
KNOWN = "known_rug_money"
LINKED = "linked_to_recent_rug"
REPEAT = "repeat_rug_operator"


def _window() -> timedelta:
    return timedelta(hours=settings.REAL_WALLET_SOURCE_BLOCK_HOURS)


def refused(ids: Iterable[str], at: datetime, recent: set[str],
            repeat: set[str] | frozenset[str] = frozenset()) -> str | None:
    """Why the wallet would refuse a coin with these addresses at `at`, or None."""
    ids = set(ids)
    if any((since := BLOCKED_SINCE.get(a)) is not None and since <= at for a in ids):
        return KNOWN
    if ids & repeat:
        return REPEAT
    return LINKED if ids & recent else None


#: Every address that had already rugged its way past the thresholds, and when
#: it was read. Held for `REPEAT_TTL_S`: the tick runs every three seconds and
#: the labels move in minutes.
_REPEAT: tuple[datetime, frozenset[str]] | None = None

#: Addresses by their record BEFORE `at`: coins they were seen on, and how many
#: of those were already labelled rugged. An unlabelled coin counts for neither.
_REPEAT_SQL = text("""
    select w as wallet
    from grad_operators o, unnest(o.ids) as w
    where o.entry_at < :at
    group by w
    having count(*) >= :coins
       and 100 * count(*) filter (where o.rugged and o.labelled_at < :at)
           >= :pct * count(*)
""")


async def repeat_rug_ids(session: AsyncSession, at: datetime) -> frozenset[str]:
    """The addresses that have rugged enough coins, by now, to be refused."""
    global _REPEAT
    if _REPEAT is not None and (at - _REPEAT[0]).total_seconds() < config.REPEAT_TTL_S:
        return _REPEAT[1]
    rows = await session.scalars(_REPEAT_SQL, {
        "at": at, "coins": config.REPEAT_MIN_COINS,
        "pct": config.REPEAT_MIN_RUG_PCT})
    _REPEAT = (at, frozenset(rows))
    return _REPEAT[1]


async def recent_rug_ids(session: AsyncSession, at: datetime) -> set[str]:
    """Every address behind a lab trade that closed at a rug's loss in the
    window before `at`: the wallet's three-hour list, off the lab's own books."""
    rugs = (select(GradPaperPosition.mint)
            .where(GradPaperPosition.closed_at > at - _window(),
                   GradPaperPosition.closed_at <= at,
                   GradPaperPosition.net_return <= settings.REAL_WALLET_RUG_RETURN))
    rows = await session.scalars(select(GradOperator.ids).where(
        GradOperator.mint.in_(rugs), GradOperator.ids.is_not(None)))
    return {a for ids in rows for a in ids}


async def refusals(session: AsyncSession, mints: Iterable[str],
                   at: datetime) -> dict[str, str]:
    """Mint -> reason, for the coins among `mints` the wallet would refuse now."""
    mints = list(mints)
    if not mints:
        return {}
    await session.flush()   # this tick's operator reads, before they are looked up
    ids = dict((await session.execute(
        select(GradOperator.mint, GradOperator.ids)
        .where(GradOperator.mint.in_(mints), GradOperator.ids.is_not(None)))).all())
    if not ids:
        return {}
    recent = await recent_rug_ids(session, at)
    repeat = await repeat_rug_ids(session, at)
    return {m: why for m, found in ids.items()
            if (why := refused(found, at, recent, repeat))}


async def restate(session: AsyncSession, *, since: datetime, apply: bool) -> dict[str, Any]:
    """Mark every closed trade opened since `since` that the wallet's checks, as
    they stood when it opened, would have refused. Only unmarked trades are
    touched, so a second run adds nothing it already counted."""
    positions = (await session.scalars(
        select(GradPaperPosition)
        .where(GradPaperPosition.opened_at >= since,
               GradPaperPosition.closed_at.is_not(None),
               GradPaperPosition.excluded.is_(None))
        .order_by(GradPaperPosition.opened_at))).all()
    rugs = (await session.execute(
        select(GradPaperPosition.mint, GradPaperPosition.closed_at)
        .where(GradPaperPosition.closed_at > since - _window(),
               GradPaperPosition.net_return <= settings.REAL_WALLET_RUG_RETURN))).all()
    mints = {p.mint for p in positions} | {m for m, _ in rugs}
    ids = dict((await session.execute(
        select(GradOperator.mint, GradOperator.ids)
        .where(GradOperator.mint.in_(mints), GradOperator.ids.is_not(None)))).all())
    marked: Counter[str] = Counter()
    pnl: Counter[str] = Counter()
    for p in positions:
        found = ids.get(p.mint)
        if not found:
            continue
        recent = {a for m, closed in rugs
                  if p.opened_at - _window() < closed <= p.opened_at
                  for a in ids.get(m) or ()}
        # The repeat-rugger list is deliberately left out of a restatement: it
        # is read live and its record grows, so applying today's list to a trade
        # from two days ago would be hindsight, which is what `restate` exists
        # to avoid.
        if refused(found, p.opened_at, recent) is None:
            continue
        marked[p.book] += 1
        pnl[p.book] += float(p.pnl_usd or 0)
        if apply:
            p.excluded = EXCLUDED
    return {"trades_checked": len(positions), "marked": dict(marked),
            "pnl_usd_left_out": {b: round(v, 2) for b, v in pnl.items()},
            "applied": apply}
