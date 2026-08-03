"""Program-derived addresses for bonding curves.

Pure maths, so every property here is checkable without a network. What cannot
be checked offline is whether a derived address matches mainnet — that needs one
RPC read, and the Helius plan is quota exhausted. The properties below are what
make the derivation *correct by construction* in the meantime.
"""

from __future__ import annotations

import pytest

from app.services.curve.pda import (
    CURVE_SEED,
    InvalidAddressError,
    b58decode,
    b58encode,
    bonding_curve_address,
    find_program_address,
    is_on_curve,
)

pytestmark = pytest.mark.unit

PUMP_PROGRAM = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
MINT = "HHbRJ9Fw2tPxETGSsaeQhpgdizfVafLvXK7eo5mwpump"
OTHER_MINT = "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263"

#: The all-zero key. Base58-encodes to 32 '1's, which is the canonical
#: round-trip case for leading-zero handling.
SYSTEM_PROGRAM = "1" * 32


class TestBase58:
    def test_round_trips(self) -> None:
        assert b58encode(b58decode(MINT)) == MINT
        assert b58encode(b58decode(PUMP_PROGRAM)) == PUMP_PROGRAM

    def test_a_public_key_decodes_to_32_bytes(self) -> None:
        """The property every downstream step depends on."""
        assert len(b58decode(MINT)) == 32
        assert len(b58decode(PUMP_PROGRAM)) == 32

    def test_leading_zeros_survive(self) -> None:
        """Leading '1's are zero bytes and are lost by naive integer maths.

        Getting this wrong shortens the key and silently derives a different
        address.
        """
        assert b58decode(SYSTEM_PROGRAM) == b"\x00" * 32
        assert b58encode(b"\x00" * 32) == SYSTEM_PROGRAM

    def test_empty_and_invalid_input_is_rejected(self) -> None:
        with pytest.raises(InvalidAddressError):
            b58decode("")
        # 0, O, I and l are excluded from the alphabet precisely because they
        # are confusable; accepting them would decode a typo into an address.
        for bad in ("0", "O", "I", "l", "abc!def"):
            with pytest.raises(InvalidAddressError):
                b58decode(bad)


class TestOnCurve:
    def test_a_real_public_key_is_on_the_curve(self) -> None:
        """Every account created from a keypair decompresses to a valid point."""
        assert is_on_curve(b58decode(PUMP_PROGRAM))
        assert is_on_curve(b58decode(MINT))

    def test_wrong_length_is_never_on_the_curve(self) -> None:
        assert not is_on_curve(b"")
        assert not is_on_curve(b"\x00" * 31)
        assert not is_on_curve(b"\x00" * 33)

    def test_it_distinguishes_at_all(self) -> None:
        """A check that answered the same for everything would let a derived
        address collide with a real key and nothing would notice."""
        results = {is_on_curve(bytes([index]) * 32) for index in range(64)}
        assert results == {True, False}


class TestDerivation:
    def test_it_is_deterministic(self) -> None:
        """Two callers deriving the same seeds must reach the same account, or
        the collector cannot address a curve it has never seen."""
        assert bonding_curve_address(MINT, program_id=PUMP_PROGRAM) == (
            bonding_curve_address(MINT, program_id=PUMP_PROGRAM)
        )

    def test_the_result_is_off_the_curve(self) -> None:
        """The guarantee that makes a PDA a PDA.

        If the address were on the curve a private key could exist for it, and
        the program's exclusive authority over the account would be fiction.
        """
        address = bonding_curve_address(MINT, program_id=PUMP_PROGRAM)
        assert not is_on_curve(b58decode(address))

    def test_it_yields_a_32_byte_key(self) -> None:
        address = bonding_curve_address(MINT, program_id=PUMP_PROGRAM)
        assert len(b58decode(address)) == 32

    def test_different_mints_derive_different_curves(self) -> None:
        assert bonding_curve_address(MINT, program_id=PUMP_PROGRAM) != (
            bonding_curve_address(OTHER_MINT, program_id=PUMP_PROGRAM)
        )

    def test_the_program_is_part_of_the_derivation(self) -> None:
        """Same seeds under a different program must not collide."""
        assert bonding_curve_address(MINT, program_id=PUMP_PROGRAM) != (
            bonding_curve_address(MINT, program_id=OTHER_MINT)
        )

    def test_the_bump_is_canonical(self) -> None:
        """Bumps descend from 255, so the first off-curve hit is the canonical
        address. Ascending would derive a valid but different account."""
        _, bump = find_program_address([CURVE_SEED, b58decode(MINT)], PUMP_PROGRAM)
        assert 0 <= bump <= 255

        # Every bump above the canonical one must have been on the curve, which
        # is exactly why it was skipped.
        import hashlib

        prefix = CURVE_SEED + b58decode(MINT)
        program = b58decode(PUMP_PROGRAM)
        for higher in range(255, bump, -1):
            digest = hashlib.sha256(
                prefix + bytes([higher]) + program + b"ProgramDerivedAddress"
            ).digest()
            assert is_on_curve(digest)

    def test_the_seed_is_the_documented_one(self) -> None:
        assert CURVE_SEED == b"bonding-curve"

    def test_a_malformed_mint_raises_rather_than_deriving_nonsense(self) -> None:
        with pytest.raises(InvalidAddressError):
            bonding_curve_address("not a key!", program_id=PUMP_PROGRAM)
