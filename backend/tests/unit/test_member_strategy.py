"""USER 1 on its own strategy (Karthik, 2026-10-03): G-Q50, several at once."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.core.config import settings
from app.real_wallet.driver import member_strategy
from app.real_wallet.policy import AutonomousExecutionPolicy, PolicyReason, PolicyState


def test_user1_trades_g_q50_and_the_others_the_owners_strategy(
        monkeypatch: pytest.MonkeyPatch) -> None:
    # What docker-compose.yml sets in production.
    monkeypatch.setattr(settings, "REAL_WALLET_MEMBER_STRATEGY", {"USER1": "G-Q50"})
    assert member_strategy("USER1", "G-QUIET") == "G-Q50"
    assert member_strategy("user1", "G-QUIET") == "G-Q50"
    assert member_strategy("USER2", "G-QUIET") == "G-QUIET"


def test_a_strategy_that_is_not_a_live_arm_is_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "REAL_WALLET_MEMBER_STRATEGY", {"USER1": "G-TYPO"})
    assert member_strategy("USER1", "G-QUIET") == "G-QUIET"


def _reasons(open_positions: int, max_open: int | None) -> tuple[str, ...]:
    state = PolicyState(open_positions=open_positions, exposure_usd=Decimal(0),
                        daily_notional_usd=Decimal(0), daily_realised_loss_usd=Decimal(0),
                        max_open_positions=max_open)
    return tuple(AutonomousExecutionPolicy._size_and_count_reasons(Decimal(10), state))


def test_a_wallet_limit_replaces_the_platforms_one(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "REAL_WALLET_MAX_OPEN_POSITIONS", 1)
    assert PolicyReason.MAX_OPEN_POSITIONS in _reasons(1, None)
    assert PolicyReason.MAX_OPEN_POSITIONS not in _reasons(1, 25)
    assert PolicyReason.MAX_OPEN_POSITIONS in _reasons(25, 25)


def test_the_owner_limit_is_off_unless_production_sets_it() -> None:
    # docker-compose.yml sets 25 in production; the user wallets keep theirs.
    assert settings.REAL_WALLET_OWNER_MAX_OPEN is None
