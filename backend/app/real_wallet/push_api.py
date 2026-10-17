"""Phone alert subscriptions (Karthik, 2026-10-17). Administrator only: the
alerts are the real wallet's trades."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy.dialects.postgresql import insert

from app.api.deps import AdminUser, DbSession
from app.core.config import settings
from app.real_wallet import push

router = APIRouter(prefix="/push", tags=["push"])


class Keys(BaseModel):
    p256dh: str
    auth: str


class SubscriptionIn(BaseModel):
    endpoint: str
    keys: Keys


@router.get("/public-key")
async def public_key(_admin: AdminUser) -> dict[str, str]:
    if not push.configured():
        raise HTTPException(
            status_code=503, detail="Phone alerts are not set up on the server yet."
        )
    return {"key": settings.VAPID_PUBLIC_KEY}


@router.post("/subscribe")
async def subscribe(
    payload: SubscriptionIn, admin: AdminUser, session: DbSession
) -> dict[str, bool]:
    if not payload.endpoint.startswith("https://"):
        raise HTTPException(status_code=422, detail="Not a push endpoint.")
    await session.execute(
        insert(push.PushSubscription)
        .values(
            endpoint=payload.endpoint,
            p256dh=payload.keys.p256dh,
            auth=payload.keys.auth,
            owner=admin.email,
        )
        .on_conflict_do_update(
            index_elements=["endpoint"],
            set_={"p256dh": payload.keys.p256dh, "auth": payload.keys.auth},
        )
    )
    await session.commit()
    return {"ok": True}


@router.post("/test")
async def test(_admin: AdminUser, session: DbSession) -> dict[str, int]:
    sent = await push.send_all(
        session,
        "✅ MEMESCOPE alerts are on",
        "You'll get a notification here for every real-wallet buy and sell.",
    )
    return {"sent": sent}
