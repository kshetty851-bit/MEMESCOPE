"""The `slow_daily` rule set — a PRE-REGISTERED test of a slower hypothesis.

Selected by `STRATEGY=slow_daily`. It exposes the eight names `strategy.py`
documents, so `replay.py`, `sim.py` and the cost model drive it unchanged.
It shares `size()`, `Position` and `Order` with the 4h strategy and nothing
else: its own indicators, its own periods, its own exits.

The rules, fixed before the first run and not to be tuned:

    direction   close > EMA_SLOW (100) and EMA_FAST (20) > EMA_SLOW  -> UP
                the mirror                                          -> DOWN
                otherwise                                           -> FLAT
    entry       a close beyond the 20-day Donchian channel OF THE PRIOR BARS,
                in the direction of that trend, with ADX(14) >= 20, and the
                regime allowing that side on the same thresholds the 4h
                strategy uses. NO BTC-alignment rule: this tests the raw
                signal.
    stop        3.0 x ATR(20) at entry, fixed at fill
    trail       the 10-day Donchian channel on the opposite side
    exits       universe, direction flip, hard stop, trail. NO time stop and
                NO regime exit: the regime gates entries only.
    sizing      unchanged — 1% risk, 20% notional cap, 5 positions, 2 new
                entries per bar

Two things the brief left open, decided here and recorded rather than
tuned:

* **The trail is not ratcheted.** "The 10-day Donchian opposite channel" is
  recomputed every bar and can therefore loosen as well as tighten, which
  is how a Donchian exit channel is normally defined. The 4h strategy's
  trail ratchets; this one does not.
* **The per-bar entry cap breaks ties by ADX**, descending, then by symbol.
  This rule set has no `strength`, so the 4h tie-break does not apply.

There is no same-side cap: the brief names the position cap and the per-bar
cap, and a trend system that may not hold five longs in a bull market is a
different hypothesis from the one being tested.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime

from app.labs.crypto_trend import config
from app.labs.crypto_trend.candles import Candle
from app.labs.crypto_trend.indicators import adx, atr, donchian, ema
from app.labs.crypto_trend.strategy import (
    CLOSE,
    LONG,
    OPEN,
    SHORT,
    Order,
    Position,
    Snapshot,
    StrategyConfig,
    _side_allowed,
    size,
)
from app.labs.crypto_trend.trend import (
    DOWN,
    FLAT,
    LONG_BIAS,
    NEUTRAL,
    SHORT_BIAS,
    UP,
    Verdict,
)

TIMEFRAMES: tuple[str, ...] = ("1d",)
DECISION_TIMEFRAME = "1d"


@dataclass(frozen=True, slots=True)
class DailyState:
    symbol: str
    timeframe: str
    bar_close_time: datetime
    computed_at: datetime
    direction: str
    close: float
    ema_fast: float
    ema_slow: float
    adx: float
    atr: float
    #: The 20-day channel of the PRIOR bars — the level a close must clear.
    breakout_high: float
    breakout_low: float
    #: The 10-day channel of the prior bars — where the trail sits.
    exit_high: float
    exit_low: float
    bars_in_state: int


def direction_of(close: float, ema_fast: float, ema_slow: float) -> str:
    if close > ema_slow and ema_fast > ema_slow:
        return UP
    if close < ema_slow and ema_fast < ema_slow:
        return DOWN
    return FLAT


def compute_states(symbol: str, timeframe: str, candles: Sequence[Candle], *,
                   computed_at: datetime) -> list[DailyState | None]:
    """Every bar's state from that bar and its past only.

    Both Donchian channels are read at `i - 1`, so the level a close is
    compared against never contains that close. Every other series is
    causal by construction, exactly as in `trend.py`.
    """
    n = len(candles)
    out: list[DailyState | None] = [None] * n
    if n < config.SLOW_DAILY_MIN_BARS:
        return out
    closes = [float(c.close) for c in candles]
    fast = ema(closes, config.SLOW_DAILY_EMA_FAST)
    slow = ema(closes, config.SLOW_DAILY_EMA_SLOW)
    atr_s = atr(candles, config.SLOW_DAILY_ATR_PERIOD)
    _, _, adx_s = adx(candles, config.SLOW_DAILY_ADX_PERIOD)
    entry_hi, entry_lo = donchian(candles, config.SLOW_DAILY_ENTRY_DONCHIAN)
    exit_hi, exit_lo = donchian(candles, config.SLOW_DAILY_EXIT_DONCHIAN)

    bars, previous = 0, None
    for i in range(1, n):
        if None in (fast[i], slow[i], atr_s[i], adx_s[i],
                    entry_hi[i - 1], exit_hi[i - 1]):
            bars, previous = 0, None
            continue
        current = direction_of(closes[i], fast[i], slow[i])  # type: ignore[arg-type]
        bars = bars + 1 if current == previous else 1
        previous = current
        out[i] = DailyState(
            symbol=symbol, timeframe=timeframe, bar_close_time=candles[i].close_time,
            computed_at=computed_at, direction=current, close=closes[i],
            ema_fast=fast[i], ema_slow=slow[i], adx=adx_s[i], atr=atr_s[i],  # type: ignore[arg-type]
            breakout_high=entry_hi[i - 1], breakout_low=entry_lo[i - 1],  # type: ignore[arg-type]
            exit_high=exit_hi[i - 1], exit_low=exit_lo[i - 1],  # type: ignore[arg-type]
            bars_in_state=bars)
    return out


def breadth_direction(states: Mapping[str, DailyState | None]) -> str | None:
    state = states.get(DECISION_TIMEFRAME)
    return None if state is None else state.direction


def verdict_of(states: Mapping[str, DailyState | None], symbol: str) -> Verdict:
    """One timeframe, so the verdict IS the direction."""
    state = states.get(DECISION_TIMEFRAME)
    if state is None:
        return Verdict(symbol, NEUTRAL, "no daily state")
    if state.direction == UP:
        return Verdict(symbol, LONG_BIAS, "daily UP")
    if state.direction == DOWN:
        return Verdict(symbol, SHORT_BIAS, "daily DOWN")
    return Verdict(symbol, NEUTRAL, "daily FLAT")


def sizing_config(cfg: StrategyConfig) -> StrategyConfig:
    """The shared sizer, with this rule set's wider stop."""
    return replace(cfg, stop_atr=float(config.SLOW_DAILY_STOP_ATR))


