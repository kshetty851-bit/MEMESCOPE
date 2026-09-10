"""`/labs/crypto-trend` — read-only. No POST/PUT/PATCH/DELETE.

With the flag off every route answers `running: false` without touching the
database: "the lab is not running" and "the lab ran and found nothing" are
different facts and must not render identically.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.labs.crypto_trend import config
from app.labs.crypto_trend.data import data_health, get_regime, get_trend_state, get_universe
from app.labs.crypto_trend.regime import Regime
from app.labs.crypto_trend.trend import TrendState, coin_verdict

router = APIRouter(prefix="/labs/crypto-trend", tags=["crypto-trend-lab"])


class TrendStateOut(BaseModel):
    timeframe: str
    bar_close_time: datetime
    computed_at: datetime
    direction: str
    strength: int
    slope: float
    atr_pct: float
    bars_in_state: int
    ema_fast: float
    ema_slow: float
    ema_trend: float | None
    adx: float
    structure: str
    structure_veto: bool
    close: float


class CoinTrendOut(BaseModel):
    symbol: str
    rank: int
    verdict: str
    reason: str
    #: Keyed by timeframe; None where no state exists yet.
    states: dict[str, TrendStateOut | None]


class TrendOut(BaseModel):
    running: bool
    computed_at: datetime | None
    coins: list[CoinTrendOut]


class RegimeOut(BaseModel):
    bar_close_time: datetime
    computed_at: datetime
    coins: int
    breadth_up: float
    breadth_down: float
    btc_direction: str | None
    eth_direction: str | None
    regime: str


class RegimeHistoryOut(BaseModel):
    running: bool
    latest: RegimeOut | None
    #: Newest first, the latest included.
    history: list[RegimeOut]


def _state_out(s: TrendState | None) -> TrendStateOut | None:
    return None if s is None else TrendStateOut(**{k: v for k, v in asdict(s).items()
                                                   if k != "symbol"})


def _regime_out(r: Regime) -> RegimeOut:
    return RegimeOut(**asdict(r))


@router.get("/health")
async def health(session: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """`data_health()`: last update per symbol and timeframe, gaps, errors."""
    return await data_health(session)


@router.get("/trend", response_model=TrendOut)
async def trend(session: AsyncSession = Depends(get_db)) -> TrendOut:
    """Every coin's latest state per timeframe, with the two-timeframe verdict."""
    if not config.enabled():
        return TrendOut(running=False, computed_at=None, coins=[])
    members = await get_universe(session)
    latest = {(s.symbol, s.timeframe): s for s in await get_trend_state(session)}
    coins = []
    for m in members:
        by_tf = {tf: latest.get((m.binance_symbol, tf)) for tf in config.TIMEFRAMES}
        v = coin_verdict(m.binance_symbol, by_tf.get("4h"), by_tf.get("1h"))
        coins.append(CoinTrendOut(symbol=m.binance_symbol, rank=m.rank, verdict=v.verdict,
                                  reason=v.reason,
                                  states={tf: _state_out(s) for tf, s in by_tf.items()}))
    return TrendOut(running=True,
                    computed_at=max((s.computed_at for s in latest.values()), default=None),
                    coins=coins)


@router.get("/regime", response_model=RegimeHistoryOut)
async def regime(session: AsyncSession = Depends(get_db)) -> RegimeHistoryOut:
    """The latest regime and the last 24 values."""
    if not config.enabled():
        return RegimeHistoryOut(running=False, latest=None, history=[])
    rows = [_regime_out(r) for r in await get_regime(session, limit=24)]
    return RegimeHistoryOut(running=True, latest=rows[0] if rows else None, history=rows)
