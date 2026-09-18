"""Every paper entry gets one holder reading, the wallet on or off.

The holder gate's cost is how many winners its line would also refuse. This is
the reading that measures it: taken for every entry of the book the wallet
copies, within seconds of the entry, and never for an entry already too old.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal as D

import pytest
from sqlalchemy import delete, select

from app.core.config import settings
from app.labs.graduation.models import GradPaperPosition
from app.models.research_data import HolderSnapshot
from app.paper.service import utcnow
from app.real_wallet import scheduler
from tests.unit.test_real_wallet_safety import _Helius, _pct

pytestmark = pytest.mark.integration


def _entry(mint: str, *, age_s: int) -> GradPaperPosition:
    opened = utcnow() - timedelta(seconds=age_s)
    quote = D("0.0005")
    return GradPaperPosition(
        id=uuid.uuid4(), book="BASE_75k_5m", mint=mint, symbol="TEST",
        opened_at=opened, closed_at=None, open_quote=quote, open_fill=quote,
        notional_usd=D(100), notional_quote=D(1), sol_usd_at_open=D(100),
        tokens=D(1) / quote, peak_quote=quote, last_quote=quote,
        impact_open=D("0.001"), liq_open_usd=D("250000"))


@pytest.fixture
async def recorder(test_session_factory, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(scheduler, "SessionFactory", test_session_factory)
    monkeypatch.setattr(settings, "HELIUS_API_KEY", "test-key")
    mints: list[str] = []
    yield test_session_factory, mints
    async with test_session_factory() as s:
        await s.execute(delete(HolderSnapshot).where(HolderSnapshot.mint_address.in_(mints)))
        await s.execute(delete(GradPaperPosition).where(GradPaperPosition.mint.in_(mints)))
        await s.commit()


async def test_a_fresh_entry_is_read_once(recorder, monkeypatch: pytest.MonkeyPatch) -> None:
    factory, mints = recorder
    mint = f"Hold{uuid.uuid4().hex[:28]}pump"
    mints.append(mint)
    chain = _Helius([("Whale", _pct("19.99"), False), ("PoolPDA", _pct("1.47"), True)],
                    mint=mint)
    monkeypatch.setattr(scheduler, "get_rpc", lambda name=None: chain)
    async with factory() as s:
        s.add(_entry(mint, age_s=20))
        await s.commit()

    assert await scheduler._record_entry_holders() == {"recorded": 1}
    assert await scheduler._record_entry_holders() == {"recorded": 0}, "read twice"
    async with factory() as s:
        rows = (await s.scalars(select(HolderSnapshot)
                                .where(HolderSnapshot.mint_address == mint))).all()
    assert [(r.context, r.largest_nonpool_pct) for r in rows] == [("paper_entry", D("19.99"))]
    assert rows[0].accounts["pool_raw"] == _pct("1.47")


async def test_an_entry_already_minutes_old_is_not_read(
    recorder, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Read late, the holders include whatever happened after the entry — for a
    rug, the dump itself. An old entry is skipped, not read wrong."""
    factory, mints = recorder
    mint = f"Hold{uuid.uuid4().hex[:28]}pump"
    mints.append(mint)
    monkeypatch.setattr(scheduler, "get_rpc", lambda name=None: _Helius([], mint=mint))
    async with factory() as s:
        s.add(_entry(mint, age_s=300))
        await s.commit()
    assert await scheduler._record_entry_holders() == {"recorded": 0}
