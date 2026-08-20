"""HQ-6: the shared token-security contract.

The suite is organised around one property rather than around the code:

    SECURITY UNKNOWN MUST NEVER BECOME SECURITY SAFE.

Most of these tests exist to make a specific way of violating it impossible,
so several assert on the *absence* of VERIFIED rather than on a value.
"""

from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta

import pytest

from app.security.contract import (
    CHECK_FRESHNESS,
    CheckName,
    CheckStatus,
    Reason,
    SecurityCheck,
    SecurityStatus,
    TokenSecurityEvaluation,
    roll_up,
)
from app.security.evaluator import evaluate_inspection, evaluate_venue
from app.security.mint import (
    TOKEN_2022_PROGRAM,
    TOKEN_PROGRAM,
    TokenInspection,
    decode_mint_account,
)

NOW = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)


def inspection(**overrides) -> TokenInspection:
    """A clean pump.fun-style mint: Token-2022, both authorities revoked."""
    values = {
        "token_program": TOKEN_2022_PROGRAM,
        "decimals": 6,
        "mint_authority_active": False,
        "freeze_authority_active": False,
        "extensions": (),
        "raw": {},
    }
    values.update(overrides)
    return TokenInspection(**values)


def status_of(checks: list[SecurityCheck], name: CheckName) -> CheckStatus:
    for check in checks:
        if check.name is name:
            return check.status
    raise AssertionError(f"{name} was not evaluated at all")


class Snapshot:
    """Only the one field `evaluate_venue` reads."""

    def __init__(self, dex_name: str | None) -> None:
        self.dex_name = dex_name


# --- mint authority -----------------------------------------------------


def test_mint_authority_active_fails():
    checks = evaluate_inspection(inspection(mint_authority_active=True))
    assert status_of(checks, CheckName.MINT_AUTHORITY) is CheckStatus.FAIL
    codes = [code for check in checks for code in check.reason_codes]
    assert Reason.MINT_AUTHORITY_ACTIVE in codes


def test_mint_authority_revoked_passes():
    checks = evaluate_inspection(inspection(mint_authority_active=False))
    assert status_of(checks, CheckName.MINT_AUTHORITY) is CheckStatus.PASS


def test_mint_authority_unreadable_is_unknown_not_pass():
    checks = evaluate_inspection(inspection(mint_authority_active=None))
    assert status_of(checks, CheckName.MINT_AUTHORITY) is CheckStatus.UNKNOWN


# --- freeze authority ---------------------------------------------------


def test_freeze_authority_active_fails():
    checks = evaluate_inspection(inspection(freeze_authority_active=True))
    assert status_of(checks, CheckName.FREEZE_AUTHORITY) is CheckStatus.FAIL


def test_freeze_authority_revoked_passes():
    assert (
        status_of(
            evaluate_inspection(inspection(freeze_authority_active=False)),
            CheckName.FREEZE_AUTHORITY,
        )
        is CheckStatus.PASS
    )


def test_freeze_authority_unreadable_is_unknown():
    assert (
        status_of(
            evaluate_inspection(inspection(freeze_authority_active=None)),
            CheckName.FREEZE_AUTHORITY,
        )
        is CheckStatus.UNKNOWN
    )


# --- provider failure ---------------------------------------------------


def test_provider_failure_makes_every_check_unknown_and_keeps_them_present():
    """An unreadable mint must not shorten the check list.

    Dropping the checks would let `roll_up` compute VERIFIED over whatever
    survived — an infrastructure outage rendering as a clean bill of health.
    """
    checks = evaluate_inspection(None)
    names = {check.name for check in checks}
    assert names == {
        CheckName.MINT_AUTHORITY,
        CheckName.FREEZE_AUTHORITY,
        CheckName.TOKEN_PROGRAM,
        CheckName.TOKEN_EXTENSIONS,
    }
    assert all(check.status is CheckStatus.UNKNOWN for check in checks)
    assert roll_up(tuple(checks)) is SecurityStatus.UNKNOWN


