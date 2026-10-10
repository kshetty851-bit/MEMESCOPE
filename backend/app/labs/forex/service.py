"""The Forex lab's use cases: data in, runs out. No FastAPI in here.

## Runs are background jobs with their own sessions

A research run replays the market hundreds of times and takes minutes, so
`create_run` only writes a `queued` row; the HTTP request ends there. The job
then runs as an asyncio task (`launch`) that opens its OWN session, commits its
own progress, and does the CPU-bound work in a worker thread so the event loop
keeps serving requests. The request's session never crosses into the job.

One run executes at a time (`_SLOT`); the rest stay `queued`. A run whose task
died with a deploy would sit `running` forever, so a read marks any queued or
running run that this process is NOT running, and that has not been touched for
30 minutes, as failed `interrupted`.

`execute_run` takes the session as a parameter so the same code path runs from
the CLI and from tests without waiting on a background task.

Nothing here places an order or reaches an account; the only network call is the
public historical-candle download in `_execute_fetch`.
"""

from __future__ import annotations

import asyncio
import csv
import io
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import SessionFactory
from app.labs.forex import codec, jobs, meta, pipeline, prose, repository, serialize
from app.labs.forex.csv_import import FORMATS, parse_csv
from app.labs.forex.data import QualityReport, resample, validate
from app.labs.forex.pipeline import Market, NoDataError
from app.labs.forex.providers import PROVIDERS_INFO, CandleProvider, DukascopyProvider
from app.labs.forex.research import chronological_split
from app.labs.forex.types import (
    CONFIG_VERSION,
    INSTRUMENTS,
    TIMEFRAME_SECONDS,
    BacktestConfig,
    Candle,
    StrategyId,
    Timeframe,
)
from app.models.forex import ForexRun

logger = get_logger(__name__)

PROVIDER = "dukascopy"
MAX_FETCH_DAYS = 366
MAX_WINDOW_DAYS = 800
MAX_COMPARE_CONFIGS = 6
QUALITY_CAP = timedelta(days=400)
MAX_STORED_IMPORT_ERRORS = 50
MAX_FAILURES_LISTED = 50
PROGRESS_POLL_SECONDS = 1.0
LAUNCH_WAIT_ATTEMPTS = 40
LAUNCH_WAIT_SECONDS = 0.25
#: A stored HTF series covering less than this share of the window is treated
#: as a sample, not a series, and the trend average is built from finer candles.
MIN_STORED_COVERAGE = 0.9

#: Run kinds a client may submit to /runs.
COMPUTE_KINDS = ("backtest", "research", "compare")

TRADE_COLUMNS = (
    "id", "direction", "signal_time", "entry_time", "exit_time", "entry_price",
    "exit_price", "stop_price", "take_profit_price", "units", "risk_usd", "gross_pnl",
    "commission", "spread_slippage_cost", "financing", "net_pnl", "r_multiple",
    "exit_reason", "reason", "ambiguous_exit", "duration_minutes",
)  # fmt: skip


class RunNotFoundError(LookupError):
    """No run with that id."""


class RunNotReadyError(RuntimeError):
    """The run has no result yet."""


class TradesUnavailableError(ValueError):
    """This kind of run has no single trade list."""


# One run at a time; held for the whole job. Background tasks are held in a set
# so the event loop cannot drop one mid-flight (same pattern as the graduation lab).
_SLOT = asyncio.Semaphore(1)
_TASKS: set[asyncio.Task[Any]] = set()
_LIVE: set[int] = set()


def _now() -> datetime:
    return datetime.now(UTC)


def as_utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


# --------------------------------------------------------------------------
# Meta
# --------------------------------------------------------------------------


def providers_meta() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for key, info in PROVIDERS_INFO.items():
        item: dict[str, Any] = {
            "id": key,
            "name": info["label"],
            "free": info["cost"] == "free",
            "needs_key": info["api_key"] != "none",
            "notes": info["notes"],
        }
        if info.get("url"):
            item["url"] = info["url"]
        out.append(item)
    return out


