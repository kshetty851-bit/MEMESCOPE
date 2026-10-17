"""Phone push alerts for real-wallet trades (Karthik, 2026-10-17).

Each subscribed device (the home-screen app on iPhone, or a desktop browser)
gets the same message WhatsApp gets, independently of WhatsApp: an alert is
pushed once (`pushed_at`), even while CallMeBot is refusing or retrying it.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta

from sqlalchemy import DateTime, String, Text, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.core.config import settings
from app.core.logging import get_logger
from app.db.base import Base

logger = get_logger(__name__)

#: Older events are history, not news: a fresh subscriber is not flooded.
FRESH = timedelta(minutes=30)


class PushSubscription(Base):
    __tablename__ = "push_subscriptions"

    endpoint: Mapped[str] = mapped_column(Text, primary_key=True)
    p256dh: Mapped[str] = mapped_column(String(200), nullable=False)
    auth: Mapped[str] = mapped_column(String(100), nullable=False)
    owner: Mapped[str | None] = mapped_column(String(320))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


def configured() -> bool:
    return bool(settings.VAPID_PUBLIC_KEY and settings.VAPID_PRIVATE_KEY.get_secret_value())


def _send(sub: PushSubscription, payload: str) -> int | None:
    """One push. Returns the HTTP status of a refusal, None when delivered."""
    from pywebpush import WebPushException, webpush

    try:
        webpush(
            subscription_info={
                "endpoint": sub.endpoint,
                "keys": {"p256dh": sub.p256dh, "auth": sub.auth},
            },
            data=payload,
            ttl=3600,
            vapid_private_key=settings.VAPID_PRIVATE_KEY.get_secret_value(),
            vapid_claims={"sub": settings.VAPID_SUBJECT},
        )
        return None
    except WebPushException as exc:
        return exc.response.status_code if exc.response is not None else 0


async def send_all(
    session: AsyncSession, title: str, body: str, url: str = "/real-wallet"
) -> int:
    """Push to every device; drop the ones the push service says are gone."""
    if not configured():
        return 0
    payload = json.dumps({"title": title, "body": body, "url": url})
    sent = 0
    for sub in (await session.scalars(select(PushSubscription))).all():
        status = await asyncio.to_thread(_send, sub, payload)
        if status is None:
            sent += 1
        elif status in (404, 410):
            await session.execute(
                delete(PushSubscription).where(PushSubscription.endpoint == sub.endpoint)
            )
        else:
            logger.warning("push_refused", status=status)
    await session.commit()
    return sent


def split(message: str) -> tuple[str, str]:
    """A WhatsApp message as a notification: first line the title, the rest the body."""
    first, _, rest = message.strip().partition("\n")
    return first.strip("* "), rest.strip()


async def push_pass(session: AsyncSession, *, now: datetime) -> int:
    """Push every recent trade event not pushed yet, oldest first."""
    from app.models.real_wallet_execution import RealWalletPosition, RealWalletTradeAlert
    from app.real_wallet import trade_alerts as ta

    rows = (
        await session.execute(
            select(RealWalletTradeAlert, RealWalletPosition, ta.DiscoveredToken.symbol)
            .join(
                RealWalletPosition, RealWalletPosition.id == RealWalletTradeAlert.position_id
            )
            .outerjoin(
                ta.DiscoveredToken,
                ta.DiscoveredToken.mint_address == RealWalletPosition.mint_address,
            )
            .where(
                RealWalletTradeAlert.pushed_at.is_(None),
                RealWalletTradeAlert.status != "baseline",
                RealWalletTradeAlert.created_at >= now - FRESH,
            )
            .order_by(RealWalletTradeAlert.created_at)
        )
    ).all()
    pushed = 0
    for alert, position, symbol in rows:
        build = ta.opened_message if alert.event == "opened" else ta.closed_message
        if await send_all(session, *split(build(position, symbol, now))):
            pushed += 1
        alert.pushed_at = now
        await session.commit()
    return pushed
