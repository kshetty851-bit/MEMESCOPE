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

from app.api.deps import AdminUser, DbSession, OptionalUser
from app.core.config import settings
from app.core.exceptions import ConflictError, ServiceUnavailableError
from app.core.logging import get_logger
from app.models.real_wallet_family import RealWalletFamilyLedger, RealWalletFamilyMember
from app.models.user import UserRole
from app.real_wallet import family, family_wallets, withdraw_service
from app.real_wallet.balance import ExecutionWalletBalanceService
from app.real_wallet.live_repository import LiveIntentRepository
from app.real_wallet.mainnet_signer_client import (
    MainnetSignerRejectedError,
    MainnetSignerUnavailableError,
    UnixMainnetSignerClient,
)
from app.real_wallet.network import verify_wallet_network
from app.real_wallet.sol_price import current_usd as sol_usd_now
from app.real_wallet.tx_inspect import lamports_from_sol
from app.services.rpc.standard import StandardSolanaRPC

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


class OwnSettingsIn(BaseModel):
    enabled: bool
    ticket_usd: Decimal


class WithdrawIn(BaseModel):
    """Amount only. The destination is Karthik's nominated address, always."""

    sol_amount: Decimal = Field(gt=0)
    confirmation_phrase: Literal["WITHDRAW_TO_KARTHIK"]


def _money(value: Decimal | None) -> str | None:
    return None if value is None else str(Decimal(value).quantize(Decimal("0.01")))


async def _own_book(session: DbSession, member: str, wallet: str) -> dict[str, object]:
    """What the member's OWN wallet has traded: switch, size, record, trades.

    Every figure is scoped to this wallet alone (`LiveIntentRepository`'s
    `wallet=`), so the owner's trades never appear here and this wallet's
    never appear on the owner's page.
    """
    row = await session.get(RealWalletFamilyMember, member)
    repo = LiveIntentRepository(session)
    now = datetime.now(UTC)
    since = await repo.since_first_trade(wallet)
    positions = await repo.positions(limit=100, wallet=wallet)
    return {
        "enabled": bool(row and row.own_enabled),
        "ticket_usd": str(row.own_ticket_usd if row else Decimal(20)),
        "ticket_choices": [str(t) for t in family.TICKETS_USD],
        "today_pnl_usd": _money(await repo.realised_pnl_today(now, wallet)),
        "open_positions": await repo.open_positions_count(wallet),
        "since_first_trade": None if since is None else {
            "trades": since["trades"], "won": since["won"], "lost": since["lost"],
            "net_pnl_usd": _money(since["net_pnl_usd"]),
        },
        "trades_list": [{
            "mint": pos.mint_address,
            "status": pos.status,
            "opened_at": pos.opened_at.isoformat(),
            "closed_at": pos.closed_at.isoformat() if pos.closed_at else None,
            "cost_usd": _money(pos.entry_price_usd * pos.quantity),
            "pnl_usd": _money(pos.realised_net_pnl_usd if pos.realised_net_pnl_usd is not None
                              else pos.realised_gross_pnl_usd),
            "exit_reason": pos.exit_reason,
        } for pos in positions],
    }


async def _own_wallet(member: str) -> dict[str, object]:
    """A member's OWN wallet: its address, and its balance read from chain.

    It receives deposits, sends only to Karthik's address, and trades when its
    own switch is on (`own_book`). A balance that cannot be read is reported
    as unread — never as zero, which would be a claim.
    """
    address = family_wallets.address(member)
    if address is None:
        return {"address": None}
    out: dict[str, object] = {
        "address": address,
        "explorer": f"https://solscan.io/account/{address}",
        "withdraws_to": settings.REAL_WALLET_WITHDRAWAL_ADDRESS.strip() or None,
        "balance_sol": None,
        "balance_usd": None,
        "balance_error": None,
    }
    rpc = StandardSolanaRPC(rpc_url=settings.REAL_WALLET_RPC_URL)
    try:
        async with rpc:
            network = await verify_wallet_network(rpc, network=settings.REAL_WALLET_NETWORK)
            if not network.verified:
                out["balance_error"] = "network_unverified"
                return out
            sol = Decimal(str((await ExecutionWalletBalanceService(rpc)
                               .get_sol_balance(address)).sol))
    except Exception:  # a read, reported as unread
        out["balance_error"] = "balance_unavailable"
        return out
    out["balance_sol"] = str(sol)
    price = await sol_usd_now(datetime.now(UTC))
    if price is not None:
        out["balance_usd"] = str((sol * price).quantize(Decimal("0.01")))
    return out


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
        "own_wallet": await _own_wallet(member),
        "own_book": (await _own_book(session, member, own)
                     if (own := family_wallets.address(member)) else None),
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



