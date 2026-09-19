"""Everything outside this process: the websocket, the RPC node, the two market APIs.

The only module in the package allowed to know a network exists.
`tests/test_isolation.py` holds that the pure modules never import it, and
everything here is injectable so the tests replay recorded payloads and never
open a socket.

## Three sources, three reasons

* `PumpPortalStream` — **discovery only**. `subscribeNewToken` for candidates
  and `subscribeMigration` for graduation timestamps. Both free. There is no
  `subscribeTokenTrade` anywhere in this package: it is metered at 0.01 SOL per
  10,000 events, and the chain reports the same curve state for nothing.
* `CurveRPC` — `getMultipleAccounts` over derived PDAs. One call per 100
  tokens, which is what makes polling the whole watch set affordable.
* `MarketSource` — DexScreener for post-graduation pair data, GeckoTerminal
  for backfilling a poll that was missed.

## One websocket connection, always

PumpPortal's documentation is unusually blunt: "PLEASE ONLY USE ONE WEBSOCKET
CONNECTION AT A TIME", and clients that open many at once "may be timed out".
Both subscriptions share this one socket, and a reconnect re-sends both — a
reconnect drops every subscription server-side, and a stream that did not
re-subscribe would keep reading healthy while silently receiving nothing.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
from dataclasses import dataclass, replace
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from types import TracebackType
from typing import Any, Self

import httpx
import websockets

from app.core.backoff import BackoffPolicy
from app.core.config import settings
from app.core.logging import get_logger
from app.labs.graduation import config, held_watch, curve
from app.security.liquidity import parse_pool
from app.services.curve.pda import InvalidAddressError, bonding_curve_address
from app.services.curve.state import CurveState
from app.services.market.providers.rate_budget import CallBudget

logger = get_logger(__name__)

#: Free, and the only two methods this lab subscribes to.
_SUBSCRIPTIONS = ("subscribeNewToken", "subscribeMigration")

DEX = "dexscreener"
GECKO = "geckoterminal"
_RETRY_STATUSES = frozenset({429})


def chunked(items: Sequence[str], size: int) -> list[list[str]]:
    return [list(items[i:i + size]) for i in range(0, len(items), size)]


class PumpPortalStream:
    """The two free subscriptions, over one socket, reconnecting for ever."""

    def __init__(
        self,
        *,
        url: str | None = None,
        connect: Callable[..., Any] = websockets.connect,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        backoff: BackoffPolicy | None = None,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._url = url or config.PUMPPORTAL_WS_URL
        self._connect = connect
        self._sleep = sleep
        self._backoff = backoff or BackoffPolicy(
            initial_seconds=config.RECONNECT_INITIAL_SECONDS,
            max_seconds=config.RECONNECT_MAX_SECONDS,
        )
        self._now = now
        self._stop = asyncio.Event()

        self.connected = False
        self.reconnects = 0
        self.messages_received = 0
        self.last_message_at: datetime | None = None
        self.last_failure: str | None = None

    @property
    def url(self) -> str:
        """No API key, no query string. Both subscriptions are free."""
        return self._url

    def stop(self) -> None:
        self._stop.set()

    async def messages(self) -> AsyncIterator[dict]:
        """Every decoded message, reconnecting for ever until `stop()`.

        A socket that has sent nothing for `STREAM_IDLE_TIMEOUT_SECONDS` is
        redialled: the launch stream alone carries ~25 messages a minute, so
        silence is a fault, and a half-open TCP connection reads exactly like a
        quiet one.
        """
        attempt = 0
        while not self._stop.is_set():
            try:
                async with self._connect(
                    self.url,
                    ping_interval=config.WS_PING_INTERVAL_SECONDS,
                    ping_timeout=config.WS_PING_INTERVAL_SECONDS,
                    close_timeout=5,
                ) as ws:
                    self.connected = True
                    attempt = 0
                    self.last_failure = None
                    for method in _SUBSCRIPTIONS:
                        await ws.send(json.dumps({"method": method}))
                    async for message in self._consume(ws):
                        yield message
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if self._stop.is_set():
                    break
                attempt += 1
                self.reconnects += 1
                self.last_failure = f"{type(exc).__name__}: {exc}"
                delay = self._backoff.delay_for(attempt)
                logger.warning("graduation_reconnect", attempt=attempt,
                               delay_seconds=round(delay, 2), error=repr(exc))
                await self._sleep(delay)
            finally:
                self.connected = False

    async def _consume(self, ws: Any) -> AsyncIterator[dict]:
        while not self._stop.is_set():
            raw = await asyncio.wait_for(
                ws.recv(), timeout=config.STREAM_IDLE_TIMEOUT_SECONDS)
            self.messages_received += 1
            self.last_message_at = self._now()
            try:
                message = json.loads(raw)
            except (ValueError, TypeError):
                logger.warning("graduation_undecodable_message")
                continue
            if isinstance(message, dict):
                yield message


class CurveRPC:
    """Bonding curve accounts, by derived address, in batches of a hundred.

    The address is DERIVED rather than looked up, which is what makes the whole
    watch set one call per hundred tokens instead of one call per token — and,
    it turns out, is also the only correct way to get it. The launch feed's own
    `bondingCurveKey` sent one identical address for three unrelated mints in a
    15-launch sample, and that address holds a zero-length System Program
    account. Derivation is `app/services/curve/pda`, checked against the feed
    where the feed happens to be right.
    """

    def __init__(
        self,
        *,
        rpc: Any = None,
        budget: CallBudget | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        program_id: str | None = None,
    ) -> None:
        self._rpc = rpc
        self._owns_rpc = rpc is None
        self._budget = budget or CallBudget(config.RPC_CALLS_PER_MINUTE, 60.0)
        self._sleep = sleep
        self._program_id = program_id or config.PUMP_PROGRAM_ID
        #: mint -> derived PDA. Derivation is ~255 SHA-256 rounds worst case,
        #: so it is done once per mint and not once per poll.
        self._addresses: dict[str, str] = {}

        self.calls = 0
        self.failures = 0
        self.rate_limited = 0
        self.last_failure: str | None = None

    async def __aenter__(self) -> Self:
        if self._rpc is None:
            from app.services.rpc.standard import StandardSolanaRPC

            self._rpc = StandardSolanaRPC(rpc_url=config.rpc_url())
            await self._rpc.start()
            self._owns_rpc = True
        return self

    async def __aexit__(self, exc_type: type[BaseException] | None,
                        exc: BaseException | None, tb: TracebackType | None) -> None:
        if self._owns_rpc and self._rpc is not None:
            await self._rpc.close()
            self._rpc = None

    def address_for(self, mint: str) -> str | None:
        """The curve PDA for a mint, or None when the mint is not base58.

        Cached: the derivation is pure, so the answer never changes, and a
        watch set of 500 re-derived every 15 seconds would be pure waste.
        """
        if mint in self._addresses:
            return self._addresses[mint]
        try:
            address = bonding_curve_address(mint, program_id=self._program_id)
        except (InvalidAddressError, ValueError) as exc:
            logger.warning("graduation_bad_mint", mint=mint, error=repr(exc))
            return None
        self._addresses[mint] = address
        return address

    def forget(self, mints: Iterable[str]) -> None:
        """Drop cached addresses for mints that have left the watch set, so the
        cache cannot outgrow the set it serves."""
        for mint in mints:
            self._addresses.pop(mint, None)

    async def fetch(self, mints: Sequence[str]) -> dict[str, CurveState | None]:
        """Read every mint's curve. Missing from the result = the read failed.

        A mint mapped to `None` means the account does not exist or did not
        decode; a mint ABSENT from the returned dict means this pass could not
        read it. The two are kept apart for the reason
        `get_multiple_accounts` raises rather than truncating: a caller must be
        able to tell "no curve" from "no answer".
        """
        out: dict[str, CurveState | None] = {}
        addressed = [(m, a) for m in mints if (a := self.address_for(m))]
        size = config.MAX_ACCOUNTS_PER_CALL
        # The window is taken by INDEX, never by how many results have already
        # accumulated. Deriving it from `len(out)` is what broke this before: a
        # single failed batch left `out` short, so every later window started
        # in the wrong place and each mint was paired with ANOTHER TOKEN'S
        # account. Nothing raised — the rows looked like real curves, because
        # they were real curves belonging to somebody else.
        for start in range(0, len(addressed), size):
            window = addressed[start:start + size]
            if not await self._acquire():
                logger.warning("graduation_rpc_budget_exhausted",
                               pending=len(window))
                self.rate_limited += 1
                break
            try:
                values = await self._rpc.get_multiple_accounts(
                    [a for _, a in window])
                self.calls += 1
            except Exception as exc:
                self.failures += 1
                self.last_failure = f"{type(exc).__name__}: {exc}"
                logger.warning("graduation_rpc_failed", size=len(window),
                               error=repr(exc))
                continue
            if len(values) != len(window):
                # Positional pairing is only sound when the lengths match.
                # Refuse the whole window rather than attribute some of it
                # wrongly: a gap is recoverable, a wrong reading is not.
                self.failures += 1
                self.last_failure = (
                    f"getMultipleAccounts returned {len(values)} for "
                    f"{len(window)} addresses")
                logger.error("graduation_rpc_length_mismatch",
                             asked=len(window), got=len(values))
                continue
            for (mint, _), value in zip(window, values, strict=True):
                out[mint] = _decode_account(value)
        return out

    async def _acquire(self) -> bool:
        """Wait for the token bucket, up to `RPC_ACQUIRE_TIMEOUT_SECONDS`.

        Blocking here rather than skipping: unlike a supplementary market
        provider, a missed curve read is a hole in the only series this lab
        has, and the next poll is `POLL_INTERVAL_S` away.
        """
        waited = 0.0
        while not self._budget.try_acquire(1):
            if waited >= config.RPC_ACQUIRE_TIMEOUT_SECONDS:
                return False
            await self._sleep(0.5)
            waited += 0.5
        return True

    async def holders(self, mint: str) -> "Holders | None":
        """One mint's holder concentration, through the same budget as the rest.

        Charged against `_acquire` like every other read here: a collector that
        quietly spends outside the rate budget is how a free-tier key gets
        revoked mid-experiment.
        """
        if self._rpc is None:
            return None
        if not await self._acquire():
            logger.warning("graduation_holders_budget_exhausted", mint=mint)
            self.rate_limited += 1
            return None
        got = await top_holders(self._rpc, mint)
        self.calls += 1
        if got is None:
            self.failures += 1
        return got




@dataclass(frozen=True, slots=True)
class Holders:
    """Who holds a mint, at the moment it was asked.

    Shares are of TOTAL SUPPLY and include the AMM pool, which after a
    graduation is normally the largest single account. `top_address` is kept so
    the analysis can identify and subtract it later: storing a
    pool-excluded figure now would bake in an interpretation before there is
    any evidence about which interpretation matters.
    """

    top1_share: Decimal
    top10_share: Decimal
    top_address: str
    seen: int


async def top_holders(rpc: StandardSolanaRPC, mint: str) -> Holders | None:
    """The concentration of a mint's supply, from two RPC reads.

    `getTokenLargestAccounts` returns at most twenty accounts, which is enough
    for a top-10 share and is one call. Supply comes from the mint account
    rather than from summing those twenty — the twenty are not the whole float,
    and a denominator built from them would make every token look concentrated.

    Returns None on any failure, never a partial figure: a share computed from
    a short read is a number about nothing.
    """
    try:
        supply = await rpc.get_token_supply(mint)
        if supply is None or supply <= 0:
            return None
        payload = await rpc.call("getTokenLargestAccounts", [mint])
    except Exception as exc:
        logger.warning("graduation_holders_failed", mint=mint, error=repr(exc))
        return None
    rows = (payload or {}).get("value") or []
    amounts: list[tuple[Decimal, str]] = []
    for row in rows:
        raw = row.get("uiAmountString") or row.get("uiAmount")
        if raw in (None, ""):
            continue
        try:
            amounts.append((Decimal(str(raw)), str(row.get("address") or "")))
        except (ArithmeticError, ValueError):
            continue
    if not amounts:
        return None
    amounts.sort(key=lambda a: a[0], reverse=True)
    top1, addr = amounts[0]
    top10 = sum(a for a, _ in amounts[:10])
    return Holders(top1_share=(top1 / supply), top10_share=(top10 / supply),
                   top_address=addr, seen=len(amounts))


def _decode_account(value: dict | None) -> CurveState | None:
    """One `getMultipleAccounts` entry -> a curve, or None."""
    if not isinstance(value, dict):
        return None
    data = value.get("data")
    if not isinstance(data, list) or not data:
        return None
    try:
        raw = base64.b64decode(data[0], validate=True)
    except (binascii.Error, ValueError):
        return None
    return curve.decode(raw)


class MarketSource:
    """DexScreener pairs, and GeckoTerminal minute candles for the gaps.

    A 429 honours `Retry-After` as a FLOOR, never a ceiling: GeckoTerminal
    answers with `Retry-After: 0` and then refuses for about thirty-five
    seconds, so taking that header literally retries four times inside a
    millisecond and gives up while the host is still angry.
    """

    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        budgets: dict[str, CallBudget] | None = None,
        backoff: BackoffPolicy | None = None,
    ) -> None:
        self._client = client
        self._owns_client = client is None
        self._sleep = sleep
        self._budgets = budgets or {
            DEX: CallBudget(config.DEXSCREENER_CALLS_PER_MINUTE, 60.0),
            GECKO: CallBudget(config.GECKOTERMINAL_CALLS_PER_MINUTE, 60.0),
        }
        self._backoff = backoff or BackoffPolicy(initial_seconds=1.0, max_seconds=30.0)
        self.requests: dict[str, int] = {DEX: 0, GECKO: 0}
        self.failures = 0

    async def __aenter__(self) -> Self:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(config.HTTP_TIMEOUT_SECONDS),
                headers={"accept": "application/json"},
            )
            self._owns_client = True
        return self

    async def __aexit__(self, exc_type: type[BaseException] | None,
                        exc: BaseException | None, tb: TracebackType | None) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _get(self, url: str, params: dict[str, Any] | None, *,
                   host: str) -> Any:
        if self._client is None:
            raise RuntimeError("MarketSource used outside `async with`")
        bucket = self._budgets[host]
        for attempt in range(1, config.HTTP_MAX_ATTEMPTS + 1):
            while not bucket.try_acquire(1):
                await self._sleep(0.5)
            response = await self._client.get(url, params=params)
            self.requests[host] += 1
            if response.status_code in _RETRY_STATUSES or response.status_code >= 500:
                delay = max(_retry_after(response), self._backoff.delay_for(attempt))
                logger.warning("graduation_http_retry", host=host,
                               status=response.status_code, attempt=attempt,
                               delay_seconds=round(delay, 2))
                await self._sleep(min(delay, 60.0))
                continue
            response.raise_for_status()
            return response.json()
        raise RuntimeError(f"graduation: gave up on {url}")

    async def dex_pairs(self, mints: Sequence[str]) -> list[dict[str, Any]]:
        """Pairs for up to `DEXSCREENER_BATCH` mints in one call.

        Batched by mint rather than polled per pair: a graduation hour holds
        roughly thirty tokens, so the whole post-graduation population is one
        or two calls a minute instead of thirty.
        """
        if not mints:
            return []
        joined = ",".join(mints[:config.DEXSCREENER_BATCH])
        try:
            body = await self._get(
                f"{config.DEXSCREENER_URL}/tokens/v1/{config.NETWORK}/{joined}",
                None, host=DEX)
        except Exception as exc:
            self.failures += 1
            logger.warning("graduation_dexscreener_failed", mints=len(mints),
                           error=repr(exc))
            return []
        return [p for p in (body or []) if isinstance(p, dict)]

    async def gecko_minute_ohlcv(self, pool: str, *, limit: int) -> list[list[Any]]:
        """Minute candles for one POOL, newest first, for backfilling a gap.

        Addresses a pool and not a mint, which is the whole constraint on this
        fallback: the pool address comes from a DexScreener response, so a
        token whose every DexScreener poll failed can never be backfilled.
        """
        try:
            body = await self._get(
                f"{config.GECKOTERMINAL_URL}/networks/{config.NETWORK}"
                f"/pools/{pool}/ohlcv/minute",
                {"limit": limit, "currency": "usd"}, host=GECKO)
        except Exception as exc:
            self.failures += 1
            logger.warning("graduation_geckoterminal_failed", pool=pool,
                           error=repr(exc))
            return []
        candles = (((body or {}).get("data") or {}).get("attributes") or {}) \
            .get("ohlcv_list")
        return [c for c in (candles or []) if isinstance(c, list) and len(c) >= 6]


def _retry_after(response: httpx.Response) -> float:
    raw = response.headers.get("retry-after")
    try:
        return float(raw) if raw is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


#: Tries at a pool read before a candidate waits for the next tick.
POOL_READ_ATTEMPTS = 3


async def pool_now(mint: str, pool: str) -> held_watch.Held | None:
    """A pool's own price and depth this moment, off its two vaults.

    What a paper buy is priced at. DexScreener's first report on a new pool can
    predate the pool's first big buy, and a book that buys at it books a jump
    that never happened. None when the pool cannot be read or decoded: the
    caller does not buy on a guess, and asks again next tick.

    Read on Helius. The public node refused a third of these reads on
    2026-09-18 even one at a time, and the lab's own node is spent on the curve
    poll; Helius is paid for and this is a handful of reads a minute. Asked up
    to `POOL_READ_ATTEMPTS` times, since a refused read costs the entry a tick.
    """
    stream = HeldVaultStream(
        url=settings.HELIUS_RPC_URL if settings.helius_configured else None)
    for attempt in range(POOL_READ_ATTEMPTS):
        try:
            held = await stream.resolve(mint, pool)
        except ConnectionError:
            await asyncio.sleep(0.4 * (attempt + 1))
            continue
        if held is None:
            return None
        await stream._read([held])
        if held.price() is not None:
            return held
        await asyncio.sleep(0.4 * (attempt + 1))
    return None


def swap_reserves(tx: dict[str, Any], *, mint: str, pool: str) -> tuple[int, int] | None:
    """(token, SOL) the pool held after this transaction, off its own balance
    records, or None when the transaction left neither in them."""
    base = quote = None
    for b in (tx.get("meta") or {}).get("postTokenBalances") or []:
        if b.get("owner") != pool:
            continue
        if b.get("mint") == mint:
            base = int(b["uiTokenAmount"]["amount"])
        elif b.get("mint") == config.WSOL_MINT:
            quote = int(b["uiTokenAmount"]["amount"])
    return None if base is None or quote is None else (base, quote)


async def reserves_at(rpc: Any, *, mint: str, pool: str, at: datetime,
                      pages: int = 3) -> tuple[int, int] | None:
    """The pool's reserves after its last swap at or before `at`: what a trade
    at that moment would have met. Newest first through Helius's own history
    call, stopping at the first transaction that recorded both balances."""
    token = None
    for _ in range(pages):
        opts: dict[str, Any] = {
            "transactionDetails": "full", "encoding": "jsonParsed",
            "maxSupportedTransactionVersion": 1, "sortOrder": "desc", "limit": 20,
            "filters": {"blockTime": {"lte": int(at.timestamp())}, "status": "succeeded"}}
        if token:
            opts["paginationToken"] = token
        page = await rpc.call("getTransactionsForAddress", [pool, opts]) or {}
        for tx in page.get("data") or []:
            if (found := swap_reserves(tx, mint=mint, pool=pool)) is not None:
                return found
        token = page.get("paginationToken")
        if not token:
            return None
    return None



async def reserves_after(rpc: Any, *, mint: str, pool: str, at: datetime,
                         within_s: int, pages: int = 3) -> tuple[int, int] | None:
    """The pool's reserves after its FIRST swap at or after `at`, within
    `within_s`: the book's own exit rule (the first mark at or after the exit
    was due), read off the swaps. A drain that lands seconds after a sell was
    due is booked as the loss it would most likely have been. None when the
    pool did not trade in that window - its state then is `reserves_at(at)`."""
    start = int(at.timestamp())
    token = None
    for _ in range(pages):
        opts: dict[str, Any] = {
            "transactionDetails": "full", "encoding": "jsonParsed",
            "maxSupportedTransactionVersion": 1, "sortOrder": "asc", "limit": 20,
            "filters": {"blockTime": {"gte": start, "lte": start + within_s},
                        "status": "succeeded"}}
        if token:
            opts["paginationToken"] = token
        page = await rpc.call("getTransactionsForAddress", [pool, opts]) or {}
        for tx in page.get("data") or []:
            if (found := swap_reserves(tx, mint=mint, pool=pool)) is not None:
                return found
        token = page.get("paginationToken")
        if not token:
            return None
    return None

#: Pages of 25 of a wallet's oldest transactions searched for its funding.
FUNDING_PAGES = 2
#: Seconds one operator read may take before the arm treats the coin as a
#: stranger; it runs inside a tick with a three-second cadence.
OPERATOR_READ_TIMEOUT_S = 6.0
#: The operator is read at the latest confirmed block. The RPC default,
#: finalized, trails it by ~13 s, and an instant graduation is read 5-8 s after
#: its launch: finalized has no such mint yet ("could not find account"), which
#: emptied 54 of the first 124 live reads (18-19 Sep 2026), every one of them
#: read under 8 s after the migration.
CONFIRMED = {"commitment": "confirmed"}
#: Even at confirmed, a mint seconds old reaches the holder index a few seconds
#: late ("not a Token mint" at +5.5 s, readable at +8 s, probed live 19 Sep),
#: so a read that early is asked again at this pause until the timeout.
OPERATOR_RETRY_PAUSE_S = 1.0


def _account_keys(tx: dict[str, Any]) -> list[str]:
    keys = ((tx.get("transaction") or {}).get("message") or {}).get("accountKeys") or []
    return [k["pubkey"] if isinstance(k, dict) else k for k in keys]


async def funder(rpc: Any, wallet: str) -> str | None:
    """Who paid SOL into `wallet` the first time it got any: the account whose
    balance fell most in that transaction. None when its oldest transactions
    never paid it.

    The real wallet's source block uses the same rule
    (`app.real_wallet_safety.sources.funding`); it is restated here because
    this lab may not import the wallet's code (`tests/test_isolation.py`).
    """
    token: str | None = None
    for _ in range(FUNDING_PAGES):
        opts: dict[str, Any] = {
            "transactionDetails": "full", "encoding": "jsonParsed",
            "maxSupportedTransactionVersion": 1, "sortOrder": "asc", "limit": 25,
            "filters": {"status": "succeeded"}}
        if token:
            opts["paginationToken"] = token
        page = await rpc.call("getTransactionsForAddress", [wallet, opts]) or {}
        for tx in page.get("data") or []:
            keys = _account_keys(tx)
            meta = tx.get("meta") or {}
            pre, post = meta.get("preBalances") or [], meta.get("postBalances") or []
            if wallet not in keys:
                continue
            i = keys.index(wallet)
            if i >= len(post) or i >= len(pre) or post[i] <= pre[i]:
                continue
            span = range(min(len(keys), len(pre), len(post)))
            paid = [(pre[j] - post[j], keys[j]) for j in span if j != i and pre[j] > post[j]]
            if paid:
                return max(paid)[1]
        token = page.get("paginationToken")
        if not token:
            break
    return None


async def operator_ids(rpc: Any, mint: str, pool: str) -> frozenset[str] | None:
    """The operator behind a coin right now: every wallet holding
    `OPERATOR_MIN_SHARE` of its supply, and whoever first funded each.

    None when the holders cannot be read — never a partial answer, which would
    make a known operator look like a stranger with a clean record. The pool
    and the bonding curve hold tokens too and are not anyone's wallet.
    """
    supply = Decimal(str((((await rpc.call("getTokenSupply", [mint, CONFIRMED])) or {})
                          .get("value") or {}).get("uiAmountString") or 0))
    if not supply:
        return None
    largest = ((await rpc.call("getTokenLargestAccounts", [mint, CONFIRMED]))
               or {}).get("value")
    if largest is None:
        return None
    share = lambda row: Decimal(str(row.get("uiAmountString") or 0)) / supply  # noqa: E731
    big = [row["address"] for row in largest if share(row) >= config.OPERATOR_MIN_SHARE]
    if not big:
        return frozenset()
    accounts = ((await rpc.call("getMultipleAccounts",
                                [big, {"encoding": "jsonParsed", **CONFIRMED}]))
                or {}).get("value") or []
    if len(accounts) != len(big):
        return None
    owners = {((a.get("data") or {}).get("parsed") or {}).get("info", {}).get("owner")
              for a in accounts if isinstance(a, dict)}
    curve = bonding_curve_address(mint, program_id=config.PUMP_PROGRAM_ID)
    owners = {o for o in owners if o and o not in {pool, curve}}
    funders = await asyncio.gather(*(funder(rpc, o) for o in owners))
    return frozenset(owners | {f for f in funders if f})


async def operator_ids_when_visible(rpc: Any, mint: str, pool: str, *,
                                    pause_s: float = OPERATOR_RETRY_PAUSE_S
                                    ) -> frozenset[str] | None:
    """`operator_ids`, asked again while the chain does not know the mint yet.
    Never ends on its own: the caller's timeout does."""
    from app.services.rpc.standard import RpcError

    while True:
        try:
            return await operator_ids(rpc, mint, pool)
        except RpcError:
            await asyncio.sleep(pause_s)


