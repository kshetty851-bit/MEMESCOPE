"""The money-source block's two stored halves, against a real database: every
paper entry records who funded its big wallets, and a rug that closed in the
window hands those wallets and funders to the gate."""

from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import delete, select

from app.core.config import settings
from app.labs.graduation.models import GradPaperPosition
from app.models.research_data import HolderSnapshot
from app.paper.service import utcnow
from app.real_wallet import scheduler
from app.real_wallet_safety import sources
from tests.integration.test_real_wallet_entry_holders import _entry
from tests.unit.test_real_wallet_safety import _Helius, _pct

pytestmark = pytest.mark.integration


def _mint() -> str:
    return f"Src{uuid.uuid4().hex[:29]}pump"


def _closed(mint: str, *, ago: timedelta, net_return: str) -> GradPaperPosition:
    row = _entry(mint, age_s=int(ago.total_seconds()) + 300)
    row.closed_at = utcnow() - ago
    row.net_return = Decimal(net_return)
    return row


def _traced(mint: str, *names: str) -> HolderSnapshot:
    return HolderSnapshot(
        mint_address=mint, captured_at=utcnow(), provider="helius", context="paper_entry",
        accounts={"wallets": [], "sources": {"wallets": [f"{n}-wallet" for n in names],
                                             "funders": [f"{n}-funder" for n in names]}})


@pytest.fixture
async def db(test_session_factory, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(scheduler, "SessionFactory", test_session_factory)
    monkeypatch.setattr(settings, "HELIUS_API_KEY", "test-key")
    mints: list[str] = []
    yield test_session_factory, mints
    async with test_session_factory() as s:
        await s.execute(delete(HolderSnapshot).where(HolderSnapshot.mint_address.in_(mints)))
        await s.execute(delete(GradPaperPosition).where(GradPaperPosition.mint.in_(mints)))
        await s.commit()


async def test_only_rugs_inside_the_window_are_blocked(db) -> None:
    factory, mints = db
    fresh_rug, old_rug, winner, untraced_rug = (_mint() for _ in range(4))
    mints += [fresh_rug, old_rug, winner, untraced_rug]
    async with factory() as s:
        s.add_all([
            _closed(fresh_rug, ago=timedelta(hours=1), net_return="-0.82"),
            _traced(fresh_rug, "a"),
            _closed(old_rug, ago=timedelta(hours=4), net_return="-0.93"),
            _traced(old_rug, "b"),
            _closed(winner, ago=timedelta(minutes=10), net_return="0.02"),
            _traced(winner, "c"),
            _closed(untraced_rug, ago=timedelta(minutes=5), net_return="-0.99"),
        ])
        await s.commit()
    async with factory() as s:
        found = await sources.recent_rug_ids(
            s, since=utcnow() - timedelta(hours=3), rug_return=Decimal("-0.50"))
    assert found == {"a-wallet", "a-funder"}


async def test_every_entry_records_who_funded_its_big_wallets(
    db, monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory, mints = db
    mint = _mint()
    mints.append(mint)
    chain = _Helius([("CurveBuyer", _pct("79.31"), False), ("PoolBuyer", _pct("17.01"), False),
                     ("PoolPDA", _pct("3.68"), True)], mint=mint,
                    funders={"CurveBuyer": "FunderA", "PoolBuyer": "FunderB"})
    monkeypatch.setattr(scheduler, "get_rpc", lambda name=None: chain)
    async with factory() as s:
        s.add(_entry(mint, age_s=15))
        await s.commit()

    assert await scheduler._record_entry_holders() == {"recorded": 1}
    async with factory() as s:
        row = await s.scalar(select(HolderSnapshot).where(HolderSnapshot.mint_address == mint))
    assert row.accounts["sources"] == {"wallets": ["CurveBuyer", "PoolBuyer"],
                                       "funders": ["FunderA", "FunderB"]}
    assert row.largest_nonpool_pct == Decimal("79.31")