# --- token program and extensions --------------------------------------


def test_unrecognised_token_program_fails():
    checks = evaluate_inspection(inspection(token_program="SomeOtherProgram1111"))
    assert status_of(checks, CheckName.TOKEN_PROGRAM) is CheckStatus.FAIL


def test_plain_spl_mint_has_extensions_not_applicable_not_unknown():
    """NOT_APPLICABLE is a complete answer; UNKNOWN is an absent one."""
    checks = evaluate_inspection(inspection(token_program=TOKEN_PROGRAM))
    assert status_of(checks, CheckName.TOKEN_EXTENSIONS) is CheckStatus.NOT_APPLICABLE
    assert roll_up(tuple(checks)) is SecurityStatus.VERIFIED


@pytest.mark.parametrize(
    "extension",
    [
        1,   # TransferFeeConfig
        12,  # DefaultAccountState
        15,  # NonTransferable
        17,  # PermanentDelegate
        20,  # TransferHook
        5,   # ConfidentialTransferMint
    ],
)
def test_dangerous_token_2022_extensions_fail(extension: int):
    checks = evaluate_inspection(inspection(extensions=(extension,)))
    assert status_of(checks, CheckName.TOKEN_EXTENSIONS) is CheckStatus.FAIL


def test_metadata_extensions_pass():
    checks = evaluate_inspection(inspection(extensions=(18, 19)))
    assert status_of(checks, CheckName.TOKEN_EXTENSIONS) is CheckStatus.PASS


def test_unclassified_extension_is_unknown_never_presumed_safe():
    checks = evaluate_inspection(inspection(extensions=(9_999,)))
    assert status_of(checks, CheckName.TOKEN_EXTENSIONS) is CheckStatus.UNKNOWN


# --- venue and liquidity security --------------------------------------


def test_recognised_venue_passes_and_says_nothing_about_custody():
    """The PumpSwap question, asserted directly.

    Since SEC-1 the liquidity verdict comes from `liquidity_verifier`, which
    reads accounts. `evaluate_venue` is venue *recognition* only and must not
    emit a liquidity check at all — if it did, recognising a name would once
    again be standing in for proving custody.
    """
    checks = evaluate_venue(Snapshot("pumpswap"))
    assert status_of(checks, CheckName.VENUE) is CheckStatus.PASS
    assert [check.name for check in checks] == [CheckName.VENUE]


def test_venue_recognition_alone_can_never_produce_a_verified_token():
    """Roll-up over venue alone must not be VERIFIED — the liquidity check is
    absent from this list, and `roll_up` is only ever given the full set."""
    checks = tuple(evaluate_venue(Snapshot("pumpswap")))
    assert CheckName.LIQUIDITY_SECURITY not in {check.name for check in checks}


def test_venue_details_never_use_the_word_locked():
    for venue in ("pumpswap", "pumpfun", None):
        for check in evaluate_venue(Snapshot(venue)):
            assert "locked" not in check.detail.lower()


def test_unrecognised_venue_fails():
    checks = evaluate_venue(Snapshot("some-random-dex"))
    assert status_of(checks, CheckName.VENUE) is CheckStatus.FAIL


def test_missing_market_snapshot_is_unknown_venue_not_failed():
    checks = evaluate_venue(None)
    assert status_of(checks, CheckName.VENUE) is CheckStatus.UNKNOWN


# --- roll-up ------------------------------------------------------------


def test_fail_dominates_unknown_and_pass():
    checks = (
        SecurityCheck(name=CheckName.MINT_AUTHORITY, status=CheckStatus.PASS),
        SecurityCheck(name=CheckName.VENUE, status=CheckStatus.UNKNOWN),
        SecurityCheck(name=CheckName.FREEZE_AUTHORITY, status=CheckStatus.FAIL),
    )
    assert roll_up(checks) is SecurityStatus.FAILED


