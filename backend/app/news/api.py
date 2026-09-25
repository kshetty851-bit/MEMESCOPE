"""GET /news/solana — the sidebar broadcast's headlines."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter

from app.news import solana

router = APIRouter(prefix="/news", tags=["news"])


@router.get("/solana", summary="Latest Solana news headlines (third-party RSS)")
async def solana_news() -> dict[str, object]:
    items = await solana.headlines()
    return {"items": items, "sources": [name for name, _ in solana.FEEDS],
            "served_at": datetime.now(UTC).isoformat()}
