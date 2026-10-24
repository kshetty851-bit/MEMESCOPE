"""Pump Catcher v3, paper only. Read raw quotes; never write DB/Redis.

Chosen after October research, not an out-of-sample performance claim.
Signals already older than ~55s waive the six weak entry gates, keep hard
crew/name/funding guards, and use +100% / armed trailing 20% / ten minutes.
Other signals retain the independently priced +30% / five-down / ten exit.
"""
from __future__ import annotations

import bisect
import heapq
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import text

AGE_S = 55.00991761684418  # Frozen fitted threshold; do not refit in the app.
PRIORITY_SOL = 0.0001075
MODEL = "independent-v3"
_CACHE: dict[tuple, Any] = {}
_READINGS = text("""
 SELECT x.id::text position_id,g.ts,g.price_usd::float8 usd,
        g.price_native::float8 native,g.pair_address pair,
        g.liquidity_usd::float8 liq,g.id::text rid
 FROM unnest(CAST(:ids AS uuid[]),CAST(:mints AS varchar[]),
             CAST(:ats AS timestamptz[])) x(id,mint,at)
 JOIN grad_postgrad_samples g ON g.mint=x.mint
   AND g.ts>=x.at-interval '2 minutes' AND g.ts<=x.at+interval '12 minutes'
   AND g.ts<=:now
 WHERE g.price_native>0 OR g.price_usd>0
 UNION ALL
 SELECT x.id::text,g.ts,g.price_usd::float8,NULL::float8,g.pair,
        g.liquidity_usd::float8,g.id::text
 FROM unnest(CAST(:ids AS uuid[]),CAST(:mints AS varchar[]),
             CAST(:ats AS timestamptz[])) x(id,mint,at)
 JOIN longwatch_readings g ON g.mint=x.mint
   AND g.ts>=x.at-interval '2 minutes' AND g.ts<=x.at+interval '12 minutes'
   AND g.ts<=:now
 WHERE g.price_usd>0
 ORDER BY position_id,ts,rid
""")


def selected(row: Any) -> bool:
    return bool(row.graduated_at and
                (row.opened_at-row.graduated_at).total_seconds() > AGE_S)


class Priced:
    """A source row plus one independent exit; no future five-minute calibration."""

    def __init__(self, row: Any, path: list[dict], pool: str | None):
        self._row = row
        self._returns = {}
        self.selected = selected(row)
        self.path = sorted((r for r in path if pool and r['pair'] == pool
                            and r['ts'] > row.opened_at),
                           key=lambda r: (r['ts'], r['rid']))
        self.times = [r['ts'] for r in self.path]
        self.fill, self.how = self.decide()
        self.closed_at = self.fill['ts'] if self.fill else row.opened_at+timedelta(seconds=720)
        self.net_return = Decimal(str(self.return_at(50)))
        self.close_quote = Decimal(str(self.native(self.fill))) if self.fill else None
        # Only the execution reading is needed after deciding. Keeping every
        # raw observation in each web worker wastes memory as history grows.
        self.path = []
        self.times = []

    def __getattr__(self, name: str) -> Any:
        return getattr(self._row, name)

    def native(self, r: dict) -> float:
        return float(r['native']) if r.get('native') and r['native'] > 0 else float(r['usd'])/float(self.sol_usd_at_open)

    def gross(self, r: dict) -> float:
        return self.native(r)/float(self.open_quote)-1

    def next(self, at: datetime) -> dict | None:
        i = bisect.bisect_right(self.times, at)
        return self.path[i] if i < len(self.path) else None

    def return_at(self, size: float, place: int = 0, reading: dict | None = None) -> float:
        from app.labs.graduation import config
        cache_key = (size, place)
        if reading is None and cache_key in self._returns:
            return self._returns[cache_key]
        r = reading if reading is not None else self.fill
        if not r or not r['liq'] or r['liq'] <= 0:
            return -1.0
        io = float(self.impact_open or 0)
        measured = float(self.notional_usd)
        old_fee = float(self.open_fill)/float(self.open_quote)/(1+io)-1
        fee_buy = old_fee+PRIORITY_SOL*float(self.sol_usd_at_open)*(1/size-1/measured)
        # The first $50 order matches the frozen research exactly. Later
        # queued orders pay linear entry impact from all preceding orders.
        factor = (1+io*(2*place+1)*size/measured)*(1+fee_buy)
        value = size*(1+self.gross(r))/factor
        bps = config.pool_fee_bps(Decimal(str(self.native(r))))
        fee_sell = (bps+10)/10000+PRIORITY_SOL*float(self.sol_usd_at_open)/size
        proceeds = value/(1+2*value*(2*place+1)/float(r['liq']))*(1-fee_sell)
        ret = max(-1.0, proceeds/size-1)
        if reading is None:
            self._returns[cache_key] = ret
        return ret

    def decide(self) -> tuple[dict | None, str]:
        end = self.opened_at+timedelta(seconds=600)
        options = []
        clock = next((r for r in self.path if r['ts'] >= end), None)
        if clock:
            options.append((clock['ts'], clock, '10m'))
        if not self.selected:
            known = next((r for r in reversed(self.path)
                          if r['ts'] <= self.opened_at+timedelta(seconds=300)), None)
            if known and self.return_at(50, reading=known) < 0:
                fill = self.next(self.opened_at+timedelta(seconds=300))
                if fill:
                    options.append((fill['ts'], fill, '5m-down'))
        peak = 1.0
        for r in self.path:
            if r['ts'] > end:
                break
            ratio = 1+self.gross(r)
            peak = max(peak, ratio)
            target = ratio >= (2 if self.selected else 1.3)
            trail = self.selected and peak >= 1.5 and ratio/peak <= .8
            if target or trail:
                fill = self.next(r['ts'])  # Strictly later timestamp, not another source at this timestamp.
                if fill:
                    options.append((fill['ts'], fill, 'target' if target else 'trailing'))
                break
        if not options:
            return None, 'unpriced-loss'
        _, fill, how = min(options, key=lambda x: x[0])
        return fill, how


