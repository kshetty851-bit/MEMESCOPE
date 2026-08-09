"""Guarded Jupiter V2 transport for a future real-wallet release.

The HTTP boundary is intentionally isolated here.  Callers must supply a
fresh ``SubmissionDecision`` from ``LiveSubmissionGuard``; this transport owns
no strategy, safety, sizing, or enablement decision.  Tests inject an HTTPX
mock and must never use the production endpoint.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, cast
from urllib.parse import urlparse

import httpx

from app.core.config import settings
from app.real_wallet.live_readiness import SubmissionDecision


class JupiterExecuteOutcome(StrEnum):
    SUCCESS = "success"
    FAILED = "failed"
    UNKNOWN = "unknown"


class LiveTransportBlockedError(RuntimeError):
    """No network execute call is permitted for this attempted submission."""


class JupiterExecuteTransportError(RuntimeError):
    """The execute response was unavailable or malformed."""


class TestOnlyExternalExecuteBlockedError(RuntimeError):
    """A test tried to point the execute path at a real Jupiter endpoint."""

    __test__ = False


@dataclass(frozen=True, slots=True)
class JupiterExecutionResult:
    outcome: JupiterExecuteOutcome
    signature: str | None
    total_input_amount: str | None
    total_output_amount: str | None
    error_code: str | None


class JupiterLiveExecutionTransport:
    """Dedicated V2 execute client; Paper Wallet never imports this type."""

    def __init__(
        self, *, client: httpx.AsyncClient | None = None, base_url: str | None = None
    ) -> None:
        self._client = client
        self._base_url = (base_url or settings.JUPITER_V2_BASE_URL).rstrip("/")

    async def execute_signed_order(
        self,
        *,
        signed_transaction: str,
        request_id: str,
        guard: SubmissionDecision,
    ) -> JupiterExecutionResult:
        """Submit only after the authoritative guard has allowed it.

        The caller must never persist or log ``signed_transaction``.  A timeout
        or malformed response is intentionally UNKNOWN, never a retry signal.
        """
        if not guard.allowed:
            raise LiveTransportBlockedError("live_submission_guard_blocked")
        if not signed_transaction or not request_id:
            raise LiveTransportBlockedError("missing_signed_order_evidence")
        self._assert_test_only_endpoint()
        api_key = settings.JUPITER_API_KEY.get_secret_value()
        headers = {"x-api-key": api_key} if api_key else {}
        try:
            if self._client is None:
                async with httpx.AsyncClient(timeout=10) as client:
                    response = await client.post(
                        f"{self._base_url}/execute",
                        json={
                            "signedTransaction": signed_transaction,
                            "requestId": request_id,
                        },
                        headers=headers,
                    )
            else:
                response = await self._client.post(
                    f"{self._base_url}/execute",
                    json={"signedTransaction": signed_transaction, "requestId": request_id},
                    headers=headers,
                )
            body = cast(dict[str, Any], response.json())
        except (httpx.HTTPError, ValueError) as exc:
            raise JupiterExecuteTransportError(
                "jupiter_execute_transport_unavailable"
            ) from exc

        status = str(body.get("status", "")).lower()
        if status == "success" and isinstance(body.get("signature"), str):
            outcome = JupiterExecuteOutcome.SUCCESS
        elif status in {"failed", "error"}:
            outcome = JupiterExecuteOutcome.FAILED
        else:
            outcome = JupiterExecuteOutcome.UNKNOWN
        return JupiterExecutionResult(
            outcome=outcome,
            signature=body.get("signature")
            if isinstance(body.get("signature"), str)
            else None,
            total_input_amount=str(body["totalInputAmount"])
            if body.get("totalInputAmount") is not None
            else None,
            total_output_amount=str(body["totalOutputAmount"])
            if body.get("totalOutputAmount") is not None
            else None,
            error_code=str(body["errorCode"]) if body.get("errorCode") else None,
        )

    def _assert_test_only_endpoint(self) -> None:
        """Make an accidental external `/execute` impossible during this sprint.

        The only allowed route is a reserved test hostname with an injected
        HTTPX client (normally ``MockTransport``). Production configured URLs,
        localhost, and a client created internally are all rejected before any
        HTTP request is constructed.
        """
        host = (urlparse(self._base_url).hostname or "").lower()
        if (
            settings.ENVIRONMENT != "test"
            or self._client is None
            or not (host.endswith(".test") or host.endswith(".invalid"))
        ):
            raise TestOnlyExternalExecuteBlockedError("external_jupiter_execute_blocked")