async def operators_now(mint: str, pool: str) -> frozenset[str] | None:
    """`operator_ids` on Helius, bounded in time. `getTransactionsForAddress`
    exists nowhere else, and the public node refuses `getTokenLargestAccounts`."""
    if not settings.helius_configured:
        return None
    from app.services.rpc.standard import StandardSolanaRPC

    rpc = StandardSolanaRPC(rpc_url=settings.HELIUS_RPC_URL)
    await rpc.start()
    try:
        return await asyncio.wait_for(operator_ids_when_visible(rpc, mint, pool),
                                      timeout=OPERATOR_READ_TIMEOUT_S)
    except Exception as exc:  # a stranger, not a crash: the tick goes on
        logger.info("graduation_operator_unread", mint=mint, error=type(exc).__name__)
        return None
    finally:
        await rpc.close()


class HeldVaultStream:
    """Sub-second prices for the positions actually open.

    In `sources.py` because this package allows exactly one module to know a
    network exists, and that rule is worth more than the convenience of
    keeping this beside its decoding. The decoding lives in `held_watch.py`,
    which stays pure.

    WHY IT EXISTS. Collapses here are cascades — median 247 sells of about
    $159, where $352 is needed to move price 10% — falling 1.14% a SECOND. So
    reaction time is the whole result:

        reaction   0.6s    3s    18s    27s    61s
        FLOOR_5m  $1040  $949   $342     $0     $0

    DexScreener refreshes about every 27 seconds (measured: on a pool taking
    1,512 sells in five minutes only 11% of 3-second polls returned a new
    price), which is past the cliff. `accountSubscribe` on the pool's two
    vaults gave 44 updates in 25 seconds on that same pool and needs NO KEY —
    Helius refuses the socket while its quota is spent, so the public node is
    not the compromise, it is the thing that works.
    """

    def __init__(
        self,
        *,
        url: str | None = None,
        connect: Callable[..., Any] = websockets.connect,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._url = url or config.SOLANA_WS_URL
        self._connect = connect
        self._now = now
        self.updates = 0

    async def _call(self, method: str, params: list[Any]) -> Any:
        """One JSON-RPC call against the same public node as the socket.

        Not the lab's RPC client: that carries the Helius key, which is spent.
        """
        body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        url = self._url.replace("wss://", "https://")
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                got = (await client.post(url, json=body)).json()
        except Exception as exc:
            logger.warning("graduation_held_rpc_failed", method=method,
                           error=repr(exc))
            return None
        return got.get("result") if isinstance(got, dict) else None

    async def accounts(self, addresses: Sequence[str], *,
                       commitment: str = "processed") -> tuple[int, list[bytes | None]]:
        """Accounts in the order asked, and the slot they were read at.

        PROCESSED by default, as the socket uses: a finalized read is seconds
        behind it. A failed read is slot 0 and no data, never a partial list.
        """
        got = await self._call("getMultipleAccounts", [
            list(addresses), {"encoding": "base64", "commitment": commitment}])
        values = (got or {}).get("value")
        slot = ((got or {}).get("context") or {}).get("slot")
        if (not isinstance(values, list) or len(values) != len(addresses)
                or not isinstance(slot, int)):
            return 0, [None] * len(addresses)
        return slot, [held_watch.account_bytes(v) for v in values]

    async def resolve(self, mint: str, pool: str) -> held_watch.Held | None:
        """The watchable form of one position's pool, or nothing.

        Two calls, once per token: the caller caches the answer, including a
        None for a venue `parse_pool` does not decode. A node that did not
        answer RAISES instead — cached as "unwatchable", one dropped request
        would leave a position on minute-old marks for its whole life.
        """
        slot, (raw,) = await self.accounts([pool], commitment="confirmed")
        if not slot or raw is None:
            # No account yet is not "not a pool": a pool seconds old can be
            # missing from the node that answered. Asked again next pass.
            raise ConnectionError(f"pool {pool} unread")
        state = parse_pool(raw)
        if state is None:
            return None
        slot, accounts = await self.accounts(
            [state.base_mint, state.quote_mint, state.base_vault, state.quote_vault,
             state.lp_mint],
            commitment="confirmed")
        # The LP mint only answers the lock rule: unread, it leaves the pool
        # priceable and not proven locked.
        if not slot or any(a is None for a in accounts[:4]):
            raise ConnectionError(f"accounts of pool {pool} unread")
        held = held_watch.watch(mint, pool, state, accounts[:4])
        if held is not None:
            held.lp_supply = held_watch.mint_supply(accounts[4])
        return held

    async def pool_from_migration(self, mint: str, signature: str) -> str | None:
        """The pumpswap pool a graduation created, read off its own transaction.

        The migration feed names the venue, not the pool, and deriving the pool
        address matched DexScreener's pair for 0 of 146 recent graduations;
        the transaction's accounts matched 10 of 10 (2026-09-16). Raises when
        the node did not answer — a transaction too new to read, or a 429 —
        so the caller asks again. None only for a migration that FAILED, which
        created nothing and never will.

        A confirmed migration with no pool in sight also raises. The first live
        dry run found no pool for both of its graduations, read seconds after
        the event; the same lookup found both minutes later. The node that
        answered had the transaction and not yet the account it created.
        """
        tx = await self._call("getTransaction", [signature, {
            "encoding": "json", "commitment": "confirmed",
            "maxSupportedTransactionVersion": 0}])
        keys = held_watch.transaction_accounts(tx)
        if not keys:
            raise ConnectionError(f"migration {signature[:12]} not readable yet")
        if (tx.get("meta") or {}).get("err") is not None:
            return None
        for start in range(0, len(keys), 100):
            batch = keys[start:start + 100]
            slot, raws = await self.accounts(batch, commitment="confirmed")
            if not slot:
                raise ConnectionError(f"accounts of migration {signature[:12]} unread")
            if found := held_watch.pool_among(mint, batch, raws):
                return found
        raise ConnectionError(f"pool of migration {signature[:12]} not visible yet")

    async def _read(self, helds: Sequence[held_watch.Held]) -> None:
        """Both balances of each pool, straight from the chain."""
        slot, raws = await self.accounts(
            [a for h in helds for a in (h.base_vault, h.quote_vault)])
        if not slot:
            return
        for i, held in enumerate(helds):
            base = held_watch.vault_amount(raws[2 * i])
            quote = held_watch.vault_amount(raws[2 * i + 1])
            if base is not None and quote is not None:
                held.apply("base", base, slot)
                held.apply("quote", quote, slot)

    async def stream(
        self,
        wanted: Callable[[], dict[str, held_watch.Held]],
        on_price: Callable[[held_watch.Held, datetime], Awaitable[None]],
    ) -> None:
        """Keep one socket subscribed to exactly the pools `wanted()` names.

        The held set changes about once a minute (0.77 changes a minute,
        measured 2026-09-16), so subscriptions are added and dropped on the
        open socket. The first version subscribed once and re-read the set
        only when the socket dropped — in its twenty live minutes it watched
        ONE token.

        A pool the socket has not spoken about for `HELD_HEARTBEAT_S` is read
        directly, and a newly added pool is read at once, so its first price
        does not wait for a trade.

        Returns only by raising: a dropped socket propagates so the caller
        reconnects, and keepalive pings turn a half-open connection into a
        drop instead of a silence that reads like a quiet market.
        """
        loop = asyncio.get_running_loop()
        watching: dict[str, held_watch.Held] = {}
        heard: dict[str, float] = {}
        subs: dict[str, list[int]] = {}
        pending: dict[int, tuple[str, str]] = {}
        live: dict[int, tuple[str, str]] = {}
        ident = 0
        async with self._connect(self._url, open_timeout=20,
                                 ping_interval=config.HELD_PING_S,
                                 ping_timeout=config.HELD_PING_S) as ws:
            tick = 0.0
            while True:
                if loop.time() >= tick:
                    tick = loop.time() + 1.0
                    want = wanted()
                    for mint in watching.keys() - want.keys():
                        del watching[mint], heard[mint]
                        for sub in subs.pop(mint, []):
                            live.pop(sub, None)
                            ident += 1
                            await ws.send(held_watch.unsubscribe_frame(sub, ident))
                    for mint in want.keys() - watching.keys():
                        held = watching[mint] = replace(want[mint])
                        heard[mint] = float("-inf")
                        for side, address in (("base", held.base_vault),
                                              ("quote", held.quote_vault)):
                            ident += 1
                            pending[ident] = (mint, side)
                            await ws.send(held_watch.subscribe_frame(address, ident))
                    quiet = [h for m, h in watching.items()
                             if loop.time() - heard[m] >= config.HELD_HEARTBEAT_S]
                    if quiet:
                        for held in quiet:
                            heard[held.mint] = loop.time()
                        await self._read(quiet)
                        for held in quiet:
                            if held.mint in watching and held.price() is not None:
                                await on_price(held, self._now())
                try:
                    payload = json.loads(await asyncio.wait_for(
                        ws.recv(), max(0.05, tick - loop.time())))
                except TimeoutError:
                    continue
                if "id" in payload:
                    key = pending.pop(payload["id"], None)
                    if key is None:
                        continue  # an unsubscribe, acknowledged
                    sub = payload.get("result")
                    if not isinstance(sub, int) or isinstance(sub, bool):
                        raise RuntimeError(f"accountSubscribe refused: {payload}")
                    if key[0] in watching:
                        live[sub] = key
                        subs.setdefault(key[0], []).append(sub)
                    else:  # the position closed while this was in flight
                        ident += 1
                        await ws.send(held_watch.unsubscribe_frame(sub, ident))
                    continue
                note = held_watch.notification(payload)
                if note is None or note[0] not in live:
                    continue
                sub, amount, slot = note
                mint, side = live[sub]
                held = watching[mint]
                heard[mint] = loop.time()
                if held.apply(side, amount, slot) and held.price() is not None:
                    self.updates += 1
                    await on_price(held, self._now())
