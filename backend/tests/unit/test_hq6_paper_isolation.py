"""HQ-6 must not have changed a single Paper Wallet entry decision.

This is the phase's most important test file and its assertions are
deliberately counter-intuitive: several of them prove that a token the shared
evaluator would call **FAILED is still bought**.

That is not an oversight being pinned in place. HQ-6 measures what enforcing
the security gate would cost *before* anyone enables it, so the wallet has to
keep trading exactly as it did while the evidence is collected. When the gate
is eventually enabled, these tests are the ones that must be rewritten, and
their failure is the signal that the behaviour genuinely changed.
"""

from __future__ import annotations

import inspect
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.paper import eligibility
from app.paper import service as paper_service
from app.paper.eligibility import Observation, Refusal
from app.security.contract import (
    CheckName,
    CheckStatus,
    SecurityCheck,
    SecurityStatus,
    roll_up,
)
from app.security.evaluator import evaluate_inspection
from app.security.mint import TOKEN_2022_PROGRAM, TokenInspection

pytestmark = pytest.mark.unit

NOW = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)
NOTHING: frozenset[str] = frozenset()


def observation(**overrides: object) -> Observation:
    base: dict[str, object] = {
        "mint_address": "probe",
        "rank": 1,
        "has_snapshot": True,
        "observed_at": NOW,
        "price_usd": Decimal("0.01"),
        "liquidity_usd": Decimal(20_000),
        "market_cap": Decimal(150_000),
        "trading_status": "trading",
    }
    base.update(overrides)
    return Observation(**base)  # type: ignore[arg-type]


class TestTheEntryContractIsUntouched:
    """`Observation` and `judge()` must know nothing about security."""

    def test_observation_carries_no_security_field(self) -> None:
        # An earlier phase added `liquidity_security_status` here off the back
        # of a function that never existed (`verify_liquidity_security`,
        # removed in 3bac791). Nothing security-shaped belongs on this type
        # until the gate is deliberately enabled.
        fields = set(Observation.__dataclass_fields__)
        assert not {
            name
            for name in fields
            if "secur" in name or "authority" in name or "mint_auth" in name
        }

    def test_judge_signature_is_unchanged(self) -> None:
        parameters = list(inspect.signature(eligibility.judge).parameters)
        assert parameters == ["observation", "held_ever", "open_now"]

    def test_refusal_vocabulary_gained_no_security_reason(self) -> None:
        assert {member.value for member in Refusal} == {
            "already_traded",
            "already_held",
            "no_market_data",
            "no_price",
            "no_liquidity",
            "not_tradeable",
            "insufficient_paper_cash",
        }

    def test_judge_module_does_not_import_the_security_package(self) -> None:
        source = inspect.getsource(eligibility)
        assert "app.security" not in source


class TestBeforeEqualsAfter:
    """The published conditions, pinned exactly as they behaved pre-HQ-6."""

    @pytest.mark.parametrize(
        ("overrides", "expected"),
        [
            ({}, None),
            ({"has_snapshot": False, "observed_at": None}, Refusal.NO_MARKET_DATA),
            ({"observed_at": None}, Refusal.NO_MARKET_DATA),
            ({"price_usd": None}, Refusal.NO_PRICE),
            ({"price_usd": Decimal(0)}, Refusal.NO_PRICE),
            ({"trading_status": "unknown"}, Refusal.NOT_TRADEABLE),
            ({"trading_status": "inactive"}, Refusal.NOT_TRADEABLE),
            ({"liquidity_usd": None}, Refusal.NO_LIQUIDITY),
            ({"liquidity_usd": Decimal(0)}, Refusal.NO_LIQUIDITY),
        ],
    )
    def test_verdicts_match_the_published_conditions(
        self, overrides: dict[str, object], expected: Refusal | None
    ) -> None:
        verdict = eligibility.judge(
            observation(**overrides), held_ever=NOTHING, open_now=NOTHING
        )
        if expected is None:
            assert verdict.eligible
            assert verdict.refused_for is None
        else:
            assert not verdict.eligible
            assert verdict.refused_for == expected.value


class TestSecurityDoesNotGateEntryYet:
    """The uncomfortable half. Deliberate, and temporary."""

    @staticmethod
    def _fails_security() -> SecurityStatus:
        checks = tuple(
            evaluate_inspection(
                TokenInspection(
                    token_program=TOKEN_2022_PROGRAM,
                    decimals=6,
                    mint_authority_active=True,   # positively dangerous
                    freeze_authority_active=True, # positively dangerous
                    extensions=(17,),             # PermanentDelegate
                    raw={},
                )
            )
        )
        return roll_up(checks)

    def test_a_token_the_evaluator_calls_failed_is_still_eligible(self) -> None:
        assert self._fails_security() is SecurityStatus.FAILED
        verdict = eligibility.judge(
            observation(), held_ever=NOTHING, open_now=NOTHING
        )
        # Same market facts, and `judge()` never asked about security.
        assert verdict.eligible is True

    def test_a_token_with_unverifiable_liquidity_is_still_eligible(self) -> None:
        """SEC-1 can now answer UNKNOWN for a real reason. Entry ignores it."""
        checks = (
            SecurityCheck(
                name=CheckName.LIQUIDITY_SECURITY,
                status=CheckStatus.UNKNOWN,
                reason_codes=("TRADED_POOL_UNVERIFIED",),
            ),
        )
        assert roll_up(checks) is SecurityStatus.UNKNOWN
        assert eligibility.judge(
            observation(), held_ever=NOTHING, open_now=NOTHING
        ).eligible is True

    def test_a_token_whose_liquidity_is_provably_pullable_is_still_eligible(self) -> None:
        """The sharpest version of this phase's stop gate.

        SEC-1 can now prove things about liquidity custody, and Paper still
        does not ask. When the gate is enabled, this test must be rewritten —
        its failure is the signal that entry behaviour genuinely changed.
        """
        checks = (
            SecurityCheck(name=CheckName.LIQUIDITY_SECURITY, status=CheckStatus.FAIL),
        )
        assert roll_up(checks) is SecurityStatus.FAILED
        assert eligibility.judge(
            observation(), held_ever=NOTHING, open_now=NOTHING
        ).eligible is True


class TestEvidenceCaptureCannotAffectTrading:
    def test_capture_runs_after_every_position_is_opened(self) -> None:
        """Ordering is the guarantee, so read it out of the source.

        If capture ever moves above the entry loop, a slow RPC inside it can
        delay a trade — and a security *audit* that interferes with the wallet
        it audits is the worst possible outcome of this phase.
        """
        source = inspect.getsource(paper_service.PaperWalletService._open_entries)
        opened = source.index("opened += 1")
        captured = source.index("capture_candidate_security")
        assert opened < captured

    def test_capture_helper_swallows_its_own_failures(self) -> None:
        from app.security import service as security_service

        source = inspect.getsource(security_service.capture_candidate_security)
        assert "except Exception" in source

    def test_open_entries_never_reads_a_security_verdict(self) -> None:
        source = inspect.getsource(paper_service.PaperWalletService._open_entries)
        # The call is made and its result discarded — no name is bound to it.
        assert "await capture_candidate_security(" in source
        assert "= await capture_candidate_security" not in source
        for banned in ("SecurityStatus", "overall_status", "VERIFIED"):
            assert banned not in source
