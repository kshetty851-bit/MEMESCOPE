"""Decoding the bonding curve account, and deriving progress from it.

The layout is the part most likely to be wrong. It is now verified against
mainnet (Sprint 13), which is also how Sprint 14's fix was found: a real
graduated account zeroes its reserves on completion, and the invariant that
"virtual reserves never drain to zero" was true only while a curve is still
open. `TestCompletedAccounts` regresses against those exact observed bytes.

The tests that matter most otherwise are still the refusals: a wrong reading
must be refused rather than reported, for an *incomplete* curve exactly as
before.
"""

from __future__ import annotations

import struct
from decimal import Decimal

import pytest

from app.services.curve.state import ACCOUNT_SIZE, CurveState, parse

pytestmark = pytest.mark.unit

#: What pump.fun seeds a curve with. Used to build realistic account bytes.
INITIAL_REAL_TOKENS = 793_100_000_000_000
TOTAL_SUPPLY = 1_000_000_000_000_000
VIRTUAL_TOKENS = 1_073_000_000_000_000
VIRTUAL_SOL = 30_000_000_000


def account(
    *,
    virtual_token: int = VIRTUAL_TOKENS,
    virtual_sol: int = VIRTUAL_SOL,
    real_token: int = INITIAL_REAL_TOKENS,
    real_sol: int = 0,
    total_supply: int = TOTAL_SUPPLY,
    complete: int = 0,
    discriminator: bytes = b"\x01" * 8,
    trailing: bytes = b"",
) -> bytes:
    """Account bytes in the documented layout."""
    return (
        discriminator
        + struct.pack(
            "<QQQQQ", virtual_token, virtual_sol, real_token, real_sol, total_supply
        )
        + bytes([complete])
        + trailing
    )


class TestParsing:
    def test_it_reads_the_documented_layout(self) -> None:
        state = parse(account(real_sol=12_345))

        assert state is not None
        assert state.virtual_token_reserves == VIRTUAL_TOKENS
        assert state.virtual_sol_reserves == VIRTUAL_SOL
        assert state.real_token_reserves == INITIAL_REAL_TOKENS
        assert state.real_sol_reserves == 12_345
        assert state.token_total_supply == TOTAL_SUPPLY
        assert state.complete is False

    def test_it_reads_the_complete_flag(self) -> None:
        """The one field that states graduation as a fact rather than inferring
        it from a venue transition."""
        assert parse(account(complete=1)).complete is True  # type: ignore[union-attr]
        assert parse(account(complete=0)).complete is False  # type: ignore[union-attr]

    def test_trailing_bytes_do_not_break_it(self) -> None:
        """Anchor accounts are often allocated larger than their struct."""
        assert parse(account(trailing=b"\x00" * 64)) is not None

    def test_the_expected_size_is_declared(self) -> None:
        assert ACCOUNT_SIZE == 49
        assert len(account()) == ACCOUNT_SIZE


class TestRefusal:
    """A wrong layout must produce no reading, never a plausible wrong one."""

    def test_short_data_is_refused(self) -> None:
        assert parse(b"") is None
        assert parse(b"\x00" * 48) is None

    def test_none_is_refused(self) -> None:
        assert parse(None) is None  # type: ignore[arg-type]

    def test_a_non_boolean_flag_is_refused(self) -> None:
        """The clearest possible sign the offsets are wrong.

        If byte 48 is neither 0 nor 1 the struct is not where we think it is,
        and every field read from it is suspect — so the whole reading goes.
        """
        assert parse(account(complete=7)) is None
        assert parse(account(complete=255)) is None

    def test_zero_virtual_reserves_are_refused_on_an_open_curve(self) -> None:
        """Virtual reserves are seeded non-zero and never drain to zero
        *while the curve is still open* — reading zero there means the offsets
        are wrong, not that the curve is empty.

        Scoped to `complete=0` deliberately: `TestCompletedAccounts` covers the
        one case where zero is the correct reading, not a misread.
        """
        assert parse(account(virtual_token=0, complete=0)) is None
        assert parse(account(virtual_sol=0, complete=0)) is None

    def test_saturated_u64_values_are_refused_regardless_of_completion(self) -> None:
        """A field at the u64 ceiling is a sentinel or a misread, never a
        reserve — completion does not change that. Only zero was the
        false-positive invariant Sprint 14 fixed; the ceiling still is not."""
        ceiling = 2**64 - 1
        assert parse(account(virtual_token=ceiling)) is None
        assert parse(account(virtual_sol=ceiling)) is None
        assert parse(account(real_sol=ceiling, total_supply=ceiling)) is None
        assert parse(account(virtual_token=ceiling, complete=1)) is None
        assert parse(account(virtual_sol=ceiling, complete=1)) is None

    def test_reserves_exceeding_supply_are_refused(self) -> None:
        """A curve cannot hold more tokens than exist."""
        assert parse(account(real_token=TOTAL_SUPPLY + 1)) is None

    def test_zero_supply_is_refused(self) -> None:
        assert parse(account(total_supply=0)) is None

    def test_random_bytes_are_overwhelmingly_refused(self) -> None:
        """The practical statement of the invariants: feeding the parser data
        that is not a curve account should almost never yield a reading."""
        accepted = 0
        for seed in range(200):
            data = bytes(((seed * 37 + index * 11) % 256) for index in range(64))
            if parse(data) is not None:
                accepted += 1
        assert accepted <= 2, f"{accepted}/200 arbitrary buffers parsed as curves"


