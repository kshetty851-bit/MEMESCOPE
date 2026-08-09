from __future__ import annotations

import json

import httpx
import pytest

from app.real_wallet.live_readiness import SubmissionDecision
from app.real_wallet.live_transport import (
    JupiterExecuteOutcome,
    JupiterLiveExecutionTransport,
    LiveTransportBlockedError,
    TestOnlyExternalExecuteBlockedError,
)
from app.real_wallet.reconciliation import (
    ChainOutcome,
    SolanaRpcTransactionReconciler,
    extract_wallet_token_delta,
)


async def test_transport_cannot_call_execute_without_guard_approval() -> None:
    transport = JupiterLiveExecutionTransport(
        client=httpx.AsyncClient(), base_url="https://jupiter.test/swap/v2"
    )
    with pytest.raises(LiveTransportBlockedError):
        await transport.execute_signed_order(
            signed_transaction="test-only",
            request_id="request",
            guard=SubmissionDecision(False, ("MODE_NOT_LIVE",)),
        )


async def test_execute_contract_is_mocked_and_unknown_is_not_a_retry() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"status": "Unknown", "signature": "sig"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await JupiterLiveExecutionTransport(
            client=client, base_url="https://jupiter.test/swap/v2"
        ).execute_signed_order(
            signed_transaction="test-only-base64",
            request_id="request-1",
            guard=SubmissionDecision(True, ()),
        )
    assert result.outcome is JupiterExecuteOutcome.UNKNOWN
    assert len(seen) == 1
    assert seen[0].url.path.endswith("/swap/v2/execute")
    assert json.loads(seen[0].content) == {
        "signedTransaction": "test-only-base64",
        "requestId": "request-1",
    }


async def test_test_environment_cannot_aim_execute_at_external_jupiter() -> None:
    handler = httpx.MockTransport(lambda _: httpx.Response(200))
    async with httpx.AsyncClient(transport=handler) as client:
        with pytest.raises(TestOnlyExternalExecuteBlockedError, match="external_jupiter"):
            await JupiterLiveExecutionTransport(client=client).execute_signed_order(
                signed_transaction="test-only-base64",
                request_id="request-1",
                guard=SubmissionDecision(True, ()),
            )


def test_wallet_owned_token_delta_sums_associated_accounts_and_rejects_ambiguity() -> None:
    transaction = {
        "meta": {
            "preTokenBalances": [
                {
                    "accountIndex": 1,
                    "owner": "wallet",
                    "mint": "mint",
                    "uiTokenAmount": {"amount": "10", "decimals": 6},
                },
            ],
            "postTokenBalances": [
                {
                    "accountIndex": 1,
                    "owner": "wallet",
                    "mint": "mint",
                    "uiTokenAmount": {"amount": "17", "decimals": 6},
                },
                {
                    "accountIndex": 2,
                    "owner": "wallet",
                    "mint": "mint",
                    "uiTokenAmount": {"amount": "5", "decimals": 6},
                },
            ],
        }
    }
    delta = extract_wallet_token_delta(
        transaction=transaction, wallet_public_key="wallet", mint="mint"
    )
    assert delta is not None
    assert delta.raw_delta == 12
    assert delta.decimals == 6


async def test_confirmed_reconciliation_uses_wallet_owned_input_and_output_deltas() -> None:
    class _Rpc:
        async def get_transaction(self, signature: str, *, attempts: int):
            assert signature == "signature"
            assert attempts == 1
            return {
                "meta": {
                    "err": None,
                    "fee": 5000,
                    "preTokenBalances": [
                        {
                            "accountIndex": 1,
                            "owner": "wallet",
                            "mint": "usdc",
                            "uiTokenAmount": {"amount": "5000000", "decimals": 6},
                        },
                        {
                            "accountIndex": 2,
                            "owner": "wallet",
                            "mint": "token",
                            "uiTokenAmount": {"amount": "0", "decimals": 6},
                        },
                    ],
                    "postTokenBalances": [
                        {
                            "accountIndex": 1,
                            "owner": "wallet",
                            "mint": "usdc",
                            "uiTokenAmount": {"amount": "0", "decimals": 6},
                        },
                        {
                            "accountIndex": 2,
                            "owner": "wallet",
                            "mint": "token",
                            "uiTokenAmount": {"amount": "2500000", "decimals": 6},
                        },
                    ],
                }
            }

    receipt = await SolanaRpcTransactionReconciler(_Rpc()).inspect(  # type: ignore[arg-type]
        type(
            "Intent",
            (),
            {
                "transaction_signature": "signature",
                "wallet_public_key": "wallet",
                "input_mint": "usdc",
                "output_mint": "token",
            },
        )()
    )
    assert receipt.outcome is ChainOutcome.CONFIRMED
    assert receipt.actual_input_amount == "5000000"
    assert receipt.actual_output_amount == "2500000"
    assert receipt.actual_input_decimals == receipt.actual_output_decimals == 6
