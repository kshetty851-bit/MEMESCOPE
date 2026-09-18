"""The harvest: every pump.fun graduation, read off the chain through Helius.

Four passes, each resumable and each writing only to the lab's SQLite file:

1. **graduations** — every successful migration, listed from the one account
   all of them touch (pump.fun's migration authority). No feed, no DexScreener:
   a graduation the chain recorded is one the lab has.
2. **tape** — each coin's full transaction history from its creation to
   `WINDOW_S` after the pool opened: every curve trade, every swap, every
   wallet's balance. Everything a strategy may know at its entry is in here.
3. **points** — the pool's exact state at each moment a backtest may buy or
   sell, one read per moment. The full 15 minutes would be 1,000 to 45,000
   transactions a coin (measured 2026-09-18); a price at 18 moments is 18 reads.
   The three entry moments are read FIRST, for every graduation: they are the
   depth screen, and a coin too shallow to trade at any of them stops there.
4. **funders** — who first paid SOL into each coin's creator and top holders.
   Operators make fresh wallets per coin and fund them from the same place.

Why Helius: `getTransactionsForAddress` returns full transactions, oldest first,
filtered by time, for 0.1 credit each. The Developer plan's 10M credits cover
~100M transactions; the binding limit is its 50 requests a second, not credits.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import sqlite3
import struct
import time
from collections import defaultdict
from collections.abc import AsyncIterator, Iterable, Iterator
from typing import Any

from app.core.config import settings
from app.core.logging import get_logger
from app.labs.graduation.sources import swap_reserves
from app.real_wallet_safety.sources import funder as first_funder
from app.security.liquidity import migration_pool_address, parse_pool
from app.services.curve.pda import b58encode, bonding_curve_address
from app.services.rpc.standard import StandardSolanaRPC
from app.services.scanner.parser import parse_pumpswap_pool_event
from app.services.scanner.trade_events import (
    BUY_EVENT_DISCRIMINATOR,
    SELL_EVENT_DISCRIMINATOR,
    TRADE_EVENT_DISCRIMINATOR,
)

logger = get_logger(__name__)

#: Every pump.fun migration names this account (its withdraw authority), and
#: little else does. Measured 2026-09-18: 48 real graduations in 88 minutes,
#: the rest failed or duplicate migrate calls, filtered by `status`.
MIGRATION_AUTHORITY = "39azUYFWPz3VHgKCf3VChUwbpURdCHRxjWVowf5jUJjg"
WSOL = "So11111111111111111111111111111111111111112"
PUMPFUN = settings.PUMPFUN_PROGRAM_ID

#: The tape runs this long past the pool's opening: the longest entry lag.
WINDOW_S = 45
#: A natural curve can hold 9,000+ trades; the first 1,000 from its creation
#: cover every instant graduation (3-60 transactions) and most natural ones.
PRE_CAP = 1_000
#: The busiest pools do 1,000 transactions in their first 30 seconds.
POST_CAP = 3_000
PAGE = 100

#: When a strategy may buy (seconds after the migration) and how long it holds.
#: 5s is a scanner reading the chain directly, 45s is today's live book, which
#: waits for DexScreener to index the pool.
ENTRY_LAGS = (5, 15, 45)
HOLDS = (60, 120, 180, 240, 300, 600)
#: A coin whose pool holds less than this at every entry moment is listed and
#: screened, nothing more (30 credits, not ~300). 250 SOL is ~$50k of depth at
#: $100 SOL: below BASE's $75k floor, so every book's population is inside it.
TRADEABLE_QUOTE = 250 * 10**9

#: Curve trades: mint 8, sol 40, tokens 48, is_buy 56, user 57, virtual SOL 97,
#: virtual tokens 105, fee bps 161, creator 177, creator fee bps 209. Offsets up
#: to 89 are the scanner's (verified 2026-08-22); the rest were checked on
#: 2026-09-18 against a graduation's curve (vSOL 115.005 = 30 + 85.005 bought,
#: vTokens 279.9M = the curve floor, fees 95 + 30 bps = pump.fun's 1.25%).
_CURVE_MIN_LEN = 217
#: Swaps: base 16, pool reserves BEFORE it 48/56, quote 64, lp fee bps 72,
#: protocol fee bps 88, pool 120, user 152, creator fee bps 344.
_SWAP_MIN_LEN = 352


def _u64(data: bytes, at: int) -> int:
    return int(struct.unpack_from("<Q", data, at)[0])


def program_data(logs: Iterable[str] | None) -> Iterator[bytes]:
    for line in logs or ():
        if line.startswith("Program data: "):
            try:
                yield base64.b64decode(line[14:], validate=True)
            except (ValueError, binascii.Error):
                continue


def parse(tx: dict[str, Any], *, mint: str, pool: str
          ) -> tuple[list[tuple[Any, ...]], list[tuple[Any, ...]], str | None]:
    """One transaction of a coin's tape as (trade rows, balance rows, creator).

    Trades come from the programs' own event logs. The pool's state after the
    transaction comes from its vault balances, which a truncated log cannot
    lose — so a swap whose event is missing still leaves a row, side '?'.
    """
    slot, idx, t = tx["slot"], tx.get("transactionIndex", 0), tx["blockTime"]
    meta = tx.get("meta") or {}
    after = swap_reserves(tx, mint=mint, pool=pool)
    rows: list[tuple[Any, ...]] = []
    creator = None
    for data in program_data(meta.get("logMessages")):
        head = data[:8]
        if (head == TRADE_EVENT_DISCRIMINATOR and len(data) >= _CURVE_MIN_LEN
                and b58encode(data[8:40]) == mint):
            creator = b58encode(data[177:209])
            rows.append(("curve", "buy" if data[56] else "sell", b58encode(data[57:89]),
                         _u64(data, 48), _u64(data, 40),
                         _u64(data, 161) + _u64(data, 209), _u64(data, 105), _u64(data, 97)))
        elif (head in (BUY_EVENT_DISCRIMINATOR, SELL_EVENT_DISCRIMINATOR)
                and len(data) >= _SWAP_MIN_LEN and b58encode(data[120:152]) == pool):
            fee = _u64(data, 72) + _u64(data, 88) + _u64(data, 344)
            rows.append(("pool", "buy" if head == BUY_EVENT_DISCRIMINATOR else "sell",
                         b58encode(data[152:184]), _u64(data, 16), _u64(data, 64), fee,
                         *(after or (None, None))))
    if after and not any(r[0] == "pool" for r in rows):
        rows.append(("pool", "?", None, None, None, None, *after))
    trades = [(mint, slot, idx, n, t, *r) for n, r in enumerate(rows)]

    held: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for side, key in ((0, "preTokenBalances"), (1, "postTokenBalances")):
        for b in meta.get(key) or []:
            if b.get("mint") == mint and b.get("owner"):
                held[b["owner"]][side] += int(b["uiTokenAmount"]["amount"])
    balances = [(mint, slot, idx, owner, t, post)
                for owner, (pre, post) in held.items() if pre != post]
    return trades, balances, creator


def migration(tx: dict[str, Any]) -> dict[str, Any] | None:
    """A migration transaction as a `grads` row, or None if it made no pool."""
    meta = tx.get("meta") or {}
    event = parse_pumpswap_pool_event(meta.get("logMessages") or [])
    if event is None:
        return None
    mint = event.mint_address
    pool, _ = migration_pool_address(mint, pumpfun_program=PUMPFUN)
    vaults = swap_reserves(tx, mint=mint, pool=pool)
    message = (tx.get("transaction") or {}).get("message") or {}
    keys = message.get("accountKeys") or []
    first = keys[0] if keys else ""
    payer = first["pubkey"] if isinstance(first, dict) else first
    return {"mint": mint, "pool": pool, "t0": tx["blockTime"], "slot": tx["slot"],
            "idx": tx.get("transactionIndex", 0),
            "sig": (tx.get("transaction") or {}).get("signatures", [""])[0],
            "migrator": payer, "base0": vaults[0] if vaults else None,
            "quote0": vaults[1] if vaults else None}


class Helius:
    """Helius JSON-RPC under the plan's rate limit, with a credit tally.

    The retries, 429 handling and URL redaction are the platform's own
    (`StandardSolanaRPC.call`); this adds the pacing a month-long harvest needs
    and counts credits the way Helius meters them (2026-09-18 price list).
    """

    def __init__(self, url: str, *, rps: float = 40.0, concurrency: int = 16) -> None:
        self.rpc = StandardSolanaRPC(rpc_url=url)
        self._sem = asyncio.Semaphore(concurrency)
        self._gap = 1.0 / rps
        self._next = 0.0
        self.calls = 0
        self.credits = 0

    async def __aenter__(self) -> Helius:
        await self.rpc.start()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.rpc.close()

    async def call(self, method: str, params: Any, *, attempts: int = 6) -> Any:
        async with self._sem:
            now = time.monotonic()
            wait, self._next = self._next - now, max(now, self._next) + self._gap
            if wait > 0:
                await asyncio.sleep(wait)
            result = await self.rpc.call(method, params, attempts=attempts)
        self.calls += 1
        if method == "getTransactionsForAddress":
            full = (params[1] or {}).get("transactionDetails") == "full"
            n = len((result or {}).get("data") or [])
            self.credits += max(10, -(-n // 100) * 10) if full else 10
        else:
            self.credits += 1
        return result

    async def history(self, address: str, *, t_from: int | None = None,
                      t_to: int | None = None, desc: bool = False, cap: int | None = None,
                      limit: int = PAGE, only: dict[str, Any] | None = None
                      ) -> AsyncIterator[dict[str, Any]]:
        """Successful transactions naming `address`, page by page, oldest first
        unless `desc`, stopping after `cap`. `only` adds Helius filters."""
        span: dict[str, int] = {}
        if t_from is not None:
            span["gte"] = t_from
        if t_to is not None:
            span["lte"] = t_to
        filters: dict[str, Any] = {"status": "succeeded", **(only or {})}
        if span:
            filters["blockTime"] = span
        token, seen = None, 0
        while True:
            opts: dict[str, Any] = {
                "transactionDetails": "full", "encoding": "json",
                "maxSupportedTransactionVersion": 1, "limit": limit,
                "sortOrder": "desc" if desc else "asc", "filters": filters}
            if token:
                opts["paginationToken"] = token
            page = await self.call("getTransactionsForAddress", [address, opts]) or {}
            for tx in page.get("data") or []:
                yield tx
                seen += 1
                if cap is not None and seen >= cap:
                    return
            token = page.get("paginationToken")
            if not token or not page.get("data"):
                return


# --- passes -------------------------------------------------------------------

async def graduations(h: Helius, db: sqlite3.Connection, *, t_from: int, t_to: int) -> int:
    """List every migration in [t_from, t_to]. Idempotent: re-listing a span
    that is already stored adds nothing."""
    added = 0
    async for tx in h.history(MIGRATION_AUTHORITY, t_from=t_from, t_to=t_to):
        row = migration(tx)
        if row is None:
            continue
        cur = db.execute(
            "INSERT OR IGNORE INTO grads (mint,pool,t0,slot,idx,sig,migrator,base0,quote0) "
            "VALUES (:mint,:pool,:t0,:slot,:idx,:sig,:migrator,:base0,:quote0)", row)
        added += cur.rowcount
    db.commit()
    return added


async def tape(h: Helius, db: sqlite3.Connection, mint: str, pool: str, t0: int) -> None:
    """A coin's history from its creation to `WINDOW_S` after the migration."""
    trades: list[tuple[Any, ...]] = []
    balances: list[tuple[Any, ...]] = []
    creator = None
    pre = post = 0
    last_t = t0
    async for tx in h.history(mint, t_to=t0 - 1, cap=PRE_CAP):
        tr, bal, who = parse(tx, mint=mint, pool=pool)
        trades += tr
        balances += bal
        creator = creator or who
        pre += 1
    async for tx in h.history(mint, t_from=t0, t_to=t0 + WINDOW_S, cap=POST_CAP):
        tr, bal, who = parse(tx, mint=mint, pool=pool)
        trades += tr
        balances += bal
        creator = creator or who
        post += 1
        last_t = tx["blockTime"]
    # Capped mid-window: only whole seconds before the last one are complete.
    end = last_t - 1 if post >= POST_CAP else t0 + WINDOW_S
    db.executemany("INSERT OR IGNORE INTO trades VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", trades)
    db.executemany("INSERT OR IGNORE INTO balances VALUES (?,?,?,?,?,?)", balances)
    db.execute("UPDATE grads SET tape='ok', creator=?, pre_txs=?, post_txs=?, tape_end=? "
               "WHERE mint=?", (creator, pre, post, end, mint))
    db.commit()


