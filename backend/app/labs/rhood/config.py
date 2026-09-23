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

#: The Pons LOCKER. Both factory addresses in the public docs returned zero
#: logs over 5.6 hours of blocks on 2026-09-23; this one fires ~13 times per
#: 34 minutes. WHAT THOSE EVENTS MEAN IS NOT YET ESTABLISHED — the first one
#: sampled resolved to a token whose main pair was five months old, so they are
#: not all graduations. Establishing that is the recorder's first job.
LOCKER = "0x736D76699C26D0d966744cAe304C000d471f7F35"
#: The only event the locker emits, seen 13/13 times.
LOCK_TOPIC = "0x1547f2bd1a244399782ebde22047e2ede698ecdc4d6c7d4b3c4e2435f1e47f7a"

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