def build_meta() -> dict[str, Any]:
    return prose.render_dict(
        {
            "instruments": meta.instruments_meta(),
            "timeframes": list(meta.TIMEFRAMES),
            "risk_options_pct": list(meta.RISK_OPTIONS_PCT),
            "strategies": meta.strategies_meta(),
            "shared_fields": meta.shared_fields(),
            "providers": providers_meta(),
            "target_pcts": list(meta.TARGET_PCTS),
            "disclaimer": {"code": meta.DISCLAIMER_CODE},
        }
    )


# --------------------------------------------------------------------------
# Validation helpers
# --------------------------------------------------------------------------


def _instrument(symbol: str) -> None:
    inst = INSTRUMENTS.get(symbol)
    if inst is None:
        raise codec.ConfigError(f"symbol: unknown instrument {symbol!r}")
    if not inst.enabled:
        raise codec.ConfigError(f"symbol: {symbol} is not enabled yet")


def _timeframe(value: str) -> Timeframe:
    try:
        return Timeframe(value)
    except ValueError as exc:
        allowed = ", ".join(meta.TIMEFRAMES)
        raise codec.ConfigError(f"timeframe: must be one of {allowed}") from exc


def _window(start: datetime, end: datetime) -> tuple[datetime, datetime]:
    start, end = as_utc(start), as_utc(end)
    if end <= start:
        raise codec.ConfigError("end_not_after_start")
    if end - start > timedelta(days=MAX_WINDOW_DAYS):
        raise codec.ConfigError(f"window: at most {MAX_WINDOW_DAYS} days")
    return start, end


def _expected_bars(start: datetime, end: datetime, timeframe: Timeframe) -> float:
    # The FX week is five days in seven; this is a coverage heuristic, not a count.
    return (end - start).total_seconds() / TIMEFRAME_SECONDS[timeframe] * 5 / 7


# --------------------------------------------------------------------------
# Market loading
# --------------------------------------------------------------------------


async def _resampled_from(
    db: AsyncSession,
    symbol: str,
    src: Timeframe,
    dst: Timeframe,
    start: datetime,
    end: datetime,
) -> list[Candle]:
    raw = await repository.load_candles(db, symbol, src.value, start, end)
    if not raw:
        return []
    return list((await asyncio.to_thread(resample, raw, src, dst)).candles)


