"""Stamp graduations as they happen, then follow the coin for an hour.

Two passes, both driven from pump.fun's own listing:

* `discover` reads `complete=true&sort=created_timestamp` and records any mint
  it has never seen complete before. That first sighting IS the graduation
  stamp — accurate to the poll interval, which is why the beat runs every
  minute.
* `mark` re-reads coins already stamped, at target ages, and writes one row per
  (coin, age).

**Freshly created only.** A coin that graduated last week still reads
`complete`, and stamping it today would enter the cohort with a graduation time
that is really a "we noticed" time — the exact error that made the snapshot
analysis unanswerable. `MAX_AGE_AT_DISCOVERY_MINUTES` refuses anything whose
creation is too old to have graduated inside our watch.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.logging import get_logger
from app.models.graduation import PumpfunGraduation, PumpfunGraduationMark

logger = get_logger(__name__)

BASE = "https://frontend-api-v3.pump.fun/coins"
PAGE_LIMIT = 100

#: Only stamp coins created recently. Graduation follows launch by minutes to
#: hours; anything older than this was already graduated before we looked, and
#: its "first seen complete" would be a fact about US rather than about it.
MAX_AGE_AT_DISCOVERY_MINUTES = 240

#: The ages we want a reading at: dense in the first hour, then hourly to 48.
#:
#: The first hour answers "is there a pop", the two days answer "does anything
#: survive". Both matter and neither substitutes for the other — the 60-minute
#: median was -33% while a quarter of coins were still up, so where that split
#: goes over a longer horizon is a real question rather than a decoration.
TARGET_MINUTES: tuple[int, ...] = (5, 15, 30) + tuple(
    60 * hour for hour in range(1, 49)
)

#: How late a reading may be and still count as that age.
#:
#: Wider than the poll interval so one slow pass does not silently drop a coin,
#: and WIDER STILL for the long horizons: four minutes either side of a
#: 48-hour mark demands the collector be alive at that exact minute two days
#: later, and a missed window is not recoverable — the age passes and that coin
#: has no 48h reading, ever. Twenty minutes at two days is 0.7% of the horizon,
#: which is precision this measurement does not need.
MARK_TOLERANCE_MINUTES = 4
LONG_MARK_TOLERANCE_MINUTES = 20
LONG_HORIZON_FROM_MINUTES = 120


def _tolerance(minutes: int) -> int:
    return (MARK_TOLERANCE_MINUTES if minutes < LONG_HORIZON_FROM_MINUTES
            else LONG_MARK_TOLERANCE_MINUTES)

#: Same guard the social collector uses: pump.fun has returned market caps
#: above 10^20. An implausible number is UNKNOWN, never stored and never
#: clamped — a clamped value is a lie that looks like data.
IMPLAUSIBLE_USD = Decimal("1e13")

#: Bound on per-coin lookups in one pass, so a backlog cannot turn into an
#: unbounded burst of requests at somebody else's API.
#:
#: Steady state with 52 targets and ~30 graduations an hour is 26 marks a
#: minute. The budget is spent in target order, so a burst against a tight
#: budget starves the LONGEST horizons — the ones that took two days to earn
#: and cannot be re-taken. Sized at roughly five times steady state for that
#: reason, not for throughput.
MARK_BUDGET = 150


def _dec(v: Any) -> Decimal | None:
    if v is None:
        return None
    try:
        d = Decimal(str(v))
    except Exception:
        return None
    if not d.is_finite() or d < 0 or d > IMPLAUSIBLE_USD:
        return None
    return d


def _ms(v: Any) -> datetime | None:
    try:
        return datetime.fromtimestamp(int(v) / 1000, tz=UTC)
    except Exception:
        return None


async def _get(client: httpx.AsyncClient, url: str, **params) -> Any:
    try:
        r = await client.get(url, params=params or None,
                             headers={"accept": "application/json"})
    except Exception:
        logger.warning("pumpfun_graduation_request_failed", url=url)
        return None
    if r.status_code != 200:
        logger.warning("pumpfun_graduation_http", url=url, status=r.status_code)
        return None
    try:
        return r.json()
    except ValueError:
        return None


async def discover(session, *, now: datetime) -> dict[str, int]:
    """Stamp every freshly-created coin that is complete and not yet known."""
    counts = {"seen": 0, "too_old": 0, "already_known": 0, "stamped": 0}
    async with httpx.AsyncClient(timeout=25) as client:
        rows = await _get(client, BASE, limit=PAGE_LIMIT,
                          sort="created_timestamp", order="DESC", complete="true")
    if not isinstance(rows, list):
        return counts

    cutoff = now - timedelta(minutes=MAX_AGE_AT_DISCOVERY_MINUTES)
    for c in rows:
        mint = c.get("mint")
        if not mint:
            continue
        counts["seen"] += 1
        created = _ms(c.get("created_timestamp"))
        if created is None or created < cutoff:
            counts["too_old"] += 1
            continue
        exists = await session.scalar(
            select(PumpfunGraduation.id).where(
                PumpfunGraduation.mint_address == mint)
        )
        if exists:
            counts["already_known"] += 1
            continue
        session.add(PumpfunGraduation(
            mint_address=mint, first_seen_complete_at=now,
            created_at_source=created,
            mcap_usd_at_graduation=_dec(c.get("usd_market_cap")),
            ath_mcap_usd_at_graduation=_dec(c.get("ath_market_cap")),
            reply_count_at_graduation=c.get("reply_count"),
        ))
        try:
            await session.flush()
            counts["stamped"] += 1
        except IntegrityError:
            # Another pass stamped it first. The unique index doing its job.
            await session.rollback()
            counts["already_known"] += 1
    return counts


async def mark(session, *, now: datetime) -> dict[str, int]:
    """Take whichever follow-up readings are due, oldest target first."""
    counts = {"due": 0, "written": 0, "unreadable": 0}
    budget = MARK_BUDGET

    for minutes in TARGET_MINUTES:
        if budget <= 0:
            break
        lo = now - timedelta(minutes=minutes + _tolerance(minutes))
        hi = now - timedelta(minutes=minutes)
        due = list((await session.execute(
            select(PumpfunGraduation)
            .where(PumpfunGraduation.first_seen_complete_at <= hi,
                   PumpfunGraduation.first_seen_complete_at >= lo,
                   ~select(PumpfunGraduationMark.id).where(
                       PumpfunGraduationMark.graduation_id == PumpfunGraduation.id,
                       PumpfunGraduationMark.minutes_since == minutes,
                   ).exists())
            .limit(budget)
        )).scalars())
        counts["due"] += len(due)

        if not due:
            continue
        async with httpx.AsyncClient(timeout=25) as client:
            for g in due:
                budget -= 1
                d = await _get(client, f"{BASE}/{g.mint_address}")
                if not isinstance(d, dict):
                    counts["unreadable"] += 1
                    continue
                session.add(PumpfunGraduationMark(
                    graduation_id=g.id, mint_address=g.mint_address,
                    observed_at=now, minutes_since=minutes,
                    mcap_usd=_dec(d.get("usd_market_cap")),
                    ath_mcap_usd=_dec(d.get("ath_market_cap")),
                ))
                try:
                    await session.flush()
                    counts["written"] += 1
                except IntegrityError:
                    await session.rollback()
    return counts
