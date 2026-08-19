"""Date-by-date paper-wallet returns from the immutable trade record.

The wallet's current return remains a marked-to-market measurement: it includes
open holdings only when every one has a stored price. Daily results answer a
different question — what completed trades recorded on each UTC calendar day.
They are derived from ``paper_trade_audit`` rather than the mutable positions
table so an old daily result cannot change when later market data arrives.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Protocol

_ZERO = Decimal(0)
_HUNDRED = Decimal(100)
_PCT = Decimal("0.01")
_MONEY = Decimal("0.01")


class AuditedReturn(Protocol):
    """The immutable fields needed to place one completed trade in a day."""

    exit_at: datetime
    gross_return_usd: Decimal
    net_return_usd: Decimal | None


@dataclass(frozen=True, slots=True)
class DailyReturn:
    """The completed-trade result for one UTC day.

    ``net_*`` stays absent if even one close that day could not be costed. It
    would be misleading to total the costed trades and present that subset as
    the day's collectable return.
    """

    date: date
    completed_trades: int
    gross_pnl_usd: Decimal
    gross_return_pct: Decimal | None
    net_pnl_usd: Decimal | None
    net_return_pct: Decimal | None
    cost_unavailable_trades: int


def daily_returns(
    audits: Iterable[AuditedReturn], *, starting_balance: Decimal
) -> list[DailyReturn]:
    """Group permanent completed-trade returns by UTC exit date, newest first.

    Percentages are each day's P/L relative to the capital the wallet began
    with. They are a comparable daily contribution to the overall return, not
    an invented intra-day equity change — the system does not retain a complete
    mark-to-market equity curve for every day.
    """

    grouped: dict[date, list[AuditedReturn]] = defaultdict(list)
    for audit in audits:
        grouped[audit.exit_at.astimezone(UTC).date()].append(audit)

    out: list[DailyReturn] = []
    for day in sorted(grouped, reverse=True):
        rows = grouped[day]
        gross = sum((row.gross_return_usd for row in rows), _ZERO).quantize(_MONEY)
        unavailable = sum(1 for row in rows if row.net_return_usd is None)
        net = (
            None
            if unavailable
            else sum((row.net_return_usd or _ZERO for row in rows), _ZERO).quantize(_MONEY)
        )
        out.append(
            DailyReturn(
                date=day,
                completed_trades=len(rows),
                gross_pnl_usd=gross,
                gross_return_pct=_return_pct(gross, starting_balance),
                net_pnl_usd=net,
                net_return_pct=None if net is None else _return_pct(net, starting_balance),
                cost_unavailable_trades=unavailable,
            )
        )
    return out


def _return_pct(pnl: Decimal, starting_balance: Decimal) -> Decimal | None:
    if starting_balance <= 0:
        return None
    return (pnl / starting_balance * _HUNDRED).quantize(_PCT)