@router.post("/{name}/withdraw", summary="Send SOL from a member's own wallet to Karthik")
async def member_withdraw(name: str, payload: WithdrawIn,
                          x_family_token: str | None = Header(default=None)
                          ) -> dict[str, object]:
    """The member's own wallet pays; Karthik's nominated address receives.

    The same path as the owner's withdrawal, with the member's wallet as the
    payer: the destination is not a parameter, is checked in the service, and
    is checked again inside the signer against its own setting — which is
    also where the member's key is chosen and proved against its pinned
    address. Behind the family password, so only the member (or whoever holds
    the family password) can start it, and the money can only reach Karthik.

    Never retried: a lost response is an UNCERTAIN transfer.
    """
    member = _member(name)
    _authorised(member, x_family_token)
    wallet = family_wallets.address(member)
    if wallet is None:
        raise HTTPException(status_code=404, detail=f"{member} has no wallet of their own yet")
    rpc = StandardSolanaRPC(rpc_url=settings.REAL_WALLET_RPC_URL)
    try:
        async with rpc:
            sol = (await ExecutionWalletBalanceService(rpc).get_sol_balance(wallet)).sol
            prepared = await withdraw_service.prepare(
                rpc, sol_amount=payload.sol_amount,
                balance_lamports=lamports_from_sol(Decimal(str(sol))), wallet=wallet,
            )
            signed = await UnixMainnetSignerClient().sign_withdrawal(
                prepared.unsigned_transaction, wallet=wallet
            )
            signature = await withdraw_service.submit(
                rpc, signed_transaction=signed["signed_transaction"]
            )
    except withdraw_service.WithdrawError as exc:
        raise ConflictError(str(exc)) from exc
    except (MainnetSignerUnavailableError, MainnetSignerRejectedError) as exc:
        raise ServiceUnavailableError(f"signer: {exc}") from exc

    logger.warning("real_wallet_family_withdrawal_submitted", member=member,
                   signature=signature, lamports=prepared.lamports)
    return {
        "submitted": True,
        "signature": signature,
        "destination": prepared.destination,
        "sol": str(prepared.sol),
        "explorer": f"https://solscan.io/tx/{signature}",
        "note": ("Submitted once and never retried. If this response was lost, "
                 "check the signature on chain rather than sending again."),
    }


@router.post("/{name}/own-settings",
             summary="Switch a member's OWN wallet on or off, and size it")
async def member_own_settings(name: str, payload: OwnSettingsIn, session: DbSession,
                              viewer: OptionalUser,
                              x_family_token: str | None = Header(default=None)
                              ) -> dict[str, object]:
    """STOP is anyone's with the family password; START and SIZE are Karthik's.

    Stopping only ends buying, so the member (or whoever holds the family
    password) may always switch their own wallet off. Switching it ON, or
    changing how much each trade spends, also needs Karthik signed in as the
    admin — starting a real wallet is his decision, as it is for his own.
    """
    member = _member(name)
    _authorised(member, x_family_token)
    if family_wallets.address(member) is None:
        raise HTTPException(status_code=404,
                            detail=f"{member} has no wallet of their own yet")
    if payload.ticket_usd not in family.TICKETS_USD:
        raise HTTPException(status_code=422, detail="trade size must be one of "
                            + ", ".join(str(t) for t in family.TICKETS_USD))
    row = await session.get(RealWalletFamilyMember, member)
    if row is None:
        raise HTTPException(status_code=404, detail="no such family member")
    starting = payload.enabled and not row.own_enabled
    resizing = payload.ticket_usd != row.own_ticket_usd
    admin = viewer is not None and viewer.role == UserRole.ADMIN
    if (starting or resizing) and not admin:
        raise HTTPException(
            status_code=403,
            detail="only Karthik, signed in, can start this wallet or change its size")
    row.own_enabled, row.own_ticket_usd = payload.enabled, payload.ticket_usd
    row.own_updated_at = datetime.now(UTC)
    row.own_updated_by = viewer.email if admin and viewer else f"family:{member}"
    await session.commit()
    logger.warning("real_wallet_family_own_settings", member=member,
                   enabled=payload.enabled, ticket=str(payload.ticket_usd),
                   by=row.own_updated_by)
    return {"member": member, "enabled": row.own_enabled,
            "ticket_usd": str(row.own_ticket_usd)}