async def load_market(
    db: AsyncSession, cfg: BacktestConfig, start: datetime, end: datetime
) -> Market:
    """Everything a replay of `cfg` over [start, end) reads, loaded once.

    Execution candles come from the stored timeframe when it covers the window,
    else are resampled from stored 1-minute candles. The trend timeframe is
    stored, else resampled from 1-minute or execution candles. Candles are
    loaded from `start - warm-up` so indicators are settled on the first day;
    trading begins at `start` (the engine's `trade_from`).
    """
    start, end = as_utc(start), as_utc(end)
    symbol, tf = cfg.symbol, cfg.timeframe
    warm_start = start - pipeline.warmup_for(cfg)

    stored = await repository.load_candles(db, symbol, tf.value, warm_start, end)
    in_window = sum(1 for c in stored if c.open_time >= start)
    exec_candles: list[Candle] = stored
    exec_derived = "stored"
    sources_tf = tf

    one_minute: list[Candle] | None = None
    if tf is not Timeframe.M1 and in_window < MIN_STORED_COVERAGE * _expected_bars(
        start, end, tf
    ):
        one_minute = await repository.load_candles(
            db, symbol, Timeframe.M1.value, warm_start, end
        )
        if one_minute:
            derived = list(
                (await asyncio.to_thread(resample, one_minute, Timeframe.M1, tf)).candles
            )
            derived_in = sum(1 for c in derived if c.open_time >= start)
            if derived_in > in_window:
                exec_candles, exec_derived, sources_tf = (
                    derived,
                    "resampled_from_1m",
                    Timeframe.M1,
                )
                in_window = derived_in
    if in_window == 0:
        raise NoDataError("no_data_for_range")

    htf: list[Candle] | None = None
    htf_tf: Timeframe | None = None
    htf_derived = "none"
    if pipeline.needs_htf(cfg):
        htf_tf = cfg.params.trend_timeframe
        htf = await repository.load_candles(db, symbol, htf_tf.value, warm_start, end)
        htf_derived = "stored"
        if len(htf) < MIN_STORED_COVERAGE * _expected_bars(warm_start, end, htf_tf):
            if one_minute is None and tf is not Timeframe.M1:
                one_minute = await repository.load_candles(
                    db, symbol, Timeframe.M1.value, warm_start, end
                )
            built: list[Candle] = []
            if one_minute:
                built = list(
                    (
                        await asyncio.to_thread(resample, one_minute, Timeframe.M1, htf_tf)
                    ).candles
                )
            elif (
                TIMEFRAME_SECONDS[htf_tf] > TIMEFRAME_SECONDS[tf]
                and TIMEFRAME_SECONDS[htf_tf] % TIMEFRAME_SECONDS[tf] == 0
            ):
                built = list(
                    (await asyncio.to_thread(resample, exec_candles, tf, htf_tf)).candles
                )
            if len(built) > len(htf):
                htf, htf_derived = built, "resampled"
        if not htf:
            raise NoDataError("market_lacks_trend_timeframe")

    lower: list[Candle] | None = None
    if tf is not Timeframe.M1:
        if one_minute is None:
            one_minute = await repository.load_candles(
                db, symbol, Timeframe.M1.value, start, end
            )
        lower = [c for c in one_minute if c.open_time >= start] or None

    sources = await repository.sources_in_range(db, symbol, sources_tf.value, start, end)
    return Market(
        symbol=symbol,
        timeframe=tf,
        candles=tuple(exec_candles),
        htf=None if htf is None else tuple(htf),
        htf_timeframe=htf_tf,
        lower=None if lower is None else tuple(lower),
        sources=tuple(sources),
        exec_derived=exec_derived,
        htf_derived=htf_derived,
    )


# --------------------------------------------------------------------------
# Data: overview, quality, CSV import
# --------------------------------------------------------------------------


def _batch_out(b: Any) -> dict[str, Any]:
    return {
        "id": b.id,
        "symbol": b.symbol,
        "timeframe": b.timeframe,
        "source": b.source,
        "filename": b.filename,
        "rows_total": b.rows_total,
        "rows_accepted": b.rows_accepted,
        "rows_inserted": b.rows_inserted,
        "rows_existing": b.rows_existing,
        "error_count": b.error_count,
        "errors": b.errors,
        "detected_format": b.detected_format,
        "start": b.start,
        "end": b.end,
        "quality": b.quality,
        "notes": serialize.codes(b.notes),
        "created_at": b.created_at,
    }


async def data_overview(db: AsyncSession) -> dict[str, Any]:
    return prose.render_dict(
        {
            "datasets": await repository.datasets(db),
            "imports": [_batch_out(b) for b in await repository.latest_import_batches(db)],
            "fetch": await repository.fetch_summary(db, PROVIDER),
            "providers": providers_meta(),
        }
    )


