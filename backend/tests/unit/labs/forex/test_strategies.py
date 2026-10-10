"""Signal generation for the three baseline strategies.

Crafted series prove each rule fires (and is vetoed) where it should; the
truncation tests prove the property a backtest depends on: a signal at bar i is
a function of bars 0..i only, so adding future data can never change history.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from app.labs.forex.strategies import generate_signals
from app.labs.forex.types import (
    INSTRUMENTS,
    TIMEFRAME_SECONDS,
    BacktestConfig,
    Candle,
    Direction,
    Session,
    Signal,
    StopMethod,
    StrategyId,
    StrategyParams,
    TakeProfitMethod,
    Timeframe,
)

pytestmark = pytest.mark.unit

EURUSD = INSTRUMENTS["EURUSD"]
PIP = EURUSD.pip_size
DAY0 = datetime(2024, 1, 2, tzinfo=UTC)  # a Tuesday
M5 = timedelta(minutes=5)


def _cfg(strategy: StrategyId, **params: object) -> BacktestConfig:
    base = StrategyParams(
        trend_filter=False,
        trend_timeframe=Timeframe.M5,
        stop_method=StopMethod.FIXED_PIPS,
        stop_pips=10.0,
    )
    return BacktestConfig(
        strategy=strategy,
        timeframe=Timeframe.M5,
        params=replace(base, **params),  # type: ignore[arg-type]
    )


def _candles(closes: Sequence[float], start: datetime = DAY0) -> list[Candle]:
    out: list[Candle] = []
    prev = closes[0]
    for i, c in enumerate(closes):
        out.append(
            Candle(start + M5 * i, prev, max(prev, c) + 0.00005, min(prev, c) - 0.00005, c)
        )
        prev = c
    return out


def _mirror(closes: Sequence[float]) -> list[float]:
    """Reflect a series about 1.1 so a long setup becomes the matching short."""
    return [2.2 - c for c in closes]


def _idx(signals: list[Signal], direction: Direction) -> list[int]:
    return [s.index for s in signals if s.direction is direction]


# --------------------------------------------------------------------- RSI


def _rsi_aligned() -> list[float]:
    """Steady climb, a sharp dip (RSI < 40), then recovery: a pullback in an uptrend."""
    climb = [1.1 + 0.0003 * i for i in range(120)]
    dip = [climb[-1] - 0.0006 * (i + 1) for i in range(8)]
    return climb + dip + [dip[-1] + 0.0003 * (i + 1) for i in range(20)]


def _rsi_opposed() -> list[float]:
    """Long decline then a bounce: RSI crosses 40 up while price is far below trend."""
    fall = [1.1 - 0.0003 * i for i in range(80)]
    return fall + [fall[-1] + 0.0003 * (i + 1) for i in range(20)]


def test_rsi_long_fires_on_cross_up_through_level() -> None:
    """LONG at the bar where RSI first reaches the level from below."""
    closes = _rsi_aligned()
    sigs = generate_signals(_cfg(StrategyId.RSI_PULLBACK), _candles(closes), None, EURUSD)
    longs = [s for s in sigs if s.direction is Direction.LONG]
    assert [s.index for s in longs] == [128]
    s = longs[0]
    assert s.reason == "rsi_pullback_long"
    assert s.stop_distance == pytest.approx(10 * PIP)
    assert s.take_profit_distance == pytest.approx(20 * PIP)


def test_rsi_short_fires_on_cross_down_through_level() -> None:
    sigs = generate_signals(
        _cfg(StrategyId.RSI_PULLBACK), _candles(_mirror(_rsi_aligned())), None, EURUSD
    )
    shorts = [s for s in sigs if s.direction is Direction.SHORT]
    assert [s.index for s in shorts] == [128]
    assert shorts[0].reason == "rsi_pullback_short"


def test_rsi_trend_filter_keeps_aligned_and_vetoes_opposed() -> None:
    """With the filter on, a long is taken only above the trend EMA and a short
    only below it; the same RSI crosses fire without the filter."""
    unfiltered = _cfg(StrategyId.RSI_PULLBACK)
    filtered = _cfg(StrategyId.RSI_PULLBACK, trend_filter=True, trend_ema_period=50)

    aligned = _candles(_rsi_aligned())
    assert _idx(generate_signals(filtered, aligned, None, EURUSD), Direction.LONG) == [128]
    # The first dip also produces a short cross; it is above the EMA, so vetoed.
    assert _idx(generate_signals(unfiltered, aligned, None, EURUSD), Direction.SHORT) == [123]
    assert _idx(generate_signals(filtered, aligned, None, EURUSD), Direction.SHORT) == []

    opposed = _candles(_rsi_opposed())
    assert _idx(generate_signals(unfiltered, opposed, None, EURUSD), Direction.LONG) == [86]
    assert generate_signals(filtered, opposed, None, EURUSD) == []

    mirrored = _candles(_mirror(_rsi_opposed()))
    assert _idx(generate_signals(unfiltered, mirrored, None, EURUSD), Direction.SHORT) == [86]
    assert generate_signals(filtered, mirrored, None, EURUSD) == []


def test_rsi_no_signal_during_warmup() -> None:
    """Never signal on an indicator that is not yet defined."""
    closes = [1.1 - 0.0003 * i for i in range(10)] + [1.1 + 0.0003 * i for i in range(5)]
    assert (
        generate_signals(_cfg(StrategyId.RSI_PULLBACK), _candles(closes), None, EURUSD) == []
    )


def test_atr_stop_and_no_take_profit() -> None:
    """ATR stop = multiple x ATR at the signal bar; TP method NONE gives None."""
    cfg = _cfg(
        StrategyId.RSI_PULLBACK,
        stop_method=StopMethod.ATR,
        stop_atr_multiple=2.0,
        take_profit_method=TakeProfitMethod.NONE,
    )
    sigs = generate_signals(cfg, _candles(_rsi_aligned()), None, EURUSD)
    assert sigs
    assert all(s.take_profit_distance is None and s.stop_distance > 0 for s in sigs)


def test_fixed_pip_take_profit() -> None:
    cfg = _cfg(
        StrategyId.RSI_PULLBACK,
        take_profit_method=TakeProfitMethod.FIXED_PIPS,
        take_profit_pips=33.0,
    )
    sigs = generate_signals(cfg, _candles(_rsi_aligned()), None, EURUSD)
    assert sigs[0].take_profit_distance == pytest.approx(33 * PIP)


def test_range_stop_is_london_only() -> None:
    """RANGE is meaningless without an Asian range, so other strategies refuse it
    loudly rather than falling back to some other stop."""
    for strat in (StrategyId.RSI_PULLBACK, StrategyId.BOLLINGER_REVERSION):
        with pytest.raises(ValueError):
            generate_signals(
                _cfg(strat, stop_method=StopMethod.RANGE), _candles([1.1] * 50), None, EURUSD
            )


def test_missing_htf_candles_raises_when_trend_needs_them() -> None:
    cfg = _cfg(StrategyId.RSI_PULLBACK, trend_filter=True, trend_timeframe=Timeframe.M15)
    with pytest.raises(ValueError):
        generate_signals(cfg, _candles([1.1] * 50), None, EURUSD)
    # A disabled filter never demands higher-timeframe data.
    off = _cfg(StrategyId.RSI_PULLBACK, trend_filter=False, trend_timeframe=Timeframe.M15)
    assert generate_signals(off, _candles([1.1] * 50), None, EURUSD) == []


# --------------------------------------------------------------- Bollinger


def _bb_base() -> list[float]:
    return [1.1 + (0.0002 if i % 2 else -0.0002) for i in range(40)]


def _bb_long(reentry: float = 1.0985) -> list[float]:
    """Quiet chop, a 50-pip plunge closing below the lower band with RSI < 30
    (bar 40), then a close back inside (bar 41)."""
    return [*_bb_base(), 1.095, reentry]


def test_bb_long_and_short_reentry() -> None:
    cfg = _cfg(StrategyId.BOLLINGER_REVERSION)
    longs = generate_signals(cfg, _candles(_bb_long()), None, EURUSD)
    assert [(s.index, s.direction, s.reason) for s in longs] == [
        (41, Direction.LONG, "bb_reentry_long")
    ]
    shorts = generate_signals(cfg, _candles(_mirror(_bb_long())), None, EURUSD)
    assert [(s.index, s.direction, s.reason) for s in shorts] == [
        (41, Direction.SHORT, "bb_reentry_short")
    ]


def test_bb_needs_oversold_rsi_not_just_a_band_break() -> None:
    """A mild break below the band whose RSI is not oversold is not a setup."""
    closes = [*_bb_base(), 1.0990, 1.1000]
    cfg = _cfg(StrategyId.BOLLINGER_REVERSION)
    assert generate_signals(cfg, _candles(closes), None, EURUSD) == []


def test_bb_trend_filter_distance_mode() -> None:
    """With a positive ATR distance, a re-entry is refused when price sits more
    than that many ATRs on the far side of the trend EMA."""
    closes = _bb_long()
    near = _cfg(
        StrategyId.BOLLINGER_REVERSION,
        trend_filter=True,
        trend_ema_period=20,
        trend_max_distance_atr=3.0,
        atr_period=14,
    )
    tight = replace(near, params=replace(near.params, trend_max_distance_atr=0.5))
    assert _idx(generate_signals(near, _candles(closes), None, EURUSD), Direction.LONG) == [41]
    assert generate_signals(tight, _candles(closes), None, EURUSD) == []
    mirrored = _candles(_mirror(closes))
    assert _idx(generate_signals(near, mirrored, None, EURUSD), Direction.SHORT) == [41]
    assert generate_signals(tight, mirrored, None, EURUSD) == []


def test_bb_trend_filter_zero_distance_means_side_of_ema() -> None:
    """trend_max_distance_atr == 0 switches the distance test off but keeps the
    side test: LONG only above the EMA, SHORT only below."""
    below = _bb_long(reentry=1.0985)  # re-entry close is under the EMA
    above = _bb_long(reentry=1.0999)  # re-entry close is over the EMA
    cfg = _cfg(
        StrategyId.BOLLINGER_REVERSION,
        trend_filter=True,
        trend_ema_period=20,
        trend_max_distance_atr=0.0,
    )
    assert generate_signals(cfg, _candles(below), None, EURUSD) == []
    assert _idx(generate_signals(cfg, _candles(above), None, EURUSD), Direction.LONG) == [41]
    assert generate_signals(cfg, _candles(_mirror(below)), None, EURUSD) == []
    assert _idx(
        generate_signals(cfg, _candles(_mirror(above)), None, EURUSD), Direction.SHORT
    ) == [41]


def test_bb_reentry_window_and_expiry() -> None:
    """The re-entry must come within `reentry_window_bars` of the setup; an
    excursion that lingers outside the band longer is abandoned."""
    # Bar 40 is the setup (RSI 26). Bars 41-42 stay below the band but their RSI
    # has recovered above 30, so they restart nothing. Bar 43 is back inside.
    closes = [*_bb_base(), 1.095, 1.096, 1.0961, 1.1]
    wide = _cfg(StrategyId.BOLLINGER_REVERSION, reentry_window_bars=3)
    narrow = _cfg(StrategyId.BOLLINGER_REVERSION, reentry_window_bars=1)
    assert _idx(generate_signals(wide, _candles(closes), None, EURUSD), Direction.LONG) == [43]
    assert generate_signals(narrow, _candles(closes), None, EURUSD) == []


def test_bb_newer_setup_restarts_window_and_signal_clears_it() -> None:
    """A deeper plunge restarts the window; after a signal the setup is spent so
    a second consecutive inside close does not signal again."""
    closes = [*_bb_base(), 1.095, 1.090, 1.0985, 1.0990, 1.0995]
    cfg = _cfg(StrategyId.BOLLINGER_REVERSION, reentry_window_bars=1)
    sigs = generate_signals(cfg, _candles(closes), None, EURUSD)
    # Window=1 from bar 40 alone would have expired by bar 42; the setup at bar
    # 41 restarts it, so bar 42 signals, and only once.
    assert _idx(sigs, Direction.LONG) == [42]


# ----------------------------------------------------------------- London


def _day(
    overrides: dict[str, float] | None = None,
    *,
    skip_asian: int = 0,
    day: datetime = DAY0,
    hours: int = 12,
) -> list[Candle]:
    """One day of 5m bars. Asian bars (00:00-06:00) span 1.1000-1.1010; every
    other bar is flat at 1.1005 unless `overrides` ("HH:MM" -> close) says so.
    `skip_asian` drops that many Asian bars from the start of the window."""
    overrides = overrides or {}
    out: list[Candle] = []
    for n in range(hours * 12):
        t = day + M5 * n
        if t.hour < 6:
            if n < skip_asian:
                continue
            out.append(Candle(t, 1.1005, 1.1010, 1.1000, 1.1005))
        else:
            c = overrides.get(f"{t:%H:%M}", 1.1005)
            o = 1.1005
            out.append(Candle(t, o, max(o, c) + 0.00002, min(o, c) - 0.00002, c))
    return out


def _london(**params: object) -> BacktestConfig:
    return _cfg(StrategyId.LONDON_BREAKOUT, **params)


def _at(candles: list[Candle], hhmm: str) -> int:
    return next(i for i, c in enumerate(candles) if f"{c.open_time:%H:%M}" == hhmm)


def test_london_long_and_short_breakout() -> None:
    long_day = _day({"07:15": 1.1015})
    sigs = generate_signals(_london(), long_day, None, EURUSD)
    assert [(s.index, s.direction, s.reason) for s in sigs] == [
        (_at(long_day, "07:15"), Direction.LONG, "asian_high_breakout")
    ]
    assert sigs[0].stop_distance == pytest.approx(10 * PIP)
    assert sigs[0].take_profit_distance == pytest.approx(20 * PIP)

    short_day = _day({"07:15": 1.0990})
    sigs = generate_signals(_london(), short_day, None, EURUSD)
    assert [(s.index, s.direction, s.reason) for s in sigs] == [
        (_at(short_day, "07:15"), Direction.SHORT, "asian_low_breakout")
    ]


def test_london_close_must_exceed_range_plus_buffer() -> None:
    """A close exactly at the range edge, or inside the buffer, is no breakout."""
    d = _day({"07:00": 1.1010, "07:05": 1.1012})
    assert generate_signals(_london(), d, None, EURUSD) != []  # 1.1012 > 1.1010
    buffered = _london(breakout_buffer_pips=3.0)
    assert generate_signals(buffered, d, None, EURUSD) == []  # needs > 1.1013


def test_london_session_boundaries() -> None:
    """Trades only from bars opening in [07:00, 10:00): none at 06:xx (even a
    breakout there), none at/after 10:00, but 09:55 is the last tradable bar."""
    pre = _day({f"06:{m:02d}": 1.1100 for m in range(0, 60, 5)})
    assert generate_signals(_london(), pre, None, EURUSD) == []

    late = _day({"10:00": 1.1100, "11:00": 1.1100})
    assert generate_signals(_london(), late, None, EURUSD) == []

    last = _day({"09:55": 1.1100})
    sigs = generate_signals(_london(), last, None, EURUSD)
    assert [s.index for s in sigs] == [_at(last, "09:55")]


def test_london_trend_filter_aligned_and_opposed() -> None:
    """A breakout in the direction of the trend EMA fires; one against it does not."""
    f = {"trend_filter": True, "trend_ema_period": 5}
    # Aligned: EMA sits near 1.1005, breakout closes are above/below it.
    up = _day({"07:00": 1.1015})
    assert _idx(generate_signals(_london(**f), up, None, EURUSD), Direction.LONG) != []
    down = _day({"07:00": 1.0990})
    assert _idx(generate_signals(_london(**f), down, None, EURUSD), Direction.SHORT) != []

    # Opposed long: pre-session closes at 1.11 drag the EMA above the breakout close.
    hi = {f"06:{m:02d}": 1.1100 for m in range(0, 60, 5)}
    opposed_long = _day({**hi, "07:00": 1.1015})
    assert generate_signals(_london(), opposed_long, None, EURUSD) != []
    assert (
        _idx(generate_signals(_london(**f), opposed_long, None, EURUSD), Direction.LONG) == []
    )

    lo = {f"06:{m:02d}": 1.0900 for m in range(0, 60, 5)}
    opposed_short = _day({**lo, "07:00": 1.0990})
    assert generate_signals(_london(), opposed_short, None, EURUSD) != []
    assert (
        _idx(generate_signals(_london(**f), opposed_short, None, EURUSD), Direction.SHORT)
        == []
    )


def test_london_insufficient_asian_data_yields_nothing() -> None:
    """Coverage below 80% of the expected bars means no range, so no trades.

    72 bars are expected; 58 (80.5%) is enough, 57 is not. A range drawn from
    a patchy window would be fabricated.
    """
    ok = _day({"07:00": 1.1015}, skip_asian=14)
    assert len([c for c in ok if c.open_time.hour < 6]) == 58
    assert len(generate_signals(_london(), ok, None, EURUSD)) == 1

    thin = _day({"07:00": 1.1015}, skip_asian=15)
    assert len([c for c in thin if c.open_time.hour < 6]) == 57
    assert generate_signals(_london(), thin, None, EURUSD) == []


def test_london_range_width_limits() -> None:
    narrow = _london(min_range_pips=12.0)  # the range is 10 pips
    assert generate_signals(narrow, _day({"07:00": 1.1015}), None, EURUSD) == []
    wide = _london(max_range_pips=8.0)
    assert generate_signals(wide, _day({"07:00": 1.1015}), None, EURUSD) == []
    exact = _london(min_range_pips=10.0, max_range_pips=10.0)
    assert len(generate_signals(exact, _day({"07:00": 1.1015}), None, EURUSD)) == 1


def test_london_confirmation_bars() -> None:
    """N consecutive closes beyond the range are required, all inside the session."""
    cfg = _london(breakout_confirmation_bars=2)
    one_bar = _day({"07:00": 1.1015})
    assert generate_signals(cfg, one_bar, None, EURUSD) == []

    two_bars = _day({"07:00": 1.1015, "07:05": 1.1016})
    assert [s.index for s in generate_signals(cfg, two_bars, None, EURUSD)] == [
        _at(two_bars, "07:05")
    ]

    broken = _day({"07:00": 1.1015, "07:05": 1.1005, "07:10": 1.1016})
    assert generate_signals(cfg, broken, None, EURUSD) == []

    # 06:55 is outside the session, so it cannot count towards the confirmation
    # of the 07:00 bar even though it closed beyond the range.
    straddle = _day({"06:55": 1.1015, "07:00": 1.1016, "07:05": 1.1017})
    assert [s.index for s in generate_signals(cfg, straddle, None, EURUSD)] == [
        _at(straddle, "07:05")
    ]


def test_london_confirmation_does_not_cross_days() -> None:
    """Confirmation counts never carry over midnight."""
    day1 = _day({"09:55": 1.1015}, hours=24)
    day2 = _day({"07:00": 1.1015}, day=DAY0 + timedelta(days=1))
    cfg = _london(breakout_confirmation_bars=2)
    assert generate_signals(cfg, day1 + day2, None, EURUSD) == []


def test_london_one_trade_per_side_per_day() -> None:
    closes = {"07:00": 1.1015, "07:05": 1.1016, "07:10": 1.1017, "08:00": 1.0990}
    d = _day(closes)
    sigs = generate_signals(_london(), d, None, EURUSD)
    assert [(s.index, s.direction) for s in sigs] == [
        (_at(d, "07:00"), Direction.LONG),
        (_at(d, "08:00"), Direction.SHORT),
    ]
    many = generate_signals(_london(one_trade_per_side_per_day=False), d, None, EURUSD)
    assert _idx(many, Direction.LONG) == [_at(d, "07:00"), _at(d, "07:05"), _at(d, "07:10")]


def test_london_each_day_has_its_own_range_and_quota() -> None:
    day1 = _day({"07:00": 1.1015}, hours=24)
    day2 = _day({"07:00": 1.1015}, day=DAY0 + timedelta(days=1))
    sigs = generate_signals(_london(), day1 + day2, None, EURUSD)
    assert len(sigs) == 2


def test_london_range_stop() -> None:
    """RANGE stop: distance to the opposite side of the range plus the buffer."""
    cfg = _london(stop_method=StopMethod.RANGE, range_stop_buffer_pips=2.0)
    long_sig = generate_signals(cfg, _day({"07:00": 1.1015}), None, EURUSD)[0]
    assert long_sig.stop_distance == pytest.approx(1.1015 - (1.1000 - 0.0002))
    short_sig = generate_signals(cfg, _day({"07:00": 1.0990}), None, EURUSD)[0]
    assert short_sig.stop_distance == pytest.approx((1.1010 + 0.0002) - 1.0990)


def test_london_atr_stop() -> None:
    cfg = _london(stop_method=StopMethod.ATR, stop_atr_multiple=1.5)
    sig = generate_signals(cfg, _day({"07:00": 1.1015}), None, EURUSD)[0]
    assert sig.stop_distance > 0
    assert sig.take_profit_distance == pytest.approx(2.0 * sig.stop_distance)


def test_london_sessions_that_wrap_midnight_are_rejected() -> None:
    cfg = _london(asian_session=Session(22, 6))
    with pytest.raises(ValueError):
        generate_signals(cfg, _day(), None, EURUSD)


# ------------------------------------------------- look-ahead and determinism


def _walk(n: int, seed: int = 7) -> list[Candle]:
    """Deterministic pseudo-random walk (LCG) of continuous 5m bars from 00:00."""
    state = seed
    price = 1.1
    out: list[Candle] = []
    start = datetime(2024, 1, 1, tzinfo=UTC)
    for i in range(n):
        state = (1103515245 * state + 12345) % 2**31
        step = (state / 2**31 - 0.5) * 0.0008
        state = (1103515245 * state + 12345) % 2**31
        wick = (state / 2**31) * 0.0003
        o, c = price, price + step
        out.append(Candle(start + M5 * i, o, max(o, c) + wick, min(o, c) - wick, c))
        price = c
    return out


def _aggregate(candles: list[Candle], per: int) -> list[Candle]:
    out: list[Candle] = []
    for i in range(0, len(candles) - per + 1, per):
        grp = candles[i : i + per]
        out.append(
            Candle(
                grp[0].open_time,
                grp[0].open,
                max(c.high for c in grp),
                min(c.low for c in grp),
                grp[-1].close,
            )
        )
    return out


def _closed_htf(htf: list[Candle], last_exec: Candle, tf: Timeframe) -> list[Candle]:
    now = last_exec.open_time + M5
    width = timedelta(seconds=TIMEFRAME_SECONDS[tf])
    return [h for h in htf if h.open_time + width <= now]


_LOOKAHEAD_CASES: list[tuple[str, BacktestConfig]] = [
    (
        "london",
        _cfg(
            StrategyId.LONDON_BREAKOUT,
            trend_filter=True,
            trend_timeframe=Timeframe.M15,
            trend_ema_period=20,
            min_range_pips=0.0,
            max_range_pips=1000.0,
        ),
    ),
    (
        "london_atr_confirm",
        _cfg(
            StrategyId.LONDON_BREAKOUT,
            trend_filter=False,
            stop_method=StopMethod.ATR,
            breakout_confirmation_bars=2,
            one_trade_per_side_per_day=False,
            min_range_pips=0.0,
            max_range_pips=1000.0,
        ),
    ),
    (
        "london_range_stop",
        _cfg(
            StrategyId.LONDON_BREAKOUT,
            trend_filter=True,
            trend_timeframe=Timeframe.M15,
            trend_ema_period=10,
            stop_method=StopMethod.RANGE,
            min_range_pips=0.0,
            max_range_pips=1000.0,
        ),
    ),
    (
        "rsi_htf",
        _cfg(
            StrategyId.RSI_PULLBACK,
            trend_filter=True,
            trend_timeframe=Timeframe.M15,
            trend_ema_period=20,
        ),
    ),
    (
        "rsi_same_tf",
        _cfg(StrategyId.RSI_PULLBACK, trend_filter=True, trend_ema_period=50),
    ),
    (
        "bb_htf",
        _cfg(
            StrategyId.BOLLINGER_REVERSION,
            trend_filter=True,
            trend_timeframe=Timeframe.M15,
            trend_ema_period=20,
            bb_std=1.5,
            stop_method=StopMethod.ATR,
        ),
    ),
    (
        "bb_zero_distance",
        _cfg(
            StrategyId.BOLLINGER_REVERSION,
            trend_filter=True,
            trend_ema_period=5,
            trend_max_distance_atr=0.0,
            bb_std=1.0,
            rsi_oversold=45.0,
            rsi_overbought=55.0,
        ),
    ),
]


@pytest.mark.parametrize(
    ("name", "cfg"), _LOOKAHEAD_CASES, ids=[n for n, _ in _LOOKAHEAD_CASES]
)
def test_no_look_ahead_signals_on_prefix_equal_prefix_of_signals(
    name: str, cfg: BacktestConfig
) -> None:
    """Truncating the data after bar k must not change any signal before k.

    If a strategy used a future bar (an HTF candle still forming, an Asian range
    not yet complete, a smoothed value at i+1), the full run would disagree with
    the run that only had data up to k, and the backtest would be trading on the
    future. The HTF slice holds only candles already closed at bar k-1's close.
    """
    candles = _walk(4000)
    htf_tf = cfg.params.trend_timeframe
    htf = _aggregate(candles, 3) if htf_tf is Timeframe.M15 else None
    full_htf = htf if htf_tf is not cfg.timeframe else None
    full = generate_signals(cfg, candles, full_htf, EURUSD)
    assert len(full) >= 5, f"{name}: crafted walk must exercise the strategy"

    # Cuts include mid-Asian-window, mid-session and arbitrary offsets.
    # Cutting right after, and right before, each signal bar is the sharpest test:
    # the decision bar then has no future data at all.
    sampled = full[:: max(1, len(full) // 12)]
    at_signals = [s.index + d for s in sampled for d in (0, 1)]
    for k in (150, 301, 1000, 1234, 1440 + 40, 2001, 2888 + 100, 3999, *at_signals):
        if k < 1:
            continue
        cut_htf = (
            _closed_htf(htf, candles[k - 1], htf_tf) if htf is not None and full_htf else None
        )
        part = generate_signals(cfg, candles[:k], cut_htf, EURUSD)
        assert part == [s for s in full if s.index < k], f"{name}: diverged at cut {k}"


@pytest.mark.parametrize(
    ("name", "cfg"), _LOOKAHEAD_CASES, ids=[n for n, _ in _LOOKAHEAD_CASES]
)
def test_signals_are_deterministic_and_sorted(name: str, cfg: BacktestConfig) -> None:
    """Same input, same output: a run must be reproducible from its config."""
    candles = _walk(1500)
    htf = _aggregate(candles, 3) if cfg.params.trend_timeframe is Timeframe.M15 else None
    a = generate_signals(cfg, candles, htf, EURUSD)
    b = generate_signals(cfg, candles, htf, EURUSD)
    assert a == b
    assert [s.index for s in a] == sorted(s.index for s in a)
    assert all(s.stop_distance > 0 for s in a)


def test_strategies_ignore_direction_session_filter_and_risk() -> None:
    """Direction mode and session filter are the engine's job; the signal list
    must not change with them."""
    candles = _walk(1500)
    base = _cfg(StrategyId.RSI_PULLBACK, trend_filter=True, trend_ema_period=50)
    from app.labs.forex.types import DirectionMode

    restricted = replace(
        base,
        direction=DirectionMode.LONG_ONLY,
        session_filter=Session(7, 10),
    )
    assert generate_signals(base, candles, None, EURUSD) == generate_signals(
        restricted, candles, None, EURUSD
    )
