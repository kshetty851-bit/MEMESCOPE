import asyncio

from app.real_wallet import push, trade_alerts


def test_whatsapp_message_becomes_title_and_body() -> None:
    assert push.split("*Vault bought SpaceX*\n$13.33 at $0.0001\nG-Q50") == (
        "Vault bought SpaceX", "$13.33 at $0.0001\nG-Q50")
    assert push.split("one line") == ("one line", "")


def test_tick_is_off_when_neither_channel_is_set(monkeypatch) -> None:
    monkeypatch.setattr(trade_alerts, "enabled", lambda: False)
    monkeypatch.setattr(push, "configured", lambda: False)
    assert asyncio.run(trade_alerts.tick(object())) == {"enabled": False}


def test_send_all_does_nothing_without_keys(monkeypatch) -> None:
    monkeypatch.setattr(push, "configured", lambda: False)
    assert asyncio.run(push.send_all(object(), "t", "b")) == 0
