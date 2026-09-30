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

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import AdminUser, DbSession, OptionalUser
from app.core.config import settings
from app.core.exceptions import ConflictError, ServiceUnavailableError
from app.core.logging import get_logger
from app.models.real_wallet_family import RealWalletFamilyMember
from app.real_wallet import family, family_wallets, user_fees, withdraw_service
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
# Seeing is the password's; acting is the admin's (Karthik, 2026-09-30: "doesnt
# matter where i open i want to see that"). Unlocking, the list and a wallet's
# page need only the JUPITER / users password, from any browser, signed in or
# not. Starting, stopping, sizing, withdrawing and collecting fees still need
# the admin sign-in as well — a guessed password can look, never move money.


def _caller(request: Request) -> str:
    """Who is guessing, for the throttle: the LAST forwarded hop is the one the
    site's own proxy added; earlier ones are whatever the client sent."""
    forwarded = request.headers.get("x-forwarded-for", "")
    hops = [h.strip() for h in forwarded.split(",") if h.strip()]
    return hops[-1] if hops else (request.client.host if request.client else "unknown")


def _unlocked(member: str, token: str | None) -> None:
    """Every user wallet needs its password as well as the admin sign-in."""
    if not family.opens(member, token):
        which = ("JUPITER" if family.scope(member) == "investment"
                 else "users")
        raise HTTPException(status_code=401, detail=f"enter the {which} password first")


class UnlockIn(BaseModel):
    password: str = Field(min_length=1, max_length=200)


def _member(name: str) -> str:
    key = name.strip().upper()
    if key not in family.MEMBERS:
        raise HTTPException(status_code=404, detail="no such user wallet")
    return key



class CollectFeeIn(BaseModel):
    """No amount and no address: it sends exactly what is due, to the fee address."""

    confirmation_phrase: Literal["COLLECT_FEE"]


class OwnSettingsIn(BaseModel):
    enabled: bool
    ticket_usd: Decimal
    #: A key of `family.BANDS`; left out keeps the wallet's band.
    band: str | None = None


class WithdrawIn(BaseModel):
    """Amount only. The destination is Karthik's nominated address, always."""

    sol_amount: Decimal = Field(gt=0)
    confirmation_phrase: Literal["WITHDRAW_TO_KARTHIK"]


_BAND_CHOICES = [{"key": k, "label": v} for k, v in family.BAND_LABELS.items()]


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
        "band": row.own_band if row else "any",
        "band_choices": _BAND_CHOICES,
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


async def _charged(session: DbSession) -> None:
    """Write any finished month's fee rows (no money moves). Idempotent."""
    await user_fees.charge(session, datetime.now(UTC))
    await session.commit()


@router.post("/unlock", summary="Trade the users password for a 12-hour token")
async def unlock(payload: UnlockIn, request: Request, _: OptionalUser,
                 x_users_token: str | None = Header(default=None)) -> dict[str, object]:
    """Either password. The new token keeps every lock the tab already opened."""
    who = _caller(request)
    if family.THROTTLE.blocked(who):
        raise HTTPException(status_code=429,
                            detail="too many wrong passwords; wait ten minutes")
    scope = family.password_scope(payload.password)
    if scope is None:
        family.THROTTLE.failed(who)
        logger.warning("real_wallet_users_unlock_refused")
        raise HTTPException(status_code=401, detail="wrong password")
    scopes = family.token_scopes(x_users_token) | {scope}
    token, expires = family.issue_token(scopes)
    return {"token": token, "expires_at": expires.isoformat(), "scopes": sorted(scopes)}


@router.get("", summary="The user wallets, their fee rates, and the fees")
async def members(session: DbSession, _: OptionalUser,
                  x_users_token: str | None = Header(default=None)) -> dict[str, object]:
    """USER 1-7 with the family investment password; USER 8-10 and the fees
    with the users password."""
    scopes = family.token_scopes(x_users_token)
    unlocked = "users" in scopes
    rows = {r.name: r for r in
            (await session.execute(select(RealWalletFamilyMember))).scalars()}
    shown = [m for m in family.MEMBERS if family.scope(m) in scopes]
    out: dict[str, object] = {
        "members": [{"member": m, "label": family.label(m),
                     "fee_rate": str(rows[m].fee_rate) if m in rows else None,
                     "enabled": bool(m in rows and rows[m].own_enabled),
                     "ticket_usd": str(rows[m].own_ticket_usd) if m in rows else None,
                     "band": rows[m].own_band if m in rows else "any",
                     "address": family_wallets.address(m)}
                    for m in shown],
        "band_choices": _BAND_CHOICES,
        "unlocked": unlocked,
        "investment_unlocked": "investment" in scopes,
        "locked_count": len(family.MEMBERS) - len(shown),
        "ticket_choices": [str(t) for t in family.TICKETS_USD]}
    if unlocked:
        await _charged(session)
        out["fees"] = await user_fees.summary(session)
    return out


