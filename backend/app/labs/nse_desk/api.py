"""GET /labs/nse-desk/company?q=… — admin only (see `screener` on why)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Query

from app.api.deps import AdminUser
from app.labs.nse_desk import screener

router = APIRouter(prefix="/labs/nse-desk", tags=["nse-desk"])


@router.get("/company", summary="One company's card from screener.in (admin only)")
async def company(admin: AdminUser,
                  q: str = Query(min_length=1, max_length=60)) -> dict[str, Any]:
    del admin
    try:
        card = await screener.company(q)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="screener.in did not answer") from exc
    if card is None:
        raise HTTPException(status_code=404,
                            detail=f"No company found for '{q}'. Try its NSE symbol.")
    return {**card, "fetched_at": datetime.now(UTC)}
