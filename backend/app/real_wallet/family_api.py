"""The user wallets' pages (USER 1 … USER 10): Karthik's alone.

Every endpoint needs Karthik signed in as the admin (2026-09-27; the family
password that used to open a member's page is gone). He sees each wallet's
address, balance and trades, switches it on or off, sizes it, and withdraws
its SOL — which can only ever reach his own nominated address.

The SHARES of the owner's wallet these pages used to manage were removed on
2026-09-25 at Karthik's request (migration 0105).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import AdminUser, DbSession
from app.core.config import settings
from app.core.exceptions import ConflictError, ServiceUnavailableError
from app.core.logging import get_logger
from app.models.real_wallet_family import RealWalletFamilyMember
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
        raise HTTPException(status_code=404, detail="no such user wallet")
    return key



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


@router.get("", summary="The user wallets, names only")
async def members(_: AdminUser) -> dict[str, object]:
    return {"members": [{"member": m, "label": family.label(m)} for m in family.MEMBERS],
            "ticket_choices": [str(t) for t in family.TICKETS_USD]}


@router.get("/{name}", summary="One member's own wallet")
async def member_view(name: str, session: DbSession, _: AdminUser) -> dict[str, object]:
    member = _member(name)
    if await session.get(RealWalletFamilyMember, member) is None:
        raise HTTPException(status_code=404, detail="no such user wallet")
    own = family_wallets.address(member)
    return {
        "member": member,
        "label": family.label(member),
        "own_wallet": await _own_wallet(member),
        "own_book": await _own_book(session, member, own) if own else None,
    }


@router.post("/{name}/withdraw", summary="Send SOL from a member's own wallet to Karthik")
async def member_withdraw(name: str, payload: WithdrawIn, _: AdminUser
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
                              viewer: AdminUser) -> dict[str, object]:
    """Start, stop and size are Karthik's, signed in as the admin."""
    member = _member(name)
    if family_wallets.address(member) is None:
        raise HTTPException(status_code=404,
                            detail=f"{member} has no wallet of their own yet")
    if payload.ticket_usd not in family.TICKETS_USD:
        raise HTTPException(status_code=422, detail="trade size must be one of "
                            + ", ".join(str(t) for t in family.TICKETS_USD))
    row = await session.get(RealWalletFamilyMember, member)
    if row is None:
        raise HTTPException(status_code=404, detail="no such user wallet")
    row.own_enabled, row.own_ticket_usd = payload.enabled, payload.ticket_usd
    row.own_updated_at = datetime.now(UTC)
    row.own_updated_by = viewer.email
    await session.commit()
    logger.warning("real_wallet_family_own_settings", member=member,
                   enabled=payload.enabled, ticket=str(payload.ticket_usd),
                   by=row.own_updated_by)
    return {"member": member, "enabled": row.own_enabled,
            "ticket_usd": str(row.own_ticket_usd)}
