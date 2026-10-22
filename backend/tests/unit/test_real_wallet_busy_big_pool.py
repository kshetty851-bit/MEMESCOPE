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
