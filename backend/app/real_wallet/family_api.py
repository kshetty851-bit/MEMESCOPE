"""The family pages: unlock with the password, then one member's share.

What a member's token allows: seeing their own money and trades, switching
their share on or off, and choosing their trade size. What it does NOT allow:
recording deposits or withdrawals, which move how much of the owner's real SOL
trades in their name, so those also need the owner's own admin sign-in.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field

from app.api.deps import AdminUser, DbSession
from app.core.logging import get_logger
from app.models.real_wallet_family import RealWalletFamilyLedger, RealWalletFamilyMember
from app.real_wallet import family

logger = get_logger(__name__)
router = APIRouter(prefix="/real-wallet/family", tags=["real-wallet"])


def _member(name: str) -> str:
    key = name.strip().upper()
    if key not in family.MEMBERS:
        raise HTTPException(status_code=404, detail="no such family member")
    return key


def _caller(request: Request) -> str:
    """Who is guessing, for the throttle. The LAST forwarded hop is the one
    the site's own proxy added; earlier ones are whatever the client sent."""
    forwarded = request.headers.get("x-forwarded-for", "")
    hops = [h.strip() for h in forwarded.split(",") if h.strip()]
    return hops[-1] if hops else (request.client.host if request.client else "unknown")


def _authorised(member: str, token: str | None) -> None:
    if family.token_member(token) != member:
        raise HTTPException(status_code=401, detail="enter the family password first")


class UnlockIn(BaseModel):
    member: str
    password: str = Field(min_length=1, max_length=200)


class SettingsIn(BaseModel):
    enabled: bool
    ticket_usd: Decimal


class LedgerIn(BaseModel):
    kind: Literal["deposit", "withdrawal"]
    amount_usd: Decimal = Field(gt=0, le=Decimal("100000"))
    note: str | None = Field(default=None, max_length=200)


@router.get("", summary="The family members, names only")
async def members() -> dict[str, object]:
    return {"members": list(family.MEMBERS),
            "ticket_choices": [str(t) for t in family.TICKETS_USD],
            "combined_cap_usd": str(family.COMBINED_CAP_USD)}


@router.post("/unlock", summary="Trade the family password for a member's token")
async def unlock(payload: UnlockIn, request: Request) -> dict[str, object]:
    member = _member(payload.member)
    who = _caller(request)
    if family.THROTTLE.blocked(who):
        raise HTTPException(status_code=429,
                            detail="too many wrong passwords; wait ten minutes")
    if not family.password_ok(payload.password):
        family.THROTTLE.failed(who)
        logger.warning("real_wallet_family_unlock_refused", member=member)
        raise HTTPException(status_code=401, detail="wrong password")
    token, expires = family.issue_token(member)
    logger.info("real_wallet_family_unlocked", member=member)
    return {"member": member, "token": token, "expires_at": expires.isoformat()}


@router.get("/{name}", summary="One member's share of the real wallet")
async def member_view(name: str, session: DbSession,
                      x_family_token: str | None = Header(default=None)) -> dict[str, object]:
    member = _member(name)
    _authorised(member, x_family_token)
    row = await session.get(RealWalletFamilyMember, member)
    if row is None:
        raise HTTPException(status_code=404, detail="no such family member")
    shares = (await family.shares_by_member(session)).get(member, [])
    ledger = (await family.ledger_by_member(session)).get(member, [])
    b = family.balance(((r.kind, r.amount_usd) for r in ledger), (s for s, _ in shares))
    return {
        "member": member,
        "enabled": row.enabled,
        "ticket_usd": str(row.ticket_usd),
        "ticket_choices": [str(t) for t in family.TICKETS_USD],
        "combined_cap_usd": str(family.COMBINED_CAP_USD),
        "deposited_usd": str(b.deposited),
        "withdrawn_usd": str(b.withdrawn),
        "pnl_usd": str(b.pnl),
        "balance_usd": str(b.balance),
        "in_trades_usd": str(b.in_trades),
        "available_usd": str(b.available),
        "trades": b.trades,
        "wins": b.wins,
        "trades_list": [{k: (v.isoformat() if isinstance(v, datetime) else
                             str(v) if isinstance(v, Decimal) else v)
                         for k, v in t.items()}
                        for t in family.rows_for_page(shares[:100])],
        "ledger": [{"kind": r.kind, "amount_usd": str(r.amount_usd), "note": r.note,
                    "at": r.at.isoformat()} for r in ledger[:100]],
    }


@router.post("/{name}/settings", summary="Switch a member's share on or off, and size it")
async def member_settings(name: str, payload: SettingsIn, session: DbSession,
                          x_family_token: str | None = Header(default=None)
                          ) -> dict[str, object]:
    member = _member(name)
    _authorised(member, x_family_token)
    if payload.ticket_usd not in family.TICKETS_USD:
        raise HTTPException(status_code=422, detail="trade size must be one of "
                            + ", ".join(str(t) for t in family.TICKETS_USD))
    row = await session.get(RealWalletFamilyMember, member)
    if row is None:
        raise HTTPException(status_code=404, detail="no such family member")
    row.enabled, row.ticket_usd = payload.enabled, payload.ticket_usd
    row.updated_at, row.updated_by = datetime.now(UTC), f"family:{member}"
    await session.commit()
    logger.warning("real_wallet_family_settings", member=member, enabled=payload.enabled,
                   ticket=str(payload.ticket_usd))
    return {"member": member, "enabled": row.enabled, "ticket_usd": str(row.ticket_usd)}


@router.post("/{name}/ledger", summary="Record money put in or taken out for a member")
async def member_ledger(name: str, payload: LedgerIn, admin: AdminUser, session: DbSession,
                        x_family_token: str | None = Header(default=None)
                        ) -> dict[str, object]:
    """Bookkeeping only: no SOL moves here. The owner sends a deposit from
    their own address and withdraws through the wallet's one withdrawal path;
    this records whose money it was."""
    member = _member(name)
    _authorised(member, x_family_token)
    if payload.kind == "withdrawal":
        shares = (await family.shares_by_member(session)).get(member, [])
        ledger = (await family.ledger_by_member(session)).get(member, [])
        b = family.balance(((r.kind, r.amount_usd) for r in ledger), (s for s, _ in shares))
        if payload.amount_usd > b.available:
            raise HTTPException(status_code=422,
                                detail=f"{member} has only ${b.available} free to withdraw")
    # Stamped here, to the microsecond: the database's now() is the same for
    # every row in one transaction, which would leave newest-first a guess.
    session.add(RealWalletFamilyLedger(member=member, kind=payload.kind,
                                       amount_usd=payload.amount_usd.quantize(Decimal("0.01")),
                                       note=payload.note, actor=admin.email,
                                       at=datetime.now(UTC)))
    await session.commit()
    logger.warning("real_wallet_family_ledger", member=member, kind=payload.kind,
                   usd=str(payload.amount_usd))
    return {"member": member, "kind": payload.kind, "amount_usd": str(payload.amount_usd)}

