"""Start the Karthik wallet. Once.

    docker compose ... run --rm --no-deps backend python -m app.karthik.activate

Deliberately a command an operator runs rather than an HTTP route or a startup
hook, because `activated_at` is the one value in this experiment that cannot be
wrong. It is the eligibility watermark: every token admitted to the Track Record
after this instant is Karthik's to trade, and every token admitted before it is
permanently not. A route could be called twice, called by accident, or called
from a machine whose clock disagrees; a startup hook would move the watermark
every time a container restarted.

Re-running this is safe and does nothing. `karthik_wallets` carries a unique
index over a constant expression, so the second wallet cannot exist, and the
repository's `ON CONFLICT DO NOTHING` turns a second activation into a read of
the first. The instant a wallet was started at is therefore permanent by
construction rather than by discipline.

It prints the state it created so the operator can check the four things that
must be true at activation — no positions, no closed trades, no realised P&L,
and the full starting capital in cash — without a second command.
"""

from __future__ import annotations

import asyncio
import json

from app.db.session import SessionFactory
from app.karthik.service import KarthikService, utcnow


async def main() -> None:
    async with SessionFactory() as session:
        service = KarthikService(session)
        wallet = await service.activate(now=utcnow())
        await session.commit()

        read = await service.read(now=utcnow())
        # A command-line tool's output is its whole purpose; the structured
        # logger writes to a stream the operator running this will not see.
        print(  # noqa: T201
            json.dumps(
                {
                    "wallet_id": str(wallet.id),
                    "name": wallet.name,
                    "activated_at": wallet.activated_at.isoformat(),
                    "starting_capital": str(wallet.starting_capital),
                    "trade_size": str(wallet.trade_size),
                    "take_profit_multiple": str(wallet.take_profit_multiple),
                    "cash": str(read.cash),
                    "full_equity": str(read.equity),
                    "open_positions": len(read.open_positions),
                    "closed_positions": len(read.closed_positions),
                    "realized_pnl": str(read.realized_pnl),
                    "historical_backfill": 0,
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    asyncio.run(main())
