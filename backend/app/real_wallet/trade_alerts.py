"""WhatsApp alerts for every real-wallet trade that opens and every one that closes.

Karthik's request, 2026-09-17: an HQ agent looks after the real wallet and
messages him on WhatsApp when a trade opens or closes. Vault is that agent —
he already stands at the door of the only room with real money in it — and his
desk now shows this log.

── WHAT THIS MAY DO ───────────────────────────────────────────────────────

Read `real_wallet_positions`, write `real_wallet_trade_alerts`, send a message.
Nothing else. It cannot start, stop, buy or sell, it never touches the
autotrade switch — starting and stopping the real wallet is Karthik's alone —
and a failure here can never reach the trading path: it runs as its own task
on its own schedule and every error ends inside this module.

── EXACTLY ONCE ───────────────────────────────────────────────────────────

One row per position per event, held unique by the database, so two workers
ticking together collapse to one row. Rows are claimed one at a time with
`FOR UPDATE SKIP LOCKED` and committed after each send, so a crash mid-batch
cannot resend what already went out.

── NO HISTORY FLOOD ───────────────────────────────────────────────────────

An event older than `FRESH_WINDOW` when it is first noticed is recorded as
`baseline` and never sent. That covers switching alerts on for the first time
(seventeen trades already happened today) and switching them back on after a
week off, with one rule instead of a special first-run case.

── THE KEY NEVER LEAVES THE REQUEST ───────────────────────────────────────

CallMeBot takes the phone number and the key as query parameters; that is its
API. So the URL is never logged, httpx's own request logging is already held
at WARNING by `app.core.logging`, and every error stored or printed here is
built from a status code or an exception TYPE — never from an exception's
text, which for an HTTP client can include the URL — and is scrubbed of both
values before it is kept.
"""

from __future__ import annotations

import asyncio
import html
import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
from sqlalchemy import case, exists, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.models.real_wallet_execution import RealWalletPosition, RealWalletTradeAlert
from app.models.token import DiscoveredToken

logger = get_logger(__name__)

CALLMEBOT_URL = "https://api.callmebot.com/whatsapp.php"
SEND_TIMEOUT_SECONDS = 20

#: An event first noticed later than this is history, not news.
FRESH_WINDOW = timedelta(minutes=30)
#: A message sent this long after its trade says how long ago the trade was.
LATE_AFTER = timedelta(minutes=2)
#: Per tick. CallMeBot is a free service; a burst is how an account gets
#: throttled, so messages are spaced and capped.
MAX_PER_TICK = 6
SEND_GAP_SECONDS = 3

#: Waits between attempts, in order. Eight attempts spread over about an hour,
#: so a short outage at CallMeBot delays a message rather than losing it.
BACKOFF = (
    timedelta(seconds=0),
    timedelta(seconds=30),
    timedelta(minutes=1),
    timedelta(minutes=2),
    timedelta(minutes=5),
    timedelta(minutes=10),
    timedelta(minutes=15),
    timedelta(minutes=30),
)
MAX_ATTEMPTS = len(BACKOFF)

#: What CallMeBot says when a message went through: "Message queued. You will
#: receive it in a few seconds" (or "Message queued with ID: …").
_QUEUED = re.compile(r"message queued", re.I)
#: Its rate limit, answered with HTTP 200: "There is currently a limit of 25
#: messages per 240 minutes. Please try to reduce the number of messages sent."
_RATE_LIMITED = re.compile(r"limit of \d+ messages", re.I)
#: Words in a reply that mean it did not send, even when the status was 200.
_REFUSED = re.compile(r"error|invalid|not valid|wrong|blocked|wait|denied|forbidden", re.I)


class AlertSendError(Exception):
    """A send that did not go through. The message never contains a secret."""

    def __init__(self, message: str, *, blocked: bool = False, rate_limited: bool = False) -> None:
        super().__init__(message)
        #: HTTP 403 from CallMeBot's web firewall: it refused this TEXT, so
        #: sending the same words again can never work.
        self.blocked = blocked
        #: Over the rate limit: waiting always works, giving up never does.
        self.rate_limited = rate_limited


def enabled() -> bool:
    return bool(settings.WHATSAPP_PHONE and settings.WHATSAPP_CALLMEBOT_KEY.get_secret_value())


def _scrub(text: str) -> str:
    """Remove the phone number and the key from anything about to be kept."""
    key = settings.WHATSAPP_CALLMEBOT_KEY.get_secret_value()
    for secret in (key, settings.WHATSAPP_PHONE, settings.WHATSAPP_PHONE.lstrip("+")):
        if secret:
            text = text.replace(secret, "[redacted]")
    return text


