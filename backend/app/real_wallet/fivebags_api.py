"""FiveBags (Karthik, 2026-10-17): USER1-5 behind one password, on its own domain.

One password, no account: its bcrypt hash lives in `FIVEBAGS_PASSWORD_HASH`
(never the password; the repo is public). A right password sets a 30-day
httpOnly cookie scoped to /api/v1/fivebags; five wrong ones in ten minutes
lock the caller out. The wallets, their rules and their safety checks are the
same USER1-5 the main site runs - this is a window and a switch, nothing more.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from app.api.deps import DbSession
from app.core.config import settings
from app.core.logging import get_logger
from app.core.security import verify_password
from app.models.real_wallet_family import RealWalletFamilyMember
from app.real_wallet import family, family_api, family_wallets

logger = get_logger(__name__)
router = APIRouter(prefix="/fivebags", tags=["fivebags"])

MEMBERS = ("USER1", "USER2", "USER3", "USER4", "USER5")
COOKIE, AUDIENCE, LIFETIME = "fivebags", "fivebags", timedelta(days=30)
COOKIE_PATH = f"{settings.API_V1_PREFIX}/fivebags"


class UnlockIn(BaseModel):
    password: str


class SettingsIn(BaseModel):
    enabled: bool
    ticket_usd: Decimal


def _signed_in(request: Request) -> None:
    token = request.cookies.get(COOKIE)
    try:
        jwt.decode(
            token or "",
            settings.SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
            audience=AUDIENCE,
        )
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="password required") from None


@router.post("/unlock")
async def unlock(payload: UnlockIn, request: Request, response: Response) -> dict[str, bool]:
    who = "fivebags:" + family_api._caller(request)
    if family.THROTTLE.blocked(who):
        raise HTTPException(
            status_code=429, detail="too many wrong passwords; wait ten minutes"
        )
    stored = settings.FIVEBAGS_PASSWORD_HASH.get_secret_value()
    if not stored or not verify_password(payload.password, stored):
        family.THROTTLE.failed(who)
        logger.warning("fivebags_unlock_refused")
        raise HTTPException(status_code=401, detail="wrong password")
    now = datetime.now(UTC)
    token = jwt.encode(
        {"aud": AUDIENCE, "iat": now, "exp": now + LIFETIME},
        settings.SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )
    response.set_cookie(
        COOKIE,
        token,
        max_age=int(LIFETIME.total_seconds()),
        httponly=True,
        secure=True,
        samesite="strict",
        path=COOKIE_PATH,
    )
    return {"ok": True}


@router.post("/lock")
async def lock(response: Response) -> dict[str, bool]:
    response.delete_cookie(COOKIE, path=COOKIE_PATH)
    return {"ok": True}


@router.get("/wallets", dependencies=[Depends(_signed_in)])
async def wallets(session: DbSession) -> dict[str, object]:
    out = []
    for member in MEMBERS:
        address = family_wallets.address(member)
        out.append(
            {
                "member": member,
                "label": family.label(member),
                "own_wallet": await family_api._own_wallet(member),
                "own_book": await family_api._own_book(session, member, address)
                if address
                else None,
            }
        )
    return {"wallets": out, "ticket_choices": [str(t) for t in family.TICKETS_USD]}


@router.post("/wallets/{name}/settings", dependencies=[Depends(_signed_in)])
async def wallet_settings(
    name: str, payload: SettingsIn, session: DbSession
) -> dict[str, object]:
    """Start, stop and trade size, with the same checks as the main site."""
    member = name.upper()
    if member not in MEMBERS:
        raise HTTPException(status_code=404, detail="not one of the five wallets")
    if family_wallets.address(member) is None:
        raise HTTPException(status_code=404, detail=f"{member} has no wallet of its own yet")
    if payload.ticket_usd not in family.TICKETS_USD:
        raise HTTPException(
            status_code=422,
            detail="trade size must be one of "
            + ", ".join(str(t) for t in family.TICKETS_USD),
        )
    row = await session.get(RealWalletFamilyMember, member)
    if row is None:
        raise HTTPException(status_code=404, detail="no such user wallet")
    row.own_enabled, row.own_ticket_usd = payload.enabled, payload.ticket_usd
    row.own_updated_at, row.own_updated_by = datetime.now(UTC), "fivebags"
    await session.commit()
    logger.warning(
        "fivebags_settings",
        member=member,
        enabled=payload.enabled,
        ticket=str(payload.ticket_usd),
    )
    return {
        "member": member,
        "enabled": row.own_enabled,
        "ticket_usd": str(row.own_ticket_usd),
    }
