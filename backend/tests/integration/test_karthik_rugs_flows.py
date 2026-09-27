"""Karthik's Lab: the graduations that rugged, and who put money into the
coins the book bought (read on-chain once each trade closed)."""

from __future__ import annotations

import base64
import struct
from datetime import timedelta
from decimal import Decimal

import pytest
from solders.keypair import Keypair
from solders.pubkey import Pubkey

from app.labs.graduation import api, config, scheduler
from app.labs.graduation.models import (
    GradMigration,
    GradOperator,
    GradPaperPosition,
    GradPostgradSample,
    GradToken,
    GradTradeFlow,
)
from app.labs.graduation.tournament import graduation_pool
from app.services.scanner.trade_events import (
    BUY_EVENT_DISCRIMINATOR,
    SELL_EVENT_DISCRIMINATOR,
)

pytestmark = pytest.mark.integration
D = Decimal
START = next(s for s in config.FRESH_BOOKS if s.book == "KARTHIK_QUIET_5M").start


def _mint() -> str:
    return str(Keypair().pubkey())


async def test_a_graduation_rugged_when_its_hour_ends_under_a_fifth(db_session):
    rug, fine, dip, thin, young = _mint(), _mint(), _mint(), _mint(), _mint()
    at = START + timedelta(hours=2)
    now = at + timedelta(hours=2)
    for mint, prices, when in ((rug, [1, 1, 0.5, 0.1, 0.05, 0.04], at),      # drained
                               (fine, [1, 1.1, 1.2, 1.1, 1.3, 1.2], at),
                               (dip, [1, 0.9, 0.05, 0.9, 1.0, 1.1], at),   # a bad print
                               (thin, [1, 0.01], at),                      # too few
                               (young, [1, 1, 1, 1, 0.01, 0.01], now - timedelta(minutes=30))):
        db_session.add(GradMigration(mint=mint, ts=when))
        pool = graduation_pool(mint)
        for i, price in enumerate(prices):
            db_session.add(GradPostgradSample(
                mint=mint, ts=when + timedelta(minutes=i * 5), source="dexscreener",
                pair_address=pool, price_native=D(str(price))))
        # A price on some OTHER pool is never read (DexScreener's order is unstable).
        db_session.add(GradPostgradSample(mint=mint, ts=when + timedelta(minutes=50),
                                          source="dexscreener", pair_address=_mint(),
                                          price_native=D("0.000001")))
    await db_session.flush()
    assert await scheduler.rugs_pass(db_session, now=now) == {"judged": 4, "rugged": 1}
    # The young one waits for its hour; the others are never judged twice.
    assert await scheduler.rugs_pass(db_session, now=now) == {"judged": 0}
    out = await api._graduation_rugs(db_session, START)
    assert out == {"rugged": 1, "measured": 3, "window_minutes": 60}


def _event(head: bytes, pool: str, user: str, sol: float) -> str:
    data = bytearray(200)
    data[:8] = head
    struct.pack_into("<Q", data, 64, int(sol * 1e9))
    data[120:152] = bytes(Pubkey.from_string(pool))
    data[152:184] = bytes(Pubkey.from_string(user))
    return "Program data: " + base64.b64encode(bytes(data)).decode()


class _Rpc:
    def __init__(self, logs: list[str]) -> None:
        self.logs, self.calls = logs, 0

    async def call(self, method: str, params: list) -> dict:
        self.calls += 1
        return {"data": [{"meta": {"logMessages": self.logs}}], "paginationToken": None}


async def test_the_flows_pass_splits_insiders_from_other_traders(db_session):
    mint, creator, funder_wallet, stranger, other = (_mint() for _ in range(5))
    pool = graduation_pool(mint)
    grad = START + timedelta(hours=3)
    db_session.add_all([
        GradToken(mint=mint, creator=creator, first_seen_at=grad - timedelta(hours=1)),
        GradOperator(mint=mint, pool=pool, migrated_at=grad, entry_at=grad,
                     price_native=D(1), depth_usd=D(100000), ids=[funder_wallet],
                     label_due_at=grad + timedelta(minutes=15)),
        GradPaperPosition(
            book="KARTHIK_QUIET_5M", mint=mint, opened_at=grad + timedelta(seconds=40),
            closed_at=grad + timedelta(minutes=6), graduated_at=grad,
            open_quote=D(1), open_fill=D(1), notional_usd=D(100), sol_usd_at_open=D(200),
            notional_quote=D("0.5"), tokens=D(1), peak_quote=D(1)),
    ])
    await db_session.flush()
    rpc = _Rpc([
        _event(BUY_EVENT_DISCRIMINATOR, pool, creator, 1.0),          # insider buys 1 SOL
        _event(SELL_EVENT_DISCRIMINATOR, pool, funder_wallet, 0.5),   # insider sells 0.5
        _event(BUY_EVENT_DISCRIMINATOR, pool, stranger, 2.0),
        _event(BUY_EVENT_DISCRIMINATOR, pool, other, 3.0),
        _event(SELL_EVENT_DISCRIMINATOR, pool, other, 1.0),
        _event(BUY_EVENT_DISCRIMINATOR, _mint(), stranger, 99.0),     # another pool: ignored
    ])
    out = await scheduler.flows_pass(db_session, now=grad + timedelta(minutes=10), rpc=rpc)
    assert out == {"read": 1, "of": 1}
    row = await db_session.get(GradTradeFlow, mint)
    assert (row.insider_buy_usd, row.insider_sell_usd) == (D("200.00"), D("100.00"))
    assert (row.other_buy_usd, row.other_sell_usd) == (D("1000.00"), D("200.00"))
    assert (row.other_buyers, row.swaps, row.insiders_known) == (2, 5, 2)
    # Read once: the next pass has nothing to do and asks the chain nothing.
    before = rpc.calls
    again = await scheduler.flows_pass(db_session, now=grad + timedelta(minutes=12), rpc=rpc)
    assert again == {"read": 0}
    assert rpc.calls == before
