"""The range strategy's decision, as a pure function of closed candles.

`evaluate` answers one question — what does the strategy say at the close of
this candle? — from the preceding `lookback` candles and nothing else. There is
no clock, no state between calls and no randomness, so the live book and a
backtest cannot disagree: they call the same function on the same candles.

Two properties are deliberate:

  - **The window excludes the candle being evaluated.** If the last candle were
    part of its own range, a breakout would stretch the range to contain
    itself and never be seen as one.
  - **Every figure on a WAIT is either measured or absent.** Entry, targets and
    reward/risk are only produced for a call that qualified; a WAIT carries
    `None`, because a level nobody would trade is an estimate.

Confidence (0..100) is a sum of three measured parts, each documented because
the number is shown to people and has to be explainable:

  - **Touches, 40 points.** Per side, `min(touches, min_touches) / min_touches`;
    the two sides are averaged. A range both ends of which have held more than
    once is a range somebody can trade; one touched once is a guess.
  - **Efficiency, 35 points.** `max(0, 1 - ER / max_trend_efficiency)`. A window
    that drifted in one direction is not oscillating, however wide it is.
  - **Width, 25 points.** All or nothing: inside `[min_width_pct,
    max_width_pct]`. Too narrow cannot pay its costs; too wide is not a range.

Decimals are quantized once, at the edge of each figure, and decisions are made
on the quantized values — what the page shows is exactly what was compared.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import ROUND_HALF_UP, Decimal

from app.labs.btc_range.types import (
    Call,
    Candle,
    RangeState,
    Reason,
    Regime,
    Signal,
    StrategyConfig,
)

PRICE_STEP = Decimal("0.01")
RATIO_STEP = Decimal("0.0001")

_ZERO = Decimal(0)
_ONE = Decimal(1)
_TWO = Decimal(2)
_HUNDRED = Decimal(100)
_BPS = Decimal(10_000)

_TOUCH_POINTS = Decimal(40)
_EFFICIENCY_POINTS = Decimal(35)
_WIDTH_POINTS = Decimal(25)


def quantize(value: Decimal, step: Decimal) -> Decimal:
    return value.quantize(step, rounding=ROUND_HALF_UP)


def _count_touch_episodes(
    window: Sequence[Candle],
    support_line: Decimal,
    resistance_line: Decimal,
) -> tuple[int, int]:
    """Touches counted as episodes, not candles.

    Price sitting on support for six candles is one test of the level, not six.
    Counting candles would let a single slow approach satisfy `min_touches`.
    """
    support_touches = 0
    resistance_touches = 0
    on_support = False
    on_resistance = False
    for candle in window:
        touching_support = candle.low <= support_line
        touching_resistance = candle.high >= resistance_line
        if touching_support and not on_support:
            support_touches += 1
        if touching_resistance and not on_resistance:
            resistance_touches += 1
        on_support = touching_support
        on_resistance = touching_resistance
    return support_touches, resistance_touches


def _efficiency_ratio(window: Sequence[Candle]) -> Decimal:
    """Kaufman's ER over closes: net move / total path. 0 when nothing moved."""
    path = _ZERO
    previous = window[0].close
    for candle in window[1:]:
        path += abs(candle.close - previous)
        previous = candle.close
    if path == 0:
        return _ZERO
    return abs(window[-1].close - window[0].close) / path


def _confidence(
    touches_support: int,
    touches_resistance: int,
    efficiency: Decimal,
    width_pct: Decimal,
    cfg: StrategyConfig,
) -> int:
    if cfg.min_touches <= 0:
        touch_credit = _ONE
    else:
        needed = Decimal(cfg.min_touches)
        touch_credit = (
            Decimal(min(touches_support, cfg.min_touches))
            + Decimal(min(touches_resistance, cfg.min_touches))
        ) / (needed * _TWO)

    if cfg.max_trend_efficiency <= 0:
        # A zero threshold admits only a window that did not move at all.
        efficiency_credit = _ONE if efficiency == 0 else _ZERO
    else:
        efficiency_credit = max(_ZERO, _ONE - efficiency / cfg.max_trend_efficiency)

    width_credit = _ONE if cfg.min_width_pct <= width_pct <= cfg.max_width_pct else _ZERO

    score = (
        _TOUCH_POINTS * touch_credit
        + _EFFICIENCY_POINTS * efficiency_credit
        + _WIDTH_POINTS * width_credit
    )
    return int(score.quantize(_ONE, rounding=ROUND_HALF_UP))


def detect_range(
    window: Sequence[Candle], price: Decimal, cfg: StrategyConfig
) -> RangeState | None:
    """The range the window describes, judged against `price`.

    None when there is no range to speak of: an empty window, or one with zero
    width (every candle flat at one price), where position and width_pct are
    undefined rather than zero.
    """
    if not window:
        return None

    support = min(candle.low for candle in window)
    resistance = max(candle.high for candle in window)
    width = resistance - support
    mid = (support + resistance) / _TWO
    if width <= 0 or mid <= 0:
        return None

    tolerance = cfg.touch_tolerance * width
    touches_support, touches_resistance = _count_touch_episodes(
        window, support + tolerance, resistance - tolerance
    )

    efficiency = quantize(_efficiency_ratio(window), RATIO_STEP)
    width_pct = quantize(width / mid * _HUNDRED, RATIO_STEP)
    position = quantize((price - support) / width, RATIO_STEP)

    if price > resistance:
        regime = Regime.BREAKOUT_UP
    elif price < support:
        regime = Regime.BREAKOUT_DOWN
    elif efficiency > cfg.max_trend_efficiency:
        regime = Regime.TRENDING
    else:
        regime = Regime.RANGE

    return RangeState(
        support=quantize(support, PRICE_STEP),
        resistance=quantize(resistance, PRICE_STEP),
        mid=quantize(mid, PRICE_STEP),
        width=quantize(width, PRICE_STEP),
        width_pct=width_pct,
        position=position,
        touches_support=touches_support,
        touches_resistance=touches_resistance,
        trend_efficiency=efficiency,
        confidence=_confidence(
            touches_support, touches_resistance, efficiency, width_pct, cfg
        ),
        regime=regime,
    )


