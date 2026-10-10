"""Deterministic synthetic EUR/USD candles for the lab's pipeline and API tests.

A seeded mean-reverting walk with slow drifting regimes, so every strategy sees
trends, pullbacks and band excursions and produces trades. It uses the lab's own
`Rng`, so the same arguments give the same candles on every machine - the tests
that compare two runs rely on that.

Weekend-closed minutes are skipped (the lab's model: Friday 21:00 to Sunday
22:00 UTC), so the series has the shape of a real feed.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

from app.labs.forex.data import resample
from app.labs.forex.rng import Rng
from app.labs.forex.sessions import is_weekend_closed
from app.labs.forex.types import Candle, Timeframe

START = datetime(2024, 3, 4, tzinfo=UTC)  # a Monday


def synthetic_m1(days: int, *, start: datetime = START, seed: int = 5) -> list[Candle]:
    rng = Rng(seed)
    price = 1.0850
    anchor = price
    out: list[Candle] = []
    t = start
    end = start + timedelta(days=days)
    while t < end:
        if not is_weekend_closed(t):
            drift = 0.00002 * math.sin(t.timestamp() / 86_400 * 2.1)
            pull = (anchor - price) * 0.002
            step = (rng.random() - 0.5) * 0.00024 + drift + pull
            o = price
            c = round(o + step, 5)
            wick_hi = rng.random() * 0.00006
            wick_lo = rng.random() * 0.00006
            out.append(
                Candle(
                    t,
                    round(o, 5),
                    round(max(o, c) + wick_hi, 5),
                    round(min(o, c) - wick_lo, 5),
                    c,
                    float(10 + int(rng.random() * 90)),
                )
            )
            price = c
            anchor += 0.0000008 * math.sin(t.timestamp() / 86_400 * 0.35)
        t += timedelta(minutes=1)
    return out


def synthetic(days: int, timeframe: Timeframe, *, seed: int = 5) -> list[Candle]:
    m1 = synthetic_m1(days, seed=seed)
    if timeframe is Timeframe.M1:
        return m1
    return list(resample(m1, Timeframe.M1, timeframe).candles)
