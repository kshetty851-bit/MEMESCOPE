"""Wire models for `/labs/forex/*`.

The page is built against `frontend/src/labs/forex/types.ts`, so these mirror
that contract. Request bounds that depend on the config (leverage, risk percent,
periods...) are NOT repeated here: `codec` owns them, so a saved version, a CLI
call and a grid cell are all held to the same limits. What lives here is only
what the wire needs - types, lengths, the 60 MB cap on an uploaded file.

Large nested results (`result`, quality reports, Monte Carlo blocks) are typed
as plain dicts on purpose: their sub-shapes are open in the contract and the
page renders them generically.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

MAX_UPLOAD_CHARS = 60_000_000


class Coded(BaseModel):
    code: str
    text: str


class MetaOut(BaseModel):
    instruments: list[dict[str, Any]]
    timeframes: list[str]
    risk_options_pct: list[str]
    strategies: list[dict[str, Any]]
    shared_fields: list[dict[str, Any]]
    providers: list[dict[str, Any]]
    target_pcts: list[int]
    disclaimer: Coded


class DatasetOut(BaseModel):
    symbol: str
    timeframe: str
    bars: int
    start: datetime
    end: datetime
    sources: list[str]


class ImportErrorOut(BaseModel):
    line: int
    message: str


class ImportBatchOut(BaseModel):
    id: int
    symbol: str
    timeframe: str
    source: str
    filename: str
    rows_total: int
    rows_accepted: int
    rows_inserted: int
    rows_existing: int
    error_count: int
    errors: list[ImportErrorOut]
    detected_format: str
    start: datetime | None
    end: datetime | None
    quality: dict[str, Any] | None
    notes: list[Coded]
    created_at: datetime


class FetchSummaryOut(BaseModel):
    provider: str
    days_ok: int
    days_empty: int
    days_failed: int
    first_day: date | None
    last_day: date | None


class DataOut(BaseModel):
    datasets: list[DatasetOut]
    imports: list[ImportBatchOut]
    fetch: FetchSummaryOut | None
    providers: list[dict[str, Any]]


class ImportIn(BaseModel):
    symbol: str = Field(min_length=1, max_length=16)
    timeframe: str = Field(min_length=1, max_length=8)
    fmt: Literal["auto", "generic", "histdata", "metatrader"] = "auto"
    utc_offset_minutes: int = Field(default=0, ge=-1440, le=1440)
    filename: str = Field(default="", max_length=256)
    content: str = Field(min_length=1, max_length=MAX_UPLOAD_CHARS)


class FetchIn(BaseModel):
    provider: Literal["dukascopy"]
    symbol: str = Field(default="EURUSD", min_length=1, max_length=16)
    start_date: date
    end_date: date


class RunIn(BaseModel):
    kind: Literal["backtest", "research", "compare"]
    config: dict[str, Any] | None = None
    configs: list[dict[str, Any]] | None = None
    start: datetime
    end: datetime
    name: str | None = Field(default=None, max_length=120)
    strategy_version_id: int | None = None
    options: dict[str, Any] | None = None


class RunOut(BaseModel):
    id: int
    kind: str
    status: str
    progress: int
    message: str | None
    name: str | None
    strategy_version_id: int | None
    config: dict[str, Any] | None
    request: dict[str, Any]
    data_fingerprint: str | None
    config_version: int
    app_version: str
    summary: dict[str, Any] | None
    error: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class RunListOut(BaseModel):
    runs: list[RunOut]


class RunDetailOut(BaseModel):
    run: RunOut
    result: dict[str, Any] | None


class VersionIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    config: dict[str, Any]
    notes: str | None = Field(default=None, max_length=4000)


class VersionOut(BaseModel):
    id: int
    name: str
    version: int
    strategy: str
    config: dict[str, Any]
    notes: str | None
    created_at: datetime


class VersionListOut(BaseModel):
    versions: list[VersionOut]
