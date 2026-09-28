"""Karthik and Rafiq's shares of the real wallet (Karthik, 2026-09-28).

"Me and Rafiq invested $100 from 3 PM today ... we did 50-50 here in the
wallet." The wallet held 0.8457 SOL (~$100) at 15:00 Dubai on 28 Sep with no
trade open, so the partnership starts there at $100, $50 each, and each
partner's share is half of every trade the wallet has closed since.

Trading profit only (closed trades, net of costs where measured): SOL's own
price moving is not counted, and a later deposit or withdrawal is not profit.
The days are 24-hour windows from 15:00 Dubai, each day's % of the balance it
opened with — the same rule as Karthik's Lab.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.real_wallet_execution import RealWalletPosition

START = datetime(2026, 9, 28, 11, 0, tzinfo=UTC)  # 15:00 Dubai
CAPITAL = Decimal("100")
SHARES: tuple[tuple[str, Decimal], ...] = (
    ("Karthik", Decimal("0.5")),
    ("Rafiq", Decimal("0.5")),
)
DAY = timedelta(hours=24)
CENT = Decimal("0.01")


def _money(value: Decimal) -> str:
    return str(value.quantize(CENT))


def book(
    rows: list[tuple[datetime, datetime | None, Decimal | None, str]], now: datetime
) -> dict[str, object]:
    """The partnership from (opened_at, closed_at, pnl, status) rows opened
    since START. Pure, so the arithmetic is tested without a database."""
    closed = sorted(
        (r for r in rows if r[3] == "CLOSED" and r[1] is not None and r[2] is not None),
        key=lambda r: r[1],
    )
    profit = sum((Decimal(r[2]) for r in closed), Decimal(0))
    days: list[dict[str, object]] = []
    n = 0
    while START + n * DAY <= now:
        start, end = START + n * DAY, START + (n + 1) * DAY
        opened_with = CAPITAL + sum(
            (Decimal(r[2]) for r in closed if r[1] < start), Decimal(0)
        )
        today = [Decimal(r[2]) for r in closed if start <= r[1] < end]
        made = sum(today, Decimal(0))
        days.append(
            {
                "n": n + 1,
                "from": start.isoformat(),
                "to": end.isoformat(),
                "running": now < end,
                "trades": len(today),
                "pnl_usd": _money(made),
                "pct": str((made / opened_with * 100).quantize(CENT))
                if opened_with
                else "0.00",
                "balance_usd": _money(opened_with + made),
            }
        )
        n += 1
    return {
        "started_at": START.isoformat(),
        "capital_usd": _money(CAPITAL),
        "profit_usd": _money(profit),
        "balance_usd": _money(CAPITAL + profit),
        "pct": str((profit / CAPITAL * 100).quantize(CENT)),
        "trades": len(closed),
        "wins": sum(1 for r in closed if Decimal(r[2]) > 0),
        "open": sum(1 for r in rows if r[3] == "OPEN"),
        "partners": [
            {
                "name": name,
                "share": str(share),
                "put_in_usd": _money(CAPITAL * share),
                "profit_usd": _money(profit * share),
                "now_usd": _money((CAPITAL + profit) * share),
            }
            for name, share in SHARES
        ],
        "days": list(reversed(days)),  # newest first, like the lab
    }


async def summary(session: AsyncSession, now: datetime | None = None) -> dict[str, object]:
    owner = settings.REAL_WALLET_PUBLIC_KEY.strip()
    pnl = func.coalesce(
        RealWalletPosition.realised_net_pnl_usd, RealWalletPosition.realised_gross_pnl_usd
    )
    rows = (
        await session.execute(
            select(
                RealWalletPosition.opened_at,
                RealWalletPosition.closed_at,
                pnl,
                RealWalletPosition.status,
            ).where(
                RealWalletPosition.opened_at >= START,
                or_(
                    RealWalletPosition.wallet_public_key == owner,
                    RealWalletPosition.wallet_public_key.is_(None),
                ),
            )
        )
    ).all()
    return book([tuple(r) for r in rows], now or datetime.now(UTC))


__all__ = ["CAPITAL", "SHARES", "START", "book", "summary"]
