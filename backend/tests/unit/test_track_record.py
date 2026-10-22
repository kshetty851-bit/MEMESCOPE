"""The track record's day summary: multiples measured, feed glitches left out."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.track_record import service

pytestmark = pytest.mark.unit
T = datetime(2026, 10, 21, 12, tzinfo=UTC)


def coin(mint: str, prices: list[float]) -> tuple:
    return (mint, T, mint.upper(), None, [60.0 * i for i in range(len(prices))], prices, 50_000.0)


def test_a_day_counts_multiples_and_ranks_the_best() -> None:
    day = service.summarise([
        coin("ten", [1, 3, 10, 10, 2]),    # 10x held two samples from minute 2, ends 2x
        coin("rug", [1, 1.2, 1.2, 0.05]),  # 1.2x, ends -95%
        coin("flat", [1, 1.05, 1.0]),
        coin("glitch", [1, 40, 1]),        # a 40x jump is the feed changing pools
        coin("blip", [1, 9, 1, 1]),        # one print at 9x is not a price
        (*coin("dead", [1, 5, 5])[:6], 9.0),  # a $9 pool's multiples mean nothing
    ])
    assert (day["graduated"], day["measured"]) == (6, 4)
    assert day["reached"]["1.1"] == 2 and day["reached"]["10"] == 1 and day["reached"]["5"] == 1
    assert day["ended_down_80"] == 1
    best = day["top"][0]
    assert (best["mint"], best["peak_x"], best["peak_after_min"], best["end_x"]) == ("ten", 10.0, 2.0, 2.0)
