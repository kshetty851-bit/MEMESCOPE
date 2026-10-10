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

SAME NAME (Karthik, 2026-09-29, after NTDA): a coin whose symbol belongs to a
coin that closed at a rug's loss on any book in the last
`SAME_NAME_BLOCK_HOURS` is refused. Two NTDAs rugged 17 minutes apart from
wallets that shared no address, so the address checks passed the second.
Replayed on the real wallet since 21 Sep: 13 of 289 trades skipped, 1 of 6
rugs prevented, +$23 -> +$63; 1-3h helped in every $75k book, 6h+ hurt.
Chosen after seeing the rug it prevents.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Sequence
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.rug_money import BLOCKED_SINCE
from app.labs.graduation import config
from app.labs.graduation.models import GradOperator, GradPaperPosition, GradToken

#: What `excluded` says on a trade the wallet's checks would have refused.
EXCLUDED = "wallet_blocked"
KNOWN = "known_rug_money"
LINKED = "linked_to_recent_rug"
REPEAT = "repeat_rug_operator"
SAME_NAME = "same_name_as_recent_rug"
SAME_NAME_BLOCK_HOURS = 3


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


#: Every address behind a coin that ever rugged on any book, and when it was
#: read. Held for `config.RUG_LINKED_TTL_S`.
_RUG_LINKED: tuple[datetime, frozenset[str]] | None = None

#: Addresses behind a trade that had ALREADY CLOSED at a rug's loss. The
#: `closed_at < :at` is the whole point — a list built from the future would
#: refuse a coin for something that had not happened yet.
_RUG_LINKED_SQL = text("""
    select distinct w
    from grad_paper_positions p
    join grad_operators o on o.mint = p.mint, unnest(o.ids) as w
    where p.closed_at is not null and p.closed_at < :at
      and p.net_return <= :rug
""")


async def rug_linked_ids(session: AsyncSession, at: datetime) -> frozenset[str]:
    """Every address seen on a coin that has already rugged.

    WIDER than `repeat_rug_ids` on purpose, and only some arms ask for it
    (`Arm.rug_blocked`). Measured 2026-09-23 over four books: it takes the
    BASELINE from +$978 to +$1,609 and its rugs from 41 to 18, and it takes
    B5_500k_flow_5m from +$256 to +$229 while preventing none, because B5 has
    never had a rug to prevent. So it is worth having where rugs are frequent
    and a pure tax where they are not — which is why it is per-arm rather than
    a rule for the whole board.
    """
    global _RUG_LINKED
    if (_RUG_LINKED is not None
            and (at - _RUG_LINKED[0]).total_seconds() < config.RUG_LINKED_TTL_S):
        return _RUG_LINKED[1]
    rows = await session.scalars(
        _RUG_LINKED_SQL, {"at": at, "rug": float(settings.REAL_WALLET_RUG_RETURN)})
    _RUG_LINKED = (at, frozenset(rows))
    return _RUG_LINKED[1]


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


def _name(symbol: str | None) -> str | None:
    return (symbol or "").strip().lower() or None


async def recent_rug_names(session: AsyncSession, at: datetime) -> set[str]:
    """Symbols of coins that closed at a rug's loss on any book in the last
    `SAME_NAME_BLOCK_HOURS` before `at`."""
    rows = await session.scalars(select(GradPaperPosition.symbol).where(
        GradPaperPosition.closed_at > at - timedelta(hours=SAME_NAME_BLOCK_HOURS),
        GradPaperPosition.closed_at <= at,
        GradPaperPosition.net_return <= settings.REAL_WALLET_RUG_RETURN))
    return {n for s in rows if (n := _name(s))}


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
    out: dict[str, str] = {}
    if ids:
        recent = await recent_rug_ids(session, at)
        repeat = await repeat_rug_ids(session, at)
        out = {m: why for m, found in ids.items()
               if (why := refused(found, at, recent, repeat))}
    # The name check needs no addresses: a coin nobody traced is still named.
    names = await recent_rug_names(session, at)
    if names:
        symbols = (await session.execute(
            select(GradToken.mint, GradToken.symbol).where(GradToken.mint.in_(mints)))).all()
        for mint, symbol in symbols:
            if mint not in out and _name(symbol) in names:
                out[mint] = SAME_NAME
    return out


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


