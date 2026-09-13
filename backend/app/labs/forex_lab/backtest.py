"""Replay the stored candles through the engine, and sweep the parameter grid.

The replay is deliberately dumb: pull candles in order, hand each to the
engine, record the equity mark once a day. All the judgement lives in
`engine.py`; this module only measures.

## Why the candles go to a file first

The sweep runs 27 configurations over ~2.4M minutes. Reading those minutes out
of Postgres 27 times would spend more wall clock in the database driver than
in the strategy, and running the configurations in parallel processes would
mean 27 concurrent connections doing identical work. So the candles are
exported once to a compact binary file — eight float32 columns and an int64
minute — and each worker memory-maps it. One read, 27 replays.
"""

from __future__ import annotations

import array
import asyncio
import json
import math
import os
import struct
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.labs.forex_lab import config
from app.labs.forex_lab.engine import GridConfig, GridEngine

HERE = Path(__file__).parent
OUTPUT = HERE / "output"
#: (minute as unix seconds, mid_open, mid_high, mid_low, mid_close). Mids
#: because the engine triggers on mids; the bid/ask split has done its job by
#: the time the integrity check has run over it.
_ROW = struct.Struct("<q4f")
CANDLE_FILE = OUTPUT / "candles.bin"


# --- export -------------------------------------------------------------------


async def export_candles(
    session, path: Path = CANDLE_FILE, symbol: str = config.SYMBOL
) -> int:
    """Write every stored candle to the binary replay file. Returns the count."""
    from app.labs.forex_lab.store import iter_candles

    path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    buf = bytearray()
    async for minute, bo, bh, bl, bc, ao, ah, al, ac in iter_candles(session, symbol):
        buf += _ROW.pack(
            int(minute.timestamp()),
            (float(bo) + float(ao)) / 2.0,
            (float(bh) + float(ah)) / 2.0,
            (float(bl) + float(al)) / 2.0,
            (float(bc) + float(ac)) / 2.0,
        )
        n += 1
    # Off the loop. Sixty megabytes of blocking write inside an async function
    # is a bug waiting for a caller that shares the loop with something else.
    await asyncio.to_thread(path.write_bytes, bytes(buf))
    return n


def load_candles(path: Path = CANDLE_FILE) -> tuple[array.array, array.array]:
    """(minutes as unix seconds, prices flattened as o,h,l,c per candle)."""
    raw = path.read_bytes()
    n = len(raw) // _ROW.size
    ts = array.array("q")
    px = array.array("f")
    for i in range(n):
        t, o, h, lo, c = _ROW.unpack_from(raw, i * _ROW.size)
        ts.append(t)
        px.extend((o, h, lo, c))
    return ts, px


# --- metrics ------------------------------------------------------------------


def _max_drawdown(curve: list[float]) -> float:
    """As a fraction of the running peak, over DAILY samples. Reported positive.

    Kept only for the comparison the report prints beside the real figure: it
    is what a daily-close drawdown would have claimed, and the gap between the
    two is the point.
    """
    peak, worst = curve[0] if curve else 0.0, 0.0
    for v in curve:
        peak = max(peak, v)
        if peak > 0:
            worst = max(worst, (peak - v) / peak)
    return worst


def _profit_factor(trades) -> float:
    won = sum(t.pnl for t in trades if t.pnl > 0)
    lost = -sum(t.pnl for t in trades if t.pnl < 0)
    if lost == 0:
        return math.inf if won > 0 else 0.0
    return won / lost


