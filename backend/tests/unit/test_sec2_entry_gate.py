"""SEC-2: the strict security entry gate.

The suite is organised around the one property the phase exists to create:

    NO NEW PAPER BUY WITHOUT POSITIVE, FRESH, VERIFIED SECURITY.

and the one it must not destroy:

    A SECURITY OUTAGE MUST NEVER STOP AN EXISTING POSITION EXITING.
"""

from __future__ import annotations

import inspect
from datetime import UTC, datetime, timedelta

import pytest

from app.security.contract import (
    EVALUATOR_VERSION,
    CheckName,
    CheckStatus,
    Reason,
    SecurityCheck,
    SecurityStatus,
    TokenSecurityEvaluation,
    roll_up,
)
from app.security.entry_policy import (
    MANDATORY_CHECKS,
    MAX_EVIDENCE_AGE,
    SECURITY_GATE_REFUSAL,
    EntryOutcome,
    decide,
)

pytestmark = pytest.mark.unit

NOW = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)


def check(name: CheckName, status: CheckStatus, *codes: str) -> SecurityCheck:
    return SecurityCheck(name=name, status=status, reason_codes=codes)


def evaluation(
    *,
    overrides: dict[CheckName, SecurityCheck] | None = None,
    at: datetime = NOW,
    version: str = EVALUATOR_VERSION,
    drop: CheckName | None = None,
) -> TokenSecurityEvaluation:
    """A fully verified token, minus whatever a test wants to break."""
    checks: list[SecurityCheck] = []
    for name in MANDATORY_CHECKS:
        if name is drop:
            continue
        checks.append((overrides or {}).get(name) or check(name, CheckStatus.PASS))
    frozen = tuple(checks)
    return TokenSecurityEvaluation(
        mint_address="mint",
        evaluated_at=at,
        overall_status=roll_up(frozen),
        checks=frozen,
        evaluator_version=version,
    )


# --- the allow path -------------------------------------------------------


class TestAllowed:
    def test_all_mandatory_pass_on_fresh_evidence_allows_entry(self) -> None:
        decision = decide(evaluation(), now=NOW)
        assert decision.outcome is EntryOutcome.ALLOWED
        assert decision.allowed is True
        assert decision.security_status is SecurityStatus.VERIFIED
        assert decision.reason_codes == ()

    def test_not_applicable_extensions_still_allow(self) -> None:
        """A plain SPL mint has no extensions. That is an answer, not a gap."""
        decision = decide(
            evaluation(
                overrides={
                    CheckName.TOKEN_EXTENSIONS: check(
                        CheckName.TOKEN_EXTENSIONS, CheckStatus.NOT_APPLICABLE
                    )
                }
            ),
            now=NOW,
        )
        assert decision.outcome is EntryOutcome.ALLOWED

    def test_evidence_at_the_freshness_boundary_still_allows(self) -> None:
        decision = decide(evaluation(at=NOW - MAX_EVIDENCE_AGE), now=NOW)
        assert decision.outcome is EntryOutcome.ALLOWED


# --- positively unsafe: REFUSED_UNSAFE ------------------------------------


class TestPositivelyUnsafeBlocks:
    @pytest.mark.parametrize(
        ("name", "code"),
        [
            (CheckName.MINT_AUTHORITY, Reason.MINT_AUTHORITY_ACTIVE),
            (CheckName.FREEZE_AUTHORITY, Reason.FREEZE_AUTHORITY_ACTIVE),
            (CheckName.TOKEN_EXTENSIONS, Reason.UNSUPPORTED_TOKEN_EXTENSION),
            (CheckName.TOKEN_PROGRAM, Reason.UNSUPPORTED_TOKEN_PROGRAM),
            (CheckName.VENUE, Reason.VENUE_UNSUPPORTED),
            (CheckName.LIQUIDITY_SECURITY, "LIQUIDITY_WITHDRAWABLE"),
        ],
    )
    def test_a_failed_mandatory_check_blocks_and_keeps_its_reason(
        self, name: CheckName, code: str
    ) -> None:
        decision = decide(
            evaluation(overrides={name: check(name, CheckStatus.FAIL, code)}), now=NOW
        )
        assert decision.outcome is EntryOutcome.REFUSED_UNSAFE
        assert decision.allowed is False
        # §8: the detailed reason survives; it is not collapsed.
        assert code in decision.reason_codes

    def test_a_failure_outranks_an_unknown_in_the_headline(self) -> None:
        decision = decide(
            evaluation(
                overrides={
                    CheckName.MINT_AUTHORITY: check(
                        CheckName.MINT_AUTHORITY, CheckStatus.FAIL,
                        Reason.MINT_AUTHORITY_ACTIVE,
                    ),
                    CheckName.LIQUIDITY_SECURITY: check(
                        CheckName.LIQUIDITY_SECURITY, CheckStatus.UNKNOWN,
                        Reason.LP_OUTSTANDING,
                    ),
                }
            ),
            now=NOW,
        )
        assert decision.outcome is EntryOutcome.REFUSED_UNSAFE


