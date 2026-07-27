"""Pure parsing of Solana log notifications and transactions.

Everything here is a plain function over plain data — no network, no database,
no clock. That is deliberate: transaction shapes are the fiddliest part of this
module, and pure functions let the whole matrix be unit-tested from fixtures.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

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


def parse_asset_metadata(asset: dict[str, Any]) -> TokenMetadata:
    """Read name/symbol/uri/decimals out of a DAS `getAsset` result.

    Every field is optional by design — partial responses are normal for a token
    that is seconds old, and a missing symbol must not discard a valid mint.
    """
    content = _as_dict(asset.get("content"))
    metadata = _as_dict(content.get("metadata"))
    token_info = _as_dict(asset.get("token_info"))

    decimals = token_info.get("decimals")

    return TokenMetadata(
        name=_clean(metadata.get("name"), 200),
        symbol=_clean(metadata.get("symbol"), 64),
        metadata_uri=_clean(content.get("json_uri"), 2048),
        decimals=decimals if isinstance(decimals, int) else None,
    )
