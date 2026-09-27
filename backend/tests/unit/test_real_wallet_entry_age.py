"""The real wallet refuses a graduation coin more than two minutes after it
graduated, or of unknown age (Karthik, 2026-09-27, after EVO)."""

from datetime import UTC, datetime, timedelta

import pytest

from app.real_wallet.driver import RealWalletDriver

pytestmark = pytest.mark.unit

NOW = datetime(2026, 9, 27, 12, 0, tzinfo=UTC)


def grad(seconds_ago: float | None) -> dict:
    return {"graduated_at": None if seconds_ago is None
            else (NOW - timedelta(seconds=seconds_ago)).isoformat()}


@pytest.mark.parametrize("age, refused", [(30, False), (120, False), (121, True),
                                          (186, True), (None, True)])
def test_a_graduation_coin_past_two_minutes_or_unknown_age_is_not_bought(age, refused):
    assert RealWalletDriver._too_old("G-QUIET", grad(age), NOW) is refused
    assert RealWalletDriver._too_old("g-q150", grad(age), NOW) is refused


def test_strategies_without_a_graduation_are_not_aged():
    assert RealWalletDriver._too_old("V7-01", None, NOW) is False
