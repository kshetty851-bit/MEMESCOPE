"""Daily paper-wallet returns from the permanent audit record."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.paper.performance import daily_returns

pytestmark = pytest.mark.unit


@dataclass(frozen=True)
class AuditRow:
    exit_at: datetime
    gross_return_usd: Decimal
    net_return_usd: Decimal | None


def row(
    *,
    at: datetime,
    gross: str,
    net: str | None,
) -> AuditRow:
    return AuditRow(
        exit_at=at,
        gross_return_usd=Decimal(gross),
        net_return_usd=None if net is None else Decimal(net),
    )


class TestDailyReturns:
    def test_groups_completed_trades_by_utc_day_newest_first(self) -> None:
        rows = [
            row(
                at=datetime(2026, 8, 2, 0, 15, tzinfo=UTC),
                gross="20.00",
                net="18.00",
            ),
            row(
                at=datetime(2026, 8, 1, 23, 55, tzinfo=UTC),
                gross="10.00",
                net="8.00",
            ),
            row(
                at=datetime(2026, 8, 1, 12, 0, tzinfo=UTC),
                gross="-5.00",
                net="-6.00",
            ),
        ]

        daily = daily_returns(rows, starting_balance=Decimal(1000))

        assert [item.date.isoformat() for item in daily] == ["2026-08-02", "2026-08-01"]
        assert daily[0].completed_trades == 1
        assert daily[0].gross_pnl_usd == Decimal("20.00")
        assert daily[0].net_pnl_usd == Decimal("18.00")
        assert daily[0].gross_return_pct == Decimal("2.00")
        assert daily[0].net_return_pct == Decimal("1.80")
        assert daily[1].completed_trades == 2
        assert daily[1].gross_pnl_usd == Decimal("5.00")
        assert daily[1].net_pnl_usd == Decimal("2.00")

    def test_a_partly_uncosted_day_does_not_claim_a_partial_net_return(self) -> None:
        daily = daily_returns(
            [
                row(
                    at=datetime(2026, 8, 1, 12, 0, tzinfo=UTC),
                    gross="10.00",
                    net="8.00",
                ),
                row(
                    at=datetime(2026, 8, 1, 18, 0, tzinfo=UTC),
                    gross="-4.00",
                    net=None,
                ),
            ],
            starting_balance=Decimal(1000),
        )

        assert daily[0].gross_pnl_usd == Decimal("6.00")
        assert daily[0].net_pnl_usd is None
        assert daily[0].net_return_pct is None
        assert daily[0].cost_unavailable_trades == 1
