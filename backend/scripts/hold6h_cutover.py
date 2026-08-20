"""HOLD-6H generation cutover. Archives the outgoing generation. Nothing else.

Deliberately identical in shape to `sec2_cutover.py`, and for the same reason:
it does not create the new wallet — `PaperWalletService` does that on its next
pass through the same `ensure_wallet` path every generation has used, so a
cutover introduces no second creation path and no second source of capital.

It touches **no position row**. Generation 7's open positions keep their rules
(no maximum hold), their watermarks and their generation attribution;
PW-LIFECYCLE-1 is what keeps them being exited after their wallet is archived.

Idempotent: run twice and the second run reports there is nothing to do.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from sqlalchemy import func, select, update

from app.db.session import SessionFactory
from app.models.paper import PaperPosition, PaperWallet
from app.paper.strategy import (
    TRAILING_STOP_25_SECURED_HOLD6H_V3,
    TRAILING_STOP_25_SECURED_V2,
    lineage_for,
)

REASON = (
    "Archived at the HOLD-6H cutover on 2026-08-20. Superseded by "
    "trailing_stop_25_secured_hold6h_v3, which applies the same $100 equal "
    "weight, the same 25% trailing stop and the same strict security entry "
    "gate, with a six-hour maximum holding time added. Capital is inherited, "
    "not recreated: both generations share one lineage pool with Generation 2. "
    "This generation's open positions continue to be exited under their "
    "original rules — including no maximum hold — and its record is retained "
    "unchanged."
)


async def main() -> None:
    async with SessionFactory() as session:
        live = await session.scalar(
            select(PaperWallet).where(PaperWallet.archived_at.is_(None)).with_for_update()
        )
        if live is None:
            print("No live wallet. Nothing to archive.")
            return
        if live.strategy_id == TRAILING_STOP_25_SECURED_HOLD6H_V3.id:
            print(f"Already cut over: generation {live.generation} is the HOLD-6H wallet.")
            return
        if live.strategy_id != TRAILING_STOP_25_SECURED_V2.id:
            raise SystemExit(
                f"refusing to archive unexpected live wallet {live.strategy_id!r}"
            )

        open_count = await session.scalar(
            select(func.count())
            .select_from(PaperPosition)
            .where(PaperPosition.wallet_id == live.id, PaperPosition.status == "open")
        )
        print(f"outgoing wallet   : generation {live.generation} ({live.strategy_id})")
        print(f"open positions    : {open_count}  (kept open, kept managed)")
        print(f"lineage           : {sorted(lineage_for(live.strategy_id))}")

        await session.execute(
            update(PaperWallet)
            .where(PaperWallet.id == live.id, PaperWallet.archived_at.is_(None))
            .values(archived_at=datetime.now(UTC), archive_reason=REASON)
        )
        await session.commit()

        still_open = await session.scalar(
            select(func.count())
            .select_from(PaperPosition)
            .where(PaperPosition.wallet_id == live.id, PaperPosition.status == "open")
        )
        assert still_open == open_count, "cutover must not touch a position"
        print("archived          : yes")
        print(f"open positions now: {still_open}  (unchanged)")
        print("The next review pass creates the HOLD-6H generation.")


if __name__ == "__main__":
    asyncio.run(main())