def replay(
    cfg: GridConfig, ts: array.array, px: array.array, with_trades: bool = False
) -> dict[str, Any]:
    """One configuration over the whole series."""
    n = len(ts)
    if n == 0:
        raise ValueError("no candles")

    eng = GridEngine(cfg, px[0], datetime.fromtimestamp(ts[0], UTC))
    # Seeded with the opening balance so the first day's move has something to
    # draw down FROM. An unseeded curve takes its first sample as the peak and
    # cannot see a loss that happened before it.
    equity_curve: list[float] = [cfg.start_equity]
    equity_days: list[str] = [datetime.fromtimestamp(ts[0], UTC).date().isoformat()]
    monthly: dict[str, float] = defaultdict(float)
    yearly: dict[int, float] = defaultdict(float)
    last_day = None
    last_equity = cfg.start_equity
    prev_minute = datetime.fromtimestamp(ts[0], UTC)

    for i in range(n):
        minute = datetime.fromtimestamp(ts[i], UTC)
        j = i * 4
        eng.step(minute, px[j], px[j + 1], px[j + 2], px[j + 3])
        day = ts[i] // 86400
        if day != last_day:
            if last_day is not None:
                eq = eng.equity(px[j + 3])
                equity_curve.append(eq)
                # Attributed to the day that EARNED it, not to the day whose
                # first candle happens to be the one that noticed. Off by one
                # here puts 31 December's P&L into January and moves the
                # per-year gate by a day every year.
                equity_days.append(prev_minute.date().isoformat())
                monthly[prev_minute.strftime("%Y-%m")] += eq - last_equity
                yearly[prev_minute.year] += eq - last_equity
                last_equity = eq
            last_day = day
        prev_minute = minute

    last = (n - 1) * 4
    end_ts = datetime.fromtimestamp(ts[n - 1], UTC)
    eng.finish(end_ts, px[last + 3])
    final = eng.balance
    equity_curve.append(final)
    equity_days.append(end_ts.date().isoformat())
    monthly[end_ts.strftime("%Y-%m")] += final - last_equity
    yearly[end_ts.year] += final - last_equity

    months = {k: round(v, 2) for k, v in sorted(monthly.items())}
    years = {int(k): round(v, 2) for k, v in sorted(yearly.items())}
    total_profit = final - cfg.start_equity
    winners = [v for v in months.values() if v > 0]
    best_month_share = (
        (max(winners) / total_profit) if (winners and total_profit > 0) else None
    )

    out = {
        "config": {
            "step_pips": cfg.step_pips,
            "levels": cfg.levels,
            "lots": cfg.lots,
            "stop_multiplier": cfg.stop_multiplier,
            "name": cfg.name,
        },
        "start_equity": cfg.start_equity,
        "final_equity": round(final, 2),
        "total_return_pct": round(100 * total_profit / cfg.start_equity, 2),
        "profit_factor": (
            None
            if _profit_factor(eng.trades) == math.inf
            else round(_profit_factor(eng.trades), 3)
        ),
        # From the engine, which marks every candle, not from the daily curve.
        # A daily sample cannot see a trough that recovers before the day ends,
        # and this figure feeds a drawdown CEILING in the gate — measured too
        # low it passes runs that should fail. Measured on the interim sweep,
        # the daily curve reported 14.92% where the true fall was 17.4%.
        "max_drawdown_pct": round(100 * eng.max_drawdown, 2),
        "max_drawdown_daily_pct": round(100 * _max_drawdown(equity_curve), 2),
        "peak_equity": round(eng.peak_equity, 2),
        "trades": len(eng.trades),
        "min_equity": round(eng.min_equity, 2),
        # An account that passed through zero did not have a bad year, it
        # stopped existing. Every ratio computed over it is a number about
        # something that no longer had a balance to compound.
        "blown": eng.min_equity <= 0,
        "recenters": eng.stats["recenters"],
        "stopouts": eng.stats["stopouts"],
        "rejected_fills": eng.stats["rejected_fills"],
        "fills": eng.stats["fills"],
        "spread_paid": round(eng.stats["spread_paid"], 2),
        "swap_paid": round(eng.stats["swap_paid"], 2),
        "recenter_loss": round(eng.stats["recenter_loss"], 2),
        "stopout_loss": round(eng.stats["stopout_loss"], 2),
        "tp_pnl": round(eng.stats["tp_pnl"], 2),
        "end_pnl": round(eng.stats["end_pnl"], 2),
        "per_year": years,
        "per_month": months,
        # Over the SIX FULL years only. 2026 is half a year and is reported
        # beside them, never folded in to make a seventh — see config.FULL_YEARS.
        "years_positive": sum(1 for y in config.FULL_YEARS if years.get(y, 0) > 0),
        "years_total": sum(1 for y in config.FULL_YEARS if y in years),
        "partial_year_pnl": years.get(config.PARTIAL_YEAR),
        "best_month_share": (None if best_month_share is None else round(best_month_share, 4)),
        "equity_curve": [round(v, 2) for v in equity_curve],
        "equity_days": equity_days,
    }
    if with_trades:
        out["trade_list"] = [
            {
                **asdict(t),
                "opened_at": t.opened_at.isoformat(),
                "closed_at": t.closed_at.isoformat(),
            }
            for t in eng.trades
        ]
    return out


