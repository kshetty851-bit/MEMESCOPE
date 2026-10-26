"""USER1's own balance floor (Karthik, 2026-10-12: "user 1 shud stop if falls
below 110$"): under it, that wallet's own switch goes off; nobody else's."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.real_wallet import rug_brake

pytestmark = pytest.mark.unit
NOW = datetime(2026, 10, 12, 12, tzinfo=UTC)
NOV = datetime(2026, 11, 2, tzinfo=UTC)


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
    from app.real_wallet.driver import OWNER_SKIP_POOL_USD, in_skipped_pool

    band = OWNER_SKIP_POOL_USD

    assert in_skipped_pool(Decimal(150_000), band)
    assert in_skipped_pool(Decimal("199999.99"), band)
    assert not in_skipped_pool(Decimal(200_000), band)
    assert not in_skipped_pool(Decimal("149999"), band)
    assert not in_skipped_pool(None, band)  # unread pool: bought as before


async def test_user1_floor_is_110_then_50_from_26_oct():
    assert rug_brake.member_floor("USER1", NOW) == Decimal(110)
    assert rug_brake.member_floor("USER1", NOV) == Decimal(50)   # $50 from 26 Oct
    assert rug_brake.member_floor("USER2", NOV) is None
    s = _Session(SimpleNamespace(own_enabled=True, own_updated_at=None, own_updated_by=None))
    assert not await rug_brake.stop_member_below_floor(s, "USER1", Decimal("200"), NOW)
    assert await rug_brake.stop_member_below_floor(s, "USER1", Decimal("40"), NOV)


def test_user1_skips_150_to_200k_pools_too():
    from app.real_wallet.driver import MEMBER_SKIP_POOL_USD, in_skipped_pool

    assert in_skipped_pool(Decimal(160_000), MEMBER_SKIP_POOL_USD["USER1"])
    assert "USER2" not in MEMBER_SKIP_POOL_USD


def test_main_wallet_skips_ai_names_only_in_small_pools():
    from app.labs.graduation.pool_lab import ai_name
    from app.real_wallet.driver import OWNER_SKIP_AI_POOL_USD, in_skipped_pool

    band = OWNER_SKIP_AI_POOL_USD
    assert in_skipped_pool(Decimal(52_000), band) and ai_name("DeepSeek")
    assert not in_skipped_pool(Decimal(60_000), band)  # bigger AI pools still bought
    assert not in_skipped_pool(Decimal(49_000), band)
