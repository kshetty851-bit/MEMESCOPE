"""On-chain liquidity-security verification for pump.fun and PumpSwap.

Pure: derivation, byte decoding and classification. No I/O, no clock. The
fetching lives in `evaluator.py`, for the same reason `curve/state.py` is
separate from `curve/collector.py` — the layout is the part most likely to be
wrong and it must be testable against literal bytes.

WHAT THIS MODULE PROVES, AND HOW IT WAS ESTABLISHED
---------------------------------------------------

Nothing here is taken from memory or from a venue label. Every constant and
every rule below was derived from live mainnet account state during SEC-1 and
is reproducible with `getAccountInfo`:

**The PumpSwap pool layout.** Decoded from pool
`5WxcQsupyQEofn16TMZozgRCz5MAnLoCocvb3b6SokW3` (301 bytes, discriminator
`f19a6d0411b16dbc`) and confirmed against ground truth: the decoded
`base_mint` equalled the token being investigated and `quote_mint` equalled
wrapped SOL. Verified identically on five independent pools.

**The migration provenance derivation.** A pump.fun token that graduates gets
a PumpSwap pool whose `creator` field is not a wallet but a program-derived
address:

    pool_authority = PDA(["pool-authority", mint], PUMP_FUN_PROGRAM)

This was confirmed by deriving it locally and matching the on-chain `creator`
byte-for-byte on 5/5 sampled pools, and it is off-curve on all of them — no
private key can exist for it. The pool address itself is then:

    pool = PDA(["pool", u16(0), pool_authority, mint, WSOL], PUMPSWAP_PROGRAM)

matched exactly on 3/3 pools tested. That derivation is why this module never
searches for a pool: the canonical migration pool for a mint is *computed*,
so there is no "which pool did we pick" ambiguity to get wrong (§12).

**Why LP supply alone is not a security check.** The obvious rule — "LP mint
supply is zero, therefore the LP was burned, therefore PASS" — is wrong, and
SEC-1 established that empirically rather than by argument. A random sample of
60 live PumpSwap pools found **all 60 with LP supply zero**, of which only 11
were pump.fun migrations. The other 49 were drained pools: their vaults held
dust (0.000000004 base, 0.00497 quote). Their LP supply is zero because every
LP token was *redeemed* — the liquidity was pulled. A naive check would have
called all 49 of them secure.

Zero LP supply is therefore necessary but nowhere near sufficient. It only
means something when combined with proof that the pool is a protocol
migration, which is what the PDA derivation supplies.

A wider scan of 200 pools found 5 with non-zero LP supply, so the check does
discriminate rather than being vacuously true.
"""

from __future__ import annotations

import enum
import struct
from dataclasses import dataclass

from app.services.curve.pda import (
    InvalidAddressError,
    PdaDerivationError,
    b58decode,
    find_program_address,
)

#: Verified live: the owner program of every 301-byte pool account read.
PUMPSWAP_PROGRAM = "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA"

#: Wrapped SOL, the quote side of every pump.fun migration pool observed.
WSOL_MINT = "So11111111111111111111111111111111111111112"

#: Anchor discriminator of the PumpSwap `Pool` account, read from mainnet.
POOL_DISCRIMINATOR = bytes.fromhex("f19a6d0411b16dbc")

#: Seed pump.fun uses for the migration authority that owns the new pool.
POOL_AUTHORITY_SEED = b"pool-authority"

#: Seed PumpSwap uses for pool accounts.
POOL_SEED = b"pool"

#: Every pump.fun migration pool observed carried index 0. A different index
#: is a different pool and is deliberately not searched for — see §12 and the
#: module docstring.
MIGRATION_POOL_INDEX = 0

#: Observed size of the pool account. Checked rather than assumed: a protocol
#: that grows the struct must produce UNKNOWN, not a misread.
POOL_ACCOUNT_SIZE = 301

# offset  size  field           (verified against mainnet, see docstring)
# 0       8     discriminator
# 8       1     pool_bump
# 9       2     index (u16)
# 11      32    creator          <- the migration authority for a graduated token
# 43      32    base_mint
# 75      32    quote_mint
# 107     32    lp_mint
# 139     32    pool_base_token_account
# 171     32    pool_quote_token_account
# 203     8     lp_supply (the pool's own notional record, NOT the mint supply)
# 211     32    coin_creator
_CREATOR_AT = 11
_FIELD_ORDER = (
    "creator",
    "base_mint",
    "quote_mint",
    "lp_mint",
    "base_vault",
    "quote_vault",
)