def _visible_text(page: str) -> str:
    """What a person would read on the reply page — no scripts, styles or tags.

    The refusal check reads the first few hundred characters, and on an HTML
    reply those can be a stylesheet. A CSS rule containing "error" would then
    turn every successful send into a failure.
    """
    page = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", page)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", page))).strip()


async def send_whatsapp(text: str) -> str:
    """Send one message. Returns CallMeBot's reply (scrubbed); raises on failure."""
    params = {
        "phone": settings.WHATSAPP_PHONE,
        "text": text,
        "apikey": settings.WHATSAPP_CALLMEBOT_KEY.get_secret_value(),
    }
    unreachable: str | None = None
    try:
        async with httpx.AsyncClient(timeout=SEND_TIMEOUT_SECONDS) as client:
            response = await client.get(CALLMEBOT_URL, params=params)
    except Exception as exc:  # noqa: BLE001 — any failure here may carry the URL
        unreachable = type(exc).__name__
    if unreachable is not None:
        # Raised OUTSIDE the except block, deliberately. `raise ... from None`
        # only hides the original error when printed; Python still keeps it on
        # `__context__`, and its text is the full request URL — key included.
        # Anything that walks the chain (a traceback, an error tracker) would
        # have published it. A test holds this.
        raise AlertSendError(f"could not reach CallMeBot ({unreachable})")
    page = _scrub(_visible_text(response.text))
    reply = page[:300]
    # The reply repeats the message ("Text to send: …"). Judge only CallMeBot's
    # own words, or a token called WAIT turns a delivered message into a resend.
    said = page.replace(" ".join(text.split()), " ")
    if response.status_code == 403:
        raise AlertSendError(f"CallMeBot's firewall refused the text (HTTP 403): {reply}", blocked=True)
    if response.status_code != 200:
        raise AlertSendError(f"CallMeBot answered HTTP {response.status_code}: {reply}")
    if _QUEUED.search(said):
        return reply
    if _RATE_LIMITED.search(said):
        raise AlertSendError(f"CallMeBot rate limit: {reply}", rate_limited=True)
    if _REFUSED.search(said):
        raise AlertSendError(f"CallMeBot refused: {reply}")
    # Neither "queued" nor a known refusal. Counted as sent: resending on a
    # reply nobody has seen before would spam Karthik; the log keeps it.
    logger.warning("real_wallet_trade_alert_unconfirmed", reply=reply[:200])
    return reply


# --- the words ------------------------------------------------------------------

_EXIT_WORDS = {
    "dead_zero": "the token died",
    "liquidity_floor": "liquidity fell below the floor",
    "liquidity_decay": "liquidity was draining away",
    "sell_route_lost": "no route left to sell through",
    "break_even": "fell back to break-even",
    "trailing_stop": "trailing stop",
    "stagnation": "the price went flat",
    # Never "time limit": CallMeBot's firewall 403s a line that starts with it.
    "time_exit_unpriced": "timed out (no price to mark)",
    "partial_taken": "partial take-profit",
    "retry": "retrying an earlier sell",
}


def _duration(delta: timedelta) -> str:
    seconds = int(delta.total_seconds())
    if seconds < 60:
        return f"{seconds}s"
    # Nearest, not floor: a 4-minute exit that fired at 3m42s reads "held 4m".
    minutes = round(seconds / 60)
    hours, minutes = divmod(minutes, 60)
    if hours < 24:
        return f"{hours}h {minutes}m" if hours else f"{minutes}m"
    days, hours = divmod(hours, 24)
    return f"{days}d {hours}h"


def describe_exit(reason: str | None) -> str:
    """The exit rule in plain words. Anything unrecognised is shown as written."""
    if not reason:
        return "reason not recorded"
    if reason.startswith("partial_promoted_to_close:"):
        return f"{describe_exit(reason.split(':', 1)[1])}, sold in full"
    if reason in _EXIT_WORDS:
        return _EXIT_WORDS[reason]
    if m := re.fullmatch(r"target_(\d+)(?:_(\d+))?x", reason):
        return f"hit the {m.group(1)}{'.' + m.group(2) if m.group(2) else ''}x target"
    if m := re.fullmatch(r"time_([\d.]+)h", reason):
        return f"timed out after {_duration(timedelta(hours=float(m.group(1))))}"
    return reason


def _usd(value: Decimal, *, signed: bool = False) -> str:
    sign = ("+" if value > 0 else "-" if value < 0 else "") if signed else ("-" if value < 0 else "")
    return f"{sign}${abs(value):,.2f}"


def _price(value: Decimal) -> str:
    """Four significant figures, never scientific notation — these are memecoins."""
    if value >= 1:
        return f"${value:,.2f}"
    if value <= 0:
        return "$0"
    places = max(2, -value.adjusted() + 3)
    return f"${value:.{places}f}"


