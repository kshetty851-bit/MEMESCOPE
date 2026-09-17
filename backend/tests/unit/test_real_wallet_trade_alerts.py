"""WhatsApp alerts for real-wallet trades.

Three promises are tested here, because each one fails quietly:

* every trade is announced once — not zero times, not twice;
* history is never announced, so switching alerts on does not flood a phone;
* the CallMeBot key and phone number never end up anywhere they could be read.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from html import escape

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import select

from app.core.config import settings
from app.models.real_wallet_execution import RealWalletPosition, RealWalletTradeAlert
from app.real_wallet import trade_alerts as ta

KEY = "k3y-5ecret-998877"
# +999 is an unassigned country code, so this cannot be anybody's number.
PHONE = "+9990001234567"
NOW = datetime(2026, 9, 17, 12, 0, tzinfo=UTC)


@pytest.fixture
def configured(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "WHATSAPP_PHONE", PHONE)
    monkeypatch.setattr(settings, "WHATSAPP_CALLMEBOT_KEY", SecretStr(KEY))


def _position(**over) -> RealWalletPosition:
    tag = uuid.uuid4().hex[:12]
    base = dict(
        id=uuid.uuid4(),
        mint_address="N1wFVHKiJxrqLGV4uGbPfxEfy4N6Za1QUv9g9rdpump",
        status="CLOSED",
        quantity=Decimal("2040.221651"),
        entry_price_usd=Decimal("0.024490578557421179"),
        opened_at=NOW - timedelta(minutes=5),
        closed_at=NOW - timedelta(minutes=1),
        strategy_id="G-B3-4M",
        # Unique per trade, as on the live table (uq_real_position_entry_signature).
        entry_transaction_signature=f"ENTRY{tag}",
        exit_transaction_signature=f"EXIT{tag}",
        exit_reason="time_0.06666666666666667h",
        realised_gross_pnl_usd=Decimal("0.3035"),
        realised_net_pnl_usd=Decimal("0.3014"),
    )
    base.update(over)
    return RealWalletPosition(**base)


# --- the words ------------------------------------------------------------------


class TestWords:
    @pytest.mark.parametrize(
        ("reason", "words"),
        [
            ("time_0.06666666666666667h", "timed out after 4m"),
            ("time_2h", "timed out after 2h 0m"),
            ("target_1_5x", "hit the 1.5x target"),
            ("target_2x", "hit the 2x target"),
            ("trailing_stop", "trailing stop"),
            ("dead_zero", "the token died"),
            ("partial_promoted_to_close:partial_taken", "partial take-profit, sold in full"),
            ("time_exit_unpriced", "timed out (no price to mark)"),
            ("something_new", "something_new"),
            (None, "reason not recorded"),
        ],
    )
    def test_every_exit_reads_in_plain_words(self, reason, words):
        assert ta.describe_exit(reason) == words

    def test_a_real_close_reads_like_the_live_one(self):
        """The DUKE trade from the live wallet, 2026-09-17."""
        text = ta.closed_message(_position(), "DUKE", NOW)
        assert text.splitlines()[0] == "✅ REAL WALLET SOLD DUKE"
        assert "+$0.30 (+0.6%) after fees" in text
        assert "timed out after 4m · held 4m" in text
        assert "https://solscan.io/tx/EXIT" in text

    def test_no_line_starts_the_way_callmebots_firewall_refuses(self):
        """It answers HTTP 403 to any line starting "time limit" (measured
        2026-09-17 against the live service), so that message never arrived."""
        reasons = [*ta._EXIT_WORDS, "time_0.06666666666666667h", "time_2h", "target_2x", None]
        for reason in reasons:
            text = ta.closed_message(_position(exit_reason=reason), "DUKE", NOW)
            assert not any(line.lower().startswith("time limit") for line in text.splitlines()), reason

    def test_held_rounds_to_the_nearest_minute(self):
        """NTDA, 2026-09-17: a 4-minute exit that fired at 3m42s once read "held 3m"."""
        opened = NOW - timedelta(minutes=10)
        text = ta.closed_message(
            _position(opened_at=opened, closed_at=opened + timedelta(minutes=3, seconds=42)), "NTDA", NOW
        )
        assert "timed out after 4m · held 4m" in text

    def test_the_short_form_keeps_the_news_and_drops_the_rest(self):
        late = ta.short_form(ta.closed_message(_position(closed_at=NOW - timedelta(minutes=10)), None, NOW))
        assert late.splitlines() == ["✅ REAL WALLET SOLD N1wF…pump", "+$0.30 (+0.6%) after fees", "(10m ago)"]
        fresh = ta.short_form(ta.opened_message(_position(opened_at=NOW), None, NOW))
        assert fresh.splitlines() == ["🟢 REAL WALLET BOUGHT N1wF…pump", "$49.97 at $0.02449"]

    def test_never_calls_gross_net(self):
        text = ta.closed_message(
            _position(realised_net_pnl_usd=None, realised_gross_pnl_usd=Decimal("-1.20")),
            "DUKE", NOW,
        )
        assert "🔻" in text
        assert "-$1.20" in text
        assert "before fees (fees not priced)" in text
        assert "after fees" not in text

    def test_says_so_when_there_is_no_result_at_all(self):
        text = ta.closed_message(
            _position(realised_net_pnl_usd=None, realised_gross_pnl_usd=None), "DUKE", NOW
        )
        assert "result not recorded yet" in text

    def test_an_open_says_what_was_spent_and_at_what_price(self):
        text = ta.opened_message(_position(), "DUKE", NOW)
        assert text.splitlines()[0] == "🟢 REAL WALLET BOUGHT DUKE"
        assert "$49.97 at $0.02449" in text
        assert "Strategy G-B3-4M" in text
        assert "https://solscan.io/tx/ENTRY" in text

    def test_a_late_message_says_how_late(self):
        old = _position(opened_at=NOW - timedelta(hours=3))
        assert "(3h 0m ago)" in ta.opened_message(old, "DUKE", NOW)
        fresh = _position(opened_at=NOW - timedelta(seconds=30))
        assert "ago" not in ta.opened_message(fresh, "DUKE", NOW)

    def test_a_token_with_no_symbol_gets_a_short_mint(self):
        assert "BOUGHT N1wF…pump" in ta.opened_message(_position(), None, NOW)

    def test_prices_never_go_scientific(self):
        assert ta._price(Decimal("0.00000000048")) == "$0.0000000004800"
        assert ta._price(Decimal("1.5")) == "$1.50"


# --- sending --------------------------------------------------------------------


_REAL_CLIENT = httpx.AsyncClient


def _mock_client(monkeypatch, handler):
    def factory(*args, **kwargs):
        return _REAL_CLIENT(*args, transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(ta.httpx, "AsyncClient", factory)


class TestSending:
    def test_is_off_unless_both_values_are_set(self, monkeypatch):
        monkeypatch.setattr(settings, "WHATSAPP_PHONE", "")
        monkeypatch.setattr(settings, "WHATSAPP_CALLMEBOT_KEY", SecretStr(KEY))
        assert ta.enabled() is False
        monkeypatch.setattr(settings, "WHATSAPP_PHONE", PHONE)
        monkeypatch.setattr(settings, "WHATSAPP_CALLMEBOT_KEY", SecretStr(""))
        assert ta.enabled() is False

    @pytest.mark.asyncio
    async def test_sends_the_text_to_the_configured_number(self, configured, monkeypatch):
        seen = {}

        def handler(request: httpx.Request):
            seen.update(dict(request.url.params))
            return httpx.Response(200, text="<p>Message queued. You will receive it in a few seconds.</p>")

        _mock_client(monkeypatch, handler)
        reply = await ta.send_whatsapp("hello")
        assert seen == {"phone": PHONE, "text": "hello", "apikey": KEY}
        assert "Message queued" in reply

    @pytest.mark.asyncio
    async def test_a_refusal_behind_a_200_is_still_a_failure(self, configured, monkeypatch):
        _mock_client(monkeypatch, lambda r: httpx.Response(200, text="APIKey is invalid"))
        with pytest.raises(ta.AlertSendError, match="refused"):
            await ta.send_whatsapp("hello")

    @pytest.mark.asyncio
    async def test_the_rate_limit_is_a_failure_that_says_so(self, configured, monkeypatch):
        """CallMeBot's own words, answered with HTTP 200. The old check read them as sent."""
        page = ("There is currently a limit of 25 messages per 240 minutes. Please try to "
                "reduce the number of messages sent. For example, group them into one message.")
        _mock_client(monkeypatch, lambda r: httpx.Response(200, text=page))
        with pytest.raises(ta.AlertSendError) as err:
            await ta.send_whatsapp("hello")
        assert err.value.rate_limited and not err.value.blocked

    @pytest.mark.asyncio
    async def test_a_403_is_the_firewall_refusing_the_words(self, configured, monkeypatch):
        page = "<h1>Forbidden</h1><p>You don't have permission to access this resource.</p>"
        _mock_client(monkeypatch, lambda r: httpx.Response(403, text=page))
        with pytest.raises(ta.AlertSendError) as err:
            await ta.send_whatsapp("time limit (4m)")
        assert err.value.blocked and not err.value.rate_limited

    @pytest.mark.asyncio
    async def test_words_in_our_own_message_never_decide_the_outcome(self, configured, monkeypatch):
        """The reply repeats the text we sent; only CallMeBot's own words count."""
        text = "🟢 REAL WALLET BOUGHT WAIT\nERROR & <invalid>"

        def echo(outcome):
            return lambda r: httpx.Response(
                200, text=f"Message to: {PHONE}<br>Text to send: {escape(r.url.params['text'])}<br>{outcome}"
            )

        # A delivered message whose confirmation wording we have never seen.
        _mock_client(monkeypatch, echo("Some brand new success wording."))
        assert "brand new" in await ta.send_whatsapp(text)
        # And a refused one, even though our text says "Message queued".
        _mock_client(monkeypatch, echo("APIKey is invalid."))
        with pytest.raises(ta.AlertSendError, match="refused"):
            await ta.send_whatsapp("Message queued")

    @pytest.mark.asyncio
    async def test_a_stylesheet_saying_error_does_not_fail_a_good_send(self, configured, monkeypatch):
        page = "<style>.error{color:red}</style><script>var e='error'</script><b>Message queued</b>"
        _mock_client(monkeypatch, lambda r: httpx.Response(200, text=page))
        assert "Message queued" in await ta.send_whatsapp("hello")

    @pytest.mark.asyncio
    async def test_no_error_ever_carries_the_key_or_the_number(self, configured, monkeypatch):
        # A reply that echoes both back, and a network failure whose text
        # would include the full request URL.
        _mock_client(monkeypatch, lambda r: httpx.Response(500, text=f"bad key {KEY} for {PHONE}"))
        with pytest.raises(ta.AlertSendError) as http_err:
            await ta.send_whatsapp("hello")

        def boom(request: httpx.Request):
            raise httpx.ConnectError(f"cannot reach {request.url}")

        _mock_client(monkeypatch, boom)
        with pytest.raises(ta.AlertSendError) as net_err:
            await ta.send_whatsapp("hello")

        for err in (http_err.value, net_err.value):
            text = str(err) + repr(err) + repr(err.__cause__) + repr(err.__context__)
            assert KEY not in text
            assert PHONE not in text
            assert PHONE.lstrip("+") not in text


