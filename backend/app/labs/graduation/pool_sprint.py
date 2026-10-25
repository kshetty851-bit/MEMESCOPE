"""Read-only Pool Sprint API. Immutable bootstrap + incremental stored readings.

No recorder, strategy worker, execution wallet, Redis, or database write path.
The memory cache serves immediately while a READ ONLY transaction refreshes it.
"""

from __future__ import annotations

import asyncio
import csv
import io
import time
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import text

from app.db.session import SessionFactory
from app.labs.graduation.pool_sprint_book import Observation, report, snapshot
from app.labs.graduation.pool_sprint_pairs import verify_pairs

router = APIRouter(prefix="/pool-sprint", tags=["pool-sprint-lab"])

ENTRIES_SQL = """
WITH first_recent AS MATERIALIZED (
 SELECT DISTINCT ON (s.mint) s.mint,s.ts,s.pair_address,s.price_usd,s.liquidity_usd,
 s.txns_m5_buys,s.txns_m5_sells
 FROM grad_postgrad_samples s
 WHERE s.source='dexscreener' AND s.pair_address IS NOT NULL AND s.liquidity_usd>0
 AND s.ts>:since AND s.ts<=:now
 ORDER BY s.mint,s.ts
)
SELECT c.*,t.symbol,t.name,t.migrated_at FROM first_recent c
LEFT JOIN grad_tokens t ON t.mint=c.mint
WHERE c.liquidity_usd>=10000 AND c.liquidity_usd<40000 AND c.price_usd>0
AND NOT EXISTS (
 SELECT 1 FROM grad_postgrad_samples p WHERE p.mint=c.mint AND p.ts<c.ts
 AND p.source='dexscreener' AND p.pair_address IS NOT NULL AND p.liquidity_usd>0
)
ORDER BY c.ts,c.mint
"""

EXITS_SQL = """
SELECT x.mint,d.ts AS dex_at,d.price_usd AS dex_price,
g.ts AS candle_start,g.ts+interval '1 minute' AS candle_end,g.price_usd AS candle_price
FROM unnest(CAST(:mints AS varchar[]),CAST(:pairs AS varchar[]),
 CAST(:ats AS timestamptz[])) x(mint,pair,at)
LEFT JOIN LATERAL (
 SELECT ts,price_usd FROM grad_postgrad_samples WHERE mint=x.mint AND pair_address=x.pair
 AND source='dexscreener' AND price_usd>0 AND ts>=x.at+interval '5 minutes'
 AND ts<=x.at+interval '7 minutes' AND ts<=:now ORDER BY ts LIMIT 1
) d ON true
LEFT JOIN LATERAL (
 SELECT ts,price_usd FROM grad_postgrad_samples WHERE mint=x.mint AND pair_address=x.pair
 AND source='geckoterminal' AND price_usd>0
 AND ts+interval '1 minute'>=x.at+interval '5 minutes'
 AND ts+interval '1 minute'<=x.at+interval '7 minutes'
 AND ts+interval '1 minute'<=:now ORDER BY ts LIMIT 1
) g ON true
"""

_records: dict[str, Observation] | None = None
_book: dict[str, Any] | None = None
_watermark: datetime | None = None
_live_as_of: datetime | None = None
_last_attempt = 0.0
_refreshing: asyncio.Task[None] | None = None
_error = False
_lock = asyncio.Lock()