def _name(position: RealWalletPosition, symbol: str | None) -> str:
    mint = position.mint_address
    return symbol.strip() if symbol and symbol.strip() else f"{mint[:4]}…{mint[-4:]}"


def _late(event_at: datetime, now: datetime) -> str:
    return f"\n({_duration(now - event_at)} ago)" if now - event_at > LATE_AFTER else ""


def _whose(position: RealWalletPosition) -> str:
    """"REAL WALLET" for the owner's, "JAYA'S WALLET" for a family member's own
    (2026-09-25). A family map that cannot be read falls back to the plain
    label rather than dropping the alert."""
    from app.real_wallet import family_wallets

    try:
        member = family_wallets.member_for(position.wallet_public_key or "")
    except family_wallets.FamilyWalletConfigError:
        member = None
    return f"{member}'S WALLET" if member else "REAL WALLET"


def opened_message(position: RealWalletPosition, symbol: str | None, now: datetime) -> str:
    cost = position.quantity * position.entry_price_usd
    lines = [
        f"🟢 {_whose(position)} BOUGHT {_name(position, symbol)}",
        f"{_usd(cost)} at {_price(position.entry_price_usd)}",
    ]
    if position.strategy_id:
        lines.append(f"Strategy {position.strategy_id}")
    if position.entry_transaction_signature:
        lines.append(f"https://solscan.io/tx/{position.entry_transaction_signature}")
    return "\n".join(lines) + _late(position.opened_at, now)


def closed_message(position: RealWalletPosition, symbol: str | None, now: datetime) -> str:
    cost = position.quantity * position.entry_price_usd
    # Net only when it IS net. The position stores net as empty, with a reason,
    # whenever the network fees could not be priced — and a gross figure
    # labelled as net is the one lie this message must not tell.
    if position.realised_net_pnl_usd is not None:
        pnl, basis = position.realised_net_pnl_usd, "after fees"
    elif position.realised_gross_pnl_usd is not None:
        pnl, basis = position.realised_gross_pnl_usd, "before fees (fees not priced)"
    else:
        pnl, basis = None, ""

    if pnl is None:
        headline = "result not recorded yet"
        mark = "⚪"
    else:
        pct = f" ({pnl / cost * 100:+.1f}%)" if cost > 0 else ""
        headline = f"{_usd(pnl, signed=True)}{pct} {basis}"
        mark = "✅" if pnl > 0 else "🔻" if pnl < 0 else "⚪"

    lines = [
        f"{mark} {_whose(position)} SOLD {_name(position, symbol)}",
        headline,
        describe_exit(position.exit_reason)
        + (f" · held {_duration(position.closed_at - position.opened_at)}" if position.closed_at else ""),
    ]
    if position.exit_transaction_signature:
        lines.append(f"https://solscan.io/tx/{position.exit_transaction_signature}")
    return "\n".join(lines) + _late(position.closed_at or now, now)


def short_form(message: str) -> str:
    """What is left when CallMeBot's firewall refuses a message: the headline
    and the amount, plus how late it is. Build `message` with no symbol — a
    token's name is text nobody here chose, so it is the likeliest trigger."""
    lines = message.split("\n")
    late = lines[-1:] if len(lines) > 2 and lines[-1].endswith(" ago)") else []
    return "\n".join(lines[:2] + late)


# --- the log --------------------------------------------------------------------


async def record_new_events(session: AsyncSession, *, now: datetime) -> dict[str, int]:
    """Give every trade event without an alert row one. Old ones become `baseline`."""
    created = {"pending": 0, "baseline": 0}
    fresh_after = now - FRESH_WINDOW

    for event, happened in (
        ("opened", RealWalletPosition.opened_at),
        ("closed", RealWalletPosition.closed_at),
    ):
        missing = (
            await session.execute(
                select(RealWalletPosition.id, happened).where(
                    happened.is_not(None),
                    ~exists().where(
                        RealWalletTradeAlert.position_id == RealWalletPosition.id,
                        RealWalletTradeAlert.event == event,
                    ),
                )
            )
        ).all()
        for position_id, at in missing:
            status = "pending" if at >= fresh_after else "baseline"
            result = await session.execute(
                insert(RealWalletTradeAlert)
                .values(position_id=position_id, event=event, status=status)
                .on_conflict_do_nothing(constraint="uq_real_wallet_trade_alerts_event")
            )
            if result.rowcount:
                created[status] += 1
    await session.commit()
    return created


def _due(alert: RealWalletTradeAlert, now: datetime) -> bool:
    if alert.attempts == 0:
        return True
    waited_from = alert.last_attempt_at or alert.created_at
    return now - waited_from >= BACKOFF[min(alert.attempts, MAX_ATTEMPTS - 1)]