# --- between bars ------------------------------------------------------------------

def advance(positions, states: Mapping[str, Mapping[str, DailyState | None]],
            cfg: StrategyConfig) -> list[Position]:
    """One bar later: count it, move the best close, and put the trail on
    the 10-day channel. Recomputed, not ratcheted — see the module docstring."""
    out = []
    for p in positions:
        state = states.get(p.symbol, {}).get(DECISION_TIMEFRAME)
        if state is None:
            out.append(replace(p, bars_held=p.bars_held + 1))
            continue
        best = max(p.best_close, state.close) if p.side == LONG \
            else min(p.best_close, state.close)
        trail = state.exit_low if p.side == LONG else state.exit_high
        out.append(replace(p, bars_held=p.bars_held + 1, best_close=best, trail_stop=trail))
    return out


# --- exits --------------------------------------------------------------------------

def exit_reason(p: Position, snapshot: Snapshot, cfg: StrategyConfig) -> str | None:
    """First rule wins: universe, direction flip, hard stop, trail."""
    if p.symbol not in snapshot.universe:
        return "universe_exit"
    v = verdict_of(snapshot.states.get(p.symbol, {}), p.symbol).verdict
    if (p.side == LONG and v == SHORT_BIAS) or (p.side == SHORT and v == LONG_BIAS):
        return "verdict_exit"
    state = snapshot.states.get(p.symbol, {}).get(DECISION_TIMEFRAME)
    if state is None:
        return None
    if (state.close - p.stop) * p.sign <= 0:
        return "hard_stop"
    if p.trail_stop is not None and (state.close - p.trail_stop) * p.sign <= 0:
        return "trail_stop"
    return None


# --- entries -------------------------------------------------------------------------

def entry_candidates(snapshot: Snapshot,
                     cfg: StrategyConfig) -> list[tuple[str, str, DailyState]]:
    """A breakout beyond the prior 20-day channel, with the trend and ADX
    behind it and the regime allowing that side. Strongest ADX first."""
    out = []
    for symbol in sorted(snapshot.universe):
        state = snapshot.states.get(symbol, {}).get(DECISION_TIMEFRAME)
        if state is None or state.adx < config.SLOW_DAILY_ADX_MIN:
            continue
        if state.direction == UP and state.close > state.breakout_high:
            side = LONG
        elif state.direction == DOWN and state.close < state.breakout_low:
            side = SHORT
        else:
            continue
        if _side_allowed(side, snapshot.regime, cfg) is not None:
            continue
        out.append((symbol, side, state))
    out.sort(key=lambda t: (-t[2].adx, t[0]))
    return out


def decide(snapshot: Snapshot, positions: Sequence[Position], equity: float,
           cfg: StrategyConfig) -> list[Order]:
    """Exits first, then at most `max_new_entries_per_bar` entries."""
    orders: list[Order] = []
    closing: set[str] = set()
    for p in positions:
        reason = exit_reason(p, snapshot, cfg)
        if reason is not None:
            orders.append(Order(p.symbol, CLOSE, p.side, reason))
            closing.add(p.symbol)

    remaining = [p for p in positions if p.symbol not in closing]
    held = {p.symbol for p in remaining}
    room = min(cfg.max_positions - len(remaining), cfg.max_new_entries_per_bar)
    sizer = sizing_config(cfg)
    for symbol, side, state in entry_candidates(snapshot, cfg):
        if room <= 0:
            break
        if symbol in held:
            continue
        sz = size(equity, state.close, state.atr, sizer)
        if sz is None:
            continue
        channel = state.breakout_high if side == LONG else state.breakout_low
        orders.append(Order(
            symbol, OPEN, side,
            reason=(f"{config.SLOW_DAILY_ENTRY_DONCHIAN}d breakout {state.close:.6g} "
                    f"beyond {channel:.6g}, adx {state.adx:.1f}, "
                    f"regime {snapshot.regime.regime if snapshot.regime else '-'}"),
            qty=sz.qty, stop_distance=sz.stop_distance, atr=state.atr,
            notional=sz.notional, implied_leverage=sz.implied_leverage,
            reference_price=state.close, intended_risk_usd=sz.intended_risk_usd))
        held.add(symbol)
        room -= 1
    return orders