def _wait(
    at_candle: Candle,
    price: Decimal,
    state: RangeState | None,
    *reasons: Reason,
) -> Signal:
    return Signal(
        at=at_candle.open_time,
        price=price,
        call=Call.WAIT,
        confidence=state.confidence if state is not None else 0,
        range=state,
        entry=None,
        take_profit=None,
        stop_loss=None,
        reward_risk=None,
        reasons=reasons,
    )


def evaluate(candles: Sequence[Candle], cfg: StrategyConfig) -> Signal:
    """The strategy's call at the close of `candles[-1]`.

    Gates run in a fixed order and the first one that fails is `reasons[0]`.
    The order is the story a reader needs: is price outside the range, is the
    range really a range, is it a tradeable size, is it trusted, is price at an
    edge, is that side allowed, and only then do the levels have to pay.
    """
    if not candles:
        # `Signal.at` comes from the last candle; with none there is nothing to
        # evaluate and a caller that gets here has a bug worth surfacing.
        raise ValueError("evaluate needs at least one candle")
    last = candles[-1]
    if cfg.lookback < 1 or len(candles) < cfg.lookback + 1:
        return _wait(last, quantize(last.close, PRICE_STEP), None, Reason.INSUFFICIENT_DATA)

    price = quantize(last.close, PRICE_STEP)
    count = len(candles)
    state = detect_range(candles[count - 1 - cfg.lookback : count - 1], last.close, cfg)
    if state is None:
        return _wait(last, price, None, Reason.INSUFFICIENT_DATA)

    if state.regime is Regime.BREAKOUT_UP:
        return _wait(last, price, state, Reason.BREAKOUT_UP)
    if state.regime is Regime.BREAKOUT_DOWN:
        return _wait(last, price, state, Reason.BREAKOUT_DOWN)
    if state.regime is Regime.TRENDING:
        return _wait(last, price, state, Reason.TRENDING)

    if state.width_pct < cfg.min_width_pct:
        return _wait(last, price, state, Reason.RANGE_TOO_NARROW)
    if state.width_pct > cfg.max_width_pct:
        return _wait(last, price, state, Reason.RANGE_TOO_WIDE)

    if state.confidence < cfg.min_confidence:
        return _wait(last, price, state, Reason.LOW_CONFIDENCE)

    if state.position <= cfg.entry_zone:
        call, zone_reason = Call.LONG, Reason.NEAR_SUPPORT
    elif state.position >= _ONE - cfg.entry_zone:
        call, zone_reason = Call.SHORT, Reason.NEAR_RESISTANCE
    else:
        return _wait(last, price, state, Reason.MID_RANGE)

    if (call is Call.LONG and not cfg.allow_long) or (
        call is Call.SHORT and not cfg.allow_short
    ):
        return _wait(last, price, state, Reason.SIDE_DISABLED, zone_reason)

    # Levels come from the raw window edges' quantized values, so the signal's
    # numbers are the ones shown in `range` and can be re-derived from them.
    width = state.resistance - state.support
    if call is Call.LONG:
        take_profit = quantize(state.support + cfg.tp_target * width, PRICE_STEP)
        stop_loss = quantize(state.support - cfg.sl_buffer * width, PRICE_STEP)
        reward = take_profit - price
        risk = price - stop_loss
    else:
        take_profit = quantize(state.resistance - cfg.tp_target * width, PRICE_STEP)
        stop_loss = quantize(state.resistance + cfg.sl_buffer * width, PRICE_STEP)
        reward = price - take_profit
        risk = stop_loss - price

    if reward <= 0 or risk <= 0:
        return _wait(last, price, state, Reason.POOR_REWARD_RISK, zone_reason)
    reward_risk = quantize(reward / risk, RATIO_STEP)
    if reward_risk < cfg.min_reward_risk:
        return _wait(last, price, state, Reason.POOR_REWARD_RISK, zone_reason)

    # Fees and slippage are paid on both fills; a target that does not clear the
    # round trip is a loss that has not happened yet.
    round_trip_cost = _TWO * (cfg.fee_bps + cfg.slippage_bps) / _BPS
    if reward / price <= round_trip_cost:
        return _wait(last, price, state, Reason.COSTS_EXCEED_TARGET, zone_reason)

    return Signal(
        at=last.open_time,
        price=price,
        call=call,
        confidence=state.confidence,
        range=state,
        entry=price,
        take_profit=take_profit,
        stop_loss=stop_loss,
        reward_risk=reward_risk,
        reasons=(zone_reason,),
    )
