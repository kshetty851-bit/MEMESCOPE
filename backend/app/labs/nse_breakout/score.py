"""Levels + bars -> a 0-100 readiness score. Pure; no session, no clock.

Five components, each clamped to `[0, 1]`, combined with `SCORE_WEIGHTS`. The
score says "coiled under a real level with participation". It does **not** say
the breakout will happen — the episode table exists to find that out, and
Phase 2 records rather than believes.

Every component is returned beside the score so the decile table in `/stats`
can ask which of the five, if any, actually predicted anything.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from app.labs.nse_breakout import config
from app.labs.nse_breakout.levels import Bar, Levels


@dataclass(frozen=True, slots=True)
class Score:
    score: int
    proximity: float
    compression: float
    trend: float
    volume: float
    touches: float

    def components(self) -> dict[str, float]:
        return {"proximity": round(self.proximity, 4),
                "compression": round(self.compression, 4),
                "trend": round(self.trend, 4),
                "volume": round(self.volume, 4),
                "touches": round(self.touches, 4)}


def _clamp(value: float) -> float:
    return 0.0 if value < 0 else 1.0 if value > 1 else value


def proximity_component(levels: Levels) -> float:
    """1.0 sitting on the level, 0.0 at `WATCH_PCT` below it or further.

    None resistance scores zero rather than one: a stock with nothing above it
    is not ready to break out, it has already broken out of everything.
    """
    distance = levels.distance_pct
    if distance is None or distance < 0:
        return 0.0
    return _clamp(1 - distance / config.WATCH_PCT)


def compression_component(levels: Levels) -> float:
    """A 20-day range at or below `TIGHT_RANGE_PCT` scores 1, twice that 0."""
    span = levels.range_pct
    if span is None:
        return 0.0
    return _clamp(2 - span / config.TIGHT_RANGE_PCT)


def trend_component(bars: Sequence[Bar], levels: Levels) -> float:
    """Above a rising 50-day mean.

    Half the component is "price above the mean", half is "the mean is rising"
    — measured over the same 50 days, so a stock that spiked once and died does
    not keep the mark. Together they say the stock is being accumulated rather
    than falling into a level from above.
    """
    days = config.SCORE_TREND_DAYS
    if len(bars) < 2 * days:
        return 0.0
    closes = [float(b.close) for b in bars]
    mean_now = sum(closes[-days:]) / days
    mean_then = sum(closes[-2 * days:-days]) / days
    if mean_now <= 0 or mean_then <= 0:
        return 0.0
    above = _clamp((levels.close / mean_now - 1) / 0.10)
    rising = _clamp((mean_now / mean_then - 1) / 0.10)
    return 0.5 * above + 0.5 * rising


def volume_component(bars: Sequence[Bar], levels: Levels) -> float:
    """Recent volume against the 20-day mean, saturating at `SCORE_VOLUME_CAP`.

    Volume BEFORE the break is the component that would distinguish a coil
    somebody is accumulating from one nobody has noticed. Whether it does is
    what the decile table is for.
    """
    mean = levels.volume_mean
    if not mean or mean <= 0:
        return 0.0
    recent = [float(b.volume) for b in bars[-config.SCORE_VOLUME_DAYS:]
              if b.volume is not None]
    if not recent:
        return 0.0
    ratio = (sum(recent) / len(recent)) / mean
    return _clamp((ratio - 1) / (config.SCORE_VOLUME_CAP - 1))


def touches_component(levels: Levels) -> float:
    """How many times the nearest level has been tested, capped at four.

    A level touched once is a high; touched four times it is a price people
    trade against, and clearing it means something.
    """
    if levels.nearest_resistance is None:
        return 0.0
    touches = next((c.touches for c in levels.clusters
                    if c.level == levels.nearest_resistance), 0)
    return _clamp((touches - 1) / (config.SCORE_TOUCH_CAP - 1))


def compute(bars: Sequence[Bar], levels: Levels) -> Score:
    """The score for one symbol on its last closed bar."""
    parts = {
        "proximity": proximity_component(levels),
        "compression": compression_component(levels),
        "trend": trend_component(bars, levels),
        "volume": volume_component(bars, levels),
        "touches": touches_component(levels),
    }
    total = sum(parts[name] * weight for name, weight in config.SCORE_WEIGHTS.items())
    return Score(score=round(total * 100), **parts)
