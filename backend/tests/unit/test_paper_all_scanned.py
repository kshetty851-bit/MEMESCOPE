"""Forward Track Record paper strategy invariants."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.models.market import TradingStatus
from app.paper.models import Candidate, ExitReason
from app.paper.service import PaperWalletService
from app.paper.strategy import PAPER_TRACK_RECORD_TP125_SL50_V1, registry

pytestmark = pytest.mark.unit

NOW = datetime(2026, 8, 16, 12, tzinfo=UTC)


def candidate(**changes: object) -> Candidate:
    values: dict[str, object] = {
        "mint_address": "mint", "rank": 999, "price_usd": Decimal("10"), "observed_at": NOW
    }
    values.update(changes)
    return Candidate(**values)  # type: ignore[arg-type]


def position(**changes: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "id": "position", "entry_price": Decimal("10"), "target_price": Decimal("12.5"),
        "stop_price": Decimal("5"), "peak_price": Decimal("10"), "last_evaluated_at": NOW,
    }
    values.update(changes)
    return SimpleNamespace(**values)


def row(price: str, at: datetime) -> SimpleNamespace:
    return SimpleNamespace(
        price_usd=Decimal(price), captured_at=at, liquidity_usd=Decimal("1000"),
        trading_status=TradingStatus.TRADING,
    )


def service() -> tuple[PaperWalletService, AsyncMock]:
    instance = PaperWalletService(None)  # type: ignore[arg-type]
    repository = AsyncMock()
    instance._repository = repository
    instance._exit_execution_for = AsyncMock(  # type: ignore[method-assign]
        return_value=SimpleNamespace(estimated_price_usd=Decimal("13"))
    )
    instance._execution_close_values = lambda _: {"exit_execution_model_version": "test"}  # type: ignore[method-assign]
    return instance, repository


def test_track_record_is_the_only_operational_ten_dollar_strategy() -> None:
    assert registry.default is PAPER_TRACK_RECORD_TP125_SL50_V1
    assert sum(strategy.operational for strategy in registry.all()) == 1
    entry = PAPER_TRACK_RECORD_TP125_SL50_V1.entry_for(
        candidate(rank=50_000), cash_available=Decimal("10"), now=NOW
    )
    assert entry is not None
    assert entry.size_usd == Decimal("10")
    assert entry.target_price == Decimal("12.50")
    assert entry.stop_price == Decimal("5.00")
    assert entry.trailing_drawdown is None
    assert entry.trailing_activation_multiple is None


def test_entry_uses_admission_not_a_second_score_risk_or_rank_gate() -> None:
    entry = PAPER_TRACK_RECORD_TP125_SL50_V1.entry_for(
        candidate(rank=999_999), cash_available=Decimal("10"), now=NOW
    )
    assert entry is not None


@pytest.mark.asyncio
async def test_gap_through_target_keeps_observed_quote_as_evidence() -> None:
    instance, repository = service()
    repository.close.return_value = True
    await instance._settle_observed_bracket(
        position(), rows=[row("13", NOW + timedelta(minutes=1))]
    )
    write = repository.close.await_args.kwargs
    assert write["exit_reason"] == ExitReason.TARGET.value
    assert write["exit_observed_price"] == Decimal("13")
    assert write["closed_at"] == NOW + timedelta(minutes=1)


@pytest.mark.asyncio
async def test_no_exit_between_fixed_barriers_and_no_trail_activation() -> None:
    instance, repository = service()
    closed = await instance._settle_observed_bracket(
        position(),
        rows=[
            row("12.4", NOW + timedelta(minutes=1)),
            row("8", NOW + timedelta(minutes=2)),
        ],
    )
    assert not closed
    repository.close.assert_not_awaited()
    repository.advance.assert_awaited_once()
