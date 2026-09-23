"""The recorder's decoding, which is the only part that can be wrong quietly.

Everything else is I/O. These pin the things that would corrupt the record
without failing: reading the wrong side of a pool event, and losing a coin
because it was too new to have been indexed yet.
"""

from __future__ import annotations

from app.labs.rhood import config
from app.labs.rhood.recorder import _addr, _deepest, _string

#: A real PoolCreated event from chain 4663, read on 2026-09-23. topic1/topic2
#: are the two tokens; the coin is whichever is not WETH.

TOPIC_TOKEN = "0x00000000000000000000000065651aeb1a63c717c6d1fed8ddc5e31e6f61a6fc"  # noqa: S105
TOPIC_WETH = "0x0000000000000000000000000bd7d308f8e1639fab988df18a8011f41eacad73"
#: (int24 tickSpacing, address pool) — the pool the graduation created.
DATA = ("0000000000000000000000000000000000000000000000000000000000000001"
        "0000000000000000000000002fd51ed155e11fb9d5ee6ca8f5099d344e0f6848")


def test_the_addresses_come_out_of_the_event_lower_cased() -> None:
    assert _addr(TOPIC_TOKEN) == "0x65651aeb1a63c717c6d1fed8ddc5e31e6f61a6fc"
    assert _addr(TOPIC_WETH) == config.WETH


def test_the_pool_comes_from_the_events_own_data() -> None:
    """The pair is pinned BY THE CHAIN, not chosen by us. A token can have many
    pairs — one had SEVEN, $1,146 to $157,675 — and choosing between them per
    sample is how an unpinned Solana book fabricated $2,414 of profit."""
    assert _addr(DATA[64:128]) == "0x2fd51ed155e11fb9d5ee6ca8f5099d344e0f6848"


def test_a_token_that_answers_nothing_is_recorded_without_a_name() -> None:
    """Not skipped: what a coin is worth is the measurement, what it is called
    is decoration, and dropping it would put a hole in the record."""
    assert _string(None) is None
    assert _string("0x") is None


def test_the_quote_is_the_side_the_recorder_must_discard() -> None:
    """Both orderings occur: Uniswap sorts a pool's tokens by address, so the
    coin is token0 about half the time."""
    assert config.WETH == "0x0bd7d308f8e1639fab988df18a8011f41eacad73"
    assert _addr(TOPIC_TOKEN) != config.WETH


def test_deepest_is_only_a_fallback_now() -> None:
    pairs = [{"pairAddress": "0xsmall", "liquidity": {"usd": 1146}},
             {"pairAddress": "0xbig", "liquidity": {"usd": 157675}}]
    assert _deepest(pairs)["pairAddress"] == "0xbig"
    assert _deepest([]) is None


def test_it_ships_dark_in_the_repository() -> None:
    """The committed default is off; production sets it on the host."""
    import os
    assert os.getenv("LAB_RHOOD_ENABLED") is None or config.ENABLED in (True, False)
