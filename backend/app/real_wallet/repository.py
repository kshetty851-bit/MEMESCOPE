"""Persistence and idempotency for real-wallet dry-run decisions."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.real_wallet_execution import RealWalletExecutionIntent
from app.real_wallet.policy import PolicyState


class RealWalletExecutionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record(self, **values: Any) -> RealWalletExecutionIntent | None:
        result = await self._session.execute(
            insert(RealWalletExecutionIntent)
            .values(**values)
            .on_conflict_do_nothing(index_elements=[RealWalletExecutionIntent.idempotency_key])
            .returning(RealWalletExecutionIntent)
        )
        return result.scalar_one_or_none()

    async def policy_state(self, *, now: datetime) -> PolicyState:
        today = now.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        would_buy = RealWalletExecutionIntent.status == "WOULD_BUY"
        totals = await self._session.execute(
            select(
                func.count().filter(would_buy).label("open_positions"),
                func.coalesce(
                    func.sum(RealWalletExecutionIntent.requested_usd).filter(would_buy), 0
                ),
                func.coalesce(
                    func.sum(RealWalletExecutionIntent.requested_usd).filter(
                        would_buy & (RealWalletExecutionIntent.evaluated_at >= today)
                    ),
                    0,
                ),
            )
        )
        row = totals.one()
        return PolicyState(
            open_positions=int(row.open_positions or 0),
            exposure_usd=Decimal(str(row[1] or 0)),
            daily_notional_usd=Decimal(str(row[2] or 0)),
            daily_realised_loss_usd=Decimal(0),
        )

    async def held_mints(self) -> set[str]:
        rows = await self._session.scalars(
            select(RealWalletExecutionIntent.mint_address).where(
                RealWalletExecutionIntent.status == "WOULD_BUY"
            )
        )
        return set(rows.all())

    async def latest(self, *, limit: int = 100) -> list[RealWalletExecutionIntent]:
        return list(
            (
                await self._session.scalars(
                    select(RealWalletExecutionIntent)
                    .order_by(RealWalletExecutionIntent.evaluated_at.desc())
                    .limit(limit)
                )
            ).all()
        )
