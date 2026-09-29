"""Karthik and Rafiq's shares of the real wallet (Karthik, 2026-09-28).

"Me and Rafiq invested $100 from 3 PM today ... we did 50-50 here in the
wallet." The wallet held 0.8457 SOL (~$100) at 15:00 Dubai on 28 Sep with no
trade open, so the partnership starts there at $100, $50 each, and each
partner's share is half of every trade the wallet has closed since.

Trading profit only (closed trades, net of costs where measured): SOL's own
price moving is not counted, and a later deposit or withdrawal is not profit.
The days are 24-hour windows from 15:00 Dubai, each day's % of the balance it
opened with — the same rule as Karthik's Lab.

WHAT IT IS WORTH NOW (Karthik, 2026-09-29: "show current profit calculating
SOL current value ... divide as per the 37.63 bcuz its fluctuate as per SOL
value"): the headline profit is the wallet's value now — its SOL at today's
price, plus an open trade at what it would sell for now, since that money is
in a coin for five minutes and not in SOL — minus the $100, split half and
half. It moves with
SOL's price. The trading profit above stays beside it, and the days are still
trading profit. A deposit or withdrawal after the start would show here as
profit or loss; there has been none.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.real_wallet_execution import RealWalletPosition

START = datetime(2026, 9, 28, 11, 0, tzinfo=UTC)  # 15:00 Dubai
CAPITAL = Decimal("100")
#: What the wallet held at START, the $100 in SOL.
CAPITAL_SOL = Decimal("0.8457")
SOL_DP = Decimal("0.0001")
SHARES: tuple[tuple[str, Decimal], ...] = (
    ("Karthik", Decimal("0.5")),
    ("Rafiq", Decimal("0.5")),
)
DAY = timedelta(hours=24)
CENT = Decimal("0.01")


def _money(value: Decimal) -> str:
    return str(value.quantize(CENT))


def _sol(value: Decimal) -> str:
    return str(value.quantize(SOL_DP, rounding=ROUND_HALF_UP))


def book(
    rows: list[tuple[datetime, datetime | None, Decimal | None, str]],
    now: datetime,
    sol_usd: Decimal | None = None,
    wallet_sol: Decimal | None = None,
    open_cost_usd: Decimal = Decimal(0),
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
    # The wallet now, at today's price: None without a price or a balance.
    worth = (None if not sol_usd or wallet_sol is None
             else Decimal(wallet_sol) * sol_usd + open_cost_usd)

    def in_sol(share: Decimal) -> dict[str, str | None]:
        """A partner's (or, share 1, the whole) value now, in dollars and SOL."""
        out: dict[str, str | None] = {"put_in_sol": _sol(CAPITAL_SOL * share),
                                      "value_usd": None, "value_profit_usd": None,
                                      "value_sol": None, "value_profit_sol": None}
        if worth is None:
            return out
        mine, made = worth * share, (worth - CAPITAL) * share
        return {**out, "value_usd": _money(mine), "value_profit_usd": _money(made),
                "value_sol": _sol(mine / sol_usd), "value_profit_sol": _sol(made / sol_usd)}

    return {
        "started_at": START.isoformat(),
        "sol_usd": None if not sol_usd else _money(Decimal(sol_usd)),
        "value_pct": (None if worth is None
                      else str(((worth - CAPITAL) / CAPITAL * 100).quantize(CENT))),
        "open_cost_usd": _money(open_cost_usd),
        **{f"total_{k}": v for k, v in in_sol(Decimal(1)).items()},
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
                **in_sol(share),
            }
            for name, share in SHARES
        ],
        "days": list(reversed(days)),  # newest first, like the lab
    }


async def summary(session: AsyncSession, now: datetime | None = None, *,
                  wallet_sol: Decimal | None = None,
                  sol_usd: Decimal | None = None) -> dict[str, object]:
    """`wallet_sol` and `sol_usd` are the ones the page's balance was read
    with, so the box and the balance agree to the cent."""
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
                RealWalletPosition.entry_price_usd * RealWalletPosition.quantity
                * func.coalesce(RealWalletPosition.last_exec_multiple, 1),
            ).where(
                RealWalletPosition.opened_at >= START,
                or_(
                    RealWalletPosition.wallet_public_key == owner,
                    RealWalletPosition.wallet_public_key.is_(None),
                ),
            )
        )
    ).all()
    now = now or datetime.now(UTC)
    if sol_usd is None:
        from app.real_wallet import sol_price

        sol_usd = await sol_price.current_usd(now)
    # An open trade at what it would sell for now, the same as the balance card.
    open_cost = sum((Decimal(r[4] or 0) for r in rows if r[3] == "OPEN"), Decimal(0))
    return book([tuple(r[:4]) for r in rows], now, sol_usd,
                wallet_sol=wallet_sol, open_cost_usd=open_cost)


__all__ = ["CAPITAL", "CAPITAL_SOL", "SHARES", "START", "book", "summary"]