async def data_quality(
    db: AsyncSession,
    *,
    symbol: str,
    timeframe: str,
    start: datetime | None,
    end: datetime | None,
) -> dict[str, Any]:
    _instrument(symbol)
    tf = _timeframe(timeframe)
    derived = "stored"
    src = tf
    span = await repository.bounds(db, symbol, tf.value)
    if span is None and tf is not Timeframe.M1:
        span = await repository.bounds(db, symbol, Timeframe.M1.value)
        if span is not None:
            derived, src = "resampled_from_1m", Timeframe.M1
    if span is None:
        return prose.render_dict(serialize.quality_json(validate([], symbol, tf), "stored"))

    lo = as_utc(start) if start is not None else span[0]
    hi = (
        as_utc(end) if end is not None else span[1] + timedelta(seconds=TIMEFRAME_SECONDS[src])
    )
    if hi - lo > QUALITY_CAP:
        # Capped, not refused: with no explicit window the most recent 400 days
        # are judged; with an explicit start, the 400 days after it.
        if start is None:
            lo = hi - QUALITY_CAP
        else:
            hi = lo + QUALITY_CAP
    candles = await repository.load_candles(db, symbol, src.value, lo, hi)
    if derived != "stored":
        candles = list((await asyncio.to_thread(resample, candles, src, tf)).candles)
    report: QualityReport = await asyncio.to_thread(validate, candles, symbol, tf)
    return prose.render_dict(serialize.quality_json(report, derived))


async def import_csv(
    db: AsyncSession,
    *,
    symbol: str,
    timeframe: str,
    fmt: str,
    utc_offset_minutes: int,
    filename: str,
    content: str,
    created_by: Any = None,
) -> dict[str, Any]:
    """Parse, store and report a CSV. Existing candles are never overwritten."""
    _instrument(symbol)
    tf = _timeframe(timeframe)
    if fmt not in FORMATS:
        raise codec.ConfigError(f"fmt: must be one of {', '.join(FORMATS)}")
    try:
        parsed = await asyncio.to_thread(
            parse_csv,
            content,
            symbol=symbol,
            timeframe=tf,
            fmt=fmt,
            utc_offset_minutes=utc_offset_minutes,
        )
    except ValueError as exc:
        raise codec.ConfigError(str(exc)) from exc

    quality = (
        serialize.quality_json(await asyncio.to_thread(validate, parsed.candles, symbol, tf))
        if parsed.candles
        else None
    )
    batch = await repository.add_import_batch(
        db,
        symbol=symbol,
        timeframe=tf.value,
        source="csv",
        filename=filename[:256],
        rows_total=parsed.rows_total,
        rows_accepted=parsed.rows_accepted,
        rows_inserted=0,
        rows_existing=0,
        error_count=parsed.error_count,
        errors=[{"line": e.line, "message": e.message} for e in parsed.errors][
            :MAX_STORED_IMPORT_ERRORS
        ],
        detected_format=parsed.detected_format,
        start=parsed.candles[0].open_time if parsed.candles else None,
        end=parsed.candles[-1].open_time if parsed.candles else None,
        quality=quality,
        notes=list(parsed.notes),
        created_by=created_by,
    )
    inserted = await repository.insert_candles(
        db, parsed.candles, symbol=symbol, timeframe=tf.value, source="csv", batch_id=batch.id
    )
    batch.rows_inserted = inserted
    batch.rows_existing = parsed.rows_accepted - inserted
    await db.flush()
    return prose.render_dict(_batch_out(batch))


# --------------------------------------------------------------------------
# Strategy versions
# --------------------------------------------------------------------------


def _version_out(v: Any) -> dict[str, Any]:
    return {
        "id": v.id,
        "name": v.name,
        "version": v.version,
        "strategy": v.strategy,
        "config": v.config,
        "notes": v.notes,
        "created_at": v.created_at,
    }


async def list_versions(db: AsyncSession) -> dict[str, Any]:
    return {"versions": [_version_out(v) for v in await repository.list_versions(db)]}


async def create_version(
    db: AsyncSession, *, name: str, config: Any, notes: str | None, created_by: Any = None
) -> dict[str, Any]:
    cfg = codec.config_from_json(config)
    row = await repository.add_version(
        db,
        name=name.strip(),
        strategy=cfg.strategy.value,
        config=codec.config_to_json(cfg),
        notes=notes,
        created_by=created_by,
    )
    return _version_out(row)


# --------------------------------------------------------------------------
# Creating runs
# --------------------------------------------------------------------------


