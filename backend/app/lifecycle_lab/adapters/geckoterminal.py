"""GeckoTerminal OHLCV - exploratory market backfill only.

For each mint: ``GET /networks/solana/tokens/{mint}/pools``, pick the top pool,
then ``GET /networks/solana/pools/{pool}/ohlcv/{minute|hour}`` for 5-minute
(``aggregate=5``) and 1-hour (``aggregate=1``) bars, newest 1000 each.

Top pool, deterministic: greatest ``reserve_in_usd``, then greatest 24h volume,
then lowest pool address.

Each bar becomes a BACKFILL ``MarketPoint`` with ``observed_at = available_at =
bar end`` (a bar is only known once it closes), ``price_usd = close`` and
``bar_volume``. Bars that have not closed by ``now`` are dropped.

Limits to keep in mind when reading results built from this:
  * OHLCV carries price and volume only - **no liquidity, holders or buyers
    history**. Features needing them are Unavailable for backfilled periods.
  * Pools that died may be missing from the API entirely: the backfilled
    universe is **survivorship-biased**. ``UNAVAILABLE no_pools`` is reported,
    never filled.
  * Free tier is ~30 calls/min; this adapter spaces calls to <= 20/min and is
    bounded to ``max_mints_per_run`` mints (3 calls each). Mints beyond the
    bound are ``UNAVAILABLE deferred_budget`` and are retried by the next run.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from app.lifecycle_lab.adapters.base import (
    AdapterError,
    AdapterResult,
    ClockFn,
    MinIntervalLimiter,
    SleepFn,
    Subject,
    aggregate_status,
    disabled_result,
    http_get,
    parse_json,
    raise_for_status,
)
from app.lifecycle_lab.domain import DataClass, MarketPoint, Source, SourceStatus

BASE = "https://api.geckoterminal.com/api/v2/networks/solana"
#: <= 20 calls per minute, under the free tier's ~30.
MIN_INTERVAL_SECONDS = 3.0
MAX_MINTS_PER_RUN = 15
#: (timeframe path segment, aggregate, bar seconds)
RESOLUTIONS: tuple[tuple[str, int, int], ...] = (("minute", 5, 300), ("hour", 1, 3600))


def _dec(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        out = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return out if out.is_finite() else None


def pick_top_pool(body: Any) -> str | None:
    if not isinstance(body, dict) or not isinstance(body.get("data"), list):
        raise AdapterError("unparseable")
    ranked: list[tuple[Decimal, Decimal, str]] = []
    for pool in body["data"]:
        attrs = pool.get("attributes") if isinstance(pool, dict) else None
        if not isinstance(attrs, dict) or not isinstance(attrs.get("address"), str):
            continue
        vol = attrs.get("volume_usd")
        h24 = _dec(vol.get("h24")) if isinstance(vol, dict) else None
        ranked.append(
            (
                _dec(attrs.get("reserve_in_usd")) or Decimal(0),
                h24 or Decimal(0),
                attrs["address"],
            )
        )
    if not ranked:
        return None
    ranked.sort(key=lambda r: (-r[0], -r[1], r[2]))
    return ranked[0][2]


def parse_ohlcv(body: Any, mint: str, *, bar_seconds: int, now: datetime) -> list[MarketPoint]:
    attrs = None
    if isinstance(body, dict) and isinstance(body.get("data"), dict):
        attrs = body["data"].get("attributes")
    rows = attrs.get("ohlcv_list") if isinstance(attrs, dict) else None
    if not isinstance(rows, list):
        raise AdapterError("unparseable")
    points: list[MarketPoint] = []
    for row in rows:
        if not isinstance(row, list) or len(row) < 6:
            continue
        try:
            start = datetime.fromtimestamp(int(row[0]), tz=UTC)
        except (ValueError, TypeError, OverflowError, OSError):
            continue
        close, volume = _dec(row[4]), _dec(row[5])
        end = start + timedelta(seconds=bar_seconds)
        if close is None or volume is None or close <= 0 or end > now:
            continue
        points.append(
            MarketPoint(
                mint_address=mint,
                observed_at=end,
                available_at=end,
                data_class=DataClass.BACKFILL,
                price_usd=close,
                bar_volume=volume,
                bar_seconds=bar_seconds,
                source="geckoterminal",
            )
        )
    points.sort(key=lambda p: (p.bar_seconds or 0, p.observed_at))
    return points


class GeckoTerminalAdapter:
    source: Source = Source.GECKOTERMINAL
    data_class: DataClass = DataClass.BACKFILL

    def __init__(
        self,
        settings: Any,
        client: httpx.AsyncClient,
        *,
        sleep: SleepFn | None = None,
        clock: ClockFn | None = None,
        max_mints_per_run: int = MAX_MINTS_PER_RUN,
    ) -> None:
        self._settings = settings
        self._client = client
        self._limiter = MinIntervalLimiter(MIN_INTERVAL_SECONDS, sleep=sleep, clock=clock)
        self._max_mints = max_mints_per_run

    def enabled(self) -> tuple[bool, str | None]:
        if not self._settings.FEATURE_LIFECYCLE_LAB_ENABLED:
            return False, "lab_disabled"
        if not self._settings.MLL_GECKOTERMINAL_BACKFILL_ENABLED:
            return False, "disabled_by_config"
        return True, None

    async def _backfill_mint(
        self, mint: str, now: datetime
    ) -> tuple[SourceStatus, str | None, list[MarketPoint]]:
        await self._limiter.wait()
        response = await http_get(self._client, f"{BASE}/tokens/{mint}/pools")
        if response.status_code == 404:
            return SourceStatus.UNAVAILABLE, "no_pools", []
        raise_for_status(response)
        pool = pick_top_pool(parse_json(response))
        if pool is None:
            return SourceStatus.UNAVAILABLE, "no_pools", []
        points: list[MarketPoint] = []
        for timeframe, aggregate, seconds in RESOLUTIONS:
            await self._limiter.wait()
            resp = await http_get(
                self._client,
                f"{BASE}/pools/{pool}/ohlcv/{timeframe}",
                params={"aggregate": aggregate, "limit": 1000, "currency": "usd"},
            )
            if resp.status_code == 404:
                continue
            raise_for_status(resp)
            points.extend(parse_ohlcv(parse_json(resp), mint, bar_seconds=seconds, now=now))
        if not points:
            return SourceStatus.UNAVAILABLE, "no_ohlcv", []
        return SourceStatus.AVAILABLE, None, points

    async def collect(self, subjects: Sequence[Subject], *, now: datetime) -> AdapterResult:
        ok, why = self.enabled()
        if not ok:
            return disabled_result(self.source, why or "disabled_by_config")
        mints = list(dict.fromkeys(m for s in subjects for m in s.mints))
        per: dict[str, tuple[SourceStatus, str | None]] = {}
        points: list[MarketPoint] = []
        blocked: str | None = None
        for index, mint in enumerate(mints):
            if blocked is not None:
                per[mint] = (SourceStatus.ERROR, blocked)
                continue
            if index >= self._max_mints:
                per[mint] = (SourceStatus.UNAVAILABLE, "deferred_budget")
                continue
            try:
                status, reason, got = await self._backfill_mint(mint, now)
            except AdapterError as exc:
                per[mint] = (SourceStatus.ERROR, exc.reason)
                if exc.reason == "rate_limited":
                    blocked = exc.reason
                continue
            per[mint] = (status, reason)
            points.extend(got)
        status, reason = aggregate_status(per)
        return AdapterResult(self.source, status, reason, (), per, tuple(points))
