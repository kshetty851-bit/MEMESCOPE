"""Shared response envelopes."""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class BaseSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class ErrorDetail(BaseSchema):
    code: str
    message: str
    details: dict[str, object] = Field(default_factory=dict)


class ErrorResponse(BaseSchema):
    error: ErrorDetail
    request_id: str | None = None


class PaginationParams(BaseSchema):
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


class Page(BaseSchema, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int

    @property
    def pages(self) -> int:
        return (self.total + self.page_size - 1) // self.page_size if self.page_size else 0


class HealthStatus(BaseSchema):
    status: str
    version: str
    environment: str
    checks: dict[str, dict[str, str]] = Field(default_factory=dict)
