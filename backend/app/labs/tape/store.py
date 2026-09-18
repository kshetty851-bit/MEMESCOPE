"""The lab's own SQLite file: what was harvested, kept after the Helius plan ends.

SQLite and not the platform's Postgres, on purpose. A month of pump.fun tapes is
millions of rows, and prod is a 3.8 GB host whose disk already sits at 85%; the
harvest and the study both run on a laptop. The file lives OUTSIDE the repo
(`TAPE_DB`, default `~/memescope-tape/tape.db`) — the repo is public and already
carries untracked bulk data nobody meant to commit.

Units are the chain's: token amounts raw (6 decimals), SOL in lamports, times in
unix seconds (`blockTime`), and (slot, idx) is a transaction's position in the
ledger. `idx` is Helius's `transactionIndex`, so two transactions in the same
second still sort in the order they executed.
"""

from __future__ import annotations

import os
import pathlib
import sqlite3

DEFAULT_PATH = pathlib.Path.home() / "memescope-tape" / "tape.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS grads (
    mint      TEXT PRIMARY KEY,
    pool      TEXT NOT NULL,
    t0        INTEGER NOT NULL,     -- the migration's blockTime
    slot      INTEGER NOT NULL,
    idx       INTEGER NOT NULL,
    sig       TEXT NOT NULL,
    migrator  TEXT NOT NULL,        -- who paid for the migration
    base0     INTEGER,              -- pool vaults right after it
    quote0    INTEGER,
    vq        INTEGER,              -- the pool's virtual quote, off its account
    creator   TEXT,                 -- the coin's creator, off its curve trades
    tape      TEXT,                 -- NULL | ok | error:...
    pre_txs   INTEGER,              -- curve-side transactions kept (capped)
    post_txs  INTEGER,              -- transactions from t0 to tape_end
    tape_end  INTEGER,              -- the tape is complete up to this second
    points    TEXT,
    funders   TEXT
);
CREATE INDEX IF NOT EXISTS grads_t0 ON grads (t0);

-- Every pump.fun curve trade and PumpSwap swap in a coin's tape, one row per
-- event. res_* is the state AFTER the transaction: the pool's two vaults for
-- a swap (vault quote only; add grads.vq to price it), the curve's virtual
-- reserves for a curve trade. A swap whose logs were truncated still leaves a
-- row, side '?', so the pool's state is never missing.
CREATE TABLE IF NOT EXISTS trades (
    mint      TEXT NOT NULL,
    slot      INTEGER NOT NULL,
    idx       INTEGER NOT NULL,
    ev        INTEGER NOT NULL,
    t         INTEGER NOT NULL,
    venue     TEXT NOT NULL,        -- curve | pool
    side      TEXT NOT NULL,        -- buy | sell | ?
    user      TEXT,
    base      INTEGER,
    quote     INTEGER,
    fee_bps   INTEGER,
    res_base  INTEGER,
    res_quote INTEGER,
    PRIMARY KEY (mint, slot, idx, ev)
);

-- A wallet's balance of the coin after each transaction that changed it.
CREATE TABLE IF NOT EXISTS balances (
    mint   TEXT NOT NULL,
    slot   INTEGER NOT NULL,
    idx    INTEGER NOT NULL,
    owner  TEXT NOT NULL,
    t      INTEGER NOT NULL,
    amount INTEGER NOT NULL,
    PRIMARY KEY (mint, slot, idx, owner)
);

-- What a trade at `at` would have met: the pool after its last swap at or
-- before `at`. Read one moment at a time, past the tape's window.
CREATE TABLE IF NOT EXISTS points (
    mint      TEXT NOT NULL,
    at        INTEGER NOT NULL,
    t         INTEGER,
    res_base  INTEGER,
    res_quote INTEGER,
    fee_bps   INTEGER,
    PRIMARY KEY (mint, at)
);

-- Each wallet holding >= 1% at the 15s entry, watched through the 4-minute
-- hold: the first transaction that left it under 99% of that bag. t NULL = it
-- never moved; capped = the watch ran out of pages first (treat as unknown).
CREATE TABLE IF NOT EXISTS moves (
    mint   TEXT NOT NULL,
    wallet TEXT NOT NULL,
    held   INTEGER NOT NULL,
    t      INTEGER,
    after  INTEGER,
    capped INTEGER NOT NULL,
    PRIMARY KEY (mint, wallet)
);

-- Who first paid SOL into a wallet. funder NULL = traced, nothing found.
CREATE TABLE IF NOT EXISTS funders (
    wallet    TEXT PRIMARY KEY,
    funder    TEXT,
    traced_at INTEGER NOT NULL
);
"""


def connect(path: str | os.PathLike[str] | None = None) -> sqlite3.Connection:
    target = pathlib.Path(path or os.environ.get("TAPE_DB") or DEFAULT_PATH)
    target.parent.mkdir(parents=True, exist_ok=True)
    # A harvest and a watch may write at once; wait for the other's commit
    # instead of failing a coin on "database is locked".
    db = sqlite3.connect(target, timeout=120)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=NORMAL")
    db.executescript(SCHEMA)
    return db
