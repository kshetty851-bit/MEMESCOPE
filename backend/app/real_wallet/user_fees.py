"""The user wallets' monthly profit fee (Karthik, 2026-09-27).

Each calendar month (UTC), each user wallet pays `fee_rate` (20%; USER 1 pays
none) of the NEW trading profit it made — profit above its high-water mark,
the highest total any earlier month was charged at. A month that loses, or
only wins back an earlier loss, pays nothing. The fee goes to the pinned fee
address (`REAL_WALLET_FEE_ADDRESS`) as a plain SOL transfer the signer checks
for itself, and every month is a row the user's page shows.

Nothing here runs on a timer. A month is charged (a row written, no money
moved) whenever Karthik's pages are read, and a due fee is SENT only when he
presses "Collect fee" on that user's page (`collect`).

Profit is REALISED trading profit only (closed positions, net of costs where
measured): deposits and withdrawals never count as profit or loss.

ponytail: a user who withdraws everything mid-month still owes that month's
fee on the 1st, paid from whatever is left; a leaver's fee is settled by hand.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import ROUND_DOWN, Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.models.real_wallet_execution import RealWalletPosition
from app.models.real_wallet_family import RealWalletFamilyMember, RealWalletUserFee
from app.real_wallet import family_wallets

logger = get_logger(__name__)
CENT = Decimal("0.01")


def month_start(at: datetime) -> date:
    return date(at.year, at.month, 1)


def previous_month(first: date) -> date:
    if first.month == 1:
        return date(first.year - 1, 12, 1)
    return date(first.year, first.month - 1, 1)


def fee_for(profit: Decimal, hwm: Decimal, rate: Decimal) -> tuple[Decimal, Decimal]:
    """(fee, new high-water mark) for a wallet whose total profit is `profit`."""
    gain = profit - hwm
    if gain <= 0:
        return Decimal(0), hwm
    return (gain * rate).quantize(CENT, rounding=ROUND_DOWN), profit


async def realised_profit(session: AsyncSession, wallet: str, before: datetime) -> Decimal:
    pnl = func.coalesce(RealWalletPosition.realised_net_pnl_usd,
                        RealWalletPosition.realised_gross_pnl_usd)
    total = await session.scalar(select(func.coalesce(func.sum(pnl), 0)).where(
        RealWalletPosition.wallet_public_key == wallet,
        RealWalletPosition.status == "CLOSED",
        RealWalletPosition.closed_at < before))
    return Decimal(total or 0).quantize(CENT)


async def charge(session: AsyncSession, now: datetime) -> list[RealWalletUserFee]:
    """Write last month's row for every user wallet that has none. Idempotent."""
    this_month = month_start(now)
    period = previous_month(this_month)
    cutoff = datetime(this_month.year, this_month.month, 1, tzinfo=UTC)
    out: list[RealWalletUserFee] = []
    for account in await family_wallets.accounts(session):
        done = await session.scalar(select(RealWalletUserFee.id).where(
            RealWalletUserFee.member == account.member, RealWalletUserFee.period == period))
        if done is not None:
            continue
        last = (await session.execute(
            select(RealWalletUserFee.hwm_after_usd)
            .where(RealWalletUserFee.member == account.member)
            .order_by(RealWalletUserFee.period.desc()).limit(1))).scalar()
        hwm = Decimal(last or 0)
        member = await session.get(RealWalletFamilyMember, account.member)
        rate = Decimal(member.fee_rate) if member else Decimal("0.20")
        profit = await realised_profit(session, account.wallet, cutoff)
        fee, hwm_after = fee_for(profit, hwm, rate)
        row = RealWalletUserFee(
            member=account.member, wallet=account.wallet, period=period,
            profit_usd=profit, hwm_before_usd=hwm, hwm_after_usd=hwm_after,
            fee_rate=rate, fee_usd=fee, status="due" if fee > 0 else "none")
        session.add(row)
        out.append(row)
    await session.flush()
    return out


