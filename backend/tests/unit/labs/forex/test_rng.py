"""The research generator must be reproducible and unbiased.

Every bootstrap and Monte-Carlo figure is quoted with its seed; that only
means something if the same seed always yields the same numbers.
"""

from __future__ import annotations

import pytest

from app.labs.forex.rng import Rng

pytestmark = pytest.mark.unit


def test_splitmix64_reference_vector() -> None:
    """Seed 0 reproduces the published SplitMix64 outputs, so the algorithm is
    the standard one and not a look-alike that happens to be deterministic."""
    r = Rng(0)
    assert r.next_u64() == 0xE220A8397B1DCDAF
    assert r.next_u64() == 0x6E789E6AA1B965F4
    assert r.next_u64() == 0x06C45D188009454F


def test_same_seed_same_sequence_different_seed_differs() -> None:
    """Replayability: results quoted with a seed can be regenerated exactly."""
    a, b, c = Rng(42), Rng(42), Rng(43)
    seq_a = [a.next_u64() for _ in range(5)]
    assert seq_a == [b.next_u64() for _ in range(5)]
    assert seq_a != [c.next_u64() for _ in range(5)]


def test_random_is_in_unit_interval() -> None:
    """A value of exactly 1.0 would index one past the end of a list."""
    r = Rng(1)
    xs = [r.random() for _ in range(5000)]
    assert all(0.0 <= x < 1.0 for x in xs)
    assert 0.45 < sum(xs) / len(xs) < 0.55


def test_randrange_bounds_and_coverage() -> None:
    """Every bucket is reachable and none is out of range."""
    r = Rng(5)
    seen = {r.randrange(7) for _ in range(500)}
    assert seen == set(range(7))


def test_randrange_is_roughly_uniform() -> None:
    """No bucket is starved: a biased modulo would skew small remainders."""
    r = Rng(9)
    counts = [0] * 5
    for _ in range(10_000):
        counts[r.randrange(5)] += 1
    assert all(1700 < c < 2300 for c in counts)


def test_randrange_rejects_non_positive() -> None:
    with pytest.raises(ValueError):
        Rng(1).randrange(0)


def test_negative_seed_is_accepted_and_deterministic() -> None:
    """Seeds are masked to 64 bits rather than raising."""
    assert Rng(-1).next_u64() == Rng(-1).next_u64()


def test_shuffle_is_a_permutation_and_deterministic() -> None:
    """A shuffle must never add or drop an element (it would change a trade list)."""
    base = list(range(20))
    a, b = list(base), list(base)
    Rng(3).shuffle(a)
    Rng(3).shuffle(b)
    assert a == b
    assert sorted(a) == base
    assert a != base


def test_shuffle_handles_tiny_lists() -> None:
    empty: list[int] = []
    one = [1]
    Rng(1).shuffle(empty)
    Rng(1).shuffle(one)
    assert empty == [] and one == [1]


def test_shuffle_reaches_every_arrangement_of_three() -> None:
    """Fisher-Yates over 3 items must produce all 6 orders."""
    r = Rng(11)
    seen: set[tuple[int, ...]] = set()
    for _ in range(300):
        xs = [0, 1, 2]
        r.shuffle(xs)
        seen.add(tuple(xs))
    assert len(seen) == 6
