"""SEC-1: on-chain liquidity-security verification.

Fixtures are built from the **real** account layouts decoded from mainnet
during this phase, not from toy structs — a fixture that is easier to parse
than the real thing can pass while production decoding is wrong.

The adversarial cases are the point of the file. Each one is a way to make a
token *look* secure, and each must fail closed.
"""

from __future__ import annotations

import pytest

from app.security.contract import CheckStatus, Reason
from app.security.liquidity import (
    POOL_ACCOUNT_SIZE,
    POOL_DISCRIMINATOR,
    PUMPSWAP_PROGRAM,
    WSOL_MINT,
    Mechanism,
    migration_pool_address,
    parse_pool,
    pool_authority_address,
)
from app.security.liquidity_verifier import classify
from app.services.curve.pda import b58decode
from app.services.curve.state import CurveState

pytestmark = pytest.mark.unit

PUMPFUN = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
TOKEN_PROGRAM = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
TOKEN_2022 = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"

#: A real graduated pump.fun mint, and the pool/authority that were verified
#: against mainnet for it during SEC-1.
MINT = "HG6dbpS5NS6eaL1eGQhySa3NGX83s58eowg5ucCcpump"
REAL_POOL = "5WxcQsupyQEofn16TMZozgRCz5MAnLoCocvb3b6SokW3"
REAL_AUTHORITY = "GWZr41UBqU1iWvbcfHsKWE8nxsZffsU7tzKgZmpGgk6a"
LP_MINT = "FJzsjHS7J1VhmPJrgU5dYDA5Z7LQrbnGcnGgWmtkxqhJ"
BASE_VAULT = "9G7cSyvgfsWvUqB8gur6wDgBxF32Cx9uBGt58wdv16Er"
QUOTE_VAULT = "5t3MTnmd88UpPUTyPZMsBnMBE7mxknkW4vhQtRc453uX"
OTHER_MINT = "2JtA4NaUek9EXzGx1MK2ZJh7DUPtxumpviWehazYWNMS"


# --- the derivations, pinned against mainnet-observed values -------------


class TestDerivationsMatchMainnet:
    def test_pool_authority_matches_the_observed_creator(self) -> None:
        assert pool_authority_address(MINT, pumpfun_program=PUMPFUN) == REAL_AUTHORITY

    def test_migration_pool_address_matches_the_observed_pool(self) -> None:
        pool, authority = migration_pool_address(MINT, pumpfun_program=PUMPFUN)
        assert pool == REAL_POOL
        assert authority == REAL_AUTHORITY

    def test_the_authority_is_off_curve_so_no_private_key_can_exist(self) -> None:
        from app.services.curve.pda import is_on_curve

        assert is_on_curve(b58decode(REAL_AUTHORITY)) is False


# --- fixtures ------------------------------------------------------------


def pool_bytes(
    *,
    creator: str = REAL_AUTHORITY,
    base_mint: str = MINT,
    quote_mint: str = WSOL_MINT,
    lp_mint: str = LP_MINT,
    base_vault: str = BASE_VAULT,
    quote_vault: str = QUOTE_VAULT,
    discriminator: bytes = POOL_DISCRIMINATOR,
    size: int = POOL_ACCOUNT_SIZE,
) -> bytes:
    """The 301-byte PumpSwap pool layout, exactly as decoded from mainnet."""
    raw = bytearray(size)
    raw[0:8] = discriminator
    raw[8] = 253
    raw[9:11] = (0).to_bytes(2, "little")
    offset = 11
    for value in (creator, base_mint, quote_mint, lp_mint, base_vault, quote_vault):
        raw[offset : offset + 32] = b58decode(value).rjust(32, b"\x00")
        offset += 32
    raw[offset : offset + 8] = (4_193_388_283_246).to_bytes(8, "little")
    return bytes(raw)


def account(owner: str, data: bytes) -> dict:
    import base64

    return {"owner": owner, "data": [base64.b64encode(data).decode(), "base64"]}


def token_account(
    mint: str, owner: str, amount: str = "1000", program: str = TOKEN_PROGRAM
) -> dict:
    return {
        "owner": program,
        "data": {
            "parsed": {
                "type": "account",
                "info": {"mint": mint, "owner": owner, "tokenAmount": {"amount": amount}},
            }
        },
    }


