"""The trade panel's figures belong to the wallet size the board is set to.

Before this, expanding an arm at $10 x 10 showed the book's $100 fills, so the
row said +14% and every trade under it said $100. Both were right, and read as
a contradiction.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.labs.graduation.api import _paper
from app.labs.graduation.models import GradPaperPosition

pytestmark = pytest.mark.integration

BOOK = "B3_198k_4m"
NOW = datetime.now(UTC) - timedelta(hours=2)


def _trade(mint: str, *, opened: datetime, minutes: int, ret: str) -> GradPaperPosition:
    """One closed $100 paper trade, priced so `net_return` is exactly `ret`."""
    open_quote = D("0.0005")
    return GradPaperPosition(
        id=uuid.uuid4(), book=BOOK, mint=mint, symbol=mint,
        opened_at=opened, closed_at=opened + timedelta(minutes=minutes),
        open_quote=open_quote, open_fill=open_quote,
        close_quote=open_quote * (1 + D(ret)), close_fill=open_quote * (1 + D(ret)),
        notional_usd=D(100), notional_quote=D(1), sol_usd_at_open=D(100),
        tokens=D(1) / open_quote, peak_quote=open_quote, last_quote=open_quote,
        net_return=D(ret), pnl_usd=D(100) * D(ret), close_reason="max_hold",
        impact_open=D("0.001"), impact_close=D("0.001"), liq_open_usd=D("613000"))


async def test_the_panel_answers_for_the_wallet_size_it_was_asked_about(
    db_session: AsyncSession,
) -> None:
    db_session.add_all([
        _trade("MintWin", opened=NOW, minutes=4, ret="0.10"),
        # Opens while the first is still held: a one-ticket wallet cannot pay.
        _trade("MintRug", opened=NOW + timedelta(minutes=1), minutes=4, ret="-0.50"),
        _trade("MintLate", opened=NOW + timedelta(minutes=30), minutes=4, ret="0.20"),
    ])
    await db_session.flush()

    plain = await _paper(db_session, book=BOOK, limit=None)
    assert plain.size_ticket_usd is None
    assert {t.size_pnl_usd for t in plain.closed_trades} == {None}

    whole = await _paper(db_session, book=BOOK, limit=None, ticket=100.0, split=1)
    by_mint = {t.mint: t for t in whole.closed_trades}
    assert by_mint["MintRug"].size_funded is False, "no free money while one is held"
    assert by_mint["MintRug"].size_pnl_usd is None
    assert by_mint["MintWin"].size_funded is True
    assert whole.size_funded == 2 and whole.size_skipped == 1

    split = await _paper(db_session, book=BOOK, limit=None, ticket=25.0, split=4)
    sized = {t.mint: t.size_pnl_usd for t in split.closed_trades}
    assert all(v is not None for v in sized.values()), "four slots pay for all three"
    assert split.size_start_usd == D("100.0")
    # The panel's own total is the row's wallet figure, to the cent.
    assert sum(sized.values()) == (split.size_end_usd - split.size_start_usd).quantize(
        D("0.01"))
    # A quarter-size stake loses about a quarter as much on the same rug.
    assert D("-13") < sized["MintRug"] < D("-12")
