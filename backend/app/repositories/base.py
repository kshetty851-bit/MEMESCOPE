"""Generic async repository.

Repositories own persistence concerns; services own business rules. Keeping the
split means query changes never leak into domain code, and services can be
unit-tested against a fake repository.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any, Generic, TypeVar, cast

from sqlalchemy import CursorResult, Select, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import Base

ModelT = TypeVar("ModelT", bound=Base)


class BaseRepository(Generic[ModelT]):
    model: type[ModelT]

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, entity_id: uuid.UUID) -> ModelT | None:
        return await self.session.get(self.model, entity_id)

    async def get_by(self, **filters: Any) -> ModelT | None:
        result = await self.session.execute(self._filtered(select(self.model), filters))
        return result.scalars().first()

    async def list(
        self, *, offset: int = 0, limit: int = 20, **filters: Any
    ) -> Sequence[ModelT]:
        stmt = self._filtered(select(self.model), filters).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def count(self, **filters: Any) -> int:
        stmt = self._filtered(select(func.count()).select_from(self.model), filters)
        return int((await self.session.execute(stmt)).scalar_one())

    def add(self, entity: ModelT) -> ModelT:
        self.session.add(entity)
        return entity

    async def create(self, **values: Any) -> ModelT:
        entity = self.model(**values)
        self.session.add(entity)
        await self.session.flush()
        await self.session.refresh(entity)
        return entity

    async def delete(self, entity: ModelT) -> None:
        await self.session.delete(entity)
        await self.session.flush()

    async def delete_by(self, **filters: Any) -> int:
        stmt = self._filtered(delete(self.model), filters)
        # DML always yields a CursorResult; only that subclass exposes rowcount.
        result = cast("CursorResult[Any]", await self.session.execute(stmt))
        return int(result.rowcount or 0)

    def _filtered(self, stmt: Any, filters: dict[str, Any]) -> Select[Any] | Any:
        for field, value in filters.items():
            column = getattr(self.model, field, None)
            if column is None:
                raise AttributeError(f"{self.model.__name__} has no column '{field}'")
            stmt = stmt.where(column == value)
        return stmt
