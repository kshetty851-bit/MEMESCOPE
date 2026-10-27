"""USER1's trades send no WhatsApp or phone alert (Karthik, 2026-10-27)."""
from app.real_wallet import family_wallets, trade_alerts


def test_only_user1_is_muted(monkeypatch):
    who = {"K1": "USER1", "K2": "USER2"}
    monkeypatch.setattr(family_wallets, "member_for", lambda k: who.get(k))
    assert trade_alerts._muted("K1") is True
    assert trade_alerts._muted("K2") is False
    assert trade_alerts._muted("OWNER") is False      # the main wallet still alerts
    assert trade_alerts._muted(None) is False
