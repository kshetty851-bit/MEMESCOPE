"""USER1's own balance floor (Karthik, 2026-10-12: "user 1 shud stop if falls
below 110$"): under it, that wallet's own switch goes off; nobody else's."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.real_wallet import rug_brake

pytestmark = pytest.mark.unit
NOW = datetime(2026, 10, 12, tzinfo=UTC)


class _Session:
    def __init__(self, row):
        self.row, self.commits = row, 0

    async def get(self, _model, _key):
        return self.row

    async def commit(self):
        self.commits += 1


async def test_user1_under_its_floor_is_switched_off():
    s = _Session(SimpleNamespace(own_enabled=True, own_updated_at=None, own_updated_by=None))
    assert await rug_brake.stop_member_below_floor(s, "USER1", Decimal("109.99"), NOW)
    assert s.row.own_enabled is False and s.row.own_updated_by == rug_brake.FLOOR_ACTOR
    assert s.commits == 1


async def test_at_or_over_the_floor_or_without_one_nothing_changes():
    for member, worth in (("USER1", Decimal("110")), ("USER2", Decimal("1"))):
        s = _Session(SimpleNamespace(own_enabled=True))
        assert not await rug_brake.stop_member_below_floor(s, member, worth, NOW)
        assert s.row.own_enabled is True and s.commits == 0


def test_the_main_wallet_skips_only_measured_150_to_200k_pools():
    from app.real_wallet.driver import OWNER_SKIP_POOL_USD as band, in_skipped_pool

    assert in_skipped_pool(Decimal(150_000), band)
    assert in_skipped_pool(Decimal("199999.99"), band)
    assert not in_skipped_pool(Decimal(200_000), band)
    assert not in_skipped_pool(Decimal("149999"), band)
    assert not in_skipped_pool(None, band)  # unread pool: bought as before