# --- the log --------------------------------------------------------------------


class _Phone:
    """Stands in for WhatsApp. Records what arrived; can be told to fail."""

    def __init__(self):
        self.inbox: list[str] = []
        #: True, or a piece of text: down for every message, or just those.
        self.failing: bool | str = False
        self.rate_limited = False
        #: The firewall 403s any message containing this.
        self.refuses: str | None = None

    async def __call__(self, text: str) -> str:
        if self.failing is True or (self.failing and self.failing in text):
            raise ta.AlertSendError(f"CallMeBot answered HTTP 503: down, key {KEY}")
        if self.rate_limited:
            raise ta.AlertSendError("CallMeBot rate limit: 25 per 240 minutes", rate_limited=True)
        if self.refuses and self.refuses in text:
            raise ta.AlertSendError("CallMeBot's firewall refused the text (HTTP 403)", blocked=True)
        self.inbox.append(text)
        return "Message queued"


async def _alerts(db_session):
    return (await db_session.execute(select(RealWalletTradeAlert))).scalars().all()


class TestTheLog:
    @pytest.mark.asyncio
    async def test_does_nothing_at_all_until_configured(self, db_session):
        db_session.add(_position())
        await db_session.flush()
        phone = _Phone()
        assert await ta.tick(db_session, now=NOW, send=phone, pause=0) == {"enabled": False}
        assert phone.inbox == []
        assert await _alerts(db_session) == []

    @pytest.mark.asyncio
    async def test_never_announces_history(self, configured, db_session):
        # Seventeen trades had already happened when alerts were switched on.
        for i in range(17):
            db_session.add(_position(
                mint_address=f"OLD{i:040d}",
                opened_at=NOW - timedelta(hours=5, minutes=i),
                closed_at=NOW - timedelta(hours=4, minutes=i),
            ))
        await db_session.flush()
        phone = _Phone()
        await ta.tick(db_session, now=NOW, send=phone, pause=0)
        assert phone.inbox == []
        rows = await _alerts(db_session)
        assert len(rows) == 34
        assert {r.status for r in rows} == {"baseline"}

    @pytest.mark.asyncio
    async def test_announces_an_open_then_its_close_exactly_once(self, configured, db_session):
        phone = _Phone()
        pos = _position(status="OPEN", closed_at=None, exit_transaction_signature=None,
                        exit_reason=None, realised_net_pnl_usd=None, realised_gross_pnl_usd=None)
        db_session.add(pos)
        await db_session.flush()

        await ta.tick(db_session, now=NOW, send=phone, pause=0)
        await ta.tick(db_session, now=NOW + timedelta(seconds=30), send=phone, pause=0)
        assert len(phone.inbox) == 1 and "BOUGHT" in phone.inbox[0]

        pos.status = "CLOSED"
        pos.closed_at = NOW + timedelta(minutes=4)
        pos.exit_transaction_signature = f"EXIT{uuid.uuid4().hex[:8]}"
        pos.realised_net_pnl_usd = Decimal("0.30")
        await db_session.flush()
        for s in (240, 270, 300):
            await ta.tick(db_session, now=NOW + timedelta(seconds=s), send=phone, pause=0)

        assert len(phone.inbox) == 2
        assert "SOLD" in phone.inbox[1]
        assert {r.status for r in await _alerts(db_session)} == {"sent"}

    @pytest.mark.asyncio
    async def test_sends_the_open_before_the_close_when_both_are_new(self, configured, db_session):
        # A trade that opened and closed between two ticks.
        db_session.add(_position(opened_at=NOW - timedelta(seconds=50),
                                 closed_at=NOW - timedelta(seconds=10)))
        await db_session.flush()
        phone = _Phone()
        await ta.tick(db_session, now=NOW, send=phone, pause=0)
        assert ["BOUGHT" in m for m in phone.inbox] == [True, False]
        assert "SOLD" in phone.inbox[1]

    @pytest.mark.asyncio
    async def test_a_failure_is_retried_later_not_hammered(self, configured, db_session):
        db_session.add(_position(opened_at=NOW - timedelta(seconds=20),
                                 closed_at=NOW - timedelta(seconds=10)))
        await db_session.flush()
        phone = _Phone()
        phone.failing = True

        result = await ta.tick(db_session, now=NOW, send=phone, pause=0)
        # One attempt, then it stops for the tick rather than trying the close too.
        assert result["delivered"] == {"sent": 0, "failed": 0, "retrying": 1}

        # Too soon: the backoff holds, and the close still waits behind the open.
        phone.failing = False
        await ta.tick(db_session, now=NOW + timedelta(seconds=5), send=phone, pause=0)
        assert phone.inbox == []

        await ta.tick(db_session, now=NOW + timedelta(seconds=40), send=phone, pause=0)
        assert ["BOUGHT" in m for m in phone.inbox] == [True, False]

    @pytest.mark.asyncio
    async def test_a_firewall_refusal_sends_the_short_form(self, configured, db_session):
        db_session.add(_position(opened_at=NOW - timedelta(seconds=20), closed_at=None))
        await db_session.flush()
        phone = _Phone()
        # The firewall objects to something in the full message — here the link.
        phone.refuses = "https://"
        result = await ta.tick(db_session, now=NOW, send=phone, pause=0)
        assert result["delivered"]["sent"] == 1
        assert phone.inbox == ["🟢 REAL WALLET BOUGHT N1wF…pump\n$49.97 at $0.02449"]
        (alert,) = await _alerts(db_session)
        assert alert.status == "sent"

    @pytest.mark.asyncio
    async def test_when_even_the_short_form_is_refused_it_retries_later(self, configured, db_session):
        db_session.add(_position(opened_at=NOW - timedelta(seconds=20), closed_at=None))
        await db_session.flush()
        phone = _Phone()
        phone.refuses = "REAL WALLET"
        result = await ta.tick(db_session, now=NOW, send=phone, pause=0)
        assert result["delivered"] == {"sent": 0, "failed": 0, "retrying": 1}
        (alert,) = await _alerts(db_session)
        assert alert.status == "pending" and "403" in alert.last_error

    @pytest.mark.asyncio
    async def test_one_stuck_trade_does_not_hold_up_another(self, configured, db_session):
        """NTDA, 2026-09-17: a refused sell message blocked every later alert."""
        db_session.add(_position(mint_address="STUCK" + "1" * 38, opened_at=NOW - timedelta(seconds=50),
                                 closed_at=NOW - timedelta(seconds=40)))
        db_session.add(_position(mint_address="FRESH" + "2" * 38, opened_at=NOW - timedelta(seconds=10),
                                 closed_at=None))
        await db_session.flush()
        phone = _Phone()
        phone.failing = "STUC"

        await ta.tick(db_session, now=NOW, send=phone, pause=0)
        assert phone.inbox == []  # one failure per tick, never a burst

        await ta.tick(db_session, now=NOW + timedelta(seconds=5), send=phone, pause=0)
        assert len(phone.inbox) == 1 and "BOUGHT FRES…2222" in phone.inbox[0]
        # The stuck trade's close still waits behind its own open.
        stuck = [a for a in await _alerts(db_session) if a.status == "pending"]
        assert sorted(a.event for a in stuck) == ["closed", "opened"]

    @pytest.mark.asyncio
    async def test_a_rate_limited_message_waits_instead_of_giving_up(self, configured, db_session):
        db_session.add(_position(opened_at=NOW, closed_at=None))
        await db_session.flush()
        phone = _Phone()
        phone.rate_limited = True
        at = NOW
        for _ in range(ta.MAX_ATTEMPTS + 4):
            await ta.tick(db_session, now=at, send=phone, pause=0)
            at += timedelta(hours=1)
        (alert,) = await _alerts(db_session)
        assert alert.status == "pending"
        assert alert.attempts == ta.MAX_ATTEMPTS - 1

        phone.rate_limited = False
        await ta.tick(db_session, now=at, send=phone, pause=0)
        assert len(phone.inbox) == 1 and phone.inbox[0].endswith("(12h 0m ago)")

    @pytest.mark.asyncio
    async def test_gives_up_after_the_last_attempt_and_says_so(self, configured, db_session):
        db_session.add(_position(opened_at=NOW, closed_at=None, exit_transaction_signature=None))
        await db_session.flush()
        phone = _Phone()
        phone.failing = True
        at = NOW
        for _ in range(ta.MAX_ATTEMPTS + 2):
            await ta.tick(db_session, now=at, send=phone, pause=0)
            at += timedelta(hours=1)
        (alert,) = await _alerts(db_session)
        assert alert.status == "failed"
        assert alert.attempts == ta.MAX_ATTEMPTS
        # The stored error says what happened, without the key in it.
        assert "503" in alert.last_error
        assert KEY not in alert.last_error

    @pytest.mark.asyncio
    async def test_never_writes_to_a_position(self, configured, db_session):
        pos = _position(opened_at=NOW - timedelta(seconds=20), closed_at=NOW - timedelta(seconds=10))
        db_session.add(pos)
        await db_session.flush()
        before = {c.key: getattr(pos, c.key) for c in RealWalletPosition.__table__.columns}
        await ta.tick(db_session, now=NOW, send=_Phone(), pause=0)
        await db_session.refresh(pos)
        after = {c.key: getattr(pos, c.key) for c in RealWalletPosition.__table__.columns}
        assert after == before