async def _require_data(
    db: AsyncSession, cfg: BacktestConfig, start: datetime, end: datetime
) -> None:
    for tf in {cfg.timeframe, Timeframe.M1}:
        if await repository.count_candles(db, cfg.symbol, tf.value, start, end) > 0:
            return
    raise codec.ConfigError("no_data_for_range")


async def create_run(
    db: AsyncSession,
    *,
    kind: str,
    config: Any,
    configs: Any,
    start: datetime,
    end: datetime,
    name: str | None,
    strategy_version_id: int | None,
    options: Any,
    created_by: Any = None,
) -> dict[str, Any]:
    """Validate a request and write a `queued` run. Does not start it."""
    if kind not in COMPUTE_KINDS:
        raise codec.ConfigError(f"kind: must be one of {', '.join(COMPUTE_KINDS)}")
    start, end = _window(start, end)
    opts = jobs.parse_options(options)
    try:
        chronological_split(start, end, opts.dev_pct, opts.val_pct)
    except ValueError as exc:
        if kind != "backtest":
            raise codec.ConfigError(str(exc)) from exc

    version = None
    if strategy_version_id is not None:
        version = await repository.get_version(db, strategy_version_id)
        if version is None:
            raise codec.ConfigError("strategy_version_id: no such version")

    cfgs: list[BacktestConfig]
    if kind == "compare":
        if configs is None:
            cfgs = [meta.default_config(s) for s in StrategyId]
        else:
            if not isinstance(configs, list) or not 1 <= len(configs) <= MAX_COMPARE_CONFIGS:
                raise codec.ConfigError(
                    f"configs: expected 1 to {MAX_COMPARE_CONFIGS} configs"
                )
            cfgs = [codec.config_from_json(c) for c in configs]
        for c in cfgs:
            jobs.resolve_default_grid(c)
    else:
        raw = config if config is not None else (version.config if version else None)
        if raw is None:
            raise codec.ConfigError("config: required")
        cfg = codec.config_from_json(raw)
        if kind == "research":
            jobs.resolve_grid(cfg, opts)
        cfgs = [cfg]
    for c in cfgs:
        await _require_data(db, c, start, end)

    request: dict[str, Any] = {
        "start": serialize.iso(start),
        "end": serialize.iso(end),
        "options": options,
    }
    if kind == "compare":
        request["configs"] = [codec.config_to_json(c) for c in cfgs]
    row = await repository.add_run(
        db,
        kind=kind,
        status="queued",
        progress=0,
        message=None,
        name=name.strip() if name and name.strip() else None,
        strategy_version_id=strategy_version_id,
        config=None if kind == "compare" else codec.config_to_json(cfgs[0]),
        request=request,
        config_version=CONFIG_VERSION,
        app_version=settings.VERSION,
        created_by=created_by,
    )
    return run_out(row)


async def create_fetch_run(
    db: AsyncSession,
    *,
    provider: str,
    symbol: str,
    start_date: date,
    end_date: date,
    created_by: Any = None,
) -> dict[str, Any]:
    if provider != PROVIDER:
        raise codec.ConfigError(f"provider: must be {PROVIDER}")
    _instrument(symbol)
    if end_date < start_date:
        raise codec.ConfigError("end_not_after_start")
    if (end_date - start_date).days + 1 > MAX_FETCH_DAYS:
        raise codec.ConfigError(f"fetch: at most {MAX_FETCH_DAYS} days")
    row = await repository.add_run(
        db,
        kind="fetch",
        status="queued",
        progress=0,
        message=None,
        name=None,
        config=None,
        request={
            "provider": provider,
            "symbol": symbol,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
        },
        config_version=CONFIG_VERSION,
        app_version=settings.VERSION,
        created_by=created_by,
    )
    return run_out(row)


# --------------------------------------------------------------------------
# Reading runs
# --------------------------------------------------------------------------


