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
the thing that works. Only OPEN positions are watched, one to five at a time,
so the public node's limits are never approached.
"""

from __future__ import annotations

import base64
import json
import struct
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from app.core.config import settings
from app.security.liquidity import derive_or_none, parse_pool

#: An SPL token account holds its balance as a little-endian u64 at byte 64,
#: after the 32-byte mint and 32-byte owner. Standard across every SPL account,
#: which is why the vaults are watched rather than the pool: the pool's own
#: layout is program-specific, a vault's is not.
_AMOUNT_AT = 64


def vault_amount(data: bytes | None) -> int | None:
    if not data or len(data) < _AMOUNT_AT + 8:
        return None
    (amount,) = struct.unpack_from("<Q", data, _AMOUNT_AT)
    return amount


@dataclass(slots=True)
class Held:
    """One watched position: its two vaults and their latest balances."""

    mint: str
    base_vault: str
    quote_vault: str
    base: int | None = None
    quote: int | None = None
    sub_ids: tuple[int, ...] = ()

    def price(self) -> Decimal | None:
        """Quote per token, straight from the reserves — the AMM's own price.

        Returned unscaled for decimals: the caller compares it against the
        price it ENTERED at, computed the same way, and a ratio of two prices
        in the same units needs no scaling. Absolute prices would.
        """
        if not self.base or not self.quote:
            return None
        return Decimal(self.quote) / Decimal(self.base)


def pool_for(mint: str) -> str | None:
    """The pool address a mint migrates to, derived rather than looked up."""
    derived = derive_or_none(mint, pumpfun_program=settings.PUMPFUN_PROGRAM_ID)
    return derived[1] if derived else None


def vaults_from_pool(raw: bytes | None) -> tuple[str, str] | None:
    """The two vault addresses inside a pool account.

    `parse_pool` is the platform's decoder, verified against mainnet, so this
    adds no new assumption about a program layout.
    """
    state = parse_pool(raw)
    if state is None or not state.base_vault or not state.quote_vault:
        return None
    return state.base_vault, state.quote_vault


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


def subscribe_frame(address: str, ident: int) -> str:
    return json.dumps({"jsonrpc": "2.0", "id": ident,
                       "method": "accountSubscribe",
                       "params": [address, {"encoding": "base64",
                                            "commitment": "processed"}]})
