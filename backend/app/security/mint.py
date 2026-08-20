"""Decoding a Solana mint account. Pure, and shared by both consumers.

Moved here verbatim from `app.real_wallet_safety.service` so the Real Wallet
policy gate and the shared security evaluator read the same bytes the same
way. This is code motion, not a rewrite: the Real Wallet imports these names
back and its behaviour is unchanged, which its existing tests pin.

A decoder is the right thing to share. A *policy* is not — what counts as an
acceptable extension, and what an active authority should cost a caller, are
decisions each consumer makes for itself.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any

PUMP_FUN_PROGRAM = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
TOKEN_PROGRAM = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"  # noqa: S105
# Canonical Token-2022 owner program. Kept as one literal so it is reviewable.
TOKEN_2022_PROGRAM = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"  # noqa: S105

#: Token-2022 extension discriminants that can take value or transferability
#: away from a holder after the fact. Named rather than inferred, because the
#: allowlist elsewhere answers "may we trade this" and this answers the
#: different question "is this token positively dangerous".
#:
#: 1  TransferFeeConfig      — skims every transfer
#: 4  MintCloseAuthority     — the mint can be closed
#: 5  ConfidentialTransfer   — balances the platform cannot audit
#: 12 DefaultAccountState    — new accounts can be born frozen
#: 13 ImmutableOwner is *safe*; 14 MemoTransfer is safe — neither is listed
#: 14 --
#: 15 NonTransferable        — a token that cannot be sold
#: 16 InterestBearingConfig  — supply changes under the holder
#: 17 PermanentDelegate      — a third party can move holder balances at will
#: 20 TransferHook           — arbitrary program logic gates every transfer
DANGEROUS_EXTENSIONS: dict[int, str] = {
    1: "TransferFeeConfig",
    4: "MintCloseAuthority",
    5: "ConfidentialTransferMint",
    12: "DefaultAccountState",
    15: "NonTransferable",
    16: "InterestBearingConfig",
    17: "PermanentDelegate",
    20: "TransferHook",
}


@dataclass(frozen=True, slots=True)
class TokenInspection:
    token_program: str | None
    decimals: int | None
    mint_authority_active: bool | None
    freeze_authority_active: bool | None
    extensions: tuple[int, ...]
    raw: dict[str, object]


def _u32(raw: bytes, start: int) -> int:
    return int.from_bytes(raw[start : start + 4], "little")


def decode_mint_account(account: dict[str, Any]) -> TokenInspection:
    """Decode the standard 82-byte Mint prefix and Token-2022 TLV extensions."""
    owner = account.get("owner")
    data = account.get("data")
    if not isinstance(owner, str) or not isinstance(data, list) or not data:
        raise ValueError("Mint account response is incomplete")
    encoded = data[0]
    if not isinstance(encoded, str):
        raise ValueError("Mint account has no base64 payload")
    raw = base64.b64decode(encoded)
    if len(raw) < 82:
        raise ValueError("Mint account is shorter than the Mint layout")
    extensions: list[int] = []
    # Token-2022 places a one-byte AccountType discriminator between the
    # legacy Mint prefix and its TLV area. Plain SPL mints stop at byte 82.
    cursor = 83 if len(raw) > 82 and raw[82] == 1 else 82
    while cursor + 4 <= len(raw):
        extension_type = int.from_bytes(raw[cursor : cursor + 2], "little")
        length = int.from_bytes(raw[cursor + 2 : cursor + 4], "little")
        if extension_type == 0 and length == 0:
            break
        end = cursor + 4 + length
        if end > len(raw):
            raise ValueError("Malformed Token-2022 extension length")
        extensions.append(extension_type)
        cursor = end
    return TokenInspection(
        token_program=owner,
        decimals=int(raw[44]),
        mint_authority_active=_u32(raw, 0) != 0,
        freeze_authority_active=_u32(raw, 46) != 0,
        extensions=tuple(extensions),
        raw={"owner": owner, "data_length": len(raw), "extensions": extensions},
    )
