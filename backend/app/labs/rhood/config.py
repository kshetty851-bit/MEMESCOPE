"""What the Robinhood Chain recorder reads, and how often.

Every number here is a COLLECTION choice, not a strategy one. There are no
floors, holds or entry rules in this module on purpose: the graduation lab's
thresholds were measured on pump.fun, and assuming they transfer to a different
chain with different fees, pool sizes and operators is the mistake this whole
lab exists to avoid making twice.
"""

from __future__ import annotations

import os


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "") or default)
    except ValueError:
        return default


def _flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    return default if raw is None else raw.strip().lower() in {"1", "true", "yes", "on"}


#: OFF until the recorder has been watched running. It writes to its own two
#: tables and nothing else reads them, so switching it on cannot reach a book.
ENABLED = _flag("LAB_RHOOD_ENABLED", False)

#: Chain 4663, an Arbitrum-stack L2. Blocks are ~0.1s, so a minute is ~600
#: blocks and a lookback in blocks is a lookback in seconds divided by ten.
RPC_URL = os.getenv("LAB_RHOOD_RPC_URL", "https://rpc.mainnet.chain.robinhood.com")
CHAIN_ID = 4663
#: DexScreener's name for this chain, verified against a live response.
DEX_CHAIN = "robinhood"

#: The pool factory. Found by asking a live Robinhood Chain pair who made it
#: (`factory()`), after the LOCKER turned out to be the wrong signal entirely:
#: watched live on 2026-09-23 it fired for the same TWO established tokens
#: every five minutes, their pairs 54 and 66 days old. Re-locks, not launches.
#:
#: This factory emits Uniswap V3 `PoolCreated` about six times an hour
#: (~144/day), each one a token meeting WETH in a pool for the first time —
#: which is what a graduation is on this chain.
FACTORY = "0x1f7d7550b1b028f7571e69a784071f0205fd2efa"
#: PoolCreated(address indexed token0, address indexed token1, uint24 indexed
#: fee, int24 tickSpacing, address pool).
POOL_CREATED_TOPIC = (
    "0x783cca1c0412dd0d695e784568c96da2e9c22ff989357a2e8b1d9b2b4e6b7118")
#: The quote side of every pool seen. The OTHER token in the event is the coin.
WETH = "0x0bd7d308f8e1639fab988df18a8011f41eacad73"

#: How far back each pass looks. 12,000 blocks is about 20 minutes, so a pass
#: that fails for a quarter of an hour still catches up rather than leaving a
#: hole in the record.
LOOKBACK_BLOCKS = _int("LAB_RHOOD_LOOKBACK_BLOCKS", 12_000)
#: Tokens re-priced per pass, newest first. DexScreener punishes bursts, so
#: this is deliberately small.
SAMPLE_PER_PASS = _int("LAB_RHOOD_SAMPLE_PER_PASS", 40)
#: How long a token keeps being sampled after its lock. One hour at a minute a
#: pass is enough to see a coin live or die.
SAMPLE_WINDOW_MINUTES = _int("LAB_RHOOD_SAMPLE_WINDOW_MINUTES", 60)
HTTP_TIMEOUT_S = _int("LAB_RHOOD_HTTP_TIMEOUT_S", 20)