class TestVaultsDesk:
    """Vault looks after the real wallet: the trades, and each WhatsApp."""

    @pytest.mark.asyncio
    async def test_shows_every_real_trade_with_its_whatsapp(self, configured, db_session):
        from app.hq_ops import desk

        now = datetime.now(UTC)
        pos = _position(opened_at=now - timedelta(seconds=50), closed_at=now - timedelta(seconds=10))
        db_session.add(pos)
        await db_session.flush()
        await ta.tick(db_session, now=now, send=_Phone(), pause=0)

        dossier = await desk.build(db_session, "vault", now=now)
        assert dossier.measured is True
        assert "1 real trade opened, 1 closed, 2 WhatsApp alerts sent." == dossier.headline
        details = [e.detail for e in dossier.timeline]
        assert all("WhatsApp sent" in d for d in details)
        assert any("+0.30 USD net" in d for d in details)

    @pytest.mark.asyncio
    async def test_says_plainly_when_alerts_are_off(self, db_session, monkeypatch):
        from app.hq_ops import desk

        monkeypatch.setattr(settings, "WHATSAPP_PHONE", "")
        now = datetime.now(UTC)
        db_session.add(_position(opened_at=now - timedelta(minutes=2), closed_at=None))
        await db_session.flush()
        dossier = await desk.build(db_session, "vault", now=now)
        assert "WhatsApp alerts are OFF" in dossier.headline
        assert dossier.timeline[0].detail.endswith("WhatsApp: off")
        assert dossier.readings[0].value == "off — not configured"

    @pytest.mark.asyncio
    async def test_never_shows_the_phone_number(self, configured, db_session):
        from app.hq_ops import desk

        now = datetime.now(UTC)
        db_session.add(_position(opened_at=now - timedelta(seconds=20), closed_at=None))
        await db_session.flush()
        phone = _Phone()
        phone.failing = True
        await ta.tick(db_session, now=now, send=phone, pause=0)
        dossier = desk.as_dict(await desk.build(db_session, "vault", now=now))
        blob = repr(dossier)
        assert PHONE not in blob and PHONE.lstrip("+") not in blob
        assert KEY not in blob
