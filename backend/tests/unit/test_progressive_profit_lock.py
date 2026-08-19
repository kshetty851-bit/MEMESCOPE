from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.paper.canonical_replay import Opportunity
from app.paper.models import Quote
from app.paper.progressive_profit_lock import replay


def quote(at: datetime, price: str) -> Quote:
    return Quote(at, Decimal(price), Decimal("10000"))


def opportunity(at: datetime) -> Opportunity:
    return Opportunity("mint", at, 1, Decimal("1"), Decimal("10000"), Decimal("12500"), None)


def test_initial_stop_uses_actual_breach_price() -> None:
    at = datetime(2026, 1, 1, tzinfo=UTC)
    result = replay(
        [opportunity(at)], {"mint": [quote(at, "1"), quote(at + timedelta(minutes=1), "0.80")]}
    )
    assert result.trades[0].exit_kind == "initial_stop"
    assert result.trades[0].exit_price == Decimal("0.80")


def test_floor_only_tightens_and_uses_actual_breach_price() -> None:
    at = datetime(2026, 1, 1, tzinfo=UTC)
    result = replay(
        [opportunity(at)],
        {
            "mint": [
                quote(at, "1"),
                quote(at + timedelta(minutes=1), "1.26"),
                quote(at + timedelta(minutes=2), "1.03"),
            ]
        },
    )
    assert result.trades[0].exit_kind == "profit_floor"
    assert result.trades[0].exit_price == Decimal("1.03")
    assert Decimal("0.25") in result.trades[0].reached


def test_after_100_percent_locks_sixty_percent_of_peak_profit() -> None:
    at = datetime(2026, 1, 1, tzinfo=UTC)
    result = replay(
        [opportunity(at)],
        {
            "mint": [
                quote(at, "1"),
                quote(at + timedelta(minutes=1), "2.50"),
                quote(at + timedelta(minutes=2), "1.85"),
            ]
        },
    )
    assert result.trades[0].exit_kind == "profit_floor"
    assert result.trades[0].exit_price == Decimal("1.85")
    assert Decimal("1.00") in result.trades[0].reached
