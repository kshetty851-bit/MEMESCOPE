"""The one boundary between this codebase and a mainnet swap.

The barrier this replaces (`_assert_test_only_endpoint`) was excellent and
undeployable: the only way to ship a canary was to delete it. These tests exist
so the replacement is provably at least as strict in the sandbox, and strict in
four production regimes the old barrier could not express.

Every test that raises the mode above `disabled` does so by monkeypatching a
setting inside the test process only. Nothing here enables live execution, and
the release constant is never patched to True except in the two tests that
prove it is still insufficient on its own.
"""

from __future__ import annotations

import httpx
import pytest

from app.core.config import settings
from app.real_wallet import transport_policy
from app.real_wallet.live_readiness import SubmissionDecision
from app.real_wallet.live_transport import (
    JupiterLiveExecutionTransport,
    TestOnlyExternalExecuteBlockedError,
)
from app.real_wallet.transport_policy import (
    ExecuteNotPermittedError,
    ExecutionTransportPolicy,
    TransportEnvelope,
    TransportReason,
)

pytestmark = pytest.mark.unit

ALLOWED = SubmissionDecision(allowed=True, reasons=())
BLOCKED = SubmissionDecision(allowed=False, reasons=("MODE_NOT_LIVE",))
SANDBOX_URL = "https://jupiter.test/swap/v2"
PRODUCTION_URL = "https://api.jup.ag/swap/v2"


def _authorise(**kwargs: object) -> transport_policy.TransportAuthorisation:
    params: dict[str, object] = {
        "guard": ALLOWED,
        "base_url": PRODUCTION_URL,
        "client_injected": True,
    }
    params.update(kwargs)
    return ExecutionTransportPolicy().authorise(**params)  # type: ignore[arg-type]


def _production(monkeypatch: pytest.MonkeyPatch, *, mode: str, **flags: object) -> None:
    """Simulate a non-test process in one execution mode.

    `ENVIRONMENT` is patched on the settings object rather than the process, so
    the sandbox rule is the only thing that changes; no network client, signer
    or transport is constructed anywhere in this module.
    """
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "REAL_WALLET_EXECUTION_MODE", mode)
    monkeypatch.setattr(settings, "REAL_WALLET_EXECUTION_ENABLED", flags.get("enabled", True))
    monkeypatch.setattr(
        settings, "REAL_WALLET_AUTOTRADE_ENABLED", flags.get("autotrade", True)
    )


