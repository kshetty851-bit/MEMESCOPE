"""Recognised venues, and the limit of what pump.fun custody can answer.

Added with the market-universe generation: the gate refused every token in
that population, and the reason was scope rather than danger.
"""

from __future__ import annotations

from app.core.config import settings
from app.security.contract import CheckName, CheckStatus, Reason
from app.security.entry_policy import MANDATORY_CHECKS, NOT_APPLICABLE_ALLOWED
from app.security.liquidity_verifier import classify

PUMPFUN = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
DERIVED = {"pool": "PoolAddr", "pool_authority": "AuthAddr", "bonding_curve": "CurveAddr"}


def _judge(**kw):
    base = dict(
        mint="Mint1111111111111111111111111111111111111111",
        curve_account=None,
        curve_state=None,
        pool_account=None,
        pool_state=None,
        lp_supply=None,
        vaults={},
        pumpfun_program=PUMPFUN,
        derived=DERIVED,
        traded_venue=None,
        traded_pool=None,
    )
    base.update(kw)
    return classify(**base)


class TestTheRealWalletSurfaceIsUnchanged:
    def test_the_two_venue_lists_are_separate_settings(self) -> None:
        """Splitting them is the point: admitting a market to the evaluator
        must not widen where the real wallet may send money."""
        assert list(settings.REAL_WALLET_SAFETY_SUPPORTED_VENUES) == ["pumpfun", "pumpswap"]
        assert "raydium" in settings.SECURITY_RECOGNISED_VENUES
        assert "meteora" in settings.SECURITY_RECOGNISED_VENUES
        assert "orca" in settings.SECURITY_RECOGNISED_VENUES


class TestCustodyScope:
    def test_a_token_that_was_never_pumpfun_is_out_of_scope(self) -> None:
        finding = _judge(traded_venue="meteora")
        assert finding.status is CheckStatus.NOT_APPLICABLE
        assert Reason.POOL_CUSTODY_OUT_OF_SCOPE in finding.reason_codes

    def test_it_says_plainly_that_custody_is_not_verified(self) -> None:
        """The detail must not read as a clean bill of health."""
        finding = _judge(traded_venue="raydium")
        assert "not verified" in finding.detail
        assert finding.evidence["custody_verified"] is False

    def test_an_unrecognised_venue_is_still_unresolved_not_excused(self) -> None:
        finding = _judge(traded_venue="some-new-amm")
        assert finding.status is CheckStatus.UNKNOWN
        assert Reason.POOL_NOT_PROTOCOL_MIGRATED in finding.reason_codes

    def test_a_pumpfun_token_with_no_pool_is_still_unresolved(self) -> None:
        """The pump.fun population keeps the full check. A graduated token
        whose destination cannot be found is a gap, not a scope question."""
        finding = _judge(
            curve_account={"owner": PUMPFUN},
            traded_venue="pumpswap",
        )
        assert finding.status is CheckStatus.UNKNOWN

    def test_no_venue_at_all_is_not_excused(self) -> None:
        finding = _judge(traded_venue=None)
        assert finding.status is CheckStatus.UNKNOWN


class TestTheGateStillDemandsTheRugChecks:
    def test_the_authority_checks_remain_mandatory(self) -> None:
        for name in (
            CheckName.MINT_AUTHORITY,
            CheckName.FREEZE_AUTHORITY,
            CheckName.TOKEN_PROGRAM,
        ):
            assert name in MANDATORY_CHECKS
            assert name not in NOT_APPLICABLE_ALLOWED, (
                f"{name} must never be waived — it is a rug vector, not a scope question"
            )