async def deliver_pending(
    session: AsyncSession,
    *,
    now: datetime,
    send=send_whatsapp,
    pause: float = SEND_GAP_SECONDS,
) -> dict[str, int]:
    """Send what is due, oldest trade first, one claimed row at a time."""
    counts = {"sent": 0, "failed": 0, "retrying": 0}
    event_time = case(
        (RealWalletTradeAlert.event == "opened", RealWalletPosition.opened_at),
        else_=RealWalletPosition.closed_at,
    )
    #: Trades whose earlier message is still waiting out its backoff.
    waiting: list = []

    for _ in range(MAX_PER_TICK):
        query = (
            select(RealWalletTradeAlert, RealWalletPosition, DiscoveredToken.symbol)
            .join(RealWalletPosition, RealWalletPosition.id == RealWalletTradeAlert.position_id)
            .outerjoin(DiscoveredToken, DiscoveredToken.mint_address == RealWalletPosition.mint_address)
            .where(RealWalletTradeAlert.status == "pending")
            .order_by(event_time, RealWalletTradeAlert.event.desc())
            .limit(1)
            .with_for_update(of=RealWalletTradeAlert, skip_locked=True)
        )
        if waiting:
            query = query.where(RealWalletTradeAlert.position_id.not_in(waiting))
        row = (await session.execute(query)).first()
        if row is None:
            break
        alert, position, symbol = row

        if not _due(alert, now):
            # Still in its backoff. That trade's later message waits with it — a
            # close must never arrive before its open — but other trades' messages
            # go ahead: one refused message once held up every alert for an hour.
            # Commit, not rollback: nothing changed, and this releases the row
            # lock without discarding anything the caller had in progress.
            waiting.append(alert.position_id)
            await session.commit()
            continue

        build = opened_message if alert.event == "opened" else closed_message
        try:
            try:
                await send(build(position, symbol, now))
            except AlertSendError as exc:
                if not exc.blocked:
                    raise
                # The firewall refused these words, and would refuse them again
                # on every retry. The short form carries the news without them.
                await send(short_form(build(position, None, now)))
        except AlertSendError as exc:
            alert.attempts += 1
            alert.last_attempt_at = now
            alert.last_error = _scrub(str(exc))[:500]
            if exc.rate_limited:
                # Keep the longest wait and never give up: the limit is 25 per
                # 240 minutes, so the message goes out late rather than never.
                alert.attempts = min(alert.attempts, MAX_ATTEMPTS - 1)
            if alert.attempts >= MAX_ATTEMPTS:
                alert.status = "failed"
                counts["failed"] += 1
                # `trade_event`, not `event`: structlog's first argument IS the
                # event, and passing both crashed the task before it could save
                # the failure — so the alert was retried for ever.
                logger.warning("real_wallet_trade_alert_failed", alert_id=str(alert.id),
                               trade_event=alert.event, attempts=alert.attempts)
            else:
                counts["retrying"] += 1
            await session.commit()
            # The service is not taking messages. Do not hammer it this tick.
            break

        alert.attempts += 1
        alert.last_attempt_at = now
        alert.status = "sent"
        alert.sent_at = now
        alert.last_error = None
        await session.commit()
        counts["sent"] += 1
        if pause:
            await asyncio.sleep(pause)

    return counts


async def tick(session: AsyncSession, *, now: datetime | None = None, send=send_whatsapp,
               pause: float = SEND_GAP_SECONDS) -> dict[str, object]:
    """One pass: notice new trade events, then send what is due."""
    if not enabled():
        return {"enabled": False}
    now = now or datetime.now(UTC)
    return {
        "enabled": True,
        "recorded": await record_new_events(session, now=now),
        "delivered": await deliver_pending(session, now=now, send=send, pause=pause),
    }


async def _send_test() -> None:
    """`python -m app.real_wallet.trade_alerts test` — prove the connection now."""
    if not enabled():
        print("Not configured: WHATSAPP_PHONE and WHATSAPP_CALLMEBOT_KEY must both be set.")
        raise SystemExit(1)
    try:
        reply = await send_whatsapp(
            "✅ MEMESCOPE is connected.\n"
            "Vault will message you here for every real-wallet trade that opens or closes."
        )
    except AlertSendError as exc:
        print(f"Test message FAILED: {exc}")
        raise SystemExit(1) from None
    print(f"Test message sent. CallMeBot replied: {reply}")


if __name__ == "__main__":
    import sys

    if sys.argv[1:] == ["test"]:
        asyncio.run(_send_test())
    else:
        print("usage: python -m app.real_wallet.trade_alerts test")
        raise SystemExit(2)
