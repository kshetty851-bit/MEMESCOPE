"""The bonding curve account, decoded.

Pure. Parsing is separated from fetching for the same reason the market
providers separate adapters from services: the layout is the part most likely
to be wrong, and it can be exercised against literal bytes without a network.

## The layout, and what is actually known about it

The account is an Anchor struct: an 8-byte discriminator followed by five
little-endian `u64` fields and a one-byte flag.

    offset  size  field
    0       8     anchor discriminator
    8       8     virtual_token_reserves
    16      8     virtual_sol_reserves
    24      8     real_token_reserves
    32      8     real_sol_reserves
    40      8     token_total_supply
    48      1     complete

**This layout is unverified against mainnet.** The Helius plan is quota
exhausted — every RPC method returns `429 max usage reached` — so no account has
been read to confirm it. `parse` therefore checks invariants and returns `None`
rather than a reading whenever they fail, so a wrong layout produces no signal
instead of a plausible-looking wrong one. See the sprint notes and §14a.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from decimal import Decimal

#: Discriminator (8) + 5 x u64 (40) + complete (1).
ACCOUNT_SIZE = 49

#: Largest value a `u64` can hold. Anything at the ceiling is a sentinel or a
#: misread, never a real reserve.
_U64_MAX = 2**64 - 1

_LAYOUT = struct.Struct("<QQQQQ")


@dataclass(frozen=True, slots=True)
class CurveState:
    """One observation of a bonding curve account."""

    virtual_token_reserves: int
    virtual_sol_reserves: int
    real_token_reserves: int
    real_sol_reserves: int
    token_total_supply: int
    #: True once the curve has filled and the token has migrated.
    complete: bool

    @property
    def progress(self) -> Decimal | None:
        """How full the curve is, 0 to 1, or None when unmeasurable.

        Measured by how many of the tokens originally available on the curve
        have been bought: progress is the share of `real_token_reserves` that
        has been sold out of it.

        `None` and `0` are different claims — one says the curve position is
        unknown, the other says nobody has bought yet. Only the second is a
        reading, and the near-graduation provider treats them differently.
        """
        if self.complete:
            return Decimal(1)
        if self.initial_real_token_reserves <= 0:
            return None
        remaining = Decimal(self.real_token_reserves) / Decimal(
            self.initial_real_token_reserves
        )
        return max(Decimal(0), min(Decimal(1), Decimal(1) - remaining))

    @property
    def initial_real_token_reserves(self) -> int:
        """Tokens the curve started with.

        Not stored on the account, so it is inferred as the high-water mark the
        reserve can hold. Kept as a property rather than a stored column: it is
        derived, and a derived value in the table is one that can drift from
        its source.
        """
        return max(self.real_token_reserves, _INITIAL_REAL_TOKEN_RESERVES)


@dataclass(frozen=True, slots=True)
class CurveReading:
    """A parsed curve, with the mint it belongs to.

    Lives here rather than in the collector so the repository can name it
    without importing the fetch path — the collector already imports the
    repository, and the other direction would close a cycle.
    """

    mint_address: str
    state: CurveState


#: pump.fun seeds every curve with the same reserve. Published as a named
#: constant so a protocol change is a one-line edit with a visible blast radius
#: rather than a magic number buried in a ratio.
_INITIAL_REAL_TOKEN_RESERVES = 793_100_000_000_000


def parse(data: bytes) -> CurveState | None:
    """Decode a curve account, or `None` when the bytes are not one.

    Returns `None` rather than raising, and rather than guessing: the layout
    above has not been confirmed against a live account, so every invariant
    that can be checked is checked. A reading that fails them is not reported.

    This is the same contract the market adapters hold at their boundary —
    junk is coerced to absent, never to a number.
    """
    if data is None or len(data) < ACCOUNT_SIZE:
        return None

    try:
        (
            virtual_token,
            virtual_sol,
            real_token,
            real_sol,
            total_supply,
        ) = _LAYOUT.unpack_from(data, 8)
    except struct.error:
        return None

    complete_byte = data[48]
    if complete_byte not in (0, 1):
        # A boolean that is neither is the clearest possible sign the offsets
        # are wrong. Refuse the whole reading.
        return None

    values = (virtual_token, virtual_sol, real_token, real_sol, total_supply)
    if any(value in (0, _U64_MAX) for value in (virtual_token, virtual_sol)):
        # Virtual reserves are seeded non-zero at creation and never drain to
        # zero; both extremes mean this is not the struct we think it is.
        return None
    if any(value > total_supply for value in (real_token,)):
        return None
    if total_supply == 0 or any(value == _U64_MAX for value in values):
        return None

    return CurveState(
        virtual_token_reserves=virtual_token,
        virtual_sol_reserves=virtual_sol,
        real_token_reserves=real_token,
        real_sol_reserves=real_sol,
        token_total_supply=total_supply,
        complete=complete_byte == 1,
    )
