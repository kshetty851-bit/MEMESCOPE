"""Fail-closed guarantees for the autonomous dry-run boundary."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock

import httpx
import pytest
from solders.pubkey import Pubkey
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.real_wallet_execution import RealWalletExecutionIntent
from app.real_wallet.dry_run import (
    RealWalletDryRunService,
    _ephemeral_dry_run_taker_public_key,
)
from app.real_wallet.jupiter_v2 import RealWalletJupiterV2Client
from app.real_wallet.policy import AutonomousExecutionPolicy, PolicyReason, PolicyState
from app.real_wallet.repository import RealWalletExecutionRepository

pytestmark = pytest.mark.unit


async def test_disabled_mode_performs_no_database_or_jupiter_activity(monkeypatch) -> None:
    monkeypatch.setattr(settings, "REAL_WALLET_EXECUTION_MODE", "disabled")
    session = AsyncMock()
    jupiter = AsyncMock(spec=RealWalletJupiterV2Client)

    outcome = await RealWalletDryRunService(session, jupiter=jupiter).review(
        now=datetime.now(UTC)
    )

    assert outcome.skipped == "execution_mode_disabled"
    assert session.method_calls == []
    assert jupiter.method_calls == []


def test_policy_applies_conservative_server_limits(monkeypatch) -> None:
    monkeypatch.setattr(settings, "REAL_WALLET_EXECUTION_MODE", "dry_run")
    state = PolicyState(1, Decimal("5"), Decimal("0"), Decimal("0"))

    decision = AutonomousExecutionPolicy().evaluate_entry(
        requested_usd=Decimal("5"), state=state
    )

    assert decision.allowed is False
    assert PolicyReason.MAX_OPEN_POSITIONS in decision.reason_codes


async def test_v2_client_calls_order_only_and_omits_transaction_from_evidence() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(
            200,
            json={
                "requestId": "request-1",
                "outAmount": "10",
                "priceImpactPct": "0.01",
                "routePlan": [{"swapInfo": {"label": "Test AMM"}}],
                "transaction": "unsigned-transaction-must-not-persist",
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        evidence = await RealWalletJupiterV2Client(client=http_client).order(
            side="BUY",
            input_mint="input",
            output_mint="output",
            amount_raw=5_000_000,
            taker_public_key="dry-run-public-only",
        )

    assert len(seen) == 1
    assert "/order" in seen[0]
    assert "/execute" not in seen[0]
    stored = evidence.as_json()
    assert "transaction" not in str(stored)
    assert not hasattr(RealWalletJupiterV2Client, "execute")


def test_ephemeral_dry_run_taker_is_a_valid_public_key_only() -> None:
    address = _ephemeral_dry_run_taker_public_key()

    assert str(Pubkey.from_string(address)) == address


async def test_duplicate_execution_intent_is_rejected_by_database(
    db_session: AsyncSession,
) -> None:
    repository = RealWalletExecutionRepository(db_session)
    values = {
        "idempotency_key": "same-radar-signal",
        "mint_address": "dry-run-mint",
        "symbol": "DRY",
        "side": "BUY",
        "mode": "dry_run",
        "status": "BLOCKED",
        "strategy_id": "trailing_stop_25_v1",
        "strategy_version": "1.0.0",
        "radar_rank": 1,
        "signal_at": datetime.now(UTC),
        "evaluated_at": datetime.now(UTC),
        "requested_usd": Decimal("5"),
        "safety_evaluation_id": None,
        "safety_decision": "REJECT",
        "reason_codes": ["TEST"],
        "liquidity_usd": Decimal("100000"),
        "buy_impact_pct": None,
        "sell_impact_pct": None,
        "round_trip_loss_pct": None,
        "buy_order": None,
        "sell_order": None,
    }

    assert await repository.record(**values) is not None
    assert await repository.record(**values) is None
    count = await db_session.scalar(
        select(func.count(RealWalletExecutionIntent.id)).where(
            RealWalletExecutionIntent.idempotency_key == "same-radar-signal"
        )
    )
    assert count == 1
