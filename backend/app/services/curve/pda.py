"""Program-derived addresses for pump.fun bonding curves.

Pure: base58, SHA-256 and modular arithmetic. No I/O, no clock, no randomness,
so the derivation is testable without a network and reproducible forever.

A bonding curve account lives at the program address derived from
`["bonding-curve", mint]` under the pump.fun program. Deriving it locally is
what makes curve collection a single batched RPC read rather than an index
lookup per token.

Implemented here rather than pulled in as a dependency: the whole of what is
needed is base58 plus an ed25519 point check, and adding a Solana SDK to get
sixty lines would bring a large surface for one function — the same trade the
compose-contract test makes when it parses YAML with a regex.
"""

from __future__ import annotations

import hashlib

#: Bitcoin-style base58. Excludes 0, O, I and l, which is the whole point.
_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_INDEX = {char: value for value, char in enumerate(_ALPHABET)}

#: Solana's marker, appended before hashing so a derived address can never
#: collide with a real public key by construction.
_PDA_MARKER = b"ProgramDerivedAddress"

#: The seed pump.fun uses for its curve accounts.
CURVE_SEED = b"bonding-curve"

# --- ed25519 curve parameters ------------------------------------------------
_P = 2**255 - 19
_D = (-121665 * pow(121666, _P - 2, _P)) % _P


class InvalidAddressError(ValueError):
    """A string that is not a valid base58 public key."""


class PdaDerivationError(RuntimeError):
    """No off-curve address existed for these seeds.

    Cryptographically improbable — roughly one seed set in 2^256 — but raising
    beats returning a wrong address.
    """


def b58decode(value: str) -> bytes:
    """Decode base58 to raw bytes."""
    if not value:
        raise InvalidAddressError("empty address")

    number = 0
    for char in value:
        digit = _INDEX.get(char)
        if digit is None:
            raise InvalidAddressError(f"invalid base58 character {char!r}")
        number = number * 58 + digit

    body = number.to_bytes((number.bit_length() + 7) // 8, "big") if number else b""
    # Leading '1's are leading zero bytes, and are lost by the integer maths.
    padding = len(value) - len(value.lstrip("1"))
    return b"\x00" * padding + body


def b58encode(raw: bytes) -> str:
    """Encode raw bytes as base58."""
    number = int.from_bytes(raw, "big")
    encoded = ""
    while number:
        number, remainder = divmod(number, 58)
        encoded = _ALPHABET[remainder] + encoded

    padding = len(raw) - len(raw.lstrip(b"\x00"))
    return "1" * padding + (encoded or "")


def is_on_curve(candidate: bytes) -> bool:
    """Whether 32 bytes decompress to a valid ed25519 point.

    A program-derived address must **not** be on the curve: if it were, a
    private key could exist for it and the program's exclusive authority over
    the account would be an illusion. This is the check that guarantees it.

    Decompression follows the ed25519 definition: the low 255 bits are `y`, and
    a point exists when `x^2 = (y^2 - 1) / (d*y^2 + 1)` has a square root
    modulo p.
    """
    if len(candidate) != 32:
        return False

    y = int.from_bytes(candidate, "little") & ((1 << 255) - 1)
    if y >= _P:
        return False

    numerator = (y * y - 1) % _P
    denominator = (_D * y * y + 1) % _P
    if denominator == 0:
        return False

    x_squared = numerator * pow(denominator, _P - 2, _P) % _P
    if x_squared == 0:
        return True

    root = pow(x_squared, (_P + 3) // 8, _P)
    if (root * root - x_squared) % _P == 0:
        return True
    # The other candidate root, multiplied by sqrt(-1).
    root = root * pow(2, (_P - 1) // 4, _P) % _P
    return (root * root - x_squared) % _P == 0


def find_program_address(seeds: list[bytes], program_id: str) -> tuple[str, int]:
    """The first off-curve address for these seeds, and its bump.

    Bumps descend from 255 so the result is canonical: two callers deriving the
    same seeds always get the same address, which is what lets the collector
    address an account it has never seen.
    """
    program = b58decode(program_id)
    prefix = b"".join(seeds)

    for bump in range(255, -1, -1):
        digest = hashlib.sha256(prefix + bytes([bump]) + program + _PDA_MARKER).digest()
        if not is_on_curve(digest):
            return b58encode(digest), bump

    raise PdaDerivationError(f"no off-curve address for seeds under {program_id}")


def bonding_curve_address(mint_address: str, *, program_id: str) -> str:
    """The bonding curve account for one mint."""
    address, _ = find_program_address([CURVE_SEED, b58decode(mint_address)], program_id)
    return address
