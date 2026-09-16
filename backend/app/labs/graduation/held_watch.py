"""Sub-second price for the positions actually open.

WHY THIS EXISTS, in one measurement. Collapses in this market are cascades:
median 247 sells of about $159 each, where $352 is needed to move price 10%,
falling 1.14% a SECOND. How fast you find out is therefore the whole result:

    reaction   0.6s   3s     18s    27s    61s
    FLOOR_5m  $1040  $949   $342     $0     $0

DexScreener refreshes about every 27 seconds — measured, not assumed: on a pool
taking 1,512 sells in five minutes, only 11% of 3-second polls returned a new
price. Polling it faster buys nothing; it lands just past the cliff.

`accountSubscribe` on the pool's two vaults returns 44 updates in 25 seconds on
that same pool — one every 0.6s — and needs NO KEY. Helius refuses the socket
while its quota is spent, so the public node is not a compromise here, it is
the thing that works. Only OPEN positions are watched, a handful at a time, so
the public node's limits are never approached.

It is also the more HONEST price, not just the faster one. DexScreener quotes
the last trade, and a dump trades far above the price it leaves behind: on
2026-09-15, after sVkL4MXW rugged, DexScreener sat 5.7x above the pool's own
reserves for over a minute.
"""

from __future__ import annotations

import base64
import json
import struct
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

from app.core.config import settings
from app.labs.graduation import config
from app.security.liquidity import PoolState, b58encode, derive_or_none

#: An SPL token account holds its balance as a little-endian u64 at byte 64,
#: after the 32-byte mint and 32-byte owner. Standard across every SPL account,
#: which is why the vaults are watched rather than the pool: the pool's own
#: layout is program-specific, a vault's is not.
_AMOUNT_AT = 64
#: An SPL mint: a 36-byte optional authority and the u64 supply, then
#: `decimals` at byte 44 and `is_initialized` at 45. Token-2022 mints share
#: these 82 bytes and append their extensions after them.
_DECIMALS_AT = 44
_INITIALIZED_AT = 45
_MINT_SIZE = 82


def vault_amount(data: bytes | None) -> int | None:
    if not data or len(data) < _AMOUNT_AT + 8:
        return None
    (amount,) = struct.unpack_from("<Q", data, _AMOUNT_AT)
    return amount


def vault_mint(data: bytes | None) -> str | None:
    """The mint a token account holds: its first 32 bytes."""
    if not data or len(data) < _AMOUNT_AT + 8:
        return None
    return b58encode(data[:32])


def mint_decimals(data: bytes | None) -> int | None:
    """A mint's decimals, read off the account rather than assumed."""
    if not data or len(data) < _MINT_SIZE or data[_INITIALIZED_AT] != 1:
        return None
    return data[_DECIMALS_AT]


@dataclass(slots=True)
class Held:
    """One watched position: its pool's two vaults, their scale, their balances."""

    mint: str
    pool: str
    base_vault: str
    quote_vault: str
    base_decimals: int
    quote_decimals: int
    base: int | None = None
    quote: int | None = None
    #: The newest slot applied. Balances arrive by two paths, the socket and a
    #: direct read, and not always in order; an older slot is dropped rather
    #: than allowed to rewind the price.
    slot: int = 0

    def apply(self, side: str, amount: int, slot: int) -> bool:
        if slot < self.slot:
            return False
        self.slot = slot
        if side == "base":
            self.base = amount
        else:
            self.quote = amount
        return True

    def price(self) -> Decimal | None:
        """Quote per WHOLE token: the unit every entry price in the book is in.

        The vaults hold raw integers. A pump.fun token carries 6 decimals and
        wrapped SOL carries 9, so the bare ratio is 1,000x the price. That bare
        ratio was written as marks for twenty minutes on 2026-09-15 and put
        FLOOR_4m_SL at $17,517; against DexScreener in calm trading it read
        997.5x. This docstring used to say the scale did not matter.
        """
        if not self.base or not self.quote:
            return None
        return self.quote_whole() / Decimal(self.base).scaleb(-self.base_decimals)

    def quote_whole(self) -> Decimal:
        return Decimal(self.quote or 0).scaleb(-self.quote_decimals)

    def depth_usd(self, quote_usd: Decimal) -> Decimal | None:
        """Pool depth as DexScreener states it: both sides at spot, which in a
        constant-product pool is twice the quote side.

        A mark without depth closes a position with no price impact at all,
        which flatters exactly the trades that ran.
        """
        if not self.quote or quote_usd <= 0:
            return None
        return 2 * self.quote_whole() * quote_usd