# --- evidence-based UNKNOWN: refuses, but is NOT relabelled ---------------


class TestEvidenceBasedUnknownBlocks:
    @pytest.mark.parametrize(
        "code",
        [
            Reason.LP_OUTSTANDING,
            Reason.MIGRATION_DESTINATION_UNVERIFIED,
            Reason.POOL_NOT_PROTOCOL_MIGRATED,
            Reason.TRADED_POOL_UNVERIFIED,
        ],
    )
    def test_unresolved_custody_blocks_entry_without_calling_it_unsafe(
        self, code: str
    ) -> None:
        decision = decide(
            evaluation(
                overrides={
                    CheckName.LIQUIDITY_SECURITY: check(
                        CheckName.LIQUIDITY_SECURITY, CheckStatus.UNKNOWN, code
                    )
                }
            ),
            now=NOW,
        )
        assert decision.allowed is False
        # §5, §9: refused, but classified as UNKNOWN and never as UNSAFE.
        assert decision.outcome is EntryOutcome.REFUSED_UNKNOWN
        assert decision.outcome is not EntryOutcome.REFUSED_UNSAFE
        assert decision.security_status is SecurityStatus.UNKNOWN
        assert code in decision.reason_codes

    def test_lp_outstanding_is_never_promoted_to_a_failure(self) -> None:
        """SEC-1 could not resolve LP holders, so FAIL would be a lie (§9)."""
        decision = decide(
            evaluation(
                overrides={
                    CheckName.LIQUIDITY_SECURITY: check(
                        CheckName.LIQUIDITY_SECURITY,
                        CheckStatus.UNKNOWN,
                        Reason.LP_OUTSTANDING,
                    )
                }
            ),
            now=NOW,
        )
        assert decision.security_status is not SecurityStatus.FAILED


# --- infrastructure: refuses "for now", token not labelled ----------------


class TestInfrastructureIsNotAVerdictAboutTheToken:
    def test_missing_evaluation_is_an_availability_refusal(self) -> None:
        decision = decide(None, now=NOW)
        assert decision.outcome is EntryOutcome.REFUSED_UNAVAILABLE
        assert decision.retryable is True
        # Nothing was established, so there is no verdict to report.
        assert decision.security_status is None

    @pytest.mark.parametrize(
        "code",
        [Reason.MINT_ACCOUNT_UNAVAILABLE, Reason.LIQUIDITY_SECURITY_UNVERIFIED,
         Reason.LP_CUSTODY_UNKNOWN, Reason.TOKEN_CONFIGURATION_UNKNOWN],
    )
    def test_provider_failure_is_temporary_not_unsafe(self, code: str) -> None:
        decision = decide(
            evaluation(
                overrides={
                    CheckName.LIQUIDITY_SECURITY: check(
                        CheckName.LIQUIDITY_SECURITY, CheckStatus.UNKNOWN, code
                    )
                }
            ),
            now=NOW,
        )
        assert decision.outcome is EntryOutcome.REFUSED_UNAVAILABLE
        assert decision.retryable is True
        assert decision.outcome is not EntryOutcome.REFUSED_UNSAFE

    def test_evidence_based_unknown_is_not_marked_retryable(self) -> None:
        """LP_OUTSTANDING will not resolve itself by waiting."""
        decision = decide(
            evaluation(
                overrides={
                    CheckName.LIQUIDITY_SECURITY: check(
                        CheckName.LIQUIDITY_SECURITY,
                        CheckStatus.UNKNOWN,
                        Reason.LP_OUTSTANDING,
                    )
                }
            ),
            now=NOW,
        )
        assert decision.retryable is False


