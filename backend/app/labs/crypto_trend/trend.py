"""Per-coin trend state on one timeframe, and the two-timeframe verdict.

Pure: candles in, a frozen `TrendState` out. Nothing here reads a database
or a network. The rules:

    UP    if close > EMA_slow, EMA_fast > EMA_slow and ADX >= ADX_MIN
    DOWN  if the mirror holds
    FLAT  otherwise

Swing structure is a VETO and a strength input, not a gate. An UP reading
is refused — the state becomes FLAT with `structure_veto` set — only when
the most recent confirmed swing is a LOWER LOW under the prior swing low by
more than STRUCTURE_VETO_ATR x ATR; DOWN mirrors it with a higher high. A
shallow break, a mixed structure, or a break that a later swing has already
answered vetoes nothing. Structure that agrees with the direction (HH_HL for
UP, LH_LL for DOWN) adds to strength; anything else adds nothing.

    LONG_BIAS   4h UP   and 1h UP or FLAT
    SHORT_BIAS  4h DOWN and 1h DOWN or FLAT
    NEUTRAL     otherwise

`strength` is a 0-100 magnitude (see `strength()` and the README);
`bars_in_state` counts consecutive closed bars, including this one, on
which the same rule fired — evaluated with only what was known on each bar.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from app.labs.crypto_trend import config
from app.labs.crypto_trend.candles import Candle
from app.labs.crypto_trend.indicators import (
    SwingStructure,
    adx,
    atr,
    donchian,
    ema,
    known_swings,
)

UP, DOWN, FLAT = "UP", "DOWN", "FLAT"
LONG_BIAS, SHORT_BIAS, NEUTRAL = "LONG_BIAS", "SHORT_BIAS", "NEUTRAL"


@dataclass(frozen=True, slots=True)
class TrendState:
    symbol: str
    timeframe: str
    #: The close of the last candle the state was computed on. The row's key.
    bar_close_time: datetime
    computed_at: datetime
    direction: str
    strength: int
    #: EMA_slow's change over `SLOPE_BARS` bars, in percent. Signed.
    slope: float
    #: ATR as a percentage of the close.
    atr_pct: float
    bars_in_state: int
    ema_fast: float
    ema_slow: float
    #: None until EMA_TREND candles exist — a newly listed contract.
    ema_trend: float | None
    adx: float
    structure: str
    #: True when the averages and ADX read a trend that the most recent swing
    #: refused. Only ever True on a FLAT state.
    structure_veto: bool
    close: float


@dataclass(frozen=True, slots=True)
class Verdict:
    symbol: str
    verdict: str
    reason: str


def _clamp01(x: float) -> float:
    return 0.0 if x < 0 else 1.0 if x > 1 else x


def raw_direction(close: float, ema_fast: float, ema_slow: float, adx_value: float) -> str:
    """The averages and ADX alone."""
    if close > ema_slow and ema_fast > ema_slow and adx_value >= config.ADX_MIN:
        return UP
    if close < ema_slow and ema_fast < ema_slow and adx_value >= config.ADX_MIN:
        return DOWN
    return FLAT


def structure_veto(raw: str, swings: SwingStructure, atr_value: float) -> bool:
    """True when the MOST RECENT confirmed swing breaks structure against
    `raw` by more than STRUCTURE_VETO_ATR x ATR: a lower low under an UP
    reading, a higher high under a DOWN one.

    Three things do not veto: a shallow break; a structure with fewer than
    two swings on the side that matters; and a break that a later swing has
    already answered — then the most recent swing is on the other side, and
    the break is history.
    """
    if raw == FLAT:
        return False
    highs, lows = swings.highs, swings.lows
    threshold = config.STRUCTURE_VETO_ATR * atr_value
    if raw == UP:
        if len(lows) < 2 or (highs and highs[-1].index > lows[-1].index):
            return False
        return lows[-2].price - lows[-1].price > threshold
    if len(highs) < 2 or (lows and lows[-1].index > highs[-1].index):
        return False
    return highs[-1].price - highs[-2].price > threshold


def direction(close: float, ema_fast: float, ema_slow: float, adx_value: float,
              swings: SwingStructure, atr_value: float) -> tuple[str, bool]:
    """(direction, vetoed). A vetoed reading is FLAT."""
    raw = raw_direction(close, ema_fast, ema_slow, adx_value)
    vetoed = structure_veto(raw, swings, atr_value)
    return (FLAT if vetoed else raw), vetoed


def strength(*, adx_value: float, ema_fast: float, ema_slow: float, atr_value: float,
             close: float, upper: float, lower: float, direction: str, structure: str) -> int:
    """0-100. Four components, each in [0, 1], weighted by `STRENGTH_WEIGHTS`:

    * ADX / STRENGTH_ADX_FULL
    * |EMA_fast - EMA_slow| / (STRENGTH_SPREAD_ATR_FULL * ATR)
    * the close's distance from the Donchian midpoint as a fraction of the
      channel's half-width, IN THE DIRECTION THE AVERAGES LEAN — a close on
      the wrong side of the midpoint scores zero rather than negative
    * 1 when the swing structure agrees with the direction (HH_HL for UP,
      LH_LL for DOWN), else 0 — so a FLAT state never earns it
    """
    w_adx, w_spread, w_donchian, w_structure = config.STRENGTH_WEIGHTS
    a = _clamp01(adx_value / config.STRENGTH_ADX_FULL)
    b = _clamp01(abs(ema_fast - ema_slow) / (config.STRENGTH_SPREAD_ATR_FULL * atr_value)) \
        if atr_value > 0 else 0.0
    half_width = (upper - lower) / 2.0
    lean = 1.0 if ema_fast >= ema_slow else -1.0
    mid = (upper + lower) / 2.0
    c = _clamp01(lean * (close - mid) / half_width) if half_width > 0 else 0.0
    d = 1.0 if (direction, structure) in ((UP, "HH_HL"), (DOWN, "LH_LL")) else 0.0
    return round(100.0 * (w_adx * a + w_spread * b + w_donchian * c + w_structure * d))


@dataclass(frozen=True, slots=True)
class _Series:
    closes: list[float]
    fast: list[float | None]
    slow: list[float | None]
    trend: list[float | None]
    atr: list[float | None]
    adx: list[float | None]
    upper: list[float | None]
    lower: list[float | None]
    swings: list[SwingStructure]

    def ready(self, i: int) -> bool:
        return None not in (self.fast[i], self.slow[i], self.atr[i], self.adx[i],
                            self.upper[i], self.lower[i])

    def direction_at(self, i: int) -> tuple[str, bool]:
        return direction(self.closes[i], self.fast[i], self.slow[i], self.adx[i],  # type: ignore[arg-type]
                         self.swings[i], self.atr[i])  # type: ignore[arg-type]


def _series(candles: Sequence[Candle]) -> _Series:
    """Every indicator over the whole series. Each is causal — the value on
    candle i depends on candles 0..i only — which is what lets one pass
    over the full history stand in for a fresh computation on every prefix.
    `compute_trend_states` relies on that, and a test holds it."""
    closes = [float(c.close) for c in candles]
    _, _, adx_s = adx(candles, config.ADX_PERIOD)
    upper, lower = donchian(candles, config.DONCHIAN_PERIOD)
    return _Series(closes=closes, fast=ema(closes, config.EMA_FAST),
                   slow=ema(closes, config.EMA_SLOW), trend=ema(closes, config.EMA_TREND),
                   atr=atr(candles, config.ATR_PERIOD), adx=adx_s, upper=upper, lower=lower,
                   swings=known_swings(candles, config.SWING_LOOKBACK))


def _state(symbol: str, timeframe: str, candles: Sequence[Candle], s: _Series, i: int,
           *, bars: int, computed_at: datetime) -> TrendState | None:
    if i + 1 < config.MIN_BARS or not s.ready(i) or s.slow[i - config.SLOPE_BARS] is None:
        return None
    current, vetoed = s.direction_at(i)
    prior = s.slow[i - config.SLOPE_BARS]
    slope = 0.0 if not prior else (s.slow[i] - prior) / prior * 100.0  # type: ignore[operator]
    structure = s.swings[i].structure
    return TrendState(
        symbol=symbol, timeframe=timeframe,
        bar_close_time=candles[i].close_time, computed_at=computed_at,
        direction=current,
        strength=strength(adx_value=s.adx[i], ema_fast=s.fast[i], ema_slow=s.slow[i],  # type: ignore[arg-type]
                          atr_value=s.atr[i], close=s.closes[i],  # type: ignore[arg-type]
                          upper=s.upper[i], lower=s.lower[i],  # type: ignore[arg-type]
                          direction=current, structure=structure),
        slope=slope,
        atr_pct=s.atr[i] / s.closes[i] * 100.0 if s.closes[i] else 0.0,  # type: ignore[operator]
        bars_in_state=bars,
        ema_fast=s.fast[i], ema_slow=s.slow[i], ema_trend=s.trend[i],  # type: ignore[arg-type]
        adx=s.adx[i], structure=structure, structure_veto=vetoed,  # type: ignore[arg-type]
        close=s.closes[i],
    )


def compute_trend_state(
    symbol: str, timeframe: str, candles: Sequence[Candle], *, computed_at: datetime,
) -> TrendState | None:
    """The state on the last candle, or None when there is not enough history."""
    n = len(candles)
    if n < config.MIN_BARS:
        return None
    s = _series(candles)
    last = n - 1
    if not s.ready(last):
        return None
    current = s.direction_at(last)[0]
    bars = 1
    while (last - bars >= 0 and s.ready(last - bars)
           and s.direction_at(last - bars)[0] == current):
        bars += 1
    return _state(symbol, timeframe, candles, s, last, bars=bars, computed_at=computed_at)


def compute_trend_states(
    symbol: str, timeframe: str, candles: Sequence[Candle], *, computed_at: datetime,
) -> list[TrendState | None]:
    """The state on EVERY candle, each from that candle and its past only.

    Element i is exactly `compute_trend_state(candles[:i + 1])` — the same
    numbers, because every indicator is causal — computed in one pass
    instead of n. This is what a replay steps through, and the identity is
    what makes the replay hindsight-free by construction; a test holds it.
    """
    n = len(candles)
    out: list[TrendState | None] = [None] * n
    if n < config.MIN_BARS:
        return out
    s = _series(candles)
    bars = 0
    previous: str | None = None
    for i in range(n):
        if not s.ready(i):
            bars, previous = 0, None
            continue
        current = s.direction_at(i)[0]
        bars = bars + 1 if current == previous else 1
        previous = current
        out[i] = _state(symbol, timeframe, candles, s, i, bars=bars, computed_at=computed_at)
    return out


def coin_verdict(
    symbol: str, state_4h: TrendState | None, state_1h: TrendState | None,
) -> Verdict:
    d4 = state_4h.direction if state_4h else None
    d1 = state_1h.direction if state_1h else None
    if d4 is None:
        return Verdict(symbol, NEUTRAL, "no 4h state")
    if d4 == UP and d1 in (UP, FLAT):
        return Verdict(symbol, LONG_BIAS, f"4h UP, 1h {d1}")
    if d4 == DOWN and d1 in (DOWN, FLAT):
        return Verdict(symbol, SHORT_BIAS, f"4h DOWN, 1h {d1}")
    if d4 == FLAT:
        return Verdict(symbol, NEUTRAL, f"4h FLAT, 1h {d1 or 'missing'}")
    if d1 is None:
        return Verdict(symbol, NEUTRAL, f"4h {d4}, 1h missing")
    return Verdict(symbol, NEUTRAL, f"4h {d4} against 1h {d1}")