@router.get("/{name}", summary="One member's own wallet")
async def member_view(name: str, session: DbSession, _: OptionalUser,
                      x_users_token: str | None = Header(default=None)) -> dict[str, object]:
    member = _member(name)
    _unlocked(member, x_users_token)
    row = await session.get(RealWalletFamilyMember, member)
    if row is None:
        raise HTTPException(status_code=404, detail="no such user wallet")
    await _charged(session)
    own = family_wallets.address(member)
    return {
        "member": member,
        "label": family.label(member),
        "own_wallet": await _own_wallet(member),
        "own_book": await _own_book(session, member, own) if own else None,
        "fee": {"rate": str(row.fee_rate), "months": await user_fees.history(session, member)},
    }


@router.post("/{name}/withdraw", summary="Send SOL from a member's own wallet to Karthik")
async def member_withdraw(name: str, payload: WithdrawIn, _: AdminUser,
                          x_users_token: str | None = Header(default=None)
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
    _unlocked(member, x_users_token)
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
                              viewer: AdminUser,
                              x_users_token: str | None = Header(default=None)
                              ) -> dict[str, object]:
    """Start, stop and size are Karthik's, signed in as the admin."""
    member = _member(name)
    _unlocked(member, x_users_token)
    if family_wallets.address(member) is None:
        raise HTTPException(status_code=404,
                            detail=f"{member} has no wallet of their own yet")
    if payload.ticket_usd not in family.TICKETS_USD:
        raise HTTPException(status_code=422, detail="trade size must be one of "
                            + ", ".join(str(t) for t in family.TICKETS_USD))
    if payload.band is not None and payload.band not in family.BANDS:
        raise HTTPException(status_code=422, detail="coin size must be one of "
                            + ", ".join(family.BANDS))
    row = await session.get(RealWalletFamilyMember, member)
    if row is None:
        raise HTTPException(status_code=404, detail="no such user wallet")
    row.own_enabled, row.own_ticket_usd = payload.enabled, payload.ticket_usd
    if payload.band is not None:
        row.own_band = payload.band
    row.own_updated_at = datetime.now(UTC)
    row.own_updated_by = viewer.email
    await session.commit()
    logger.warning("real_wallet_family_own_settings", member=member,
                   enabled=payload.enabled, ticket=str(payload.ticket_usd),
                   band=row.own_band, by=row.own_updated_by)
    return {"member": member, "enabled": row.own_enabled,
            "ticket_usd": str(row.own_ticket_usd), "band": row.own_band}


@router.post("/{name}/collect-fee", summary="Send a user's due profit fee to the fee address")
async def member_collect_fee(name: str, payload: CollectFeeIn, session: DbSession,
                             _: AdminUser,
                             x_users_token: str | None = Header(default=None)
                             ) -> dict[str, object]:
    """Karthik's button. Sends every month's due fee for this user as one SOL
    transfer to the pinned fee address; the signer re-checks the address.
    Never retried: a lost response is an UNCERTAIN transfer to look up."""
    member = _member(name)
    _unlocked(member, x_users_token)
    await _charged(session)
    price = await sol_usd_now(datetime.now(UTC))
    if price is None:
        raise ServiceUnavailableError("SOL price unavailable; try again shortly")
    rpc = StandardSolanaRPC(rpc_url=settings.REAL_WALLET_RPC_URL)
    try:
        async with rpc:
            return await user_fees.collect(session, member, sol_usd=price, rpc=rpc,
                                           signer=UnixMainnetSignerClient())
    except withdraw_service.WithdrawError as exc:
        raise ConflictError(str(exc)) from exc
    except (MainnetSignerUnavailableError, MainnetSignerRejectedError) as exc:
        raise ServiceUnavailableError(f"signer: {exc}") from exc
