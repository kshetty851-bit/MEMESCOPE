"""Decoding trade events from the log stream the scanner already receives.

**No new subscription and no RPC.** The scanner is subscribed to pump.fun and
PumpSwap logs to find creations; every Buy and Sell on both programs already
arrives on that same socket and was being discarded. Reading it costs a base64
decode and a few struct unpacks per event.

Every offset below was verified against mainnet on 2026-08-22 by decoding live
events and matching the decoded values to the transactions they came from —
the same discipline `parse_create_event` follows, and for the same reason: a
wrong offset produces a confident, wrong wallet.

    pump.fun TradeEvent  (discriminator bddb7fd34ee661ee, observed len 359)
        8   mint            pubkey   (matched a tx account key)
        40  sol_amount      u64
        48  token_amount    u64
        56  is_buy          bool
        57  user            pubkey   (matched the fee payer)
        89  timestamp       i64      (== blockTime)

    PumpSwap BuyEvent    (67f4521f2cf57777, observed len 480)
    PumpSwap SellEvent   (3e2f370aa503dc2a, observed len 417)
        8   timestamp       i64      (== blockTime)
        16  base_amount     u64      (matched the tx's base-token delta)
        120 pool            pubkey   (46 of 54 sampled values matched
                                      `token_market_snapshots.pool_address`;
                                      no other offset matched any)
        152 user            pubkey   (matched the fee payer)

**The side comes from the discriminator, not a flag.** PumpSwap emits two
distinct events, so there is no boolean to misread.

**PumpSwap events carry no mint.** They name the pool, which is why the pool is
decoded and resolved through the pool→mint mapping the platform already stores.
An event whose pool is unknown is reported as such rather than guessed.

Amounts are left in raw base units. Every metric built on them is a *share
within one mint* — top-5 volume share, largest-buyer share — so the unit
cancels. That is deliberate: a PumpSwap pool may be quoted in WSOL or USDC
(both observed), and normalising to USD would need a price oracle to compute a
ratio that does not require one.
"""

from __future__ import annotations

import base64
import binascii
import struct
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Final

from app.services.curve.pda import b58encode

_PROGRAM_DATA_PREFIX: Final = "Program data: "

#: sha256("event:<Name>")[:8]. Pinned as literal bytes so they are greppable in
#: a raw payload, and confirmed present on mainnet in a 400-transaction sample:
#: SellEvent 114, BuyEvent 98, TradeEvent 68.
TRADE_EVENT_DISCRIMINATOR: Final = bytes.fromhex("bddb7fd34ee661ee")
BUY_EVENT_DISCRIMINATOR: Final = bytes.fromhex("67f4521f2cf57777")
SELL_EVENT_DISCRIMINATOR: Final = bytes.fromhex("3e2f370aa503dc2a")

_PUBKEY = 32
#: A timestamp outside this range means the offsets are wrong, so the whole
#: reading is refused. Same guard as the creation parsers.
_MIN_TS: Final = 1_600_000_000
_MAX_TS: Final = 4_100_000_000


class Side(StrEnum):
    BUY = "buy"
    SELL = "sell"


@dataclass(frozen=True, slots=True)
class TradeEvent:
    """One decoded trade. `mint` or `pool` identifies it — never both required.

    pump.fun names the mint directly; PumpSwap names the pool and the mint is
    resolved later. Carrying both as optional is what keeps the decoder honest
    about which fact the chain actually gave it.
    """

    side: Side
    user: str
    amount: int
    observed_at: datetime
    mint: str | None = None
    pool: str | None = None
    venue: str = "pumpswap"


def _pubkey(data: bytes, offset: int) -> str | None:
    if offset + _PUBKEY > len(data):
        return None
    return b58encode(data[offset : offset + _PUBKEY])


def _u64(data: bytes, offset: int) -> int | None:
    if offset + 8 > len(data):
        return None
    return int(struct.unpack_from("<Q", data, offset)[0])


def _i64(data: bytes, offset: int) -> int | None:
    if offset + 8 > len(data):
        return None
    return int(struct.unpack_from("<q", data, offset)[0])


def _timestamp(value: int | None) -> datetime | None:
    if value is None or not (_MIN_TS <= value <= _MAX_TS):
        return None
    return datetime.fromtimestamp(value, tz=UTC)


def decode_trade_event(payload: bytes) -> TradeEvent | None:
    """Decode one `Program data:` payload, or None if it is not a trade.

    Returns None rather than raising for every failure mode — a malformed or
    unrecognised payload is an ordinary occurrence on a shared log stream, and
    the caller counts it instead of dying on it.
    """
    if len(payload) < 8:
        return None
    head = payload[:8]

    if head == TRADE_EVENT_DISCRIMINATOR:
        mint = _pubkey(payload, 8)
        amount = _u64(payload, 48)
        user = _pubkey(payload, 57)
        observed_at = _timestamp(_i64(payload, 89))
        if not mint or not user or amount is None or observed_at is None:
            return None
        if len(payload) < 57 + _PUBKEY:
            return None
        return TradeEvent(
            side=Side.BUY if payload[56] else Side.SELL,
            user=user,
            amount=amount,
            observed_at=observed_at,
            mint=mint,
            venue="pumpfun",
        )

    if head in (BUY_EVENT_DISCRIMINATOR, SELL_EVENT_DISCRIMINATOR):
        observed_at = _timestamp(_i64(payload, 8))
        amount = _u64(payload, 16)
        pool = _pubkey(payload, 120)
        user = _pubkey(payload, 152)
        if not pool or not user or amount is None or observed_at is None:
            return None
        return TradeEvent(
            side=Side.BUY if head == BUY_EVENT_DISCRIMINATOR else Side.SELL,
            user=user,
            amount=amount,
            observed_at=observed_at,
            pool=pool,
            venue="pumpswap",
        )

    return None


def decode_trade_events(logs: list[str] | tuple[str, ...]) -> list[TradeEvent]:
    """Every trade in one transaction's logs. Usually zero or one."""
    out: list[TradeEvent] = []
    for line in logs:
        if not line.startswith(_PROGRAM_DATA_PREFIX):
            continue
        try:
            payload = base64.b64decode(line[len(_PROGRAM_DATA_PREFIX) :], validate=True)
        except (ValueError, binascii.Error):
            continue
        event = decode_trade_event(payload)
        if event is not None:
            out.append(event)
    return out