def buy_and_hold(
    ts: array.array, px: array.array, lots: float = config.DEFAULT_LOTS
) -> dict[str, Any]:
    """The other baseline: long one micro lot, start to finish, paying the same
    spread on both fills and the same long swap every night."""
    cfg = GridConfig(lots=lots)
    entry = px[0] + cfg.half_spread
    exit_ = px[(len(ts) - 1) * 4 + 3] - cfg.half_spread
    units = lots * config.MICRO_LOT_UNITS
    gross = (exit_ - entry) * units

    swap = 0.0
    from datetime import timedelta

    from app.labs.forex_lab.engine import _swap_rates

    d = datetime.fromtimestamp(ts[0], UTC).date()
    end = datetime.fromtimestamp(ts[len(ts) - 1], UTC).date()
    while d < end:
        if d.weekday() < 5:
            mult = 3.0 if d.weekday() == config.TRIPLE_SWAP_WEEKDAY else 1.0
            swap += _swap_rates(d.year)[0] * lots * mult
        d += timedelta(days=1)

    total = gross + swap
    return {
        "name": "buy_and_hold",
        "entry": round(entry, 5),
        "exit": round(exit_, 5),
        "gross": round(gross, 2),
        "swap": round(swap, 2),
        "final_equity": round(config.DEFAULT_START_EQUITY + total, 2),
        "total_return_pct": round(100 * total / config.DEFAULT_START_EQUITY, 2),
    }


# --- sweep --------------------------------------------------------------------


def _one(args) -> dict[str, Any]:
    step, levels, mult, lots, path = args
    ts, px = load_candles(Path(path))
    cfg = GridConfig(step_pips=step, levels=levels, lots=lots, stop_multiplier=mult)
    r = replay(cfg, ts, px)
    # The curve is for the report's best config only; 27 of them is 27 MB of
    # JSON for nothing.
    r.pop("equity_curve", None)
    r.pop("equity_days", None)
    return r


def run_sweep_sync(
    out: str = "sweep.json", jobs: int = 0, path: Path = CANDLE_FILE
) -> dict[str, Any]:
    combos = [
        (s, n, m, config.DEFAULT_LOTS, str(path))
        for s in config.SWEEP_STEPS
        for n in config.SWEEP_LEVELS
        for m in config.SWEEP_STOP_MULTIPLIERS
    ]
    jobs = jobs or (os.cpu_count() or 4)
    with ProcessPoolExecutor(max_workers=jobs) as pool:
        results = list(pool.map(_one, combos))

    ts, px = load_candles(path)
    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "candles": len(ts),
        "first_minute": datetime.fromtimestamp(ts[0], UTC).isoformat(),
        "last_minute": datetime.fromtimestamp(ts[-1], UTC).isoformat(),
        "results": results,
        "buy_and_hold": buy_and_hold(ts, px),
    }
    dest = OUTPUT / out if not os.path.isabs(out) else Path(out)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(payload, indent=2, default=str))
    return {"written": str(dest), "configs": len(results), "candles": len(ts)}


def run_one_sync(
    step: float,
    levels: int,
    mult: float,
    lots: float,
    with_trades: bool = False,
    path: Path = CANDLE_FILE,
) -> dict[str, Any]:
    ts, px = load_candles(path)
    cfg = GridConfig(step_pips=step, levels=levels, lots=lots, stop_multiplier=mult)
    r = replay(cfg, ts, px, with_trades=with_trades)
    if not with_trades:
        r.pop("equity_curve", None)
        r.pop("equity_days", None)
    return r


# --- publishing ---------------------------------------------------------------


def _git_sha() -> str | None:
    import subprocess

    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=str(HERE),
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=5,
        ).strip()
    except Exception:
        return None


async def publish(session_factory, sweep_path: str = "sweep.json") -> dict[str, Any]:
    """Write a sweep's result into `fx_sweep_runs`, where the dashboard reads it.

    A separate operator step, not a side effect of running the sweep. A sweep
    over a half-loaded window is a legitimate thing to run while the download
    is still going; publishing it is a decision to put it in front of a reader,
    and the two should not be the same keystroke.
    """
    from app.labs.forex_lab.models import FxSweepRun
    from app.labs.forex_lab.report import gate_verdict

    path = Path(sweep_path)
    if not path.is_absolute():
        path = OUTPUT / sweep_path
    # Read off the loop: this is a one-shot CLI today, but an async function
    # that blocks is a bug waiting for a caller that cares.
    data = json.loads(await asyncio.to_thread(path.read_text))
    ranked = sorted(data["results"], key=lambda x: -(x["profit_factor"] or -1))
    best = ranked[0]
    verdict = gate_verdict(best)

    payload = dict(data)
    payload["gate"] = verdict
    payload["best_config"] = best["config"]["name"]

    async with session_factory() as session:
        row = FxSweepRun(
            symbol=config.SYMBOL,
            first_minute=datetime.fromisoformat(data["first_minute"]),
            last_minute=datetime.fromisoformat(data["last_minute"]),
            candles=data["candles"],
            git_sha=_git_sha(),
            best_config=best["config"]["name"],
            gate_passed=verdict["passed"],
            result=payload,
        )
        session.add(row)
        await session.commit()
        return {
            "published": str(row.id),
            "best_config": row.best_config,
            "gate_passed": row.gate_passed,
            "candles": row.candles,
        }
