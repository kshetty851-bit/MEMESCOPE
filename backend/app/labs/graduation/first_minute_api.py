"""First-minute recorder's status page (Karthik, 2026-10-25: "option 1 with own
page"): is it recording, how soon after graduation the first real price lands,
and how much room it takes. Read only; research rows, nothing trades on them."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter
from sqlalchemy import text

from app.api.deps import DbSession
from app.labs.graduation import config

router = APIRouter(prefix="/labs/graduation/first-minute", tags=["graduation-lab"])

_CACHE: tuple[float, dict[str, Any]] | None = None

_DAYS = text("""
with p as (
  select mint, min(ts) first_at, min(migrated_at) grad_at, count(*) n,
         bool_and(sol_quoted) sol
  from grad_first_minute where migrated_at >= :since group by mint),
g as (
  select (ts at time zone 'Asia/Dubai')::date d, count(*) n from grad_migrations
  where ts >= :since and pool = :venue group by 1)
select coalesce(x.d, g.d) d, coalesce(x.pools, 0) pools, g.n grads, x.med, x.p10, x.p90, coalesce(x.rows, 0) rows_
from (select (grad_at at time zone 'Asia/Dubai')::date d, count(*) pools, sum(n) rows,
             percentile_cont(.5) within group (order by extract(epoch from first_at - grad_at)) med,
             percentile_cont(.1) within group (order by extract(epoch from first_at - grad_at)) p10,
             percentile_cont(.9) within group (order by extract(epoch from first_at - grad_at)) p90
      from p group by 1) x full join g on g.d = x.d
order by 1 desc""")

_RECENT = text("""
select f.mint, t.symbol, min(f.migrated_at) grad_at, min(f.ts) first_at, count(*) n,
       (array_agg(f.quote_reserve order by f.slot))[1] q0,
       (array_agg(f.price_native order by f.slot))[1] p0,
       (array_agg(f.price_native order by f.slot desc))[1] p1
from grad_first_minute f left join grad_tokens t on t.mint = f.mint
where f.migrated_at >= :since group by f.mint, t.symbol order by grad_at desc limit 12""")


@router.get("", summary="First-minute recorder: coverage, speed, size")
async def status(session: DbSession) -> dict[str, Any]:
    global _CACHE
    import time

    if _CACHE and time.monotonic() - _CACHE[0] < 60:
        return _CACHE[1]
    now = datetime.now(UTC)
    days = (await session.execute(_DAYS, {"since": now - timedelta(days=14),
                                          "venue": config.PUMPSWAP_VENUE})).all()
    recent = (await session.execute(_RECENT, {"since": now - timedelta(hours=2)})).all()
    size = (await session.execute(text(
        "select pg_total_relation_size('grad_first_minute'), "
        "(select max(ts) from grad_first_minute where ts >= now() - interval '1 day')"))).one()
    out = {
        "enabled": config.FIRST_MINUTE_ENABLED,
        "window_s": config.FIRST_MINUTE_WINDOW_S,
        "size_mb": round(size[0] / 1e6, 1),
        "last_at": size[1].isoformat() if size[1] else None,
        "days": [{"day": d.isoformat(), "pools": pools, "graduations": grads or 0,
                  "median_s": med, "p10_s": p10, "p90_s": p90, "rows": rows}
                 for d, pools, grads, med, p10, p90, rows in days if d],
        "recent": [{"mint": m, "symbol": sym, "graduated_at": ga.isoformat(),
                    "first_after_s": (fa - ga).total_seconds(), "readings": n,
                    "pool_sol": float(2 * q0) if q0 is not None else None,
                    "move": float(p1 / p0) if p0 else None}
                   for m, sym, ga, fa, n, q0, p0, p1 in recent],
    }
    _CACHE = (time.monotonic(), out)
    return out