def run_out(run: ForexRun) -> dict[str, Any]:
    return {
        "id": run.id,
        "kind": run.kind,
        "status": run.status,
        "progress": run.progress,
        "message": run.message,
        "name": run.name,
        "strategy_version_id": run.strategy_version_id,
        "config": run.config,
        "request": run.request,
        "data_fingerprint": run.data_fingerprint,
        "config_version": run.config_version,
        "app_version": run.app_version,
        "summary": run.summary,
        "error": prose.error_text(run.error),
        "created_at": run.created_at,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
    }


async def _fail_stale(db: AsyncSession, now: datetime | None) -> None:
    await repository.fail_stale_runs(
        db, now=now or _now(), live=set(_LIVE), message="interrupted"
    )


async def list_runs(
    db: AsyncSession, *, kind: str | None, limit: int, now: datetime | None = None
) -> dict[str, Any]:
    await _fail_stale(db, now)
    rows = await repository.list_runs(db, kind=kind, limit=limit)
    return {"runs": [run_out(r) for r in rows]}


async def get_run(
    db: AsyncSession, run_id: int, *, now: datetime | None = None
) -> dict[str, Any]:
    await _fail_stale(db, now)
    run = await repository.get_run(db, run_id)
    if run is None:
        raise RunNotFoundError(run_id)
    return {"run": run_out(run), "result": prose.render(run.result)}


def _csv_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


async def trades_csv(db: AsyncSession, run_id: int) -> tuple[str, Iterator[str]]:
    """(filename, CSV lines) with EVERY trade of the run, losers included."""
    run = await repository.get_run(db, run_id)
    if run is None:
        raise RunNotFoundError(run_id)
    if run.kind not in ("backtest", "research"):
        raise TradesUnavailableError(run.kind)
    if run.status != "done" or run.result is None:
        raise RunNotReadyError(run_id)
    trades: list[dict[str, Any]] = run.result.get("trades", [])

    def lines() -> Iterator[str]:
        buf = io.StringIO()
        writer = csv.writer(buf, lineterminator="\n")
        writer.writerow(TRADE_COLUMNS)
        yield buf.getvalue()
        for t in trades:
            buf.seek(0)
            buf.truncate()
            writer.writerow([_csv_cell(t.get(c)) for c in TRADE_COLUMNS])
            yield buf.getvalue()

    return f"forex-run-{run.id}-trades.csv", lines()


# --------------------------------------------------------------------------
# Executing runs
# --------------------------------------------------------------------------


async def _checkpoint(db: AsyncSession, commit: bool) -> None:
    if commit:
        await db.commit()
    else:
        await db.flush()


def _error_message(exc: BaseException) -> str:
    if isinstance(exc, ValueError):
        return str(exc)[:500]
    return f"{type(exc).__name__}: {exc}"[:500]


class _Holder:
    """Progress written from the worker thread, read by the polling loop.

    `cancel` makes the NEXT progress report raise, which is how a run that is
    cancelled (a server shutting down) stops its thread: the replay loops report
    after every replay, so the thread ends within one replay instead of holding
    the process open for the length of the job.
    """

    __slots__ = ("cancelled", "message", "pct")

    def __init__(self) -> None:
        self.pct = 0
        self.message = ""
        self.cancelled = False

    def __call__(self, pct: int, message: str) -> None:
        if self.cancelled:
            raise RunCancelledError("run_cancelled")
        self.pct, self.message = pct, message


class RunCancelledError(RuntimeError):
    """Raised inside the worker thread when its run was cancelled."""


