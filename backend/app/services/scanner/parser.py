"""Pure parsing of Solana log notifications and transactions.

Everything here is a plain function over plain data — no network, no database,
no clock. That is deliberate: transaction shapes are the fiddliest part of this
module, and pure functions let the whole matrix be unit-tested from fixtures.
"""

from __future__ import annotations

import base64
import binascii
import struct
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.services.curve.pda import b58encode

# Log markers that indicate a mint is being created. `initializeMint`/
# `initializeMint2` is the authoritative signal — a mint account cannot come
# into existence without it — and covers both the SPL Token and Token-2022
# programs, so new launchpads are picked up without a code change.
MINT_INIT_MARKERS = ("Instruction: InitializeMint2", "Instruction: InitializeMint")

# Creation markers emitted by launchpad programs wrapping the mint init.
CREATE_MARKERS = (
    "Instruction: Create",
    "Instruction: CreateV2",
    "Instruction: CreateMetadataAccountV3",
)


@dataclass(frozen=True, slots=True)
class LogEvent:
    """A candidate token-creation transaction seen on the log stream."""

    signature: str
    slot: int
    logs: tuple[str, ...]
    source_program: str | None = None


@dataclass(frozen=True, slots=True)
class TokenCreation:
    """A token creation extracted from a fetched transaction."""

    mint_address: str
    signature: str
    slot: int
    creator_address: str | None
    decimals: int | None
    block_time: datetime | None
    source_program: str | None = None


def is_token_creation_log(logs: list[str] | tuple[str, ...]) -> bool:
    """Cheap pre-filter applied to the raw stream before any RPC call.

    The stream carries hundreds of transactions per second; fetching each one
    would be both slow and a good way to get rate limited. Requiring a mint-init
    marker discards the overwhelming majority for the cost of a substring scan.
    """
    blob = "\n".join(logs)
    return any(marker in blob for marker in MINT_INIT_MARKERS)


def parse_log_notification(message: dict[str, Any]) -> LogEvent | None:
    """Extract a `LogEvent` from a `logsNotification`, or None if not applicable.

    Failed transactions are skipped: a reverted mint never existed.
    """
    params = message.get("params")
    if not isinstance(params, dict):
        return None

    result = params.get("result")
    if not isinstance(result, dict):
        return None

    value = result.get("value")
    if not isinstance(value, dict):
        return None

    if value.get("err") is not None:
        return None

    signature = value.get("signature")
    logs = value.get("logs")
    if not isinstance(signature, str) or not isinstance(logs, list):
        return None

    context = result.get("context") or {}
    slot = context.get("slot")

    return LogEvent(
        signature=signature,
        slot=int(slot) if isinstance(slot, int) else 0,
        logs=tuple(str(entry) for entry in logs),
    )


