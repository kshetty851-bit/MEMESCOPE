"""Replay: the engine and the strategy over stored history, bar by bar, at cost.

    python -m app.labs.crypto_trend.replay --from 2026-08-01 --to 2026-09-10
    python -m app.labs.crypto_trend.replay --from ... --to ... --param STOP_ATR=3
    python -m app.labs.crypto_trend.replay --from ... --to ... --grid
    python -m app.labs.crypto_trend.replay --from ... --to ... --grid STOP_ATR=1.5,2,3

HINDSIGHT-FREE BY CONSTRUCTION. Every indicator is causal, so the state on
bar i computed over the whole series equals the state computed over bars
0..i alone (`compute_trend_states` — a test holds the identity bit for bit).
The replay steps through those per-bar states, decides on a bar's close and
fills at the NEXT bar's open. A test appends future candles to a dataset and
requires the result to be unchanged.

COSTS ON EVERY FILL: the taker fee and slippage on both sides, and funding
on open positions at every 8h boundary — the stored rate when `ct_funding`
covers the boundary, `FUNDING_FALLBACK` otherwise. Funding history starts
the day the lab went live, so a replay before that runs on the fallback.

SURVIVORSHIP: the universe is the CURRENT top-20 for the whole window. A
coin that was in the top-20 in the window and has since dropped out is not
replayed; one that has since entered is replayed for days it did not
qualify. Nothing here corrects for that. Treat every number as optimistic.

1h HISTORY BOUNDS THE WINDOW: the verdict needs a 1h state, and 1,000
hourly candles is about six weeks, so bars before that read NEUTRAL and
enter nothing, whatever the 4h says.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import sys
from bisect import bisect_right
from collections.abc import Iterable, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from itertools import product
from pathlib import Path
from statistics import mean
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.labs.crypto_trend import config
from app.labs.crypto_trend.candles import Candle, from_ms, to_ms
from app.labs.crypto_trend.data import (
    get_candles,
    get_funding_history,
    get_universe,
    get_universe_snapshot,
)
from app.labs.crypto_trend.models import CtReplayRun
from app.labs.crypto_trend.regime import compute_regime
from app.labs.crypto_trend.sim import SimAccount, Trade
from app.labs.crypto_trend.strategy import (
    CLOSE,
    LONG,
    SHORT,
    Position,
    Snapshot,
    StrategyConfig,
    advance,
    decide,
    verdict_of,
)
from app.labs.crypto_trend.trend import TrendState, compute_trend_states

FUNDING_INTERVAL_MS = 8 * 3_600_000
OUTPUT_DIR = Path(__file__).resolve().parent / "output"
DEFAULT_GRID: dict[str, list[Any]] = {
    "STOP_ATR": [1.5, 2.0, 3.0], "STRENGTH_MIN": [30, 40, 50], "ADX_MIN": [20, 25],
}
MAX_COMBOS = 50


# --- inputs ---------------------------------------------------------------------------

@dataclass
class Dataset:
    #: (symbol, timeframe) -> closed candles, oldest first.
    candles: dict[tuple[str, str], list[Candle]]
    #: (symbol, settlement ms) -> rate per 8h.
    funding: dict[tuple[str, int], float]
    universe: list[str]
    #: `live`, or the name of a `ct_universe_snapshots` row.
    universe_name: str = "live"


@dataclass
class BarLog:
    time: datetime
    regime: str | None
    breadth_up: float | None
    verdicts: dict[str, str]
    equity: float
    open_positions: int
    orders: list[str]


@dataclass
class ReplayResult:
    params: dict[str, Any]
    start: datetime
    end: datetime
    trades: list[Trade]
    open_positions: list[Position]
    equity_curve: list[tuple[datetime, float]]
    bars: list[BarLog]
    unfilled: list[str]
    final_equity: float
    fees_total: float
    funding_total: float
    universe_name: str = "live"
    coins: int = 0
    summary: dict[str, Any] = field(default_factory=dict)


# --- parameter overrides ----------------------------------------------------------------

def _coerce(raw: Any, like: Any) -> Any:
    if isinstance(like, bool):
        if isinstance(raw, bool):
            return raw
        return str(raw).strip().lower() in {"1", "true", "yes", "on"}
    if isinstance(like, int):
        return int(float(raw))
    if isinstance(like, float):
        return float(raw)
    return type(like)(raw)


@contextmanager
def overrides(params: Mapping[str, Any]):
    """Set `config.py` values for the duration of a run, then put them back.
    The engine reads the module at call time, so this reaches ADX_MIN and
    the rest of Phase 2 as well as the strategy."""
    saved: dict[str, Any] = {}
    try:
        for key, raw in params.items():
            if not key.isupper() or not hasattr(config, key):
                raise ValueError(f"unknown parameter {key!r}")
            saved[key] = getattr(config, key)
            setattr(config, key, _coerce(raw, saved[key]))
        yield
    finally:
        for key, value in saved.items():
            setattr(config, key, value)


def parse_params(items: Iterable[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for item in items:
        key, sep, value = item.partition("=")
        if not sep:
            raise ValueError(f"expected KEY=VALUE, got {item!r}")
        out[key.strip()] = value.strip()
    return out


def parse_grid(items: Sequence[str]) -> dict[str, list[str]]:
    if not items:
        return {k: [str(v) for v in vs] for k, vs in DEFAULT_GRID.items()}
    grid: dict[str, list[str]] = {}
    for item in items:
        key, sep, values = item.partition("=")
        if not sep:
            raise ValueError(f"expected KEY=a,b,c, got {item!r}")
        grid[key.strip()] = [v.strip() for v in values.split(",") if v.strip()]
    return grid


def grid_combos(grid: Mapping[str, Sequence[Any]]) -> list[dict[str, Any]]:
    keys = list(grid)
    combos = [dict(zip(keys, values, strict=True))
              for values in product(*(grid[k] for k in keys))]
    if len(combos) > MAX_COMBOS:
        raise ValueError(f"{len(combos)} combinations; the cap is {MAX_COMBOS}")
    return combos


# --- the replay -----------------------------------------------------------------------

def run_replay(dataset: Dataset, *, start: datetime, end: datetime,
               params: Mapping[str, Any] | None = None) -> ReplayResult:
    params = dict(params or {})
    with overrides(params):
        cfg = StrategyConfig.from_module()
        tf = cfg.timeframe
        start_ms, end_ms = to_ms(start), to_ms(end)
        symbols = [s for s in dataset.universe if (s, tf) in dataset.candles]
        series = {(sym, tf_): compute_trend_states(sym, tf_, cands, computed_at=start)
                  for (sym, tf_), cands in dataset.candles.items()}
        close_ms = {key: [to_ms(c.close_time) for c in cands]
                    for key, cands in dataset.candles.items()}
        funding_by_symbol: dict[str, list[tuple[int, float]]] = {}
        for (symbol, boundary), rate in sorted(dataset.funding.items()):
            funding_by_symbol.setdefault(symbol, []).append((boundary, rate))

        def index_at(symbol: str, tf_: str, t_ms: int) -> int:
            return bisect_right(close_ms.get((symbol, tf_), []), t_ms) - 1

        def state_at(symbol: str, tf_: str, t_ms: int) -> TrendState | None:
            i = index_at(symbol, tf_, t_ms)
            return series[(symbol, tf_)][i] if i >= 0 else None

        def states_at(t_ms: int) -> dict[str, dict[str, TrendState | None]]:
            return {s: {"4h": state_at(s, "4h", t_ms), "1h": state_at(s, "1h", t_ms)}
                    for s in symbols}

        def funding_at(symbol: str, boundary_ms: int) -> float:
            return dataset.funding.get((symbol, boundary_ms), cfg.funding_fallback)

        def funding_known(symbol: str, t_ms: int) -> float | None:
            rows = funding_by_symbol.get(symbol, [])
            i = bisect_right([b for b, _ in rows], t_ms + 1) - 1
            return rows[i][1] if i >= 0 else None

        times = sorted({t for s in symbols for t in close_ms[(s, tf)]
                        if start_ms <= t <= end_ms})
        account = SimAccount(cfg)
        curve: list[tuple[datetime, float]] = []
        bars: list[BarLog] = []
        unfilled: list[str] = []
        previous = states_at(times[0] - 1) if times else {}
        marks: dict[str, float] = {}

        for t in times:
            now = from_ms(t)
            states = states_at(t)
            marks = {}
            for s in symbols:
                i = index_at(s, tf, t)
                if i >= 0:
                    marks[s] = float(dataset.candles[(s, tf)][i].close)

            # Funding at the boundary this bar's close runs into, on positions
            # held across it — before this bar's fills, which open AT it.
            if (t + 1) % FUNDING_INTERVAL_MS == 0:
                for s in list(account.positions):
                    if s in marks:
                        account.charge_funding(s, funding_at(s, t + 1), marks[s])

            account.positions = {p.symbol: p
                                 for p in advance(account.positions.values(), states, cfg)}
            directions = {s: st["4h"].direction for s, st in states.items() if st["4h"]}
            regime = compute_regime(directions, bar_close_time=now, computed_at=now) \
                if directions else None
            funding_now = {s: r for s in symbols if (r := funding_known(s, t)) is not None}
            equity = account.equity(marks)
            curve.append((now, equity))

            snapshot = Snapshot(now=now, states=states, previous=previous, regime=regime,
                                funding=funding_now, universe=frozenset(symbols))
            orders = decide(snapshot, list(account.positions.values()), equity, cfg)
            filled: list[str] = []
            for order in sorted(orders, key=lambda o: o.action != CLOSE):
                i = index_at(order.symbol, tf, t)
                nxt = dataset.candles[(order.symbol, tf)]
                if i + 1 >= len(nxt) or to_ms(nxt[i + 1].open_time) > end_ms:
                    unfilled.append(f"{now.isoformat()} {order.action} {order.side} "
                                    f"{order.symbol}: no next open inside the window")
                    continue
                fill_time, fill_open = nxt[i + 1].open_time, float(nxt[i + 1].open)
                if order.action == CLOSE:
                    trade = account.fill_close(order.symbol, fill_open, fill_time,
                                               order.reason)
                    filled.append(f"CLOSE {order.side} {order.symbol} @ "
                                  f"{trade.exit_price:.6g} ({order.reason}) "
                                  f"pnl {trade.pnl_usd:+.2f}")
                else:
                    p = account.fill_open(order, fill_open, fill_time)
                    filled.append(f"OPEN {order.side} {order.symbol} @ {p.entry_price:.6g} "
                                  f"qty {p.qty:.6g} stop {p.stop:.6g} ({order.reason})")
            bars.append(BarLog(
                time=now, regime=regime.regime if regime else None,
                breadth_up=regime.breadth_up if regime else None,
                verdicts={s: verdict_of(st, s).verdict for s, st in states.items()},
                equity=equity, open_positions=len(account.positions), orders=filled))
            previous = states

        final_equity = account.equity(marks)
        result = ReplayResult(
            params=params, start=start, end=end, trades=list(account.trades),
            open_positions=list(account.positions.values()), equity_curve=curve, bars=bars,
            unfilled=unfilled, final_equity=final_equity, fees_total=account.fees_total,
            funding_total=account.funding_total, universe_name=dataset.universe_name,
            coins=len(symbols))
        result.summary = summarise(result, cfg, marks)
        return result


# --- the summary --------------------------------------------------------------------------

def _r(x: float | None, places: int = 4) -> float | None:
    return None if x is None else round(x, places)


def summarise(result: ReplayResult, cfg: StrategyConfig, marks: Mapping[str, float]) -> dict:
    trades = result.trades
    start_eq = cfg.starting_equity
    net = result.final_equity - start_eq
    peak, max_dd = start_eq, 0.0
    for _, eq in result.equity_curve:
        peak = max(peak, eq)
        max_dd = max(max_dd, (peak - eq) / peak * 100.0 if peak else 0.0)
    wins = [t for t in trades if t.pnl_usd > 0]
    losses = [t for t in trades if t.pnl_usd <= 0]
    gross_win = sum(t.pnl_usd for t in wins)
    gross_loss = -sum(t.pnl_usd for t in losses)

    def side_block(side: str) -> dict[str, Any]:
        mine = [t for t in trades if t.side == side]
        return {
            "trades": len(mine), "net_pnl": _r(sum(t.pnl_usd for t in mine), 2),
            "win_rate_pct": _r(100.0 * sum(1 for t in mine if t.pnl_usd > 0) / len(mine), 1)
            if mine else None,
            "expectancy_r": _r(mean(t.pnl_r for t in mine)) if mine else None,
        }

    by_reason: dict[str, dict[str, Any]] = {}
    for t in trades:
        block = by_reason.setdefault(t.reason, {"trades": 0, "net_pnl": 0.0})
        block["trades"] += 1
        block["net_pnl"] = round(block["net_pnl"] + t.pnl_usd, 2)

    return {
        "window": {"start": result.start.isoformat(), "end": result.end.isoformat(),
                   "bars": len(result.bars), "universe": result.universe_name,
                   "coins": result.coins},
        "params": result.params,
        "starting_equity": start_eq, "final_equity": _r(result.final_equity, 2),
        "net_pnl": _r(net, 2), "return_pct": _r(net / start_eq * 100.0, 2),
        "max_drawdown_pct": _r(max_dd, 2),
        "trades": len(trades),
        "win_rate_pct": _r(100.0 * len(wins) / len(trades), 1) if trades else None,
        "avg_win_r": _r(mean(t.pnl_r for t in wins)) if wins else None,
        "avg_loss_r": _r(mean(t.pnl_r for t in losses)) if losses else None,
        "expectancy_r": _r(mean(t.pnl_r for t in trades)) if trades else None,
        "profit_factor": _r(gross_win / gross_loss) if gross_loss else None,
        "long": side_block(LONG), "short": side_block(SHORT),
        "exposure_pct": _r(100.0 * sum(1 for b in result.bars if b.open_positions)
                           / len(result.bars), 1) if result.bars else None,
        "avg_implied_leverage": _r(mean(t.implied_leverage for t in trades))
        if trades else None,
        # 100 means the stop risked exactly RISK_PER_TRADE; lower means the
        # notional cap bound and less was actually at risk.
        "actual_risk_pct_of_intended": _r(mean(
            100.0 * t.risk_usd / t.intended_risk_usd
            for t in trades if t.intended_risk_usd), 1)
        if any(t.intended_risk_usd for t in trades) else None,
        "fees_total": _r(result.fees_total, 2), "funding_total": _r(result.funding_total, 2),
        "pnl_by_exit_reason": by_reason,
        "open_at_end": {
            "positions": len(result.open_positions),
            "unrealised": _r(sum(p.unrealised(marks[p.symbol]) for p in result.open_positions
                                 if p.symbol in marks), 2),
        },
        "unfilled_orders": len(result.unfilled),
    }


def format_summary(s: Mapping[str, Any]) -> str:
    def f(v: Any, suffix: str = "") -> str:
        return "-" if v is None else f"{v}{suffix}"

    lines = [
        f"window          {s['window']['start'][:10]} .. {s['window']['end'][:10]}  "
        f"({s['window']['bars']} 4h bars)   universe {s['window']['universe']} "
        f"({s['window']['coins']} coins)",
        f"params          {json.dumps(s['params']) if s['params'] else 'defaults'}",
        f"equity          {s['starting_equity']:.2f} -> {f(s['final_equity'])}   "
        f"net {f(s['net_pnl'])}  return {f(s['return_pct'], '%')}  max drawdown "
        f"{f(s['max_drawdown_pct'], '%')}",
        f"trades          {s['trades']}   win rate {f(s['win_rate_pct'], '%')}   "
        f"avg win {f(s['avg_win_r'], 'R')}   avg loss {f(s['avg_loss_r'], 'R')}",
        f"expectancy      {f(s['expectancy_r'], 'R')}   profit factor {f(s['profit_factor'])}",
        f"long            {s['long']['trades']} trades  net {f(s['long']['net_pnl'])}  "
        f"win {f(s['long']['win_rate_pct'], '%')}  exp {f(s['long']['expectancy_r'], 'R')}",
        f"short           {s['short']['trades']} trades  net {f(s['short']['net_pnl'])}  "
        f"win {f(s['short']['win_rate_pct'], '%')}  exp {f(s['short']['expectancy_r'], 'R')}",
        f"exposure        {f(s['exposure_pct'], '%')} of bars   avg implied leverage "
        f"{f(s['avg_implied_leverage'], 'x')}   actual risk "
        f"{f(s['actual_risk_pct_of_intended'], '%')} of intended",
        f"costs           fees {f(s['fees_total'])}   funding {f(s['funding_total'])}",
        "by exit reason  " + (", ".join(f"{k}: {v['trades']} / {v['net_pnl']:+.2f}"
                                        for k, v in s['pnl_by_exit_reason'].items())
                              or "-"),
        f"open at end     {s['open_at_end']['positions']} positions, unrealised "
        f"{f(s['open_at_end']['unrealised'])}   unfilled orders {s['unfilled_orders']}",
    ]
    return "\n".join(lines)


# --- outputs ----------------------------------------------------------------------

def write_outputs(result: ReplayResult, run_dir: Path) -> Path:
    run_dir.mkdir(parents=True, exist_ok=True)
    with (run_dir / "trades.csv").open("w", newline="") as fh:
        fields = list(Trade.__dataclass_fields__)
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for t in result.trades:
            writer.writerow({k: (v.isoformat() if isinstance(v, datetime) else v)
                             for k, v in asdict(t).items()})
    with (run_dir / "equity.csv").open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["time", "equity"])
        writer.writerows((t.isoformat(), round(e, 4)) for t, e in result.equity_curve)
    (run_dir / "summary.json").write_text(json.dumps(result.summary, indent=2) + "\n")
    if result.unfilled:
        (run_dir / "unfilled.txt").write_text("\n".join(result.unfilled) + "\n")
    return run_dir


async def load_dataset(session: AsyncSession, *, end: datetime,
                       universe: str | None = None) -> Dataset:
    """Candles and funding for the live universe, or for a frozen snapshot
    by name."""
    if universe is None:
        symbols = [c.binance_symbol for c in await get_universe(session)]
        name = "live"
    else:
        snapshot = await get_universe_snapshot(session, universe)
        if snapshot is None:
            raise ValueError(f"no universe snapshot named {universe!r}")
        symbols = [entry["symbol"] for entry in snapshot.symbols]
        name = snapshot.name
    candles: dict[tuple[str, str], list[Candle]] = {}
    for symbol in symbols:
        for tf in config.TIMEFRAMES:
            rows = await get_candles(session, symbol, tf)
            candles[(symbol, tf)] = [c for c in rows if c.close_time <= end]
    funding = {(s, to_ms(t)): r for s, t, r in await get_funding_history(session, symbols)}
    return Dataset(candles=candles, funding=funding, universe=symbols, universe_name=name)


async def store_run(session: AsyncSession, result: ReplayResult,
                    label: str | None) -> CtReplayRun:
    row = CtReplayRun(window_start=result.start, window_end=result.end, label=label,
                      params=result.params, summary=result.summary, trades=len(result.trades))
    session.add(row)
    await session.flush()
    return row


# --- CLI --------------------------------------------------------------------------

def _window(from_date: str, to_date: str) -> tuple[datetime, datetime]:
    start = datetime.fromisoformat(from_date).replace(tzinfo=UTC)
    end = datetime.fromisoformat(to_date).replace(tzinfo=UTC) + timedelta(days=1) \
        - timedelta(milliseconds=1)
    if end <= start:
        raise ValueError("--to must be after --from")
    return start, end


def _grid_table(rows: list[tuple[dict[str, Any], dict[str, Any]]]) -> str:
    keys = list(rows[0][0]) if rows else []
    head = ("".join(f"{k:>14}" for k in keys)
            + f"{'trades':>8}{'net':>10}{'ret%':>8}{'maxdd%':>8}{'win%':>7}"
            + f"{'exp_R':>8}{'PF':>7}")
    lines = [head]
    for params, s in rows:
        def cell(v: Any) -> str:
            return "-" if v is None else str(v)
        lines.append("".join(f"{cell(params[k]):>14}" for k in keys)
                     + f"{s['trades']:>8}{cell(s['net_pnl']):>10}{cell(s['return_pct']):>8}"
                       f"{cell(s['max_drawdown_pct']):>8}{cell(s['win_rate_pct']):>7}"
                       f"{cell(s['expectancy_r']):>8}{cell(s['profit_factor']):>7}")
    return "\n".join(lines)


async def _main(args: argparse.Namespace) -> int:
    from app.db.session import SessionFactory

    start, end = _window(args.from_date, args.to_date)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    async with SessionFactory() as session:
        dataset = await load_dataset(session, end=end, universe=args.universe)
        if not dataset.universe:
            sys.stderr.write("no universe stored; run the data tick first\n")
            return 1
        base = parse_params(args.param or [])
        if args.grid is None:
            result = run_replay(dataset, start=start, end=end, params=base)
            run_dir = write_outputs(result, OUTPUT_DIR / f"replay_{stamp}")
            sys.stdout.write(format_summary(result.summary)
                             + f"\noutputs         {run_dir}\n")
            if not args.no_store:
                await store_run(session, result, args.label)
                await session.commit()
            return 0

        combos = grid_combos(parse_grid(args.grid))
        rows = []
        for combo in combos:
            params = {**base, **combo}
            result = run_replay(dataset, start=start, end=end, params=params)
            write_outputs(result, OUTPUT_DIR / f"grid_{stamp}"
                          / "_".join(f"{k}={v}" for k, v in combo.items()))
            rows.append((combo, result.summary))
            if not args.no_store:
                await store_run(session, result, args.label or "grid")
        if not args.no_store:
            await session.commit()
        rows.sort(key=lambda r: (r[1]["expectancy_r"] is None,
                                 -(r[1]["expectancy_r"] or 0)))
        sys.stdout.write(_grid_table(rows) + "\n")
        sys.stdout.write(
            f"\n{len(rows)} combinations over ONE window of ONE universe. The top rows\n"
            "are the ones that happened to fit this sample; a parameter chosen here was\n"
            "chosen BY the sample, and its out-of-sample expectancy is unknown. This\n"
            "platform has ten recorded no-edge findings that looked like a grid's top row.\n")
        sys.stdout.write(f"outputs         {OUTPUT_DIR / f'grid_{stamp}'}\n")
        return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.labs.crypto_trend.replay")
    parser.add_argument("--from", dest="from_date", required=True, help="YYYY-MM-DD, UTC")
    parser.add_argument("--to", dest="to_date", required=True,
                        help="YYYY-MM-DD, UTC, inclusive")
    parser.add_argument("--param", action="append", metavar="KEY=VALUE",
                        help="override a config.py value for this run (repeatable)")
    parser.add_argument("--grid", nargs="*", metavar="KEY=a,b,c",
                        help="run every combination; no values = the default grid")
    parser.add_argument("--universe", metavar="NAME",
                        help="a ct_universe_snapshots name; default: the live universe")
    parser.add_argument("--label", help="stored with the run")
    parser.add_argument("--no-store", action="store_true",
                        help="do not write ct_replay_runs")
    args = parser.parse_args(argv)
    return asyncio.run(_main(args))


if __name__ == "__main__":
    raise SystemExit(main())