def mint_account(supply: str, program: str = TOKEN_2022) -> dict:
    return {
        "owner": program,
        "data": {"parsed": {"type": "mint", "info": {"supply": supply}}},
    }


def curve(complete: bool = True) -> CurveState:
    return CurveState(
        virtual_token_reserves=0 if complete else 878_399_025_394_841,
        virtual_sol_reserves=0 if complete else 36_646_215_824,
        real_token_reserves=0 if complete else 598_499_025_394_841,
        real_sol_reserves=0 if complete else 6_646_215_824,
        token_total_supply=1_000_000_000_000_000,
        complete=complete,
    )


DERIVED = {
    "pool": REAL_POOL,
    "pool_authority": REAL_AUTHORITY,
    "bonding_curve": "3Sz3ZCntxcGTTixQ6vd6GPx9mwVSxJFnjoJpEUPQ9HeC",
    "pumpswap_program": PUMPSWAP_PROGRAM,
    "pumpfun_program": PUMPFUN,
}


def run(**overrides):
    base = {
        "mint": MINT,
        "curve_account": account(PUMPFUN, b"\x00" * 151),
        "curve_state": curve(complete=True),
        "pool_account": account(PUMPSWAP_PROGRAM, pool_bytes()),
        "pool_state": parse_pool(pool_bytes()),
        "lp_supply": 0,
        "vaults": {
            BASE_VAULT: token_account(MINT, REAL_POOL),
            QUOTE_VAULT: token_account(WSOL_MINT, REAL_POOL),
        },
        "pumpfun_program": PUMPFUN,
        "derived": DERIVED,
        "traded_venue": "pumpswap",
        "traded_pool": REAL_POOL,
    }
    base.update(overrides)
    return classify(**base)


# --- the happy paths -----------------------------------------------------


class TestVerifiedPaths:
    def test_migrated_pool_with_burned_lp_passes(self) -> None:
        finding = run()
        assert finding.status is CheckStatus.PASS
        assert finding.mechanism is Mechanism.PUMPSWAP_MIGRATED_LP_BURNED
        assert finding.reason_codes == ()

    def test_token_still_on_its_curve_passes_with_curve_custody(self) -> None:
        finding = run(
            curve_state=curve(complete=False), traded_venue="pumpfun", traded_pool=None
        )
        assert finding.status is CheckStatus.PASS
        assert finding.mechanism is Mechanism.BONDING_CURVE_CUSTODY

    def test_the_pass_detail_never_claims_the_liquidity_is_locked(self) -> None:
        """§10: protocol custody and a locker are different facts."""
        curve_pass = run(
            curve_state=curve(complete=False), traded_venue="pumpfun", traded_pool=None
        )
        for finding in (run(), curve_pass):
            assert "lock" not in finding.detail.lower()


# --- adversarial: things designed to look secure -------------------------


