"""`/labs/btc-range` - paper only. Two GETs and one POST that computes.

The POST (`/backtest`) replays stored candles through the strategy and returns
the result. It places no order, holds no key and writes nothing: the lab has no
wallet, no router and no exchange credential anywhere in the package, so there
is nothing here for a request to move.

With `LAB_BTC_RANGE_ENABLED` off, `/status` answers `running: false` without a
query - "off" and "found nothing" are different facts. `/config` and `/backtest`
work either way, because they read candles that are already stored.

Thin by design: parse, call the service, map its two error types to 422. SQL
lives in the repository and the maths in the engine.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException

from app.api.deps import DbSession
from app.core.config import settings
from app.labs.btc_range import service
from app.labs.btc_range.schemas import BacktestIn, BacktestOut, ConfigOut, StatusOut

router = APIRouter(prefix="/labs/btc-range", tags=["btc-range-lab"])


@router.get("/status", response_model=StatusOut)
async def status(db: DbSession) -> StatusOut:
    return await service.build_status(
        db,
        now=datetime.now(UTC),
        enabled=settings.LAB_BTC_RANGE_ENABLED,
        live_start=service.as_utc(settings.LAB_BTC_RANGE_LIVE_START),
    )


@router.get("/config", response_model=ConfigOut)
async def config(db: DbSession) -> ConfigOut:
    return await service.build_config(db)


@router.post("/backtest", response_model=BacktestOut)
async def backtest(body: BacktestIn, db: DbSession) -> BacktestOut:
    try:
        return await service.run_window_backtest(
            db, cfg=body.config.to_config(), start=body.start, end=body.end
        )
    except (service.InvalidConfigError, service.InvalidWindowError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
