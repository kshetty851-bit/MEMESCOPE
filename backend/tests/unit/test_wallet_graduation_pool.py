"""Pool selection must be shared by refresh, safety and vault price checks."""

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.labs.graduation import tournament
from app.real_wallet import executor as ex
from app.real_wallet.market_refresh import Reading

AT = datetime(2026, 10, 25, tzinfo=UTC)
POOL = "canonical-graduation-pool"


def runner():
    instance = object.__new__(ex.RealWalletExecutor)
    instance._session = object()
    instance._repository = SimpleNamespace(transition=AsyncMock())
    return instance


@pytest.mark.parametrize("strategy", ["G-Q50", "V6-06"])
async def test_same_pool_is_passed_to_refresh_and_gate(monkeypatch, strategy):
    calls = []

    async def refresh(session, mint, **kwargs):
        calls.append(("refresh", kwargs))
        return Reading("fresh", AT)

    class Gate:
        def __init__(self, session):
            pass

        async def evaluate(self, **kwargs):
            calls.append(("gate", kwargs))
            return SimpleNamespace(decision="REJECT", reason_codes=("TEST_REJECTION",))

    monkeypatch.setattr(tournament, "graduation_pool", lambda mint: POOL)
    monkeypatch.setattr(ex.market_refresh, "ensure_fresh", refresh)
    monkeypatch.setattr(ex, "RealWalletSafetyGate", Gate)
    intent = SimpleNamespace(
        id="intent",
        mint_address="mint",
        side="BUY",
        strategy_id=strategy,
        requested_usd=Decimal(10),
        state="created",
    )
    result = await runner()._run_safety(intent, AT)
    assert result.state == "blocked"
    assert [kind for kind, _ in calls] == ["refresh", "gate"]
    for _, kwargs in calls:
        assert kwargs.get("pool_address") == (POOL if strategy == "G-Q50" else None)


async def test_unverifiable_graduation_pool_fails_before_refresh(monkeypatch):
    refresh = AsyncMock()
    monkeypatch.setattr(tournament, "graduation_pool", lambda mint: None)
    monkeypatch.setattr(ex.market_refresh, "ensure_fresh", refresh)
    intent = SimpleNamespace(id="intent", mint_address="mint", side="BUY", strategy_id="G-Q50")
    result = await runner()._run_safety(intent, AT)
    assert result.state == "blocked" and result.reason == "safety:GRADUATION_POOL_UNVERIFIED"
    refresh.assert_not_awaited()


async def test_sell_does_not_acquire_buy_pool_requirements(monkeypatch):
    refresh = AsyncMock()
    monkeypatch.setattr(ex.market_refresh, "ensure_fresh", refresh)
    intent = SimpleNamespace(
        id="intent", mint_address="mint", side="SELL", strategy_id="G-Q50"
    )
    result = await runner()._run_safety(intent, AT)
    assert result.state == "safety_approved"
    refresh.assert_not_awaited()


async def test_existing_blocked_intent_is_never_reopened(monkeypatch):
    intent = SimpleNamespace(id="intent", state="blocked", side="BUY")
    instance = runner()
    instance._repository.by_id = AsyncMock(return_value=intent)
    instance._repository.active_kill_switches = AsyncMock(return_value=[])
    instance._run_safety = AsyncMock()
    monkeypatch.setattr(
        ex,
        "AutotradeSwitchService",
        lambda session: SimpleNamespace(
            state=AsyncMock(return_value=SimpleNamespace(enabled=True))
        ),
    )
    result = await instance.advance("intent", now=AT)
    assert not result.changed and result.reason == "terminal_state"
    instance._run_safety.assert_not_awaited()