def _fee(tx: dict[str, Any], pool: str) -> int | None:
    fees = [(_u64(d, 72) + _u64(d, 88) + _u64(d, 344))
            for d in program_data((tx.get("meta") or {}).get("logMessages"))
            if d[:8] in (BUY_EVENT_DISCRIMINATOR, SELL_EVENT_DISCRIMINATOR)
            and len(d) >= _SWAP_MIN_LEN and b58encode(d[120:152]) == pool]
    fees = [f for f in fees if f]
    return fees[-1] if fees else None


async def point(h: Helius, mint: str, pool: str, at: int) -> tuple[Any, ...]:
    """The pool after its last swap at or before `at`: what a trade then met."""
    async for tx in h.history(pool, t_to=at, desc=True, cap=20, limit=5):
        found = swap_reserves(tx, mint=mint, pool=pool)
        if found is not None:
            return (mint, at, tx["blockTime"], found[0], found[1], _fee(tx, pool))
    return (mint, at, None, None, None, None)


def exit_times(t0: int) -> list[int]:
    return sorted({t0 + lag + hold for lag in ENTRY_LAGS for hold in HOLDS})


async def read_points(h: Helius, db: sqlite3.Connection, mint: str, pool: str,
                      times: Iterable[int]) -> list[tuple[Any, ...]]:
    rows = await asyncio.gather(*(point(h, mint, pool, at) for at in times))
    db.executemany("INSERT OR REPLACE INTO points VALUES (?,?,?,?,?,?)", rows)
    db.commit()
    return rows