def _iter_instructions(transaction: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten top-level and inner instructions into one list."""
    instructions: list[dict[str, Any]] = []

    message = (transaction.get("transaction") or {}).get("message") or {}
    for instruction in message.get("instructions") or []:
        if isinstance(instruction, dict):
            instructions.append(instruction)

    meta = transaction.get("meta") or {}
    for inner in meta.get("innerInstructions") or []:
        if not isinstance(inner, dict):
            continue
        for instruction in inner.get("instructions") or []:
            if isinstance(instruction, dict):
                instructions.append(instruction)

    return instructions


def extract_mint_and_decimals(transaction: dict[str, Any]) -> tuple[str | None, int | None]:
    """Find the newly initialised mint and its decimals.

    Primary source is the parsed `initializeMint`/`initializeMint2` instruction,
    which carries both values directly. When an RPC node returns unparsed
    instructions, fall back to diffing token balances — that yields the mint but
    not the decimals, which the metadata step fills in later.
    """
    for instruction in _iter_instructions(transaction):
        parsed = instruction.get("parsed")
        if not isinstance(parsed, dict):
            continue
        if not str(parsed.get("type", "")).startswith("initializeMint"):
            continue

        info = parsed.get("info")
        if not isinstance(info, dict):
            continue

        mint = info.get("mint")
        if isinstance(mint, str) and mint:
            decimals = info.get("decimals")
            return mint, decimals if isinstance(decimals, int) else None

    meta = transaction.get("meta") or {}
    pre = {
        balance.get("mint")
        for balance in meta.get("preTokenBalances") or []
        if isinstance(balance, dict)
    }
    post = {
        balance.get("mint")
        for balance in meta.get("postTokenBalances") or []
        if isinstance(balance, dict)
    }
    new_mints = {mint for mint in (post - pre) if isinstance(mint, str) and mint}
    if len(new_mints) == 1:
        return new_mints.pop(), None

    return None, None


def extract_fee_payer(transaction: dict[str, Any]) -> str | None:
    """The first account key is the fee payer — the wallet that launched it."""
    message = (transaction.get("transaction") or {}).get("message") or {}
    keys = message.get("accountKeys") or []
    if not keys:
        return None

    first = keys[0]
    if isinstance(first, dict):
        pubkey = first.get("pubkey")
        return pubkey if isinstance(pubkey, str) else None
    return first if isinstance(first, str) else None


def parse_block_time(transaction: dict[str, Any]) -> datetime | None:
    block_time = transaction.get("blockTime")
    if not isinstance(block_time, int):
        return None
    return datetime.fromtimestamp(block_time, tz=UTC)


def parse_transaction(
    transaction: dict[str, Any],
    *,
    signature: str,
    fallback_slot: int = 0,
    source_program: str | None = None,
) -> TokenCreation | None:
    """Build a `TokenCreation` from a fetched transaction, or None if it is not one."""
    # A transaction that failed on-chain created nothing.
    if (transaction.get("meta") or {}).get("err") is not None:
        return None

    mint, decimals = extract_mint_and_decimals(transaction)
    if not mint:
        return None

    slot = transaction.get("slot")
    return TokenCreation(
        mint_address=mint,
        signature=signature,
        slot=int(slot) if isinstance(slot, int) else fallback_slot,
        creator_address=extract_fee_payer(transaction),
        decimals=decimals,
        block_time=parse_block_time(transaction),
        source_program=source_program,
    )


@dataclass(frozen=True, slots=True)
class TokenMetadata:
    name: str | None
    symbol: str | None
    metadata_uri: str | None
    image_url: str | None
    decimals: int | None


def _as_dict(value: Any) -> dict[str, Any]:
    """Coerce an untrusted nested value to a dict, so `.get()` chains are safe."""
    return value if isinstance(value, dict) else {}


def _clean(value: Any, limit: int) -> str | None:
    """Normalise an on-chain string.

    On-chain metadata is attacker-controlled: it is padded with NULs, can be
    arbitrarily long, and can contain control characters. Truncate and strip
    before anything downstream stores or renders it.
    """
    if not isinstance(value, str):
        return None
    cleaned = value.replace("\x00", "").strip()
    if not cleaned:
        return None
    return cleaned[:limit]


@dataclass(frozen=True, slots=True)
class CreateEvent:
    """A launchpad creation event decoded straight from the log stream.

    Carries everything `TokenCreation` needs except `decimals`, plus the
    metadata that would otherwise cost a DAS `getAsset` call.
    """

    mint_address: str
    creator_address: str | None
    name: str | None
    symbol: str | None
    metadata_uri: str | None
    block_time: datetime | None


#: Anchor derives an event discriminator as `sha256("event:<Name>")[:8]`. Pinned
#: as literal bytes so the value is greppable when reading a raw payload; the
#: derivation is recorded so a second event type can be added without guessing.
#: Verified equal to the bytes observed on mainnet, 2026-08-03.
CREATE_EVENT_DISCRIMINATOR = bytes.fromhex("1b72a94ddeeb6376")

_PROGRAM_DATA_PREFIX = "Program data: "

#: Plausibility bounds on the borsh length prefixes. A value outside these does
#: not mean a token has a very long name — it means the offsets are wrong, and
#: every field read after it is garbage. Same discipline as `curve/state.py`:
#: refuse the whole reading rather than report a plausible-looking wrong one.
_MAX_NAME_BYTES = 200
_MAX_SYMBOL_BYTES = 64
_MAX_URI_BYTES = 2048

#: A Unix timestamp outside this range is the strongest single signal that the
#: layout has shifted, because it is read *after* three variable-length strings
#: and four public keys — it validates every offset before it in one check.
_MIN_BLOCK_TIME = 1_600_000_000  # 2020-09
_MAX_BLOCK_TIME = 4_100_000_000  # 2100-01

_PUBKEY_BYTES = 32


class _Reader:
    """Minimal borsh cursor. Raises `ValueError` the moment anything is off."""

    __slots__ = ("_data", "_offset")

    def __init__(self, data: bytes, offset: int = 0) -> None:
        self._data = data
        self._offset = offset

    @property
    def remaining(self) -> int:
        return len(self._data) - self._offset

    def string(self, limit: int) -> str:
        if self.remaining < 4:
            raise ValueError("truncated length prefix")
        (length,) = struct.unpack_from("<I", self._data, self._offset)
        length = int(length)
        self._offset += 4
        if length > limit or length > self.remaining:
            raise ValueError(f"implausible string length {length}")
        raw = self._data[self._offset : self._offset + length]
        self._offset += length
        # `strict` on purpose: on-chain bytes that are not valid UTF-8 mean the
        # offsets are wrong. Replacing them would manufacture a readable name
        # out of a misread and hide the fault.
        return raw.decode("utf-8")

    def pubkey(self) -> str:
        if self.remaining < _PUBKEY_BYTES:
            raise ValueError("truncated public key")
        raw = self._data[self._offset : self._offset + _PUBKEY_BYTES]
        self._offset += _PUBKEY_BYTES
        return b58encode(raw)

    def i64(self) -> int:
        if self.remaining < 8:
            raise ValueError("truncated i64")
        (value,) = struct.unpack_from("<q", self._data, self._offset)
        self._offset += 8
        return int(value)


def parse_create_event(logs: Sequence[str]) -> CreateEvent | None:
    """Decode a launchpad `CreateEvent` from log lines, or None if absent.

    The launchpad emits an Anchor event carrying the mint, the creator and the
    token's own metadata. Reading it costs nothing: the bytes are already in the
    log notification the scanner subscribed to, so a token resolved this way
    needs neither `getTransaction` nor a DAS `getAsset` call.

    That matters twice over. Public RPC endpoints rate-limit `getTransaction`
    hard enough that roughly half of all creation events were being lost, and
    DAS is an indexer extension no standard node serves at all — which is why
    every token discovered since the switch to standard RPC has sat at
    `MetadataStatus.PENDING` with no name.

    Returns None whenever the event is absent or fails a single invariant, so
    the caller falls back to fetching the transaction. That fallback is what
    keeps the scanner launchpad-agnostic: a program that emits `InitializeMint`
    without this event is still discovered exactly as before.

    `decimals` is deliberately not returned. The event does not carry it, and
    while these mints are conventionally six, asserting a value the chain did
    not report would be estimating missing data. It stays null and the metadata
    step fills it in later.
    """
    for line in logs:
        if not line.startswith(_PROGRAM_DATA_PREFIX):
            continue

        try:
            payload = base64.b64decode(line[len(_PROGRAM_DATA_PREFIX) :], validate=True)
        except (ValueError, binascii.Error):
            continue

        if not payload.startswith(CREATE_EVENT_DISCRIMINATOR):
            # A different event on the same transaction — a trade, a fee read.
            # Discriminating by prefix is what stops one being decoded as the
            # other and producing a confident, wrong reading.
            continue

        try:
            reader = _Reader(payload, offset=len(CREATE_EVENT_DISCRIMINATOR))
            name = reader.string(_MAX_NAME_BYTES)
            symbol = reader.string(_MAX_SYMBOL_BYTES)
            uri = reader.string(_MAX_URI_BYTES)
            mint = reader.pubkey()
            reader.pubkey()  # bonding curve — not needed here
            reader.pubkey()  # user
            creator = reader.pubkey() if reader.remaining >= _PUBKEY_BYTES else None
            timestamp = reader.i64() if reader.remaining >= 8 else None
        except ValueError:
            # The layout moved. Refuse the reading and let the caller fall back
            # to the transaction, which is the pre-existing behaviour.
            return None

        if timestamp is not None and not (_MIN_BLOCK_TIME <= timestamp <= _MAX_BLOCK_TIME):
            return None

        return CreateEvent(
            mint_address=mint,
            creator_address=creator,
            # Cleaned exactly like DAS metadata: these strings are chosen by
            # whoever launched the token and reach the UI unmodified otherwise.
            name=_clean(name, 200),
            symbol=_clean(symbol, 64),
            metadata_uri=_clean(uri, 2048),
            block_time=(
                datetime.fromtimestamp(timestamp, tz=UTC) if timestamp is not None else None
            ),
        )

    return None


def parse_asset_metadata(asset: dict[str, Any]) -> TokenMetadata:
    """Read name/symbol/uri/decimals out of a DAS `getAsset` result.

    Every field is optional by design — partial responses are normal for a token
    that is seconds old, and a missing symbol must not discard a valid mint.
    """
    content = _as_dict(asset.get("content"))
    metadata = _as_dict(content.get("metadata"))
    links = _as_dict(content.get("links"))
    token_info = _as_dict(asset.get("token_info"))

    decimals = token_info.get("decimals")

    return TokenMetadata(
        name=_clean(metadata.get("name"), 200),
        symbol=_clean(metadata.get("symbol"), 64),
        metadata_uri=_clean(content.get("json_uri"), 2048),
        image_url=_clean(links.get("image"), 2048),
        decimals=decimals if isinstance(decimals, int) else None,
    )
