"""Candle construction for the engine tests.

Every path here is built from candles small enough that the engine's two
intra-candle orderings coincide — a 5-pip candle cannot reach a second trigger,
so `open→low→high→close` and `open→high→low→close` land in the same place and
the expected values below are a single hand calculation rather than a pair.
The tests assert that coincidence rather than assuming it: `test_paths_agree`
re-runs each fixture with the orderings forced apart.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

PIP = 0.0001


def walk(
    start: float,
    end: float,
    step_pips: float = 5.0,
    t0: datetime | None = None,
    minutes: int = 1,
) -> list[tuple]:
    """Candles marching from `start` to `end` in `step_pips` increments.

    No wicks: each candle's high and low are its own open and close. Returned as
    (minute, mid_open, mid_high, mid_low, mid_close), which is the shape
    `GridEngine.step` takes.
    """
    t = t0 or datetime(2023, 1, 3, 10, 0, tzinfo=UTC)
    d = step_pips * PIP * (1 if end > start else -1)
    n = round(abs(end - start) / (step_pips * PIP))
    out = []
    cur = start
    for _ in range(n):
        nxt = round(cur + d, 7)
        out.append((t, round(cur, 7), round(max(cur, nxt), 7), round(min(cur, nxt), 7), nxt))
        cur = nxt
        t += timedelta(minutes=minutes)
    return out


def run(engine, candles) -> None:
    for minute, o, h, lo, c in candles:
        engine.step(minute, o, h, lo, c)


def cents(x: float) -> float:
    return round(x, 2)
