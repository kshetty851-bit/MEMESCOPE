"""Runs the trend engine over the universe and persists what it finds.

Reads candles through `data.py` only, computes through `trend.py` and
`regime.py`, writes `ct_trend_state` and `ct_regime`. It never calls a
network. Every write is an upsert keyed on the bar it describes, so running
it every minute between bar closes rewrites the same rows; the row count
moves only when a bar closes.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.labs.crypto_trend import config
from app.labs.crypto_trend.data import get_candles, get_universe
from app.labs.crypto_trend.models import CtRegime, CtTrendState
from app.labs.crypto_trend.regime import Regime, compute_regime
from app.labs.crypto_trend.trend import TrendState, compute_trend_state

logger = get_logger(__name__)

_STATE_KEY = ("symbol", "timeframe", "bar_close_time")
_STATE_VALUES = ("computed_at", "direction", "strength", "slope", "atr_pct", "bars_in_state",
                 "ema_fast", "ema_slow", "ema_trend", "adx", "structure", "structure_veto",
                 "close")
_REGIME_VALUES = ("computed_at", "coins", "breadth_up", "breadth_down", "btc_direction",
                  "eth_direction", "regime")


def _dec(value: float | None, places: int) -> Decimal | None:
    return None if value is None else Decimal(str(round(value, places)))


def state_row(s: TrendState) -> dict[str, Any]:
    return {
        "symbol": s.symbol, "timeframe": s.timeframe, "bar_close_time": s.bar_close_time,
        "computed_at": s.computed_at, "direction": s.direction, "strength": s.strength,
        "slope": _dec(s.slope, 6), "atr_pct": _dec(s.atr_pct, 6),
        "bars_in_state": s.bars_in_state, "ema_fast": _dec(s.ema_fast, 8),
        "ema_slow": _dec(s.ema_slow, 8), "ema_trend": _dec(s.ema_trend, 8),
        "adx": _dec(s.adx, 4), "structure": s.structure, "structure_veto": s.structure_veto,
        "close": _dec(s.close, 8),
    }


def regime_row(r: Regime) -> dict[str, Any]:
    return {
        "bar_close_time": r.bar_close_time, "computed_at": r.computed_at, "coins": r.coins,
        "breadth_up": _dec(r.breadth_up, 4), "breadth_down": _dec(r.breadth_down, 4),
        "btc_direction": r.btc_direction, "eth_direction": r.eth_direction, "regime": r.regime,
    }


class TrendEngine:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def run(self, *, now: datetime) -> dict[str, Any]:
        members = await get_universe(self._session)
        states: list[TrendState] = []
        skipped: list[str] = []
        for member in members:
            for timeframe in config.TIMEFRAMES:
                candles = await get_candles(self._session, member.binance_symbol, timeframe)
                state = compute_trend_state(member.binance_symbol, timeframe, candles,
                                            computed_at=now)
                if state is None:
                    skipped.append(f"{member.binance_symbol} {timeframe}")
                    continue
                states.append(state)
        await self.upsert_states(states)

        regime: Regime | None = None
        if states:
            regime = compute_regime(
                {s.symbol: s.direction for s in states if s.timeframe == "4h"},
                bar_close_time=max(s.bar_close_time for s in states), computed_at=now)
            await self.upsert_regime(regime)

        pruned = await self.prune(now)
        await self._session.flush()
        logger.info("crypto_trend_engine_ran", states=len(states), skipped=skipped,
                    regime=regime.regime if regime else None,
                    breadth_up=regime.breadth_up if regime else None)
        return {
            "states": len(states), "skipped": skipped,
            "regime": regime.regime if regime else None,
            "breadth_up": regime.breadth_up if regime else None,
            "breadth_down": regime.breadth_down if regime else None,
            "pruned": pruned,
        }

    async def upsert_states(self, states: list[TrendState]) -> int:
        if not states:
            return 0
        stmt = pg_insert(CtTrendState).values([state_row(s) for s in states])
        await self._session.execute(stmt.on_conflict_do_update(
            constraint="uq_ct_trend_state_symbol_timeframe_bar_close_time",
            set_={c: getattr(stmt.excluded, c) for c in _STATE_VALUES},
        ))
        return len(states)

    async def upsert_regime(self, regime: Regime) -> None:
        stmt = pg_insert(CtRegime).values(regime_row(regime))
        await self._session.execute(stmt.on_conflict_do_update(
            constraint="uq_ct_regime_bar_close_time",
            set_={c: getattr(stmt.excluded, c) for c in _REGIME_VALUES},
        ))

    async def prune(self, now: datetime) -> int:
        cutoff = now - timedelta(days=config.TREND_RETENTION_DAYS)
        a = await self._session.execute(
            delete(CtTrendState).where(CtTrendState.bar_close_time < cutoff))
        b = await self._session.execute(
            delete(CtRegime).where(CtRegime.bar_close_time < cutoff))
        return (a.rowcount or 0) + (b.rowcount or 0)
