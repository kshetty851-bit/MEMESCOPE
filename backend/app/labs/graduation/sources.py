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
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable, Sequence
from datetime import UTC, datetime
from types import TracebackType
from typing import Any, Self

import httpx
import websockets

from app.core.backoff import BackoffPolicy
from app.core.logging import get_logger
from app.labs.graduation import config, curve
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
        for batch in chunked([a for _, a in addressed], config.MAX_ACCOUNTS_PER_CALL):
            offset = len(out)
            if not await self._acquire():
                logger.warning("graduation_rpc_budget_exhausted", pending=len(batch))
                self.rate_limited += 1
                break
            try:
                values = await self._rpc.get_multiple_accounts(batch)
                self.calls += 1
            except Exception as exc:
                self.failures += 1
                self.last_failure = f"{type(exc).__name__}: {exc}"
                logger.warning("graduation_rpc_failed", size=len(batch),
                               error=repr(exc))
                continue
            for (mint, _), value in zip(addressed[offset:], values, strict=False):
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