async def refresh(now: datetime | None = None) -> None:
    """Advance only after the entire transaction and report succeed."""
    global _records, _book, _watermark, _live_as_of, _error
    async with _lock:
        at, seed = snapshot()
        now = now or datetime.now(UTC)
        records = dict(_records or {r.mint: r for r in seed})
        since = (_watermark or at) - timedelta(minutes=2)
        async with SessionFactory() as db:
            await db.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
            await db.execute(text("SET LOCAL statement_timeout='25s'"))
            entries = (
                (await db.execute(text(ENTRIES_SQL), {"since": since, "now": now}))
                .mappings()
                .all()
            )
            for r in entries:
                records.setdefault(
                    r["mint"],
                    Observation(
                        mint=r["mint"],
                        pair=r["pair_address"],
                        opened_at=r["ts"],
                        entry_price=Decimal(r["price_usd"]),
                        liquidity=Decimal(r["liquidity_usd"]),
                        symbol=r["symbol"],
                        name=r["name"],
                        graduated_at=r["migrated_at"],
                        entry_buys=r["txns_m5_buys"],
                        entry_sells=r["txns_m5_sells"],
                    ),
                )
            # Never substitute a different pool. Refresh all unresolved observations,
            # including old gaps that a late historical candle may finally cover.
            pending = [r for r in records.values() if not r.priced]
            for start in range(0, len(pending), 200):
                batch = pending[start : start + 200]
                exits = (
                    (
                        await db.execute(
                            text(EXITS_SQL),
                            {
                                "mints": [r.mint for r in batch],
                                "pairs": [r.pair for r in batch],
                                "ats": [r.opened_at for r in batch],
                                "now": now,
                            },
                        )
                    )
                    .mappings()
                    .all()
                )
                for e in exits:
                    r = records[e["mint"]]
                    if e["dex_price"] is not None:
                        records[r.mint] = replace(
                            r,
                            exited_at=e["dex_at"],
                            exit_price=Decimal(e["dex_price"]),
                            source="dexscreener",
                        )
                    elif e["candle_price"] is not None and now >= r.opened_at + timedelta(
                        minutes=7
                    ):
                        records[r.mint] = replace(
                            r,
                            exited_at=e["candle_end"],
                            exit_price=Decimal(e["candle_price"]),
                            source="geckoterminal_candle_close",
                            candle_start_at=e["candle_start"],
                        )
            await db.rollback()
        # Identity checks never choose a replacement pool or a later entry.
        # Unknown identities remain excluded and are retried on the next refresh.
        identities = await verify_pairs(
            {r.pair: r.mint for r in records.values() if not r.pair_evidence}
        )
        for mint, r in list(records.items()):
            if identity := identities.get(r.pair):
                records[mint] = replace(
                    r, base_mint=identity[0], quote_mint=identity[1], pair_evidence=identity[2]
                )
        built = await asyncio.to_thread(report, list(records.values()), now)
        _records, _book, _watermark, _live_as_of = records, built, now, now
        _error = False


async def _attempt_refresh() -> None:
    global _error
    try:
        await refresh()
    except Exception:
        # Do not expose DSNs, SQL parameters, environment or provider credentials.
        _error = True


async def current() -> dict[str, Any]:
    global _book, _last_attempt, _refreshing
    if _book is None:
        try:
            at, records = snapshot()
        except FileNotFoundError as exc:
            raise HTTPException(
                503, "Pool Sprint historical snapshot is not installed"
            ) from exc
        _book = await asyncio.to_thread(report, list(records), at)
    if time.monotonic() - _last_attempt >= 60 and (_refreshing is None or _refreshing.done()):
        _last_attempt = time.monotonic()
        _refreshing = asyncio.create_task(_attempt_refresh())
    at, _ = snapshot()
    return {
        **_book,
        "snapshot_at": at.isoformat(),
        "live_read_as_of": _live_as_of.isoformat() if _live_as_of else None,
        "refreshing": bool(_refreshing and not _refreshing.done()),
        "refresh_error": _error,
    }


@router.get("")
async def get_book() -> dict[str, Any]:
    data = await current()
    return {k: v for k, v in data.items() if k not in {"trades_list", "skipped_list"}}


@router.get("/trades")
async def get_trades(
    day: str | None = None,
    status: str = Query("all", pattern="^(all|priced|unpriced|open|cash_skipped|rugs)$"),
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=250),
) -> dict[str, Any]:
    data = await current()
    rows = data["skipped_list"] if status == "cash_skipped" else data["trades_list"]
    if day:
        from app.labs.graduation.pool_sprint_book import DUBAI

        rows = [
            r
            for r in rows
            if datetime.fromisoformat(
                r.get("closed_at") or r["opened_at"],
            )
            .astimezone(DUBAI)
            .date()
            .isoformat()
            == day
        ]
    if status == "rugs":
        rows = [r for r in rows if r.get("rugged")]
    elif status in {"priced", "unpriced", "open"}:
        rows = [r for r in rows if r["status"] == status]
    return {
        "total": len(rows),
        "offset": offset,
        "limit": limit,
        "trades": rows[offset : offset + limit],
        "as_of": data["as_of"],
    }


@router.get("/trades.csv")
async def get_csv() -> Response:
    data = await current()
    output = io.StringIO()
    fields = [
        "mint",
        "symbol",
        "name",
        "pair",
        "base_mint",
        "quote_mint",
        "quote_symbol",
        "pair_evidence",
        "graduated_at",
        "entry_buys",
        "entry_sells",
        "opened_at",
        "closed_at",
        "pool_usd",
        "entry_price",
        "exit_price",
        "status",
        "pct",
        "pnl_usd",
        "source",
        "rugged",
    ]
    writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    for r in data["trades_list"]:
        # Token metadata is untrusted text; prevent spreadsheet formula execution.
        safe = {
            k: (
                "'" + v
                if isinstance(v, str)
                and v.lstrip().startswith(("=", "+", "-", "@"))
                and k in {"symbol", "name"}
                else v
            )
            for k, v in r.items()
        }
        writer.writerow(safe)
    return Response(
        output.getvalue(),
        media_type="text/csv",
        headers={
            "Content-Disposition": 'attachment; filename="pool-sprint-trades.csv"',
        },
    )