# --- The crew of a bad coin (Karthik, 2026-10-10) ----------------------------
#
# "block such creators", then "anything more than 30% loss, flag as rug so we
# don't buy those again": after SI and TM, two -46% coins one morning from one
# crew. SI's creator sold 80 SOL 76s after the buy; a partner wallet sold
# 100 SOL from TM 76s after, with SI's creator sitting inside TM.
#
# A coin that closed at CREW_RETURN or worse on any book puts its creator and
# its RARE insider wallets (on CREW_MAX_COINS coins or fewer) on a standing
# list, from the moment that close happened. A later coin with any of them is
# refused. Rare only: some insiders are trading bots on hundreds of coins,
# mostly winners, and listing every insider cost $81 on the $50k book.
# Replayed on that book 1-10 Oct: refused 2 of 807 (TM, -46%, and one +9%
# winner), +$18. It does NOT stop a new crew: 24 of the 25 bad trades in those
# days came from wallets nobody had seen. Chosen after seeing the loss it
# prevents. The rug brake keeps its own -50% line.

CREW = "crew_of_a_bad_coin"
CREW_RETURN = -0.30
CREW_MAX_COINS = 3
CREW_TTL_S = 60

#: Wallet -> when it went on the list. Coin counts are as of the read, so a
#: wallet that later turns out to be common drops off the list.
_CREW_SQL = text("""
    with bad as (
        select mint, min(closed_at) as known_at from grad_paper_positions
        where closed_at is not null and net_return <= :ret
        group by mint),
    seen as (
        select w, count(*) as n from grad_operators, unnest(ids) as w group by w)
    select w, min(known_at) from (
        select u.w, b.known_at
        from bad b join grad_operators o on o.mint = b.mint
        cross join lateral unnest(o.ids) as u(w)
        join seen s on s.w = u.w
        where s.n <= :max
        union all
        select d.creator_address, b.known_at
        from bad b join discovered_tokens d on d.mint_address = b.mint
        where d.creator_address is not null) x
    group by w
""")

_COIN_WALLETS_SQL = text("""
    select m.mint, o.ids, d.creator_address
    from unnest(cast(:m as varchar[])) as m(mint)
    left join grad_operators o on o.mint = m.mint
    left join discovered_tokens d on d.mint_address = m.mint
""")

_CREW: tuple[datetime, dict[str, datetime]] | None = None


async def crew_list(session: AsyncSession, now: datetime) -> dict[str, datetime]:
    """Every listed wallet and the moment it was listed. Cached CREW_TTL_S."""
    global _CREW
    if _CREW is not None and (now - _CREW[0]).total_seconds() < CREW_TTL_S:
        return _CREW[1]
    rows = await session.execute(_CREW_SQL, {"ret": CREW_RETURN, "max": CREW_MAX_COINS})
    _CREW = (now, dict(rows.all()))
    return _CREW[1]


async def coin_wallets(session: AsyncSession, mints: Iterable[str]) -> dict[str, set[str]]:
    """Mint -> its creator and recorded insider wallets."""
    mints = list(mints)
    if not mints:
        return {}
    rows = await session.execute(_COIN_WALLETS_SQL, {"m": mints})
    return {m: {*(ids or ()), *([c] if c else [])} for m, ids, c in rows.all()}


def crew_hit(wallets: Iterable[str], at: datetime, crew: dict[str, datetime]) -> bool:
    """Was any of these wallets already listed before `at`?"""
    return any((t := crew.get(w)) is not None and t < at for w in wallets)


async def without_crew(session: AsyncSession, rows: Sequence[Any],
                       now: datetime) -> list[Any]:
    """`rows` less the trades the crew rule would have refused when each opened."""
    crew = await crew_list(session, now)
    wallets = await coin_wallets(session, {r.mint for r in rows})
    return [r for r in rows if not crew_hit(wallets.get(r.mint, ()), r.opened_at, crew)]
