"""The single decision point for whether a real Jupiter `/execute` may happen.

## What this replaces, and why it was replaced carefully

Until this sprint the only thing standing between this codebase and a mainnet
swap was `JupiterLiveExecutionTransport._assert_test_only_endpoint`, which
refused unless `ENVIRONMENT == "test"`, an HTTPX client had been injected, and
the host ended `.test`/`.invalid`. That is an excellent barrier and a useless
production design: the only way to ever ship a canary was to delete it, and
deleting a barrier is a one-line diff that looks like cleanup.

So it is not deleted. It is subsumed. The test-sandbox rule below is the same
rule, kept verbatim in effect, and it is now one branch of a policy that also
knows what `disabled`, `dry_run`, `armed` and `live` mean.

## The envelopes

* **TEST** — an external host is impossible. Only a reserved `.test`/`.invalid`
  hostname with an injected client is permitted. A test that forgets its mock
  fails locally rather than reaching the internet, which is the property that
  matters most in a suite of 3,500 tests.
* **DISABLED / DRY_RUN** — `/execute` is impossible. Quotes, orders, safety
  evaluation and accounting all still work; only submission is refused.
* **ARMED** — every pre-submit condition may be evaluated and audited, and
  `/execute` is *still* impossible. This is the canary-readiness rehearsal
  state: it proves the whole chain without a transaction existing.
* **LIVE** — permitted only when every condition below holds at once.

## Live requires all of these, and they are deliberately not all env vars

`RELEASE_APPROVED` is a module constant rather than a setting. Everything else
here can be changed by whoever can edit an environment; this one requires a code
change, a diff, and a review. A deployment misconfiguration must not be able to
reach mainnet on its own, and an operator with env access alone cannot flip it.

The host allowlist matters for the same reason: `JUPITER_V2_BASE_URL` is
configuration, so without it a live build could be pointed at any endpoint that
would happily be handed a signed transaction.

Nothing in this module performs I/O, holds a signer, or builds a transaction.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import urlparse

from app.core.config import settings
from app.real_wallet.live_readiness import SubmissionDecision

#: **The reviewed-release switch. Flipping this is the release.**
#:
#: While False, no configuration of any kind can produce a real `/execute`.
#: It is a constant so that enabling live submission is a reviewable code
#: change rather than an environment edit, and so `git log -S` finds the exact
#: commit that authorised mainnet execution.
#:
#: Turning this True is necessary and *not sufficient*: mode, the three enable
#: flags, the submission guard, and the host allowlist all still apply.
LIVE_TRANSPORT_RELEASE_APPROVED = False

#: Hostnames a production `/execute` may be sent to. A signed transaction is
#: bearer-grade material; it must not be postable to an arbitrary configured
#: host. Reserved test domains are handled separately and are never in here.
ALLOWED_EXECUTE_HOSTS = frozenset({"api.jup.ag", "lite-api.jup.ag"})

#: Reserved TLDs that can never resolve to a real endpoint (RFC 2606/6761).
_SANDBOX_SUFFIXES = (".test", ".invalid")


class TransportEnvelope(StrEnum):
    """Which regime the process is running under."""

    TEST_SANDBOX = "test_sandbox"
    DISABLED = "disabled"
    DRY_RUN = "dry_run"
    ARMED = "armed"
    LIVE = "live"


class TransportReason(StrEnum):
    """Why a submission was refused. Persisted and surfaced on the dashboard."""

    RELEASE_NOT_APPROVED = "RELEASE_NOT_APPROVED"
    MODE_NOT_LIVE = "MODE_NOT_LIVE"
    EXECUTION_DISABLED = "EXECUTION_DISABLED"
    AUTOTRADE_DISABLED = "AUTOTRADE_DISABLED"
    SUBMISSION_GUARD_BLOCKED = "SUBMISSION_GUARD_BLOCKED"
    ENDPOINT_NOT_ALLOWED = "ENDPOINT_NOT_ALLOWED"
    TEST_CLIENT_REQUIRED = "TEST_CLIENT_REQUIRED"
    TEST_SANDBOX_HOST_REQUIRED = "TEST_SANDBOX_HOST_REQUIRED"
    PRODUCTION_ENDPOINT_IN_TEST = "PRODUCTION_ENDPOINT_IN_TEST"


class ExecuteNotPermittedError(RuntimeError):
    """No network `/execute` is permitted for this attempt."""

    def __init__(self, reasons: tuple[str, ...]) -> None:
        super().__init__(",".join(reasons) or "execute_not_permitted")
        self.reasons = reasons


@dataclass(frozen=True, slots=True)
class TransportAuthorisation:
    """One decision, with every reason it failed."""

    permitted: bool
    envelope: TransportEnvelope
    reasons: tuple[str, ...]

    def require(self) -> None:
        if not self.permitted:
            raise ExecuteNotPermittedError(self.reasons)


def current_envelope() -> TransportEnvelope:
    """Which regime this process is in, independent of any single attempt."""
    if settings.ENVIRONMENT == "test":
        return TransportEnvelope.TEST_SANDBOX
    return {
        "disabled": TransportEnvelope.DISABLED,
        "dry_run": TransportEnvelope.DRY_RUN,
        "armed": TransportEnvelope.ARMED,
        "live": TransportEnvelope.LIVE,
    }[settings.REAL_WALLET_EXECUTION_MODE]


class ExecutionTransportPolicy:
    """Authorise — or refuse — one `/execute` attempt.

    Reasons accumulate and `permitted` is `not reasons`, so a new condition can
    only ever make the policy stricter. Adding a check cannot accidentally
    authorise anything.
    """

    def authorise(
        self, *, guard: SubmissionDecision, base_url: str, client_injected: bool
    ) -> TransportAuthorisation:
        envelope = current_envelope()
        host = (urlparse(base_url).hostname or "").lower()

        if envelope is TransportEnvelope.TEST_SANDBOX:
            # Permitted only against a reserved hostname through an injected
            # client — which is to say, against a mock. The suite must be able
            # to exercise the request/response contract; what it must never be
            # able to do is reach a host that resolves.
            sandbox = self._sandbox_reasons(host, client_injected=client_injected)
            return TransportAuthorisation(
                permitted=not sandbox, envelope=envelope, reasons=sandbox
            )

        reasons: list[str] = []
        # The release switch is checked first because it is the one condition an
        # environment cannot satisfy on its own.
        if not LIVE_TRANSPORT_RELEASE_APPROVED:
            reasons.append(TransportReason.RELEASE_NOT_APPROVED)
        if envelope is not TransportEnvelope.LIVE:
            reasons.append(TransportReason.MODE_NOT_LIVE)
        if not settings.REAL_WALLET_EXECUTION_ENABLED:
            reasons.append(TransportReason.EXECUTION_DISABLED)
        if not settings.REAL_WALLET_AUTOTRADE_ENABLED:
            reasons.append(TransportReason.AUTOTRADE_DISABLED)
        if not guard.allowed:
            reasons.append(TransportReason.SUBMISSION_GUARD_BLOCKED)
        if host not in ALLOWED_EXECUTE_HOSTS:
            reasons.append(TransportReason.ENDPOINT_NOT_ALLOWED)

        return TransportAuthorisation(
            permitted=not reasons, envelope=envelope, reasons=tuple(reasons)
        )

    @staticmethod
    def _sandbox_reasons(host: str, *, client_injected: bool) -> tuple[str, ...]:
        """The original test-only barrier, unchanged in effect.

        Empty means "a mock may be exercised". It distinguishes *why* it
        refused, so a suite that forgot its mock gets `TEST_CLIENT_REQUIRED`
        rather than a generic block, and one that pointed at a real endpoint
        gets `PRODUCTION_ENDPOINT_IN_TEST`.

        Note what is **not** consulted here: mode, the enable flags, and the
        release switch. In the sandbox they are irrelevant, because the only
        reachable hosts are reserved TLDs that cannot resolve. That
        independence is the point — no combination of settings, and no flip of
        `LIVE_TRANSPORT_RELEASE_APPROVED`, lets the test suite touch mainnet.
        """
        reasons: list[str] = []
        if not client_injected:
            reasons.append(TransportReason.TEST_CLIENT_REQUIRED)
        if not host.endswith(_SANDBOX_SUFFIXES):
            reasons.append(
                TransportReason.PRODUCTION_ENDPOINT_IN_TEST
                if host
                else TransportReason.TEST_SANDBOX_HOST_REQUIRED
            )
        return tuple(reasons)


@dataclass(frozen=True, slots=True)
class TransportReadiness:
    """What the admin dashboard says about submission capability."""

    envelope: str
    release_approved: bool
    production_transport_installed: bool
    submission_permitted: bool
    reasons: tuple[str, ...]
    allowed_hosts: tuple[str, ...]
    configured_host: str | None


def readiness() -> TransportReadiness:
    """Report the boundary without attempting anything.

    Evaluated against a deliberately blocked guard: this answers "could this
    process submit at all", never "would this particular intent submit". No
    caller can turn a readiness read into an execution attempt.
    """
    authorisation = ExecutionTransportPolicy().authorise(
        guard=SubmissionDecision(allowed=False, reasons=("READINESS_PROBE",)),
        base_url=settings.JUPITER_V2_BASE_URL,
        client_injected=False,
    )
    host = (urlparse(settings.JUPITER_V2_BASE_URL).hostname or "").lower()
    return TransportReadiness(
        envelope=str(authorisation.envelope),
        release_approved=LIVE_TRANSPORT_RELEASE_APPROVED,
        # There is a transport class, but no approved release installs it.
        production_transport_installed=LIVE_TRANSPORT_RELEASE_APPROVED,
        submission_permitted=False,
        reasons=authorisation.reasons,
        allowed_hosts=tuple(sorted(ALLOWED_EXECUTE_HOSTS)),
        configured_host=host or None,
    )