async def prepare(db: Any, rows: list, now: datetime | None = None) -> tuple[list, int]:
    from app.labs.graduation.tournament import graduation_pool
    now = now or datetime.now(UTC)
    settled = [r for r in rows if r.opened_at <= now-timedelta(seconds=720)]
    keys = {r.id: (str(r.id), str(r.open_quote), str(r.open_fill),
                   str(r.impact_open), str(r.notional_usd), str(r.sol_usd_at_open),
                   r.graduated_at, graduation_pool(r.mint)) for r in settled}
    todo = [r for r in settled if keys[r.id] not in _CACHE]
    if todo:
        readings = (await db.execute(_READINGS, {
            'ids': [r.id for r in todo], 'mints': [r.mint for r in todo],
            'ats': [r.opened_at for r in todo], 'now': now,
        })).mappings().all()
        paths = defaultdict(list)
        for r in readings:
            paths[r['position_id']].append(dict(r))
        for r in todo:
            _CACHE[keys[r.id]] = Priced(r, paths[str(r.id)], keys[r.id][-1])
        # Bound worker memory; a process restart simply recomputes from raw tables.
        if len(_CACHE) > 20000:
            active = set(keys.values())
            for k in list(_CACHE):
                if k not in active:
                    del _CACHE[k]
    return [_CACHE[keys[r.id]] for r in settled], len(rows)-len(settled)


def walk(rows: list, *, ticket: float = 50, start: float = 500,
         tickets: list | None = None, loss_streak_limit: int = 0,
         cooldown_minutes: int = 0):
    """One funded history: only rugs actually funded can ban later names."""
    from app.labs.graduation.api import Walk
    from app.labs.graduation.pool_lab import name_key
    cash = low = start
    held = []
    banned = defaultdict(list)
    pnl = []
    took = []
    skipped = paused = streak = 0
    pause_until = None
    for i, r in enumerate(rows):
        size = tickets[i] if tickets is not None else ticket
        while held and held[0][0] < r.opened_at:
            at, _, ret, stake, name = heapq.heappop(held)
            cash += stake*(1+ret)
            low = min(low, cash+sum(x[3] for x in held))
            if ret <= -.5 and name:
                banned[name].append(at)
            streak = streak+1 if ret < 0 else 0
            if loss_streak_limit and streak >= loss_streak_limit:
                pause_until = at+timedelta(minutes=cooldown_minutes)
                streak = 0
        name = name_key(r.symbol)
        if any(r.opened_at-timedelta(hours=12) < at < r.opened_at for at in banned[name]):
            pnl.append(None)
            continue
        if pause_until and r.opened_at < pause_until:
            paused += 1
            pnl.append(None)
            continue
        if cash < size-1e-8:
            skipped += 1
            pnl.append(None)
            continue
        ret = r.return_at(size)
        cash -= size
        heapq.heappush(held, (r.closed_at, i, ret, size, name))
        pnl.append(size*ret)
        took.append((r.closed_at, ret))
    while held:
        _, _, ret, size, _ = heapq.heappop(held)
        cash += size*(1+ret)
        low = min(low, cash+sum(x[3] for x in held))
    return Walk(cash, len(took), skipped, took, low, tuple(pnl), paused)


def wallet_run(rows: list, n: int, start: float) -> list[dict]:
    """Same entry/exit signals, each wallet's cash/name history and queue cost."""
    from app.labs.graduation.pool_lab import name_key
    wallets = [dict(cash=start, held=[], banned=defaultdict(list), profit=0.,
                    trades=0, rugs=0, last=datetime.min.replace(tzinfo=UTC), number=i)
               for i in range(n)]
    for i, r in enumerate(rows):
        ready = []
        name = name_key(r.symbol)
        for w in wallets:
            while w['held'] and w['held'][0][0] < r.opened_at:
                at, _, ret, closed_name = heapq.heappop(w['held'])
                w['cash'] += 50*(1+ret)
                if ret <= -.5 and closed_name:
                    w['banned'][closed_name].append(at)
            if w['cash'] >= 50-1e-8 and not any(
                r.opened_at-timedelta(hours=12) < at < r.opened_at
                for at in w['banned'][name]
            ):
                ready.append(w)
        for place, w in enumerate(sorted(ready, key=lambda w: (w['last'], w['number']))):
            ret = r.return_at(50, place)
            w['cash'] -= 50
            w['profit'] += 50*ret
            w['trades'] += 1
            w['rugs'] += ret <= -.5
            w['last'] = r.opened_at
            heapq.heappush(w['held'], (r.closed_at, i, ret, name))
    return sorted([dict(pnl_usd=round(w['profit'], 2), trades=w['trades'], rugs=w['rugs'])
                   for w in wallets], key=lambda w: -w['pnl_usd'])
