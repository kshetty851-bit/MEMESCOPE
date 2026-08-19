"""Forward PAPER_2X_TRAIL25_V1 state-machine tests.

These tests deliberately exercise the service's stored-observation path rather
than the old generic trailing resolver: activation and conservative gap fills
are properties of the forward strategy, not of historical strategies.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.models.market import TradingStatus
from app.paper.models import Candidate, ExitReason
from app.paper.service import PaperWalletService
from app.paper.strategy import (
    PAPER_2X_TRAIL25_V1,
    PAPER_TRACK_RECORD_TP125_SL50_V1,
    registry,
)

pytestmark = pytest.mark.unit

NOW = datetime(2026, 8, 16, 12, tzinfo=UTC)


def position(**changes: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "id": "position-1",
        "entry_price": Decimal("10"),
        "trailing_activation_multiple": Decimal("2"),
        "trailing_drawdown": Decimal("0.25"),
        "trailing_activated_at": None,
        "trailing_activation_observed_price": None,
        "peak_price": Decimal("10"),
        "trailing_stop_price": None,
        "last_evaluated_at": NOW,
    }
    values.update(changes)
    return SimpleNamespace(**values)


def row(
    at: datetime, price: str | None, status: TradingStatus = TradingStatus.TRADING
) -> SimpleNamespace:
    return SimpleNamespace(
        captured_at=at,
        price_usd=None if price is None else Decimal(price),
        trading_status=status,
    )


def service() -> tuple[PaperWalletService, AsyncMock]:
    # The state machine is pure with respect to the supplied observations; the
    # repository is its persistence seam and is mocked to assert exact writes.
    instance = PaperWalletService(None)  # type: ignore[arg-type]
    repo = AsyncMock()
    instance._repository = repo
    return instance, repo


def candidate() -> Candidate:
    return Candidate(
        mint_address="mint", rank=500, price_usd=Decimal("10"), observed_at=NOW,
        liquidity_usd=Decimal("1000"),
    )


def test_trailing_strategy_is_archived_and_track_record_generation_is_operational() -> None:
    assert registry.default is PAPER_TRACK_RECORD_TP125_SL50_V1
    assert sum(item.operational for item in registry.all()) == 1
    assert not PAPER_2X_TRAIL25_V1.operational
    assert (
        PAPER_2X_TRAIL25_V1.entry_for(
            candidate(), cash_available=Decimal("10"), now=NOW
        )
        is None
    )


@pytest.mark.asyncio
async def test_no_price_stop_before_two_x_even_after_ninety_percent_decline() -> None:
    instance, repo = service()
    closed = await instance._settle_activated_trail(
        position(), rows=[row(NOW + timedelta(minutes=1), "1")], now=NOW + timedelta(minutes=1)
    )
    assert not closed
    repo.close.assert_not_awaited()
    repo.advance_activated_trail.assert_awaited_once()
    assert repo.advance_activated_trail.await_args.kwargs["activated_at"] is None


@pytest.mark.asyncio
async def test_exactly_two_x_arms_but_does_not_sell_same_sample() -> None:
    instance, repo = service()
    at = NOW + timedelta(minutes=1)
    closed = await instance._settle_activated_trail(position(), rows=[row(at, "20")], now=at)
    assert not closed
    repo.close.assert_not_awaited()
    write = repo.advance_activated_trail.await_args.kwargs
    assert write["activated_at"] == at
    assert write["activation_observed_price"] == Decimal("20")
    assert write["peak_price"] == Decimal("20")
    assert write["trailing_stop_price"] == Decimal("15")


@pytest.mark.asyncio
async def test_gap_through_trail_uses_observed_trigger_not_theoretical_stop() -> None:
    instance, repo = service()
    at = NOW + timedelta(minutes=2)
    repo.close.return_value = True
    closed = await instance._settle_activated_trail(
        position(
            trailing_activated_at=NOW + timedelta(minutes=1),
            trailing_activation_observed_price=Decimal("20"),
            peak_price=Decimal("20"), trailing_stop_price=Decimal("15"),
        ),
        rows=[row(at, "12")], now=at,
    )
    assert closed
    write = repo.close.await_args.kwargs
    assert write["exit_reason"] == ExitReason.TRAILING_STOP.value
    assert write["trailing_trigger_price"] == Decimal("15")
    assert write["trailing_trigger_observed_price"] == Decimal("12")
    assert write["exit_price"] == Decimal("12")


@pytest.mark.asyncio
async def test_peak_and_trail_only_rise_after_activation_and_terminal_needs_price() -> None:
    instance, repo = service()
    active = position(
        trailing_activated_at=NOW, trailing_activation_observed_price=Decimal("20"),
        peak_price=Decimal("20"), trailing_stop_price=Decimal("15"),
    )
    await instance._settle_activated_trail(
        active, rows=[row(NOW + timedelta(minutes=1), "30")], now=NOW + timedelta(minutes=1)
    )
    write = repo.advance_activated_trail.await_args.kwargs
    assert write["peak_price"] == Decimal("30")
    assert write["trailing_stop_price"] == Decimal("22.50")

    repo.reset_mock()
    await instance._settle_activated_trail(
        position(),
        rows=[row(NOW + timedelta(minutes=1), None, TradingStatus.INACTIVE)],
        now=NOW + timedelta(minutes=1),
    )
    repo.close.assert_not_awaited()