def holders_at(db: sqlite3.Connection, mint: str, pool: str, t: int) -> list[tuple[str, int]]:
    """Wallets holding the coin at second `t`, biggest first, leaving out the
    curve and the pool. Exact within the tape: every balance a transaction
    that names the mint changed. (A plain SPL `Transfer` does not name the
    mint and is missed until that wallet's next transaction that does.)"""
    skip = {pool, bonding_curve_address(mint, program_id=PUMPFUN)}
    latest: dict[str, int] = {}
    for owner, amount in db.execute(
            "SELECT owner, amount FROM balances WHERE mint=? AND t<=? ORDER BY slot, idx",
            (mint, t)):
        latest[owner] = amount
    return sorted(((o, a) for o, a in latest.items() if a > 0 and o not in skip),
                  key=lambda r: -r[1])


def key_wallets(db: sqlite3.Connection, mint: str, pool: str, t0: int,
                creator: str | None, top: int = 3) -> list[str]:
    """The creator and the biggest holders 15s after the pool opened."""
    wallets = [o for o, _ in holders_at(db, mint, pool, t0 + 15)[:top]]
    if creator and creator not in wallets:
        wallets.append(creator)
    return wallets


async def funders(h: Helius, db: sqlite3.Connection, wallets: list[str]) -> None:
    todo = [w for w in wallets
            if not db.execute("SELECT 1 FROM funders WHERE wallet=?", (w,)).fetchone()]
    found = await asyncio.gather(*(first_funder(h, w) for w in todo))
    now = int(time.time())
    db.executemany("INSERT OR REPLACE INTO funders VALUES (?,?,?)",
                   [(w, f, now) for w, f in zip(todo, found, strict=True)])


