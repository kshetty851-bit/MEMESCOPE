"""The real and user wallets' big-pool rule (2026-10-22): $200k+ pools only when busy."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.real_wallet.driver import RealWalletDriver

pytestmark = pytest.mark.unit
NOW = datetime(2026, 10, 22, 12, 0, tzinfo=UTC)


class _Session:
    def __init__(self, buys):
        self.buys, self.asked = buys, 0

    async def scalar(self, _query):
        self.asked += 1
        return self.buys


def _driver(buys) -> RealWalletDriver:
    d = RealWalletDriver.__new__(RealWalletDriver)
    d._session = _Session(buys)
    return d


@pytest.mark.parametrize(("pool", "buys", "skipped"), [
    (199_999, 0, False),        # under $200k: the quiet rule decides, not this
    (250_000, 14, True),        # big and quiet
    (250_000, 15, False),       # big and busy
    (900_000, None, True),      # unread count is quiet, as in the lab
    (None, 40, False),          # pool unread: not this rule's call
])
async def test_big_pools_need_buyers(pool, buys, skipped) -> None:
    d = _driver(buys)
    assert await d._quiet_big_pool("Mint", pool, NOW) is skipped
    assert d._session.asked == (0 if pool is None or pool < 200_000 else 1)


async def test_the_count_is_read_at_the_time_given() -> None:
    # 2026-10-23: the wallet passes the lab's pick time, not its own later
    # clock, so it judges the same buy count the lab refused on.
    from datetime import timedelta

    asked: list[dict] = []

    class Session:
        async def scalar(self, query):
            asked.append(query.compile().params)
            return 20

    d = RealWalletDriver.__new__(RealWalletDriver)
    d._session = Session()
    picked = NOW - timedelta(seconds=40)
    await d._quiet_big_pool("Mint", 500_000, picked)
    assert picked in asked[0].values() and NOW not in asked[0].values()