class TestAdversarial:
    def test_dex_name_alone_cannot_produce_a_pass(self) -> None:
        """The headline rule. No pool, but the venue says pumpswap."""
        finding = run(pool_account=None, pool_state=None, lp_supply=None, vaults={})
        assert finding.status is not CheckStatus.PASS
        assert Reason.POOL_NOT_PROTOCOL_MIGRATED in finding.reason_codes

    def test_pool_owned_by_the_wrong_program_is_not_a_pass(self) -> None:
        finding = run(pool_account=account(TOKEN_PROGRAM, pool_bytes()))
        assert finding.status is CheckStatus.UNKNOWN
        assert Reason.POOL_PROGRAM_MISMATCH in finding.reason_codes

    def test_pool_for_a_different_mint_is_not_a_pass(self) -> None:
        data = pool_bytes(base_mint=OTHER_MINT)
        finding = run(
            pool_account=account(PUMPSWAP_PROGRAM, data), pool_state=parse_pool(data)
        )
        assert finding.status is CheckStatus.UNKNOWN
        assert Reason.POOL_MINT_MISMATCH in finding.reason_codes

    def test_pool_not_created_by_the_migration_authority_is_not_a_pass(self) -> None:
        """A real wallet as creator: this is somebody's own pool, not a migration."""
        data = pool_bytes(creator=OTHER_MINT)
        finding = run(
            pool_account=account(PUMPSWAP_PROGRAM, data), pool_state=parse_pool(data)
        )
        assert finding.status is CheckStatus.UNKNOWN
        assert Reason.POOL_NOT_PROTOCOL_MIGRATED in finding.reason_codes

    def test_outstanding_lp_supply_is_never_a_pass(self) -> None:
        finding = run(lp_supply=13_999_900)
        assert finding.status is CheckStatus.UNKNOWN
        assert Reason.LP_OUTSTANDING in finding.reason_codes

    def test_vault_held_by_someone_other_than_the_pool_is_not_a_pass(self) -> None:
        """A valid-looking vault with the wrong authority."""
        finding = run(
            vaults={
                BASE_VAULT: token_account(MINT, OTHER_MINT),
                QUOTE_VAULT: token_account(WSOL_MINT, REAL_POOL),
            }
        )
        assert finding.status is CheckStatus.UNKNOWN
        assert Reason.POOL_VAULT_INVALID in finding.reason_codes

    def test_missing_vault_is_not_a_pass(self) -> None:
        finding = run(vaults={QUOTE_VAULT: token_account(WSOL_MINT, REAL_POOL)})
        assert finding.status is CheckStatus.UNKNOWN
        assert Reason.POOL_VAULT_INVALID in finding.reason_codes

    def test_vault_for_the_wrong_mint_is_not_a_pass(self) -> None:
        finding = run(
            vaults={
                BASE_VAULT: token_account(OTHER_MINT, REAL_POOL),
                QUOTE_VAULT: token_account(WSOL_MINT, REAL_POOL),
            }
        )
        assert finding.status is CheckStatus.UNKNOWN

    def test_verified_curve_cannot_vouch_for_a_different_traded_venue(self) -> None:
        """The live bug SEC-1 found on `GbM8TcLh...`.

        Genuinely on its bonding curve *and* trading on Orca with $194k. The
        curve custody verdict is correct and about the wrong market.
        """
        finding = run(
            curve_state=curve(complete=False), traded_venue="orca", traded_pool="somewhere"
        )
        assert finding.status is CheckStatus.UNKNOWN
        assert Reason.TRADED_POOL_UNVERIFIED in finding.reason_codes

    def test_verified_pool_cannot_vouch_for_a_different_traded_pool(self) -> None:
        finding = run(traded_pool="3hvLgtY4PSGB4mz5Ax5JyPTp85a5R6zH36nWmptrByAq")
        assert finding.status is CheckStatus.UNKNOWN
        assert Reason.TRADED_POOL_UNVERIFIED in finding.reason_codes

    def test_stale_pumpfun_label_on_a_graduated_token_does_not_pass_as_curve(self) -> None:
        """Graduated, but no pool found: must not fall back to curve custody."""
        finding = run(
            curve_state=curve(complete=True),
            pool_account=None,
            pool_state=None,
            lp_supply=None,
            vaults={},
        )
        assert finding.status is CheckStatus.UNKNOWN
        assert Reason.MIGRATION_DESTINATION_UNVERIFIED in finding.reason_codes


# --- infrastructure failures must be UNKNOWN, never FAIL -----------------


class TestFailsClosedToUnknown:
    def test_unreadable_lp_supply_is_unknown(self) -> None:
        finding = run(lp_supply=None)
        assert finding.status is CheckStatus.UNKNOWN
        assert Reason.LP_CUSTODY_UNKNOWN in finding.reason_codes

    def test_undecodable_curve_is_unknown(self) -> None:
        finding = run(curve_state=None, pool_account=None, pool_state=None, vaults={})
        assert finding.status is CheckStatus.UNKNOWN
        assert Reason.BONDING_CURVE_INVALID in finding.reason_codes

    def test_undecodable_pool_is_unknown(self) -> None:
        finding = run(pool_state=None)
        assert finding.status is CheckStatus.UNKNOWN
        assert Reason.POOL_ACCOUNT_INVALID in finding.reason_codes

    def test_nothing_here_ever_returns_fail_on_infrastructure(self) -> None:
        """Infrastructure failure is an absence of evidence, not a verdict."""
        for finding in (
            run(lp_supply=None),
            run(pool_state=None),
            run(pool_account=None, pool_state=None, lp_supply=None, vaults={}),
            run(curve_state=None, pool_account=None, pool_state=None, vaults={}),
        ):
            assert finding.status is not CheckStatus.FAIL


# --- the decoder ---------------------------------------------------------