#: The operator watch: wallets holding >= 1% at the entry second, followed
#: through the base trade's 4-minute hold. A move is the first transaction that
#: leaves one under 99% of its bag; the exit it triggers is read 2s later (a
#: websocket sees the move in ~1s, a sell lands in ~1-2s) and 5s later.
WATCH_ENTRY, WATCH_HOLD = 15, 240
WATCH_CAP = 500
REACTIONS = (2, 5)
BIG = 10**13  # 1% of a pump.fun supply, raw


async def first_move(h: Helius, mint: str, wallet: str, held: int, t_from: int,
                     t_to: int) -> tuple[int | None, int | None, bool]:
    """(when, balance after) of `wallet`'s first drop under 99% of `held`,
    and whether the watch ran out of pages before finding one.

    Asks Helius only for transactions moving this coin out of the wallet. A
    creator wallet is named by every swap on its pool, so some answers leave
    its balance untouched; only a transaction that shows the wallet's own
    balance of the coin counts."""
    seen = 0
    async for tx in h.history(wallet, t_from=t_from, t_to=t_to, cap=WATCH_CAP,
                              only={"tokenTransfer": {"mint": mint, "direction": "out"}}):
        seen += 1
        meta = tx.get("meta") or {}
        mine = [(key, b) for key in ("preTokenBalances", "postTokenBalances")
                for b in meta.get(key) or []
                if b.get("owner") == wallet and b.get("mint") == mint]
        if not mine:
            continue
        after = sum(int(b["uiTokenAmount"]["amount"]) for key, b in mine
                    if key == "postTokenBalances")
        if after < held * 0.99:
            return tx["blockTime"], after, False
    return None, None, seen >= WATCH_CAP


