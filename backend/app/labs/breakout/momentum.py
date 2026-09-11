"""Levels + candles -> a momentum score, 0-100. Pure; no I/O, no clock.

Five components, each clamped to `[0, 1]`, combined with the weights in
`config.MOMENTUM_WEIGHTS`. Every component is returned alongside the score,
because a score nobody can take apart is a number nobody can argue with — and
the whole point of `bo_episodes` is to find out later which of these five, if
any, actually predicted anything.

The score says "coiling into resistance with participation". It does NOT say
the breakout will happen; Phase 2 records, it does not believe.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from itertools import pairwise

from app.labs.breakout import config
from app.labs.breakout.candles import Candle
from app.labs.breakout.levels import Levels


@dataclass(frozen=True, slots=True)
class Momentum:
    score: int
    volume: float
    structure: float
    position: float
    compression: float
    #: None when there were not enough hourly bars to read.
    hourly: float | None
    hourly_missing: bool

    def components(self) -> dict[str, float | None]:
        return {
            "volume": self.volume,
            "structure": self.structure,
            "position": self.position,
            "compression": self.compression,
            "hourly": self.hourly,
        }


def _clamp(value: float) -> float:
    return 0.0 if value < 0 else 1.0 if value > 1 else value


def volume_component(daily: Sequence[Candle], mean: float | None) -> float:
    """Today plus yesterday against twice the 20-day mean, capped.

    Two days rather than one because a single bar's volume on a thin Solana
    pool is one wallet as often as it is a crowd.
    """
    if not mean or mean <= 0 or len(daily) < 2:
        return 0.0
    recent = [c.volume_usd for c in daily[-2:]]
    if any(v is None for v in recent):
        return 0.0
    ratio = sum(float(v) for v in recent) / (2 * mean)  # type: ignore[arg-type]
    return _clamp(ratio / config.VOLUME_RATIO_CAP)


def structure_component(daily: Sequence[Candle],
                        bars: int = config.STRUCTURE_BARS) -> float:
    """The share of the last `bars` daily bars whose low is above the one
    before it. Rising lows is the cheapest description of accumulation."""
    if len(daily) < bars + 1:
        return 0.0
    window = daily[-(bars + 1):]
    rising = sum(1 for a, b in pairwise(window) if float(b.low) > float(a.low))
    return rising / bars


def position_component(levels: Levels) -> float:
    """Where the close sits in the 10-day range, 0 at the low and 1 at the high.

    The brief frames this as "close within the top 30% of the range". A
    threshold would throw away the difference between a close at the 31st
    percentile and one at the 99th, which is exactly the difference that
    matters here, so the component is the CONTINUOUS position — a close in the
    top 30% is simply one scoring above 0.7. Recorded as an unattended
    decision in the README.
    """
    if levels.high_range is None or levels.low_range is None:
        return 0.0
    span = levels.high_range - levels.low_range
    if span <= 0:
        return 0.0
    return _clamp((levels.close - levels.low_range) / span)


def compression_component(levels: Levels) -> float:
    """How much tighter the last 5 days are than the last 20. A coil scores
    high; an expansion scores zero."""
    if not levels.atr_fast or not levels.atr_slow or levels.atr_slow <= 0:
        return 0.0
    return _clamp(1.0 - levels.atr_fast / levels.atr_slow)


def hourly_component(hourly: Sequence[Candle],
                     bars: int = config.HOURLY_CONFIRM_BARS) -> float | None:
    """Half the slope's sign, half the share of green bars, over the last
    `bars` hourly closes. None when there are not enough bars — the caller
    turns that into `hourly_missing`, never into a zero."""
    if len(hourly) < bars:
        return None
    window = hourly[-bars:]
    closes = [float(c.close) for c in window]
    rising = 1.0 if closes[-1] > closes[0] else 0.0
    green = sum(1 for c in window if float(c.close) > float(c.open)) / bars
    return _clamp(0.5 * rising + 0.5 * green)


def score(
    levels: Levels, daily: Sequence[Candle], hourly: Sequence[Candle],
) -> Momentum:
    """The weighted score, 0-100, with every component.

    With no hourly confirmation the hourly weight is DROPPED and the other
    four are renormalised to sum to one, then the result is capped at
    `HOURLY_MISSING_SCORE_CAP`. Scoring the missing component zero would be a
    penalty for our own data gap; leaving the weights alone would quietly
    score the token out of 85. The cap is what stops a half-seen token
    outranking a fully-seen one.
    """
    parts = {
        "volume": volume_component(daily, levels.volume_mean),
        "structure": structure_component(daily),
        "position": position_component(levels),
        "compression": compression_component(levels),
    }
    confirmation = hourly_component(hourly)
    weights = dict(config.MOMENTUM_WEIGHTS)

    if confirmation is None:
        weights.pop("hourly", None)
        total = sum(weights.values()) or 1.0
        raw = sum(parts[k] * w for k, w in weights.items()) / total
        value = min(round(100 * raw), config.HOURLY_MISSING_SCORE_CAP)
    else:
        parts["hourly"] = confirmation
        raw = sum(parts[k] * w for k, w in weights.items())
        value = round(100 * raw)

    return Momentum(
        score=int(max(0, min(100, value))),
        volume=parts["volume"],
        structure=parts["structure"],
        position=parts["position"],
        compression=parts["compression"],
        hourly=confirmation,
        hourly_missing=confirmation is None,
    )