class TestPoolDecoding:
    def test_decodes_the_mainnet_layout(self) -> None:
        state = parse_pool(pool_bytes())
        assert state is not None
        assert state.base_mint == MINT
        assert state.quote_mint == WSOL_MINT
        assert state.lp_mint == LP_MINT
        assert state.creator == REAL_AUTHORITY

    def test_wrong_discriminator_refuses(self) -> None:
        assert parse_pool(pool_bytes(discriminator=b"\x00" * 8)) is None

    def test_wrong_size_refuses(self) -> None:
        assert parse_pool(pool_bytes()[:200]) is None
        assert parse_pool(pool_bytes() + b"\x00" * 8) is None

    def test_none_and_empty_refuse(self) -> None:
        assert parse_pool(None) is None
        assert parse_pool(b"") is None

    def test_the_pool_lp_supply_field_is_not_used_as_the_lp_supply(self) -> None:
        """It disagrees with the mint on mainnet, so it must not be trusted.

        Every migrated pool observed carried ~4.19e12 in this field while the
        LP mint's real supply was 0. The field is the pool's own notional
        record; the mint is the cryptographic truth.
        """
        state = parse_pool(pool_bytes())
        assert state is not None and state.lp_supply_field > 0
        # ...and a burned-LP pool still passes, because the mint says zero.
        assert run(lp_supply=0).status is CheckStatus.PASS


# --- what SEC-1 must never be able to reach ------------------------------


class TestNoExecutionPathExists:
    def test_no_signing_or_submission_symbol_is_reachable_from_sec1(self) -> None:
        """A security reader must not be able to touch a wallet.

        Asserted over the imports of the whole SEC-1 surface rather than by
        inspection, so a future edit that pulls a signer in fails here.
        """
        import app.security.evaluator as evaluator
        import app.security.liquidity as liquidity
        import app.security.liquidity_verifier as verifier

        banned = (
            "sign", "signer", "keypair", "secret", "private_key",
            "send_transaction", "sendTransaction", "submit", "wallet",
        )
        for module in (liquidity, verifier, evaluator):
            source = __import__("inspect").getsource(module).lower()
            for term in banned:
                # `real_wallet` appears in prose in the evaluator docstring;
                # what matters is that no symbol is imported or called.
                assert f"import {term}" not in source, (module.__name__, term)
                assert f"{term}(" not in source, (module.__name__, term)

    def test_the_verifier_only_ever_issues_read_calls(self) -> None:
        import inspect

        import app.security.liquidity_verifier as verifier

        source = inspect.getsource(verifier)
        # No write-shaped RPC method may appear anywhere.
        for method in (
            "sendTransaction",
            "simulateTransaction",
            "requestAirdrop",
            "signTransaction",
        ):
            assert method not in source

    def test_no_program_accounts_scan_is_used(self) -> None:
        """§16: the canonical pool is derived, never searched for.

        A `getProgramAccounts` here would be an unbounded scan of half a
        million accounts on every evaluation.
        """
        import inspect

        import app.security.liquidity_verifier as verifier

        # Checked as a quoted RPC method name: the module docstring discusses
        # `getProgramAccounts` in prose, and explaining why it is not used is
        # not the same as using it.
        assert '"getProgramAccounts"' not in inspect.getsource(verifier)


class TestNoHistoricalBackfill:
    def test_a_current_evaluation_carries_its_own_timestamp_only(self) -> None:
        """Current chain state must never be presented as entry-time evidence.

        The evaluation records when *it* ran. Nothing in the contract lets a
        reading be attributed to an earlier moment, which is what stops a
        token verified today from retroactively legitimising a trade taken
        ten days ago.
        """
        import dataclasses
        from datetime import UTC, datetime

        from app.security.contract import TokenSecurityEvaluation

        fields = {f.name for f in dataclasses.fields(TokenSecurityEvaluation)}
        # There is no "applies_from", "entry_at" or similar back-dating field.
        assert not {name for name in fields if "entry" in name or "backfill" in name}
        item = TokenSecurityEvaluation(
            mint_address=MINT,
            evaluated_at=datetime(2026, 8, 20, tzinfo=UTC),
            overall_status=__import__(
                "app.security.contract", fromlist=["SecurityStatus"]
            ).SecurityStatus.VERIFIED,
            checks=(),
        )
        assert item.evaluated_at == datetime(2026, 8, 20, tzinfo=UTC)