async def watch(h: Helius, db: sqlite3.Connection, mint: str, pool: str, t0: int) -> None:
    entry = t0 + WATCH_ENTRY
    ops = [(o, a) for o, a in holders_at(db, mint, pool, entry) if a >= BIG]
    found = await asyncio.gather(*(first_move(h, mint, o, a, entry + 1, entry + WATCH_HOLD)
                                   for o, a in ops))
    db.executemany("INSERT OR REPLACE INTO moves VALUES (?,?,?,?,?,?)",
                   [(mint, o, a, t, after, int(capped))
                    for (o, a), (t, after, capped) in zip(ops, found, strict=True)])
    first = min((t for t, _, _ in found if t is not None), default=None)
    if first is not None:
        await read_points(h, db, mint, pool, [first + r for r in REACTIONS])
    db.commit()


async def watch_all(h: Helius, db: sqlite3.Connection, *, t_from: int, t_to: int,
                    workers: int = 8) -> dict[str, Any]:
    """The watch pass over every harvested coin deep enough at 15s to trade."""
    todo = db.execute(
        "SELECT g.mint, g.pool, g.t0 FROM grads g JOIN points p "
        "ON p.mint=g.mint AND p.at=g.t0+? WHERE g.t0 BETWEEN ? AND ? AND g.tape='ok' "
        "AND p.res_quote >= ? AND NOT EXISTS (SELECT 1 FROM moves m WHERE m.mint=g.mint) "
        "ORDER BY g.t0", (WATCH_ENTRY, t_from, t_to, TRADEABLE_QUOTE)).fetchall()
    queue: asyncio.Queue[tuple[Any, ...]] = asyncio.Queue()
    for row in todo:
        queue.put_nowait(row)
    failed = 0

    async def worker() -> None:
        nonlocal failed
        while not queue.empty():
            mint, pool, t0 = queue.get_nowait()
            try:
                await watch(h, db, mint, pool, t0)
            except Exception as exc:  # one coin never stops the run
                failed += 1
                logger.warning("tape_watch_failed", mint=mint, error=str(exc)[:200])

    started = time.monotonic()
    await asyncio.gather(*(worker() for _ in range(workers)))
    return {"watched": len(todo) - failed, "failed": failed, "calls": h.calls,
            "credits": h.credits, "seconds": round(time.monotonic() - started)}