async def _compute(
    db: AsyncSession,
    run: ForexRun,
    commit: bool,
    fn: Callable[[jobs.Progress], tuple[dict[str, Any], dict[str, Any]]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Run `fn` in a worker thread while writing its progress to the run row."""
    holder = _Holder()
    task = asyncio.ensure_future(asyncio.to_thread(fn, holder))
    last = -1
    try:
        while True:
            done, _pending = await asyncio.wait({task}, timeout=PROGRESS_POLL_SECONDS)
            if done:
                break
            if holder.pct != last:
                last = holder.pct
                run.progress = max(run.progress, min(last, 99))
                run.message = holder.message[:256] or None
                await _checkpoint(db, commit)
    except asyncio.CancelledError:
        holder.cancelled = True
        raise
    return task.result()


def _parse_dt(value: str) -> datetime:
    return as_utc(datetime.fromisoformat(value))


async def _execute_compute(db: AsyncSession, run: ForexRun, commit: bool) -> None:
    req = run.request
    start, end = _parse_dt(req["start"]), _parse_dt(req["end"])
    opts = jobs.parse_options(req.get("options"))
    fn: Callable[[jobs.Progress], tuple[dict[str, Any], dict[str, Any]]]

    if run.kind == "compare":
        cfgs = [codec.config_from_json(c) for c in req["configs"]]
        cache: dict[tuple[Any, ...], Market] = {}
        markets: list[Market] = []
        for c in cfgs:
            key = (
                c.symbol,
                c.timeframe,
                pipeline.needs_htf(c),
                c.params.trend_timeframe,
                pipeline.warmup_for(c),
            )
            if key not in cache:
                cache[key] = await load_market(db, c, start, end)
            markets.append(cache[key])
        prints = sorted(
            {pipeline.fingerprint(m.candles, m.symbol, m.timeframe) for m in markets}
        )
        run.data_fingerprint = pipeline.combined_fingerprint(prints)

        def fn(progress: jobs.Progress) -> tuple[dict[str, Any], dict[str, Any]]:
            return jobs.run_compare_job(cfgs, markets, start, end, opts, progress)

    else:
        cfg = codec.config_from_json(run.config)
        market = await load_market(db, cfg, start, end)
        run.data_fingerprint = pipeline.fingerprint(market.candles, cfg.symbol, cfg.timeframe)
        if run.kind == "research":

            def fn(progress: jobs.Progress) -> tuple[dict[str, Any], dict[str, Any]]:
                return jobs.run_research_job(
                    cfg, market, start, end, opts, name=run.name, progress=progress
                )

        else:

            def fn(progress: jobs.Progress) -> tuple[dict[str, Any], dict[str, Any]]:
                return jobs.run_backtest_job(cfg, market, start, end, opts, progress)

    run.progress, run.message = 5, "candles loaded"
    await _checkpoint(db, commit)
    result, summary = await _compute(db, run, commit, fn)
    run.result, run.summary = result, summary


@dataclass
class _FetchStats:
    fetched: int = 0
    cached: int = 0
    empty: int = 0
    failed: int = 0
    incomplete: int = 0
    inserted: int = 0


async def _execute_fetch(
    db: AsyncSession, run: ForexRun, commit: bool, provider: CandleProvider | None
) -> None:
    req = run.request
    symbol = req["symbol"]
    first, last = date.fromisoformat(req["start_date"]), date.fromisoformat(req["end_date"])
    days = [first + timedelta(days=i) for i in range((last - first).days + 1)]
    today = _now().date()
    cached = await repository.fetch_days(db, PROVIDER, symbol, first, last)
    stats = _FetchStats()
    failures: list[dict[str, str]] = []

    client: httpx.AsyncClient | None = None
    if provider is None:
        client = httpx.AsyncClient(timeout=httpx.Timeout(30.0))
        provider = DukascopyProvider(client)
    try:
        for i, day in enumerate(days, start=1):
            if day >= today:
                # An unfinished day cached as "done" would be wrong forever.
                stats.incomplete += 1
            elif (row := cached.get(day)) is not None and row.ok:
                stats.cached += 1
            else:
                try:
                    got = await provider.fetch_day(symbol, day)
                except Exception as exc:  # network trouble is a per-day fact, never fatal
                    stats.failed += 1
                    message = f"{type(exc).__name__}: {exc}"[:256]
                    if len(failures) < MAX_FAILURES_LISTED:
                        failures.append({"day": day.isoformat(), "error": message})
                    await repository.record_fetch_day(
                        db,
                        provider=PROVIDER,
                        symbol=symbol,
                        day=day,
                        ok=False,
                        empty=False,
                        candles=0,
                        error=message,
                        fetched_at=_now(),
                    )
                else:
                    stats.inserted += await repository.insert_candles(
                        db,
                        got.candles,
                        symbol=symbol,
                        timeframe=Timeframe.M1.value,
                        source=PROVIDER,
                    )
                    stats.fetched += 1
                    stats.empty += int(got.empty)
                    await repository.record_fetch_day(
                        db,
                        provider=PROVIDER,
                        symbol=symbol,
                        day=day,
                        ok=True,
                        empty=got.empty,
                        candles=len(got.candles),
                        error=None,
                        fetched_at=_now(),
                    )
            run.progress = min(99, int(i / len(days) * 100))
            run.message = f"day {i} of {len(days)}"
            await _checkpoint(db, commit)
    finally:
        if client is not None:
            await client.aclose()

    run.result = {
        "type": "fetch",
        "provider": PROVIDER,
        "symbol": symbol,
        "start_date": first.isoformat(),
        "end_date": last.isoformat(),
        "days_total": len(days),
        "days_fetched": stats.fetched,
        "days_cached": stats.cached,
        "days_empty": stats.empty,
        "days_failed": stats.failed,
        "days_incomplete": stats.incomplete,
        "candles_inserted": stats.inserted,
        "failures": failures,
    }
    run.summary = None


async def execute_run(
    db: AsyncSession,
    run_id: int,
    *,
    commit: bool = True,
    provider: CandleProvider | None = None,
) -> None:
    """Run one queued run to completion on `db`. Never raises for a failed run:
    the failure is recorded on the run. With `commit=False` (tests) progress is
    flushed instead of committed."""
    run = await repository.get_run(db, run_id)
    if run is None or run.status != "queued":
        return
    run.status, run.started_at, run.progress, run.message = "running", _now(), 1, "starting"
    await _checkpoint(db, commit)
    try:
        if run.kind == "fetch":
            await _execute_fetch(db, run, commit, provider)
        else:
            await _execute_compute(db, run, commit)
    except Exception as exc:
        logger.warning("forex_run_failed", run_id=run_id, kind=run.kind, error=str(exc))
        if commit:
            await db.rollback()
        failed = await repository.get_run(db, run_id)
        if failed is None:  # pragma: no cover - the row cannot vanish mid-run
            return
        failed.status, failed.error = "failed", _error_message(exc)
        failed.finished_at, failed.message = _now(), None
        await _checkpoint(db, commit)
        return
    run.status, run.progress, run.message, run.finished_at = "done", 100, None, _now()
    await _checkpoint(db, commit)


async def _run_in_background(run_id: int) -> None:
    try:
        async with _SLOT:
            # The request that created the run commits AFTER it hands us the id,
            # so the row may not be visible yet; wait for it instead of assuming
            # the framework's teardown order.
            for _ in range(LAUNCH_WAIT_ATTEMPTS):
                async with SessionFactory() as session:
                    if (
                        await repository.get_run(session, run_id, with_result=False)
                        is not None
                    ):
                        await execute_run(session, run_id, commit=True)
                        return
                await asyncio.sleep(LAUNCH_WAIT_SECONDS)
            logger.warning("forex_run_never_appeared", run_id=run_id)
    except Exception:  # pragma: no cover - execute_run records its own failures
        logger.exception("forex_run_crashed", run_id=run_id)
    finally:
        _LIVE.discard(run_id)


async def launch(run_id: int) -> None:
    """Start a queued run as a background task (it returns at once)."""
    _LIVE.add(run_id)
    task = asyncio.get_running_loop().create_task(_run_in_background(run_id))
    _TASKS.add(task)
    task.add_done_callback(_TASKS.discard)
