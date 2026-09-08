"""Collect point-in-time comment activity from pump.fun's listing API.

Read-only against a third party, bounded, and contained: a failure logs and
returns, so a provider outage cannot stop the beat that also settles the labs.

## Which listings, and why those two

pump.fun exposes exactly six sorts — its own validation error names them:
`created_timestamp, market_cap, ath_market_cap, reply_count, last_reply,
last_trade_timestamp`. There is NO volume or price-change sort, so the explore
page's "movers" has to be built from these.

Two are collected:

**`last_reply`** — coins being discussed RIGHT NOW. This is the point-in-time
social signal and the reason the collector exists. Sorting by `reply_count`
instead would select coins that have merely been around long enough to
accumulate comments, which is age wearing a signal's clothes.

**`market_cap`** — the movers. Measured when this was written, 58% of this list
sat within 5% of its own all-time high, against 23% of the `last_reply` list. A
coin at its ATH is what the page means by moving.

They are stored with `source_sort` rather than pooled, because the sort IS the
population: a coin seen under `last_reply` is being talked about, one seen
under `market_cap` is merely large, and blending them merges two samples.

## Velocity is not collected, it is derived

`reply_count` is cumulative. What matters is replies per hour, which needs two
readings, so the raw count is stored with its timestamp and the rate is
computed at read time from consecutive rows.

A consequence worth stating: a coin only yields a velocity if it appears in TWO
polls. Coins that drop out of the listing between polls have one reading and no
rate — and that is the correct behaviour, because sustained presence in the
`last_reply` list is itself the population of interest.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import httpx

from app.core.logging import get_logger

logger = get_logger(__name__)

BASE = "https://frontend-api-v3.pump.fun/coins"

#: The two listings collected. `last_reply` is the signal; `market_cap` is the
#: movers comparison. Both bounded — this is somebody else's API.
SORTS: tuple[str, ...] = ("last_reply", "market_cap")

#: Per sort, per poll. 100 x 2 every ten minutes is ~29k rows a day.
PAGE_LIMIT = 100


@dataclass(frozen=True, slots=True)
class SocialReading:
    mint: str
    reply_count: int | None
    usd_market_cap: Decimal | None
    ath_market_cap: Decimal | None
    complete: bool | None
    is_currently_live: bool | None
    source_sort: str


#: Above this a market cap is not a big coin, it is bad data.
#:
#: The provider returned a value above 10^20 on the first live poll, which
#: overflowed NUMERIC(24,4) and lost the whole batch. Widening the column was
#: the wrong fix: it would have stored a market cap larger than every asset on
#: earth as though it were a measurement. $10 trillion is already an order of
#: magnitude above anything real, so beyond it the honest value is "not known".
IMPLAUSIBLE_USD = Decimal("1e13")


def _dec(v: Any) -> Decimal | None:
    """A USD figure, or None when it is missing OR unbelievable.

    None rather than a clamp, deliberately. Clamping to the ceiling would put a
    coin that returned nonsense at the very top of any ranking by market cap —
    the bad row would become the most interesting one.
    """
    if v is None:
        return None
    try:
        d = Decimal(str(round(float(v), 4)))
    except (TypeError, ValueError, ArithmeticError):
        return None
    if not d.is_finite() or abs(d) >= IMPLAUSIBLE_USD:
        return None
    return d


def _reading(row: dict[str, Any], sort: str) -> SocialReading | None:
    mint = row.get("mint")
    if not mint or not isinstance(mint, str):
        return None
    replies = row.get("reply_count")
    return SocialReading(
        mint=mint,
        reply_count=int(replies) if isinstance(replies, (int, float)) else None,
        # `usd_market_cap` and NOT `market_cap`: the latter is denominated in
        # the quote asset (SOL) while `ath_market_cap` is USD, and dividing one
        # by the other produces a "1% of ATH" that is a unit error.
        usd_market_cap=_dec(row.get("usd_market_cap")),
        ath_market_cap=_dec(row.get("ath_market_cap")),
        complete=row.get("complete") if isinstance(row.get("complete"), bool) else None,
        is_currently_live=(row.get("is_currently_live")
                           if isinstance(row.get("is_currently_live"), bool) else None),
        source_sort=sort,
    )


async def fetch(*, limit: int = PAGE_LIMIT) -> list[SocialReading]:
    """One reading per coin per listing. `[]` on any failure — never raises."""
    out: list[SocialReading] = []
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            for sort in SORTS:
                try:
                    r = await client.get(BASE, params={
                        "limit": limit, "sort": sort, "order": "DESC",
                    }, headers={"accept": "application/json"})
                except Exception:
                    logger.warning("pumpfun_social_request_failed", sort=sort)
                    continue
                if r.status_code != 200:
                    logger.warning("pumpfun_social_http",
                                   sort=sort, status=r.status_code)
                    continue
                try:
                    rows = r.json()
                except ValueError:
                    logger.warning("pumpfun_social_bad_json", sort=sort)
                    continue
                if not isinstance(rows, list):
                    continue
                for row in rows:
                    if isinstance(row, dict) and (reading := _reading(row, sort)):
                        out.append(reading)
    except Exception:
        logger.exception("pumpfun_social_fetch_failed")
        return []
    return out


def to_rows(readings: list[SocialReading], *, now: datetime | None = None):
    """Model rows for a batch, all sharing one observation instant.

    One timestamp for the whole poll rather than per row: the rate derived
    later divides by the gap between polls, and per-row clocks would make that
    denominator differ by coin for no reason.
    """
    from app.models.social import PumpfunSocialSnapshot

    at = now or datetime.now(UTC)
    return [
        PumpfunSocialSnapshot(
            mint_address=r.mint, observed_at=at, reply_count=r.reply_count,
            usd_market_cap=r.usd_market_cap, ath_market_cap=r.ath_market_cap,
            complete=r.complete, is_currently_live=r.is_currently_live,
            source_sort=r.source_sort,
        )
        for r in readings
    ]
