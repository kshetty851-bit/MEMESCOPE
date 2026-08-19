"""Deliberately resume the persisted Generation 2 trailing-stop paper wallet.

Run once, after verifying the archived rows.  This script does not create,
delete, or update any paper position, audit, snapshot, or decision row.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from app.db.session import SessionFactory
from app.paper.repository import PaperRepository


async def main() -> None:
    resumed_at = datetime.now(UTC)
    async with SessionFactory() as session:
        async with session.begin():
            wallet = await PaperRepository(session).restore_generation_two(
                resumed_at=resumed_at,
                archive_live_reason=(
                    "Archived unchanged while persisted Generation 2 "
                    "trailing_stop_25_v1 was explicitly resumed."
                ),
            )
        print(
            "resumed_generation=2 "
            f"strategy={wallet.strategy_id} version={wallet.strategy_version} "
            f"resume_watermark_at={resumed_at.isoformat()}"
        )


if __name__ == "__main__":
    asyncio.run(main())
