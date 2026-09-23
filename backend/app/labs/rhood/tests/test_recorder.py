"""The recorder's decoding, which is the only part that can be wrong quietly.

Everything else is I/O. These pin the two things that would corrupt the record
without failing: reading the wrong address out of an event, and re-choosing a
token's pair between samples.
"""

from __future__ import annotations

from app.labs.rhood import config
from app.labs.rhood.recorder import _addr, _deepest, _string

#: A real locker event, read from chain 4663 on 2026-09-23. topic1 resolved to
#: the token (symbol INJOH) and the first data word to WETH.
TOPIC1 = "0x0000000000000000000000002cc0fac44b8252f6b10208b091aff2c94b4da77d"
WORD0 = "0000000000000000000000000bd7d308f8e1639fab988df18a8011f41eacad73"


def test_the_token_comes_out_of_the_event_lower_cased() -> None:
    assert _addr(TOPIC1) == "0x2cc0fac44b8252f6b10208b091aff2c94b4da77d"
    assert _addr(WORD0) == "0x0bd7d308f8e1639fab988df18a8011f41eacad73"


def test_a_token_that_answers_nothing_is_recorded_without_a_name() -> None:
    """Not skipped: what a coin is worth is the measurement, what it is called
    is decoration, and dropping it would put a hole in the record."""
    assert _string(None) is None
    assert _string("0x") is None


def test_the_deepest_pair_is_the_one_pinned() -> None:
    """One token had SEVEN pairs, $1,146 to $157,675. Choosing per sample is
    how a Solana book once fabricated $2,414 of profit out of pair switching."""
    pairs = [{"pairAddress": "0xsmall", "liquidity": {"usd": 1146}},
             {"pairAddress": "0xbig", "liquidity": {"usd": 157675}},
             {"pairAddress": "0xnone"}]
    assert _deepest(pairs)["pairAddress"] == "0xbig"
    assert _deepest([]) is None


def test_it_ships_dark() -> None:
    """Off until someone sets the flag, and the task returns without touching
    the chain when it is off."""
    assert config.ENABLED is False