class TestCompletedAccounts:
    """Regression: the exact shape of a real graduated account.

    Observed live in Sprint 13 via the standard-RPC path (no Helius key)
    against two real pump.fun mints on `api.mainnet-beta.solana.com`. Both
    returned `complete_byte=1` with every reserve field zeroed and
    `token_total_supply` unchanged at the seeded constant. The pre-Sprint-14
    parser refused both — the bug this sprint fixes.
    """

    def test_a_real_graduated_account_is_accepted(self) -> None:
        """The literal observed state: all four reserves zero, complete=1."""
        state = parse(
            account(
                virtual_token=0,
                virtual_sol=0,
                real_token=0,
                real_sol=0,
                total_supply=TOTAL_SUPPLY,
                complete=1,
            )
        )

        assert state is not None
        assert state.complete is True
        assert state.virtual_token_reserves == 0
        assert state.virtual_sol_reserves == 0
        assert state.real_token_reserves == 0
        assert state.real_sol_reserves == 0

    def test_it_survives_the_extra_account_padding_actually_observed(self) -> None:
        """The two live accounts were 115 and 151 bytes — larger than the
        49-byte struct, which `trailing` already covers, but worth pinning to
        the exact sizes seen rather than an arbitrary padding length."""
        for total_length in (115, 151):
            padded = account(
                virtual_token=0,
                virtual_sol=0,
                real_token=0,
                real_sol=0,
                total_supply=TOTAL_SUPPLY,
                complete=1,
                trailing=b"\x00" * (total_length - ACCOUNT_SIZE),
            )
            assert len(padded) == total_length
            state = parse(padded)
            assert state is not None
            assert state.complete is True

    def test_a_completed_curve_with_zero_reserves_reports_full_progress(self) -> None:
        """The whole point of accepting the reading: `complete` is the
        authority (existing behaviour), and now the reserves it sits beside are
        no longer rejected before `progress` ever gets to run."""
        state = parse(account(real_token=0, real_sol=0, complete=1))

        assert state is not None
        assert state.progress == Decimal(1)

    def test_zero_reserves_still_refused_on_an_incomplete_curve(self) -> None:
        """The other half of the fix's precision: zero reserves are only a
        valid reading *because* the curve completed. The same bytes with
        `complete=0` are exactly the misread the original invariant guarded
        against, and must stay refused.
        """
        assert (
            parse(
                account(
                    virtual_token=0,
                    virtual_sol=0,
                    real_token=0,
                    real_sol=0,
                    total_supply=TOTAL_SUPPLY,
                    complete=0,
                )
            )
            is None
        )

    def test_a_malformed_flag_byte_is_still_refused_alongside_zero_reserves(
        self,
    ) -> None:
        """A non-boolean flag is refused before completion is even considered
        — zero reserves must not smuggle a bad offset through by coincidence."""
        assert (
            parse(
                account(
                    virtual_token=0,
                    virtual_sol=0,
                    real_token=0,
                    real_sol=0,
                    complete=7,
                )
            )
            is None
        )


class TestProgress:
    def test_an_untouched_curve_reads_as_zero(self) -> None:
        """Nobody has bought yet. Distinct from unknown."""
        state = parse(account(real_token=INITIAL_REAL_TOKENS))
        assert state is not None
        assert state.progress == Decimal(0)

    def test_a_half_sold_curve_reads_as_half(self) -> None:
        state = parse(account(real_token=INITIAL_REAL_TOKENS // 2))
        assert state is not None
        assert state.progress == pytest.approx(Decimal("0.5"), abs=Decimal("0.001"))

    def test_a_drained_curve_reads_as_full(self) -> None:
        state = parse(account(real_token=0))
        assert state is not None
        assert state.progress == Decimal(1)

    def test_a_completed_curve_is_full_regardless_of_reserves(self) -> None:
        """`complete` is the authority. A migrated curve is finished whatever
        its reserve field happens to hold afterwards."""
        state = parse(account(real_token=INITIAL_REAL_TOKENS, complete=1))
        assert state is not None
        assert state.progress == Decimal(1)

    def test_progress_stays_in_range(self) -> None:
        for reserve in (0, 1, INITIAL_REAL_TOKENS, TOTAL_SUPPLY):
            state = parse(account(real_token=reserve))
            assert state is not None
            progress = state.progress
            assert progress is not None
            assert Decimal(0) <= progress <= Decimal(1)

    def test_progress_is_monotonic_as_the_curve_fills(self) -> None:
        """The property the near-graduation velocity component depends on."""
        readings = []
        for remaining in (INITIAL_REAL_TOKENS, INITIAL_REAL_TOKENS // 2, 0):
            state = parse(account(real_token=remaining))
            assert state is not None
            readings.append(state.progress)
        assert readings == sorted(readings)  # type: ignore[type-var]

    def test_it_is_derived_not_stored(self) -> None:
        """Progress is a property, so a corrected derivation needs no migration
        and cannot drift from the reserves it comes from."""
        assert "progress" not in CurveState.__annotations__
        assert isinstance(CurveState.progress, property)