_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def b58encode(raw: bytes) -> str:
    number = int.from_bytes(raw, "big")
    encoded = ""
    while number:
        number, remainder = divmod(number, 58)
        encoded = _ALPHABET[remainder] + encoded
    return "1" * (len(raw) - len(raw.lstrip(b"\x00"))) + (encoded or "")


class Mechanism(enum.StrEnum):
    """How liquidity is held, when it could be established.

    Kept distinct on purpose (§10). "Protocol custody", "LP burned" and
    "locked by a locker program" are three different facts and collapsing them
    is how a UI ends up claiming something nobody proved. This platform has
    never seen a locker program on these venues, so `LOCK_PROGRAM` is
    deliberately absent rather than declared and unused.
    """

    #: Reserves sit in the pump.fun bonding-curve account while the token is
    #: still on its curve. There is no LP token and no pool.
    BONDING_CURVE_CUSTODY = "BONDING_CURVE_CUSTODY"
    #: A pump.fun graduation pool whose LP supply is zero: the migration LP was
    #: burned, so no redeemable claim on the reserves exists.
    PUMPSWAP_MIGRATED_LP_BURNED = "PUMPSWAP_MIGRATED_LP_BURNED"
    #: Nothing could be established.
    NONE = "NONE"


@dataclass(frozen=True, slots=True)
class PoolState:
    """A decoded PumpSwap pool account."""

    creator: str
    base_mint: str
    quote_mint: str
    lp_mint: str
    base_vault: str
    quote_vault: str
    lp_supply_field: int
    pool_bump: int
    index: int


def parse_pool(data: bytes | None) -> PoolState | None:
    """Decode a pool account, or `None` when the bytes are not one.

    Returns `None` rather than raising and rather than guessing, exactly as
    `curve.state.parse` does: a protocol change must produce no signal instead
    of a plausible-looking wrong one.
    """
    if data is None or len(data) != POOL_ACCOUNT_SIZE:
        return None
    if data[:8] != POOL_DISCRIMINATOR:
        return None
    try:
        fields = {}
        offset = _CREATOR_AT
        for name in _FIELD_ORDER:
            fields[name] = b58encode(data[offset : offset + 32])
            offset += 32
        (lp_supply,) = struct.unpack_from("<Q", data, offset)
    except (struct.error, IndexError):
        return None
    if any(len(value) < 32 for value in fields.values()):
        # An all-zero pubkey encodes short. A pool with a null mint or vault is
        # not a pool this module will reason about.
        return None
    return PoolState(
        lp_supply_field=lp_supply,
        pool_bump=data[8],
        index=int.from_bytes(data[9:11], "little"),
        **fields,
    )


def pool_authority_address(mint: str, *, pumpfun_program: str) -> str:
    """The pump.fun migration authority for one mint.

    Off-curve by construction, which is the point: the account that created
    the graduation pool cannot have a private key, so it cannot be a person.
    """
    address, _ = find_program_address(
        [POOL_AUTHORITY_SEED, b58decode(mint)], pumpfun_program
    )
    return address


def migration_pool_address(
    mint: str,
    *,
    pumpfun_program: str,
    pumpswap_program: str = PUMPSWAP_PROGRAM,
    quote_mint: str = WSOL_MINT,
) -> tuple[str, str]:
    """The canonical pump.fun→PumpSwap pool for a mint, and its authority.

    Computed, never searched. Two consequences worth stating: the platform
    makes no RPC call to *find* a pool, and there is no ambiguity about which
    of a mint's several pools was verified — this is the one the pump.fun
    migration creates, and any other pool is a different question this module
    does not answer.
    """
    authority = pool_authority_address(mint, pumpfun_program=pumpfun_program)
    address, _ = find_program_address(
        [
            POOL_SEED,
            MIGRATION_POOL_INDEX.to_bytes(2, "little"),
            b58decode(authority),
            b58decode(mint),
            b58decode(quote_mint),
        ],
        pumpswap_program,
    )
    return address, authority


def derive_or_none(mint: str, *, pumpfun_program: str) -> tuple[str, str] | None:
    """`migration_pool_address`, with a malformed mint answered as absence."""
    try:
        return migration_pool_address(mint, pumpfun_program=pumpfun_program)
    except (InvalidAddressError, PdaDerivationError, ValueError):
        return None
