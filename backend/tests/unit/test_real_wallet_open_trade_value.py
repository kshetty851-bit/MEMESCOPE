"""The main balance includes an open trade (Karthik, 2026-09-29)."""

from decimal import Decimal as D
from types import SimpleNamespace as P

from app.real_wallet.api import open_trade_value

OWNER = "Owner1111111111111111111111111111111111111"


def test_open_trades_count_at_their_mark_and_only_the_owners():
    positions = [
        P(status="OPEN", wallet_public_key=OWNER, entry_price_usd=D("0.5"),
          quantity=D("100"), last_exec_multiple=D("1.024")),      # $50 now worth $51.20
        P(status="OPEN", wallet_public_key=None, entry_price_usd=D("1"),
          quantity=D("10"), last_exec_multiple=None),              # unmarked: at cost, $10
        P(status="CLOSED", wallet_public_key=OWNER, entry_price_usd=D("1"),
          quantity=D("99"), last_exec_multiple=D("2")),            # closed: not counted
        P(status="OPEN", wallet_public_key="SomeUserWallet", entry_price_usd=D("1"),
          quantity=D("50"), last_exec_multiple=D("1")),            # a user wallet's
    ]
    assert open_trade_value(positions, OWNER) == D("61.200")
    assert open_trade_value([], OWNER) == 0
