"""Run the real-wallet safety gate against current Radar candidates.

This command makes only public RPC/Jupiter quote reads. It does not construct,
sign, submit, or simulate a transaction. Each resulting safety decision is
persisted as an append-only audit record and printed as aggregate evidence.
"""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from decimal import Decimal

from sqlalchemy import select

from app.db.session import SessionFactory
from app.models.radar import RadarToken
from app.real_wallet_safety.service import RealWalletSafetyGate


async def run(*, limit: int, trade_size_usd: Decimal) -> None:
    async with SessionFactory() as session:
        mints = list(
            (
                await session.execute(
                    select(RadarToken.mint_address)
                    .where(RadarToken.is_active.is_(True))
                    .order_by(
                        RadarToken.current_opportunity_score.desc(),
                        RadarToken.mint_address.asc(),
                    )
                    .limit(limit)
                )
            ).scalars()
        )
        decisions = []
        for mint in mints:
            decisions.append(
                await RealWalletSafetyGate(session).evaluate(
                    mint_address=mint, trade_size_usd=trade_size_usd
                )
            )
        await session.commit()

    reasons = Counter(reason for item in decisions for reason in item.reason_codes)
    print(
        {
            "evaluated": len(decisions),
            "allowed": sum(item.decision == "ALLOW" for item in decisions),
            "rejected": sum(item.decision == "REJECT" for item in decisions),
            "rejections": dict(sorted(reasons.items())),
        }
    )
    for item in (item for item in decisions if item.decision == "REJECT"):
        print({"mint": item.mint_address, "reasons": list(item.reason_codes)})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--trade-size-usd", type=Decimal, default=Decimal("100"))
    args = parser.parse_args()
    asyncio.run(run(limit=args.limit, trade_size_usd=args.trade_size_usd))


if __name__ == "__main__":
    main()