async def collect(session: AsyncSession, member: str, *, sol_usd: Decimal,
                  rpc, signer) -> dict[str, object]:
    """Send this user's due fees as ONE transfer, when Karthik presses the button.

    Refused before sending (no fee address, too little SOL, the wallet mid-
    trade, signer said no): the rows stay "due" and the refusal is raised.
    Once a transfer might have left, the rows are "sending", then "paid" or
    "uncertain", and are never sent again — the chain decides.
    """
    from app.real_wallet import withdraw_service
    from app.real_wallet.balance import ExecutionWalletBalanceService
    from app.real_wallet.tx_inspect import lamports_from_sol

    rows = (await session.execute(select(RealWalletUserFee).where(
        RealWalletUserFee.member == member, RealWalletUserFee.status == "due")
        .with_for_update())).scalars().all()
    if not rows:
        raise withdraw_service.WithdrawError("no_fee_due")
    wallet = rows[0].wallet
    if await _busy(session, wallet):
        raise withdraw_service.WithdrawError("wallet_is_trading_try_after_it_sells")
    usd = sum((Decimal(r.fee_usd) for r in rows), Decimal(0))
    sol = (usd / sol_usd).quantize(Decimal("1e-9"), rounding=ROUND_DOWN)
    balance = (await ExecutionWalletBalanceService(rpc).get_sol_balance(wallet)).sol
    prepared = await withdraw_service.prepare(
        rpc, sol_amount=sol, wallet=wallet, to_fee=True,
        balance_lamports=lamports_from_sol(Decimal(str(balance))))
    signed = await signer.sign_withdrawal(prepared.unsigned_transaction,
                                          wallet=wallet, to_fee=True)
    now = datetime.now(UTC)
    for r in rows:
        r.status, r.sol_usd, r.sent_at = "sending", sol_usd, now
        r.lamports = int(prepared.lamports * Decimal(r.fee_usd) / usd)
        r.signature = signed.get("signature")
    await session.commit()          # before the send: a crash now is never re-sent
    try:
        await withdraw_service.submit(rpc, signed_transaction=signed["signed_transaction"])
        status, note = "paid", None
    except Exception as exc:
        status, note = "uncertain", f"check chain: {exc}"[:200]
    for r in rows:
        r.status, r.note = status, note
    await session.commit()
    logger.warning("real_wallet_user_fee_collected", member=member, usd=str(usd),
                   lamports=prepared.lamports, status=status,
                   signature=signed.get("signature"))
    return {"status": status, "usd": str(usd.quantize(CENT)), "sol": str(prepared.sol),
            "destination": prepared.destination, "signature": signed.get("signature"),
            "explorer": f"https://solscan.io/tx/{signed.get('signature')}"}


async def _busy(session: AsyncSession, wallet: str) -> bool:
    from app.models.real_wallet_execution import RealWalletLiveIntent

    held = await session.scalar(select(func.count()).select_from(RealWalletPosition).where(
        RealWalletPosition.wallet_public_key == wallet, RealWalletPosition.status == "OPEN"))
    flying = await session.scalar(select(func.count()).select_from(RealWalletLiveIntent).where(
        RealWalletLiveIntent.wallet_public_key == wallet,
        RealWalletLiveIntent.state.in_(("created", "safety_approved", "order_created",
                                        "signed", "submitted"))))
    return bool(held or flying)


async def summary(session: AsyncSession) -> dict[str, object]:
    """Karthik's totals: collected, waiting, and any send to check by hand."""
    rows = (await session.execute(
        select(RealWalletUserFee.status, func.coalesce(func.sum(RealWalletUserFee.fee_usd), 0),
               func.count()).group_by(RealWalletUserFee.status))).all()
    usd = {status: Decimal(total).quantize(CENT) for status, total, _ in rows}
    count = {status: n for status, _, n in rows}
    return {
        "collected_usd": str(usd.get("paid", Decimal("0.00"))),
        "waiting_usd": str(usd.get("due", Decimal("0.00"))),
        # A send whose outcome only the chain knows: look it up, never resend.
        "to_check": count.get("sending", 0) + count.get("uncertain", 0),
        "fee_address": settings.REAL_WALLET_FEE_ADDRESS.strip() or None,
    }


async def history(session: AsyncSession, member: str) -> list[dict[str, object]]:
    rows = (await session.execute(select(RealWalletUserFee).where(
        RealWalletUserFee.member == member)
        .order_by(RealWalletUserFee.period.desc()))).scalars().all()
    return [{
        "month": r.period.isoformat()[:7], "profit_usd": str(r.profit_usd),
        "high_water_usd": str(r.hwm_before_usd), "rate": str(r.fee_rate),
        "fee_usd": str(r.fee_usd), "status": r.status,
        "explorer": f"https://solscan.io/tx/{r.signature}" if r.signature else None,
    } for r in rows]


__all__ = ["charge", "collect", "fee_for", "history", "month_start", "previous_month",
           "realised_profit", "summary"]