def test_one_unknown_prevents_verified():
    checks = (
        SecurityCheck(name=CheckName.MINT_AUTHORITY, status=CheckStatus.PASS),
        SecurityCheck(name=CheckName.LIQUIDITY_SECURITY, status=CheckStatus.UNKNOWN),
    )
    assert roll_up(checks) is SecurityStatus.UNKNOWN


def test_empty_check_list_is_unknown_never_vacuously_verified():
    assert roll_up(()) is SecurityStatus.UNKNOWN


# --- freshness ----------------------------------------------------------


def evaluation(evaluated_at: datetime, *names: CheckName) -> TokenSecurityEvaluation:
    checks = tuple(
        SecurityCheck(name=name, status=CheckStatus.PASS) for name in names
    )
    return TokenSecurityEvaluation(
        mint_address="mint",
        evaluated_at=evaluated_at,
        overall_status=roll_up(checks),
        checks=checks,
    )


def test_each_check_ages_on_its_own_window():
    """Authority facts outlive market facts, and the object knows which."""
    aged = NOW - timedelta(minutes=30)
    item = evaluation(aged, CheckName.MINT_AUTHORITY, CheckName.VENUE)
    stale = item.stale_checks(now=NOW)
    assert CheckName.VENUE in stale
    assert CheckName.MINT_AUTHORITY not in stale
    assert item.is_fresh(now=NOW) is False


def test_fresh_at_the_boundary_and_stale_one_second_past_it():
    window = CHECK_FRESHNESS[CheckName.VENUE]
    exactly = evaluation(NOW - window, CheckName.VENUE)
    assert exactly.is_fresh(now=NOW) is True
    past = evaluation(NOW - window - timedelta(seconds=1), CheckName.VENUE)
    assert past.is_fresh(now=NOW) is False


def test_reason_codes_are_deduplicated_and_ordered():
    checks = (
        SecurityCheck(
            name=CheckName.MINT_AUTHORITY,
            status=CheckStatus.FAIL,
            reason_codes=(Reason.MINT_AUTHORITY_ACTIVE,),
        ),
        SecurityCheck(
            name=CheckName.FREEZE_AUTHORITY,
            status=CheckStatus.FAIL,
            reason_codes=(Reason.MINT_AUTHORITY_ACTIVE, Reason.FREEZE_AUTHORITY_ACTIVE),
        ),
    )
    item = TokenSecurityEvaluation(
        mint_address="mint",
        evaluated_at=NOW,
        overall_status=roll_up(checks),
        checks=checks,
    )
    assert item.reason_codes == (
        Reason.MINT_AUTHORITY_ACTIVE,
        Reason.FREEZE_AUTHORITY_ACTIVE,
    )


# --- reason-code stability ---------------------------------------------


def test_reason_codes_reused_from_the_real_wallet_vocabulary_match_exactly():
    """One code, one meaning, platform-wide.

    If these ever drift, a stored real-wallet row and a stored shared row stop
    being readable side by side, and every dashboard filtering on a code
    silently under-reports.
    """
    from app.real_wallet_safety.service import Reason as RealWalletReason

    for name in (
        "MINT_AUTHORITY_ACTIVE",
        "FREEZE_AUTHORITY_ACTIVE",
        "UNSUPPORTED_TOKEN_PROGRAM",
        "UNSUPPORTED_TOKEN_EXTENSION",
        "VENUE_UNSUPPORTED",
        "TOKEN_CONFIGURATION_UNKNOWN",
    ):
        assert getattr(Reason, name) == getattr(RealWalletReason, name)


# --- malformed RPC data -------------------------------------------------


def test_malformed_mint_account_raises_rather_than_guessing():
    with pytest.raises(ValueError):
        decode_mint_account({"owner": TOKEN_PROGRAM, "data": ["", "base64"]})


def test_short_mint_account_raises():
    with pytest.raises(ValueError):
        decode_mint_account(
            {
                "owner": TOKEN_PROGRAM,
                "data": [base64.b64encode(b"\x00" * 10).decode(), "base64"],
            }
        )


def test_incomplete_response_raises():
    with pytest.raises(ValueError):
        decode_mint_account({"owner": None, "data": None})
