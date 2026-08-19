"""Best-effort, append-only forward research capture.

Callers deliberately swallow this writer's errors after logging: research
instrumentation must never change a paper decision or wallet accounting.
"""
from __future__ import annotations
from datetime import datetime
from typing import Any
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.logging import get_logger
from app.models.paper_research import PaperDecisionSnapshot

logger = get_logger(__name__)


async def capture_decision(
    session: AsyncSession, *, source: str, source_key: str, wallet_code: str,
    strategy_id: str, strategy_version: str, mint: str, decided_at: datetime,
    decision: str, reason_codes: list[str], token_id: object | None = None,
    market_snapshot_id: object | None = None, market_features: dict[str, Any] | None = None,
    radar_state: dict[str, Any] | None = None, observation_history: dict[str, Any] | None = None,
    availability: dict[str, Any] | None = None,
) -> bool:
    """Persist a decision snapshot; return false rather than affect trading on error."""
    try:
        result = await session.execute(insert(PaperDecisionSnapshot).values(
            decision_source=source, source_decision_key=source_key, wallet_code=wallet_code,
            strategy_id=strategy_id, strategy_version=strategy_version, mint_address=mint,
            token_id=token_id, market_snapshot_id=market_snapshot_id, decided_at=decided_at,
            decision=decision, reason_codes=reason_codes, market_features=market_features or {},
            radar_state=radar_state or {}, observation_history=observation_history or {},
            availability=availability or {},
        ).on_conflict_do_nothing(index_elements=["decision_source", "source_decision_key"]).returning(PaperDecisionSnapshot.id))
        return result.scalar_one_or_none() is not None
    except Exception:
        logger.exception("paper_research_decision_capture_failed", source=source, mint_address=mint)
        return False
