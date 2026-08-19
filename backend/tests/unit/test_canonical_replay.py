from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.paper.canonical_replay import Opportunity, replay
from app.paper.models import ExitReason, Quote


def q(at: datetime, price: str, liquidity: str = "10000") -> Quote:
    return Quote(at, Decimal(price), Decimal(liquidity))


def o(
    mint: str, at: datetime, price: str = "1", liquidity: str = "10000", volume: str = "12500"
) -> Opportunity:
    return Opportunity(mint, at, 1, Decimal(price), Decimal(liquidity), Decimal(volume), None)


def test_uses_first_observed_take_profit_breach_not_theoretical_fill() -> None:
    at = datetime(2026, 1, 1, tzinfo=UTC)
    result = replay([o("a", at)], {"a": [q(at, "1"), q(at + timedelta(minutes=1), "1.34")]})
    trade = result.trades[0]
    assert trade.reason is ExitReason.TARGET
    assert trade.exit_price == Decimal("1.34")


def test_uses_first_observed_hard_stop_breach_not_theoretical_fill() -> None:
    at = datetime(2026, 1, 1, tzinfo=UTC)
    result = replay([o("a", at)], {"a": [q(at, "1"), q(at + timedelta(minutes=1), "0.70")]})
    assert result.trades[0].reason is ExitReason.STOP
    assert result.trades[0].exit_price == Decimal("0.70")


def test_cash_and_costs_prevent_unlimited_overlapping_entries() -> None:
    at = datetime(2026, 1, 1, tzinfo=UTC)
    opportunities = [o(str(index), at + timedelta(seconds=index)) for index in range(11)]
    result = replay(opportunities, {str(index): [q(at, "1")] for index in range(11)})
    assert result.accepted < 11
    assert result.rejected_insufficient_cash > 0
    assert result.marked_equity is not None


def test_survival_and_unresolved_mark_are_deterministic() -> None:
    at = datetime(2026, 1, 1, tzinfo=UTC)
    histories = {"a": [q(at, "1"), q(at + timedelta(minutes=1), "1.10")]}
    first = replay([o("a", at)], histories)
    second = replay([o("a", at)], histories)
    assert first == second
    assert first.trades[0].closed is False
    assert first.trades[0].final_mark == Decimal("1.10")
    rejected = replay([o("b", at, volume="12499")], {"b": [q(at, "1")]})
    assert rejected.accepted == 0
    assert rejected.rejected_survival == 1


def test_entry_uses_only_entry_time_survival_evidence() -> None:
    at = datetime(2026, 1, 1, tzinfo=UTC)
    # A later observation could pass the gate, but it cannot repair this entry.
    result = replay(
        [o("a", at, volume="100")],
        {"a": [q(at, "1"), q(at + timedelta(minutes=1), "2", "10")]},
    )
    assert result.accepted == 0
    assert result.rejected_survival == 1


def test_missing_liquidity_is_refused_not_costed_at_an_invented_depth() -> None:
    at = datetime(2026, 1, 1, tzinfo=UTC)
    result = replay(
        [Opportunity("a", at, 1, Decimal("1"), None, Decimal("100"), None)],
        {"a": [Quote(at, Decimal("1"), None)]},
    )
    assert result.accepted == 0
    assert result.rejected_missing_data == 1