async def pool_virtual_quotes(h: Helius, db: sqlite3.Connection) -> int:
    """Each pool's virtual quote, off its account: 100 pools a call."""
    pools = [p for (p,) in db.execute("SELECT pool FROM grads WHERE vq IS NULL")]
    done = 0
    for i in range(0, len(pools), 100):
        chunk = pools[i:i + 100]
        res = await h.call("getMultipleAccounts", [chunk, {"encoding": "base64"}]) or {}
        for pool, acct in zip(chunk, res.get("value") or [], strict=False):
            state = parse_pool(base64.b64decode(acct["data"][0])) if acct else None
            if state is not None:
                db.execute("UPDATE grads SET vq=? WHERE pool=?", (state.virtual_quote, pool))
                done += 1
    db.commit()
    return done


async def harvest(h: Helius, db: sqlite3.Connection, *, t_from: int, t_to: int,
                  workers: int = 8, min_quote0: int = 50 * 10**9) -> dict[str, Any]:
    """Every pass over [t_from, t_to], resuming wherever the last run stopped.

    Stops 15 minutes short of now: a point read for a moment still in the
    future would return today's pool and call it the past."""
    t_to = min(t_to, int(time.time()) - 900)
    if t_to <= t_from:  # a span that has not happened yet: Helius errors on it
        return {"listed": 0, "harvested": 0, "failed": 0, "calls": 0, "credits": 0}
    listed = await graduations(h, db, t_from=t_from, t_to=t_to)
    todo = db.execute(
        "SELECT mint, pool, t0, creator, tape, tape_end, points, funders FROM grads "
        "WHERE t0 BETWEEN ? AND ? AND quote0 >= ? AND "
        "(tape IS NULL OR points IS NULL OR funders IS NULL) ORDER BY t0",
        (t_from, t_to, min_quote0)).fetchall()
    queue: asyncio.Queue[tuple[Any, ...]] = asyncio.Queue()
    for row in todo:
        queue.put_nowait(row)
    failed = 0

    async def one(row: tuple[Any, ...]) -> None:
        mint, pool, t0, creator, tape_state, _, points_state, funders_state = row
        if points_state is None:
            entries = await read_points(h, db, mint, pool, (t0 + lag for lag in ENTRY_LAGS))
            if max((r[4] or 0) for r in entries) < TRADEABLE_QUOTE:
                db.execute("UPDATE grads SET points='screened', tape='skip', funders='skip' "
                           "WHERE mint=?", (mint,))
                db.commit()
                return
            await read_points(h, db, mint, pool, exit_times(t0))
            db.execute("UPDATE grads SET points='ok' WHERE mint=?", (mint,))
            db.commit()
        if tape_state != "ok":
            await tape(h, db, mint, pool, t0)
            (creator,) = db.execute(
                "SELECT creator FROM grads WHERE mint=?", (mint,)).fetchone()
        if funders_state is None:
            await funders(h, db, key_wallets(db, mint, pool, t0, creator))
            db.execute("UPDATE grads SET funders='ok' WHERE mint=?", (mint,))
            db.commit()

    async def worker() -> None:
        nonlocal failed
        while not queue.empty():
            row = queue.get_nowait()
            try:
                await one(row)
            except Exception as exc:  # one coin never stops the run
                failed += 1
                db.execute("UPDATE grads SET tape=? WHERE mint=? AND tape IS NULL",
                           (f"error:{type(exc).__name__}", row[0]))
                db.commit()
                logger.warning("tape_harvest_failed", mint=row[0], error=str(exc)[:200])

    started = time.monotonic()
    await asyncio.gather(*(worker() for _ in range(workers)))
    vq = await pool_virtual_quotes(h, db)
    return {"listed": listed, "harvested": len(todo) - failed, "failed": failed,
            "virtual_quotes": vq, "calls": h.calls, "credits": h.credits,
            "seconds": round(time.monotonic() - started)}
