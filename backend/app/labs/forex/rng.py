"""A tiny seeded generator (SplitMix64) so research results are replayable.

The stdlib `random` module is banned in this package: its global state makes a
bootstrap or Monte-Carlo figure depend on whatever else ran first. An explicit
`Rng(seed)` makes every resampled number reproducible from the seed recorded
next to it.
"""

from __future__ import annotations

from typing import TypeVar

T = TypeVar("T")

_MASK = (1 << 64) - 1
_GAMMA = 0x9E3779B97F4A7C15
_MUL1 = 0xBF58476D1CE4E5B9
_MUL2 = 0x94D049BB133111EB
_TWO_POW_53 = float(1 << 53)


class Rng:
    """SplitMix64. Not cryptographic; deterministic and fast enough for 1e6 draws."""

    __slots__ = ("_state",)

    def __init__(self, seed: int) -> None:
        self._state = seed & _MASK

    def next_u64(self) -> int:
        self._state = (self._state + _GAMMA) & _MASK
        z = self._state
        z = ((z ^ (z >> 30)) * _MUL1) & _MASK
        z = ((z ^ (z >> 27)) * _MUL2) & _MASK
        return z ^ (z >> 31)

    def random(self) -> float:
        """Uniform in [0, 1) using the top 53 bits, so every value is exact."""
        return (self.next_u64() >> 11) / _TWO_POW_53

    def randrange(self, n: int) -> int:
        """Uniform in [0, n). Rejection sampling: a bare modulo would bias low values."""
        if n <= 0:
            raise ValueError("randrange_needs_positive_n")
        limit = (1 << 64) - ((1 << 64) % n)
        while True:
            x = self.next_u64()
            if x < limit:
                return x % n

    def shuffle(self, items: list[T]) -> None:
        """In-place Fisher-Yates."""
        for i in range(len(items) - 1, 0, -1):
            j = self.randrange(i + 1)
            items[i], items[j] = items[j], items[i]