def watch(mint: str, pool_address: str, pool: PoolState | None,
          accounts: Sequence[bytes | None]) -> Held | None:
    """A position's pool, PROVEN watchable, or nothing.

    `accounts` is [base mint, quote mint, base vault, quote vault] as the chain
    returned them. Nothing is taken on trust:

    * the pool's BASE token must be the position's token — a pool listing it
      as the quote would invert every price;
    * each vault must hold the mint the pool says it does;
    * both decimals come off the mint accounts. Guessing them is how the wrong
      number shipped the first time.
    """
    if pool is None or pool.base_mint != mint or len(accounts) != 4:
        return None
    base_mint, quote_mint, base_vault, quote_vault = accounts
    base_decimals = mint_decimals(base_mint)
    quote_decimals = mint_decimals(quote_mint)
    if base_decimals is None or quote_decimals is None:
        return None
    if (vault_mint(base_vault) != pool.base_mint
            or vault_mint(quote_vault) != pool.quote_mint):
        return None
    return Held(mint=mint, pool=pool_address, base_vault=pool.base_vault,
                quote_vault=pool.quote_vault, base_decimals=base_decimals,
                quote_decimals=quote_decimals)


@dataclass(slots=True)
class MarkWriter:
    """Which socket prices become marks.

    CHECKED FIRST, IN ONE DIRECTION. A mint's first price must not sit more
    than `HELD_SCALE_BAND` ABOVE DexScreener's for the same pair. That is the
    error that shipped: 1,000x above, fabricating profits on a book that only
    buys. BELOW is not checked, because below is what a rug looks like —
    D9W99Lzd, 2026-09-16, drained to 0.2382 SOL while DexScreener sat frozen
    75x higher for minutes; the node's own parser agreed with the socket to
    four places. A long book marked low can understate a result and never
    invent one. The band is wide because DexScreener lags honestly too: 17%
    on a fresh graduate, with depth 9.4% apart and 0.906² = 0.821.

    THEN THROTTLED. The socket gives an update every ~0.6s. A row lands on a
    `HELD_WRITE_PCT` move, on any change after `HELD_INTERVAL_S`, and at least
    every `HELD_HEARTBEAT_S`, so a quiet pool's mark stays provably current.
    """

    trusted: set[str] = field(default_factory=set)
    last: dict[str, tuple[Decimal, datetime]] = field(default_factory=dict)

    def decide(self, mint: str, price: Decimal, reference: Decimal | None,
               at: datetime) -> str:
        if mint not in self.trusted:
            if not reference or reference <= 0:
                return "unchecked"
            if price > reference * config.HELD_SCALE_BAND:
                return "wrong_scale"
            self.trusted.add(mint)
        seen = self.last.get(mint)
        if seen is not None:
            moved = abs(price / seen[0] - 1)
            elapsed = (at - seen[1]).total_seconds()
            if not (moved >= config.HELD_WRITE_PCT
                    or (moved and elapsed >= config.HELD_INTERVAL_S)
                    or elapsed >= config.HELD_HEARTBEAT_S):
                return "hold"
        self.last[mint] = (price, at)
        return "write"

    def keep(self, mints: Iterable[str]) -> None:
        """Forget closed positions, so memory tracks what is held."""
        keep = set(mints)
        self.trusted &= keep
        for mint in self.last.keys() - keep:
            del self.last[mint]


def pool_for(mint: str) -> str | None:
    """The pool address a mint migrates to, derived from the mint.

    NOT used by the held watcher, and the reason is worth keeping: derivation
    returned an address with no account on chain for a live pumpswap token.
    A graduation can land on more than one venue and only the price feed knows
    which, so the watcher uses the pair DexScreener actually priced — which is
    also the pair the entry price came from, already pinned on the first
    sample. Kept because it is the right tool when there is no feed to ask.
    """
    derived = derive_or_none(mint, pumpfun_program=settings.PUMPFUN_PROGRAM_ID)
    return derived[1] if derived else None


def account_bytes(value: Any) -> bytes | None:
    """The base64 payload out of an RPC account value, or nothing."""
    data = (value or {}).get("data")
    if not isinstance(data, list) or not data:
        return None
    try:
        return base64.b64decode(data[0])
    except Exception:
        return None


def subscription_of(payload: dict[str, Any]) -> int | None:
    """The subscription a notification belongs to, if it is one."""
    if payload.get("method") != "accountNotification":
        return None
    return (payload.get("params") or {}).get("subscription")


def notification(payload: dict[str, Any]) -> tuple[int, int, int] | None:
    """(subscription, balance, slot) from an account notification, or nothing."""
    sub = subscription_of(payload)
    if sub is None:
        return None
    result = (payload.get("params") or {}).get("result") or {}
    amount = vault_amount(account_bytes(result.get("value")))
    slot = (result.get("context") or {}).get("slot")
    if amount is None or not isinstance(slot, int):
        return None
    return sub, amount, slot


def subscribe_frame(address: str, ident: int) -> str:
    return json.dumps({"jsonrpc": "2.0", "id": ident,
                       "method": "accountSubscribe",
                       "params": [address, {"encoding": "base64",
                                            "commitment": "processed"}]})


def unsubscribe_frame(subscription: int, ident: int) -> str:
    return json.dumps({"jsonrpc": "2.0", "id": ident,
                       "method": "accountUnsubscribe", "params": [subscription]})
