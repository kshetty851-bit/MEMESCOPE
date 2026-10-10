"""`/labs/forex` - research and paper only.

Reads are public. Every POST needs a signed-in user, because a POST either
writes stored market data or starts a job that holds the lab's single worker
slot for minutes. There is no broker, no order route and no credential anywhere
in the package; nothing a request does can move money.

Thin by design: parse, call the service, map its errors. A config or request
that is out of bounds is 422, a missing run 404, a run with no trade list 400, a
run that has not finished 409. SQL lives in the repository and the maths in the
pure modules.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.api.deps import CurrentUser, DbSession
from app.labs.forex import prose, service
from app.labs.forex.schemas import (
    DataOut,
    FetchIn,
    ImportBatchOut,
    ImportIn,
    MetaOut,
    RunDetailOut,
    RunIn,
    RunListOut,
    RunOut,
    VersionIn,
    VersionListOut,
    VersionOut,
)

router = APIRouter(prefix="/labs/forex", tags=["forex-lab"])


def _unprocessable(exc: ValueError) -> HTTPException:
    return HTTPException(status_code=422, detail=prose.error_text(str(exc)))


def _not_found(run_id: int) -> HTTPException:
    return HTTPException(status_code=404, detail=f"No run {run_id}.")


@router.get("/meta", response_model=MetaOut)
async def get_meta() -> dict[str, object]:
    return service.build_meta()


@router.get("/data", response_model=DataOut)
async def get_data(db: DbSession) -> dict[str, object]:
    return await service.data_overview(db)


@router.get("/data/quality")
async def get_quality(
    db: DbSession,
    symbol: str = "EURUSD",
    timeframe: str = "5m",
    start: datetime | None = None,
    end: datetime | None = None,
) -> dict[str, object]:
    try:
        return await service.data_quality(
            db, symbol=symbol, timeframe=timeframe, start=start, end=end
        )
    except ValueError as exc:
        raise _unprocessable(exc) from exc


@router.post("/data/import", response_model=ImportBatchOut)
async def import_data(body: ImportIn, db: DbSession, user: CurrentUser) -> dict[str, object]:
    try:
        return await service.import_csv(
            db,
            symbol=body.symbol,
            timeframe=body.timeframe,
            fmt=body.fmt,
            utc_offset_minutes=body.utc_offset_minutes,
            filename=body.filename,
            content=body.content,
            created_by=user.id,
        )
    except ValueError as exc:
        raise _unprocessable(exc) from exc


@router.post("/data/fetch", response_model=RunOut, status_code=202)
async def fetch_data(
    body: FetchIn, db: DbSession, user: CurrentUser, background: BackgroundTasks
) -> dict[str, object]:
    try:
        run = await service.create_fetch_run(
            db,
            provider=body.provider,
            symbol=body.symbol,
            start_date=body.start_date,
            end_date=body.end_date,
            created_by=user.id,
        )
    except ValueError as exc:
        raise _unprocessable(exc) from exc
    background.add_task(service.launch, int(run["id"]))
    return run


@router.post("/runs", response_model=RunOut, status_code=202)
async def create_run(
    body: RunIn, db: DbSession, user: CurrentUser, background: BackgroundTasks
) -> dict[str, object]:
    try:
        run = await service.create_run(
            db,
            kind=body.kind,
            config=body.config,
            configs=body.configs,
            start=body.start,
            end=body.end,
            name=body.name,
            strategy_version_id=body.strategy_version_id,
            options=body.options,
            created_by=user.id,
        )
    except ValueError as exc:
        raise _unprocessable(exc) from exc
    background.add_task(service.launch, int(run["id"]))
    return run


@router.get("/runs", response_model=RunListOut)
async def list_runs(
    db: DbSession,
    kind: Annotated[str | None, Query(pattern="^(backtest|research|compare|fetch)$")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> dict[str, object]:
    return await service.list_runs(db, kind=kind, limit=limit)


@router.get("/runs/{run_id}", response_model=RunDetailOut)
async def get_run(run_id: int, db: DbSession) -> dict[str, object]:
    try:
        return await service.get_run(db, run_id)
    except service.RunNotFoundError as exc:
        raise _not_found(run_id) from exc


@router.get("/runs/{run_id}/trades.csv")
async def get_trades_csv(run_id: int, db: DbSession) -> StreamingResponse:
    try:
        filename, lines = await service.trades_csv(db, run_id)
    except service.RunNotFoundError as exc:
        raise _not_found(run_id) from exc
    except service.TradesUnavailableError as exc:
        raise HTTPException(
            status_code=400, detail="Only a backtest or research run has a trade list."
        ) from exc
    except service.RunNotReadyError as exc:
        raise HTTPException(status_code=409, detail="The run has not finished.") from exc
    return StreamingResponse(
        lines,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/versions", response_model=VersionListOut)
async def list_versions(db: DbSession) -> dict[str, object]:
    return await service.list_versions(db)


@router.post("/versions", response_model=VersionOut, status_code=201)
async def create_version(
    body: VersionIn, db: DbSession, user: CurrentUser
) -> dict[str, object]:
    try:
        return await service.create_version(
            db, name=body.name, config=body.config, notes=body.notes, created_by=user.id
        )
    except ValueError as exc:
        raise _unprocessable(exc) from exc