# --- TOCTOU ---------------------------------------------------------------


class TestTimeOfCheckTimeOfUse:
    def test_a_stale_pass_cannot_authorise_a_buy(self) -> None:
        decision = decide(
            evaluation(at=NOW - MAX_EVIDENCE_AGE - timedelta(seconds=1)), now=NOW
        )
        assert decision.allowed is False
        assert decision.outcome is EntryOutcome.REFUSED_UNAVAILABLE
        assert Reason.EVIDENCE_STALE in decision.reason_codes

    def test_a_pass_that_expires_between_check_and_use_stops_the_buy(self) -> None:
        """The same evaluation, allowed now and refused later."""
        item = evaluation(at=NOW)
        assert decide(item, now=NOW).allowed is True
        later = NOW + MAX_EVIDENCE_AGE + timedelta(seconds=1)
        assert decide(item, now=later).allowed is False

    def test_evidence_from_the_future_is_refused_rather_than_trusted(self) -> None:
        decision = decide(evaluation(at=NOW + timedelta(hours=1)), now=NOW)
        assert decision.allowed is False

    def test_a_per_check_window_expiring_blocks_even_inside_the_global_window(
        self,
    ) -> None:
        # Every check carries its own validity period; the shortest one wins.
        item = evaluation(at=NOW - MAX_EVIDENCE_AGE)
        assert decide(item, now=NOW).allowed is True
        assert decide(item, now=NOW + timedelta(seconds=1)).allowed is False


# --- version compatibility ------------------------------------------------


class TestEvaluatorVersion:
    def test_an_evaluation_from_a_different_evaluator_cannot_authorise(self) -> None:
        """A 1.0.0 UNKNOWN means 'never checked'; a 1.1.0 UNKNOWN does not."""
        decision = decide(evaluation(version="1.0.0"), now=NOW)
        assert decision.allowed is False
        assert decision.outcome is EntryOutcome.REFUSED_UNAVAILABLE

    def test_a_newer_evaluator_is_also_refused(self) -> None:
        assert decide(evaluation(version="9.9.9"), now=NOW).allowed is False


# --- completeness ---------------------------------------------------------


class TestEveryMandatoryCheckMustBePresent:
    @pytest.mark.parametrize("name", list(MANDATORY_CHECKS))
    def test_a_missing_mandatory_check_blocks_entry(self, name: CheckName) -> None:
        decision = decide(evaluation(drop=name), now=NOW)
        assert decision.allowed is False

    def test_liquidity_security_is_mandatory(self) -> None:
        """The whole point of SEC-1 feeding SEC-2."""
        assert CheckName.LIQUIDITY_SECURITY in MANDATORY_CHECKS

    def test_an_empty_evaluation_never_allows(self) -> None:
        empty = TokenSecurityEvaluation(
            mint_address="mint",
            evaluated_at=NOW,
            overall_status=SecurityStatus.UNKNOWN,
            checks=(),
        )
        assert decide(empty, now=NOW).allowed is False

    def test_market_quality_can_never_substitute_for_a_security_check(self) -> None:
        """§3: no amount of liquidity, volume or score buys a PASS.

        `decide` takes only an evaluation and a clock. There is no parameter
        through which a market fact could influence the verdict, which is the
        structural version of this guarantee.
        """
        parameters = set(inspect.signature(decide).parameters)
        assert parameters == {"evaluation", "now", "evaluation_id", "max_age"}


# --- the aggregate/detail contract ---------------------------------------


class TestRefusalRecording:
    def test_the_aggregate_code_exists_and_details_are_kept_beside_it(self) -> None:
        decision = decide(
            evaluation(
                overrides={
                    CheckName.LIQUIDITY_SECURITY: check(
                        CheckName.LIQUIDITY_SECURITY,
                        CheckStatus.UNKNOWN,
                        Reason.LP_OUTSTANDING,
                    )
                }
            ),
            now=NOW,
        )
        assert SECURITY_GATE_REFUSAL == "security_gate"
        payload = decision.as_json()
        assert payload["security_status"] == "UNKNOWN"
        assert Reason.LP_OUTSTANDING in payload["reason_codes"]
        assert payload["evaluator_version"] == EVALUATOR_VERSION
        assert payload["evaluated_at"] is not None
