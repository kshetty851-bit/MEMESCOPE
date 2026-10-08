"""Builds the lab's responses from stored candles, the engine and the simulator.

No FastAPI in here and no clock: `now` is always a parameter, so a status board
can be rebuilt for any instant and the tests do not race the wall clock.

The CPU-heavy part is `run_backtest`: a 365-day window is ~35,000 candles and
takes seconds, which on the event loop would stall every other request. It is
pure and takes plain arguments, so it runs in a worker thread
(`asyncio.to_thread`); the session never crosses into that thread.

Nothing here writes. A backtest computes and returns; the live book is a replay
over stored candles, recomputed on read, so there is no book table to drift from
the candles it is made of.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TypeVar

from sqlalchemy.ext.asyncio import AsyncSession

from app.labs.btc_range import repository
from app.labs.btc_range.bounds import BOUNDS, config_field_names
from app.labs.btc_range.engine import PRICE_STEP, evaluate, quantize
from app.labs.btc_range.execution import run_backtest
from app.labs.btc_range.prose import reason_text
from app.labs.btc_range.schemas import (
    BacktestOut,
    BookOut,
    CandleOut,
    ConfigOut,
    DataOut,
    EquityPointOut,
    FieldBoundsOut,
    MetricsOut,
    OpenPositionOut,
    PriceOut,
    RangeOut,
    ReasonOut,
    SignalCountsOut,
    SignalOut,
    StatusOut,
    StrategyConfigOut,
    TradeOut,
    WaitReasonOut,
)
from app.labs.btc_range.types import (
    CONFIG_VERSION,
    SYMBOL,
    TIMEFRAME,
    TIMEFRAME_SECONDS,
    BacktestResult,
    Call,
    Candle,
    EquityPoint,
    Metrics,
    OpenPosition,
    RangeState,
    Reason,
    Signal,
    StrategyConfig,
    Trade,
)

PERIOD = timedelta(seconds=TIMEFRAME_SECONDS)

#: Candles the status board draws.
CHART_CANDLES = 192
BOOK_TRADES_CAP = 100
BOOK_CURVE_CAP = 300
BACKTEST_TRADES_CAP = 1_000
BACKTEST_CURVE_CAP = 500
DEFAULT_WINDOW = timedelta(days=30)
MAX_WINDOW = timedelta(days=365)
#: A feed is "stale" when its newest closed candle closed more than this ago.
STALE_AFTER = 2 * PERIOD

LAB_OFF_REASON = (
    "The BTC Range Lab is switched off, so no candles are being collected and no calls "
    "are being made. Set LAB_BTC_RANGE_ENABLED=true and restart the API and beat "
    "workers to turn it on."
)
NO_CANDLES_REASON = (
    "No candles stored yet - run the backfill: python -m app.labs.btc_range backfill"
)

T = TypeVar("T")


class InvalidConfigError(ValueError):
    """A config whose fields are each in bounds but contradict one another."""


class InvalidWindowError(ValueError):
    """A backtest window that is empty, inverted or longer than the maximum."""


# --- formatting --------------------------------------------------------------


def dec(value: Decimal) -> str:
    """A Decimal as plain digits. `str(Decimal("1E+2"))` would leak an exponent."""
    return format(value, "f")


def price_str(value: Decimal) -> str:
    """A stored candle price at the engine's own precision.

    The table keeps eight places (`NUMERIC(24,8)`), so BTC/USDT's two-place
    prices come back padded with zeros. Signals and trades are already at
    `PRICE_STEP`; showing the chart and the headline price at the same step
    keeps one price from looking like two different numbers.
    """
    return dec(quantize(value, PRICE_STEP))


def dec_or_none(value: Decimal | None) -> str | None:
    return None if value is None else dec(value)


def as_utc(value: datetime) -> datetime:
    """Naive instants are read as UTC; aware ones are converted."""
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def downsample(items: Sequence[T], cap: int) -> list[T]:
    """At most `cap` items, evenly spaced, always keeping the first and the last.

    The ends carry meaning (where the curve starts and where it stands now); a
    sampler that dropped the last point would show a stale balance.
    """
    if cap < 2:
        raise ValueError("cap must be at least 2")
    n = len(items)
    if n <= cap:
        return list(items)
    last = n - 1
    # n > cap, so consecutive indices differ by more than 1 and never collide.
    return [items[round(i * last / (cap - 1))] for i in range(cap)]


# --- domain -> wire ----------------------------------------------------------


def config_out(cfg: StrategyConfig) -> StrategyConfigOut:
    values: dict[str, object] = {}
    for name in config_field_names():
        value = getattr(cfg, name)
        values[name] = dec(value) if isinstance(value, Decimal) else value
    return StrategyConfigOut(**values)


def metrics_out(m: Metrics) -> MetricsOut:
    return MetricsOut(
        trades=m.trades,
        wins=m.wins,
        losses=m.losses,
        win_rate=dec_or_none(m.win_rate),
        net_pnl=dec(m.net_pnl),
        gross_profit=dec(m.gross_profit),
        gross_loss=dec(m.gross_loss),
        profit_factor=dec_or_none(m.profit_factor),
        expectancy=dec_or_none(m.expectancy),
        max_drawdown_pct=dec_or_none(m.max_drawdown_pct),
        return_pct=dec(m.return_pct),
        ending_equity=dec(m.ending_equity),
    )


def trade_out(t: Trade) -> TradeOut:
    return TradeOut(
        side=t.side,
        signal_at=t.signal_at,
        entry_at=t.entry_at,
        entry_price=dec(t.entry_price),
        take_profit=dec(t.take_profit),
        stop_loss=dec(t.stop_loss),
        quantity=dec(t.quantity),
        notional=dec(t.notional),
        exit_at=t.exit_at,
        exit_price=dec(t.exit_price),
        exit_reason=t.exit_reason,
        fees=dec(t.fees),
        pnl=dec(t.pnl),
        r_multiple=dec_or_none(t.r_multiple),
    )


def open_position_out(p: OpenPosition) -> OpenPositionOut:
    return OpenPositionOut(
        side=p.side,
        signal_at=p.signal_at,
        entry_at=p.entry_at,
        entry_price=dec(p.entry_price),
        take_profit=dec(p.take_profit),
        stop_loss=dec(p.stop_loss),
        quantity=dec(p.quantity),
        notional=dec(p.notional),
        mark_price=dec(p.mark_price),
        unrealised_pnl=dec(p.unrealised_pnl),
    )


def equity_out(points: Sequence[EquityPoint], cap: int) -> list[EquityPointOut]:
    return [EquityPointOut(at=p.at, equity=dec(p.equity)) for p in downsample(points, cap)]


def range_out(r: RangeState) -> RangeOut:
    return RangeOut(
        support=dec(r.support),
        resistance=dec(r.resistance),
        mid=dec(r.mid),
        width_pct=dec(r.width_pct),
        position=dec(r.position),
        touches_support=r.touches_support,
        touches_resistance=r.touches_resistance,
        trend_efficiency=dec(r.trend_efficiency),
        confidence=r.confidence,
        regime=r.regime,
    )


def reasons_out(reasons: Sequence[Reason]) -> list[ReasonOut]:
    return [ReasonOut(code=r.value, text=reason_text(r)) for r in reasons]


def signal_out(s: Signal) -> SignalOut:
    return SignalOut(
        at=s.at,
        price=dec(s.price),
        call=s.call,
        confidence=s.confidence,
        range=range_out(s.range) if s.range is not None else None,
        entry=dec_or_none(s.entry),
        take_profit=dec_or_none(s.take_profit),
        stop_loss=dec_or_none(s.stop_loss),
        reward_risk=dec_or_none(s.reward_risk),
        reasons=reasons_out(s.reasons),
    )


def candle_out(c: Candle) -> CandleOut:
    return CandleOut(
        t=c.open_time,
        o=price_str(c.open),
        h=price_str(c.high),
        l=price_str(c.low),
        c=price_str(c.close),
    )


def wait_reasons_out(counts: dict[Reason, int]) -> list[WaitReasonOut]:
    """Largest first; ties by code so the order is the same on every run."""
    ordered = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0].value))
    return [WaitReasonOut(code=r.value, text=reason_text(r), count=n) for r, n in ordered]


def signal_counts_out(counts: dict[Call, int]) -> SignalCountsOut:
    return SignalCountsOut(
        long=counts.get(Call.LONG, 0),
        short=counts.get(Call.SHORT, 0),
        wait=counts.get(Call.WAIT, 0),
    )


# --- status ------------------------------------------------------------------


def _empty_data() -> DataOut:
    return DataOut(candles=0, first_at=None, last_closed_at=None, stale=False)


def _book(result: BacktestResult, cfg: StrategyConfig, live_start: datetime) -> BookOut:
    # The window starts `lookback` candles early so the first live call has a
    # full range behind it. Those candles are context, not history: the
    # simulator already begins trading after them, and this filter is the belt
    # to that brace - a trade entered before the book started must never be
    # counted in it, whatever a gap in the stored candles does to the indexing.
    kept = [t for t in result.trades if t.entry_at >= live_start]
    newest_first = list(reversed(kept))[:BOOK_TRADES_CAP]
    return BookOut(
        started_at=live_start,
        config_version=CONFIG_VERSION,
        config=config_out(cfg),
        metrics=metrics_out(result.metrics),
        long=metrics_out(result.long_metrics),
        short=metrics_out(result.short_metrics),
        open_position=open_position_out(result.open_position)
        if result.open_position
        else None,
        trades=[trade_out(t) for t in newest_first],
        equity_curve=equity_out(
            [p for p in result.equity_curve if p.at >= live_start], BOOK_CURVE_CAP
        ),
    )


async def build_status(
    session: AsyncSession, *, now: datetime, enabled: bool, live_start: datetime
) -> StatusOut:
    """The status board. With the lab off this touches no table at all.

    "Off" and "on but empty" must not render alike, so the off answer says why
    and carries no price, signal or book - not zeros that read as a quiet market.
    """
    if not enabled:
        return StatusOut(
            running=False,
            reason=LAB_OFF_REASON,
            symbol=SYMBOL,
            timeframe=TIMEFRAME,
            price=None,
            data=_empty_data(),
            signal=None,
            book=None,
            candles=[],
        )

    cfg = StrategyConfig()
    count, first_at, last_at = await repository.stats(session)
    latest = await repository.latest_candle(session)
    price = (
        PriceOut(
            value=price_str(latest[0].close), at=latest[0].open_time, candle_closed=latest[1]
        )
        if latest is not None
        else None
    )
    data = DataOut(
        candles=count,
        first_at=first_at,
        last_closed_at=last_at,
        stale=last_at is not None and now - (last_at + PERIOD) > STALE_AFTER,
    )
    if count == 0 or last_at is None:
        return StatusOut(
            running=True,
            reason=NO_CANDLES_REASON,
            symbol=SYMBOL,
            timeframe=TIMEFRAME,
            price=price,
            data=data,
            signal=None,
            book=None,
            candles=[],
        )

    recent = await repository.closed_candles(
        session, limit=max(CHART_CANDLES, cfg.lookback + 1), newest=True
    )
    signal = evaluate(recent[-(cfg.lookback + 1) :], cfg)

    warm_start = live_start - cfg.lookback * PERIOD
    history = await repository.closed_candles(session, start=warm_start, end=now)
    result = await asyncio.to_thread(run_backtest, history, cfg, close_open_at_end=False)

    return StatusOut(
        running=True,
        reason=None,
        symbol=SYMBOL,
        timeframe=TIMEFRAME,
        price=price,
        data=data,
        signal=signal_out(signal),
        book=_book(result, cfg, live_start),
        candles=[candle_out(c) for c in recent[-CHART_CANDLES:]],
    )


# --- config ------------------------------------------------------------------


def bounds_out() -> dict[str, FieldBoundsOut]:
    return {
        name: FieldBoundsOut(
            min=dec(b.min),
            max=dec(b.max),
            step=dec(b.step),
            label=b.label,
            help=b.help,
            kind=b.kind,
            group=b.group,
        )
        for name, b in BOUNDS.items()
    }


async def build_config(session: AsyncSession) -> ConfigOut:
    _, first_at, last_at = await repository.stats(session)
    return ConfigOut(
        config_version=CONFIG_VERSION,
        defaults=config_out(StrategyConfig()),
        bounds=bounds_out(),
        data_first_at=first_at,
        data_last_at=last_at,
    )


# --- backtest ----------------------------------------------------------------


def check_config(cfg: StrategyConfig) -> None:
    if cfg.min_width_pct > cfg.max_width_pct:
        raise InvalidConfigError("min_width_pct must not exceed max_width_pct")


def _unavailable(
    cfg: StrategyConfig, reason: str, start: datetime | None, end: datetime | None
) -> BacktestOut:
    """Nothing to run on. Zeroed figures, not estimated ones, and the reason why."""
    empty = run_backtest([], cfg)
    return BacktestOut(
        available=False,
        reason=reason,
        config=config_out(cfg),
        start=start,
        end=end,
        candles=0,
        signal_counts=signal_counts_out(empty.signal_counts),
        wait_reasons=[],
        metrics=metrics_out(empty.metrics),
        long=metrics_out(empty.long_metrics),
        short=metrics_out(empty.short_metrics),
        trades=[],
        equity_curve=[],
    )


def resolve_window(
    start: datetime | None, end: datetime | None, last_closed_open: datetime | None
) -> tuple[datetime, datetime] | None:
    """The window to run, or None when it cannot be defaulted (no data stored).

    Defaults: `end` is the close of the newest stored closed candle and `start`
    is 30 days before `end`. Raises `InvalidWindowError` for a window that is
    inverted or longer than a year.
    """
    start = as_utc(start) if start is not None else None
    end = as_utc(end) if end is not None else None
    if end is None:
        if last_closed_open is None:
            return None
        end = last_closed_open + PERIOD
    if start is None:
        start = end - DEFAULT_WINDOW
    if start >= end:
        raise InvalidWindowError("start must be before end")
    if end - start > MAX_WINDOW:
        raise InvalidWindowError(f"the window may not exceed {MAX_WINDOW.days} days")
    return start, end


async def run_window_backtest(
    session: AsyncSession,
    *,
    cfg: StrategyConfig,
    start: datetime | None,
    end: datetime | None,
) -> BacktestOut:
    """Replay stored candles through `cfg`. Reads only; writes nothing.

    A candle is in the window when it opens in `[start, end]`. The page sends
    the end of a day, or the open time of the newest candle, as `end`; treating
    it as inclusive makes both mean what they say instead of dropping the last
    candle.
    """
    check_config(cfg)
    count, _, last_open = await repository.stats(session)
    window = resolve_window(start, end, last_open)
    if window is None or count == 0:
        return _unavailable(cfg, NO_CANDLES_REASON, None, None)
    w_start, w_end = window

    candles = await repository.closed_candles(
        session,
        start=w_start - cfg.lookback * PERIOD,
        end=w_end + timedelta(microseconds=1),
    )
    needed = cfg.lookback + 1
    if len(candles) < needed:
        return _unavailable(
            cfg,
            f"Only {len(candles)} closed candles are stored for this window; "
            f"{needed} are needed (the {cfg.lookback}-candle range window plus one). "
            "Nothing was estimated.",
            w_start,
            w_end,
        )

    result = await asyncio.to_thread(run_backtest, candles, cfg)
    return BacktestOut(
        available=True,
        reason=None,
        config=config_out(cfg),
        start=candles[cfg.lookback].open_time,
        end=candles[-1].open_time,
        candles=result.candles - cfg.lookback,
        signal_counts=signal_counts_out(result.signal_counts),
        wait_reasons=wait_reasons_out(result.wait_reasons),
        metrics=metrics_out(result.metrics),
        long=metrics_out(result.long_metrics),
        short=metrics_out(result.short_metrics),
        # Oldest first, and when there are more than the cap the NEWEST are kept:
        # metrics above cover every trade, the list is what the page can draw.
        trades=[trade_out(t) for t in result.trades[-BACKTEST_TRADES_CAP:]],
        equity_curve=equity_out(result.equity_curve, BACKTEST_CURVE_CAP),
    )


# --- replay (CLI) ------------------------------------------------------------


async def replay(session: AsyncSession, *, now: datetime, hours: int) -> dict[str, object]:
    """The last `hours` replayed through the defaults. Backs `replay --hours N`."""
    cfg = StrategyConfig()
    start = now - timedelta(hours=hours)
    candles = await repository.closed_candles(
        session, start=start - cfg.lookback * PERIOD, end=now
    )
    window: dict[str, object] = {
        "hours": hours,
        "requested_start": start.isoformat(),
        "requested_end": now.isoformat(),
    }
    if len(candles) < cfg.lookback + 1:
        return {
            "available": False,
            "reason": f"Only {len(candles)} closed candles are stored for this window; "
            f"{cfg.lookback + 1} are needed. Nothing was estimated.",
            "window": window,
            "candles": 0,
        }
    result = await asyncio.to_thread(run_backtest, candles, cfg)
    window["first_candle"] = candles[cfg.lookback].open_time.isoformat()
    window["last_candle"] = candles[-1].open_time.isoformat()
    return {
        "available": True,
        "window": window,
        "candles": result.candles - cfg.lookback,
        "signal_counts": signal_counts_out(result.signal_counts).model_dump(),
        "wait_reasons": [w.model_dump() for w in wait_reasons_out(result.wait_reasons)],
        "trade_count": len(result.trades),
        "trades": [trade_out(t).model_dump(mode="json") for t in result.trades],
        "metrics": metrics_out(result.metrics).model_dump(),
    }