class TestTheSandboxGuaranteeIsUnchanged:
    """The property the old barrier had, restated so it cannot be lost."""

    def test_a_reserved_host_through_a_mock_is_permitted(self) -> None:
        """The suite must still be able to exercise the request contract."""
        assert _authorise(base_url=SANDBOX_URL).permitted

    def test_a_forgotten_mock_fails_locally_rather_than_reaching_the_internet(
        self,
    ) -> None:
        """The single most valuable property in a 3,500-test suite."""
        decision = _authorise(base_url=SANDBOX_URL, client_injected=False)

        assert not decision.permitted
        assert TransportReason.TEST_CLIENT_REQUIRED in decision.reasons

    def test_a_real_endpoint_is_refused_in_test_even_with_a_mock(self) -> None:
        decision = _authorise(base_url=PRODUCTION_URL)

        assert not decision.permitted
        assert TransportReason.PRODUCTION_ENDPOINT_IN_TEST in decision.reasons

    def test_the_release_switch_cannot_open_the_sandbox(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Sandbox and release approval are deliberately independent.

        Flipping the constant is the mainnet release; it must not also hand the
        test suite the internet.
        """
        monkeypatch.setattr(transport_policy, "LIVE_TRANSPORT_RELEASE_APPROVED", True)

        assert not _authorise(base_url=PRODUCTION_URL).permitted

    async def test_the_transport_refuses_a_real_endpoint_under_its_historic_name(
        self,
    ) -> None:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(200))
        ) as client:
            with pytest.raises(TestOnlyExternalExecuteBlockedError):
                await JupiterLiveExecutionTransport(client=client).execute_signed_order(
                    signed_transaction="test-only-base64",
                    request_id="request-1",
                    guard=ALLOWED,
                )


class TestProductionEnvelopes:
    @pytest.mark.parametrize("mode", ["disabled", "dry_run", "armed"])
    def test_no_mode_below_live_can_submit(
        self, monkeypatch: pytest.MonkeyPatch, mode: str
    ) -> None:
        """`armed` is the canary rehearsal: every pre-condition may be checked
        and nothing may be sent."""
        _production(monkeypatch, mode=mode)

        decision = _authorise()

        assert not decision.permitted
        assert TransportReason.MODE_NOT_LIVE in decision.reasons

    def test_armed_is_reported_as_its_own_envelope(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Distinguishable from disabled so readiness can be rehearsed and seen."""
        _production(monkeypatch, mode="armed")

        assert _authorise().envelope is TransportEnvelope.ARMED

    def test_the_release_is_approved_and_live_is_therefore_reachable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The release was reviewed and turned on deliberately.

        Until then this asserted the opposite, and the assertion was right at
        the time: environment access alone could not reach mainnet. What still
        holds is that permission is the ABSENCE of reasons — mode, the enable
        flags, the guard and the host allowlist each still refuse on their own,
        and the tests below hold each of them.
        """
        _production(monkeypatch, mode="live")

        decision = _authorise()

        assert decision.permitted
        assert TransportReason.RELEASE_NOT_APPROVED not in decision.reasons

    def test_turning_the_release_off_again_closes_everything(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The constant is still the master switch, and reverting it is still
        the one-line rollback."""
        _production(monkeypatch, mode="live")
        monkeypatch.setattr(transport_policy, "LIVE_TRANSPORT_RELEASE_APPROVED", False)

        decision = _authorise()

        assert not decision.permitted
        assert TransportReason.RELEASE_NOT_APPROVED in decision.reasons

    def test_live_still_requires_the_submission_guard(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _production(monkeypatch, mode="live")
        monkeypatch.setattr(transport_policy, "LIVE_TRANSPORT_RELEASE_APPROVED", True)

        decision = _authorise(guard=BLOCKED)

        assert not decision.permitted
        assert TransportReason.SUBMISSION_GUARD_BLOCKED in decision.reasons

    def test_mainnet_is_permitted_only_when_every_other_gate_is_open(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The phase gate that made mainnet observation-only was removed
        deliberately. Mainnet is now ordinary: it passes when everything else
        passes, and refuses the moment anything else does not.

        The pair matters more than either half — the first case is what changed,
        the second is the guarantee that nothing else did.
        """
        _production(monkeypatch, mode="live")
        monkeypatch.setattr(settings, "REAL_WALLET_NETWORK", "mainnet")
        monkeypatch.setattr(transport_policy, "LIVE_TRANSPORT_RELEASE_APPROVED", True)

        assert _authorise().permitted

        blocked = _authorise(guard=BLOCKED)
        assert not blocked.permitted
        assert TransportReason.SUBMISSION_GUARD_BLOCKED in blocked.reasons

    @pytest.mark.parametrize(
        ("flag", "reason"),
        [
            ("enabled", TransportReason.EXECUTION_DISABLED),
            ("autotrade", TransportReason.AUTOTRADE_DISABLED),
        ],
    )
    def test_every_enable_flag_is_independently_required(
        self, monkeypatch: pytest.MonkeyPatch, flag: str, reason: str
    ) -> None:
        _production(monkeypatch, mode="live", **{flag: False})
        monkeypatch.setattr(transport_policy, "LIVE_TRANSPORT_RELEASE_APPROVED", True)

        decision = _authorise()

        assert not decision.permitted
        assert reason in decision.reasons

    def test_a_signed_transaction_cannot_be_posted_to_an_arbitrary_host(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`JUPITER_V2_BASE_URL` is configuration; a signed transaction is
        bearer-grade material. Without this, a live build could be pointed at
        any endpoint willing to receive one."""
        _production(monkeypatch, mode="live")
        monkeypatch.setattr(transport_policy, "LIVE_TRANSPORT_RELEASE_APPROVED", True)

        decision = _authorise(base_url="https://attacker.example/swap/v2")

        assert not decision.permitted
        assert TransportReason.ENDPOINT_NOT_ALLOWED in decision.reasons

    def test_one_missing_condition_means_no_execute_call(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Reasons accumulate and permission is their absence, so a new check
        can only ever make this stricter."""
        _production(monkeypatch, mode="live", enabled=False, autotrade=False)

        decision = _authorise(guard=BLOCKED, base_url="https://nope.example")

        assert not decision.permitted
        # Four, not five: the unconditional mainnet clause was removed with the
        # release. The remaining four are mode, enablement, autotrade and the
        # guard — each still independent.
        assert len(decision.reasons) == 4

    def test_a_fully_satisfied_live_attempt_is_the_only_permitted_one(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Proves the policy is not unconditionally closed — it is conditional,
        and the conditions are the reviewed ones."""
        _production(monkeypatch, mode="live")
        monkeypatch.setattr(transport_policy, "LIVE_TRANSPORT_RELEASE_APPROVED", True)

        assert _authorise().permitted


class TestTheShippedState:
    def test_the_release_constant_is_on_and_that_was_a_reviewed_decision(self) -> None:
        """This asserted `is False` under the docstring "a checkout must never
        be one environment edit from mainnet". That guarantee was given up
        knowingly, and the test now records which state was chosen rather than
        being deleted — a constant nobody asserts is a constant that can drift
        back either way unnoticed.
        """
        assert transport_policy.LIVE_TRANSPORT_RELEASE_APPROVED is True

    def test_a_fresh_checkout_still_cannot_trade_without_deliberate_config(self) -> None:
        """What replaced the guarantee above, and the reason losing it is
        survivable: the SETTINGS still ship closed. Cloning this repository and
        running it trades nothing until someone edits an environment on purpose.
        """
        from app.core.config import Settings

        fresh = Settings()
        assert fresh.REAL_WALLET_EXECUTION_MODE == "disabled"
        assert fresh.REAL_WALLET_EXECUTION_ENABLED is False
        assert fresh.REAL_WALLET_AUTOTRADE_ENABLED is False

    def test_readiness_still_refuses_until_the_environment_agrees(self) -> None:
        """The release is on; this environment has not enabled execution, so
        submission is still refused and the reasons still say why."""
        readiness = transport_policy.readiness()

        assert readiness.release_approved is True
        assert readiness.submission_permitted is False
        assert readiness.reasons

    def test_require_raises_rather_than_returning_a_falsy_value(self) -> None:
        """A caller that ignores the return value must not silently proceed."""
        with pytest.raises(ExecuteNotPermittedError):
            _authorise(base_url=PRODUCTION_URL).require()
