"""SEC-2 generation cutover. Archives the outgoing generation. Nothing else.

Deliberately minimal. It does not create the new wallet — `PaperWalletService`
does that on its next pass, through the same `ensure_wallet` path every
generation has used, so the cutover introduces no second creation path.

It touches **no position row**. The outgoing generation's open positions keep
their rules, their watermarks and their generation attribution; PW-LIFECYCLE-1
is what keeps them being exited after their wallet is archived.

Idempotent: run twice and the second run reports that there is nothing to do.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from sqlalchemy import func, select, update

from app.db.session import SessionFactory
from app.models.paper import PaperPosition, PaperWallet
from app.paper.strategy import (
    TRAILING_STOP_25_SECURED_V2,
    TRAILING_STOP_25_V1,
    lineage_for,
)

REASON = (
    "Archived at the SEC-2 cutover on 2026-08-20. Superseded by "
    "trailing_stop_25_secured_v2, which applies the same rules with a strict "
    "on-chain security precondition on new entries. Capital is inherited, not "
    "recreated: both generations share one lineage pool. This generation's "
    "open positions continue to be exited under their original rules and its "
    "record is retained unchanged."
)


async def main() -> None:
    async with SessionFactory() as session:
        live = await session.scalar(
            select(PaperWallet).where(PaperWallet.archived_at.is_(None)).with_for_update()
        )
        if live is None:
            print("No live wallet. Nothing to archive.")
            return
        if live.strategy_id == TRAILING_STOP_25_SECURED_V2.id:
            print(f"Already cut over: generation {live.generation} is the secured wallet.")
            return
        if live.strategy_id != TRAILING_STOP_25_V1.id:
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
        print(f"archived          : yes")
        print(f"open positions now: {still_open}  (unchanged)")
        print("The next review pass creates the secured generation.")


if __name__ == "__main__":
    asyncio.run(main())
