"""USER1's G-PUMP feed: the Pump Catcher Lab's coins, with the book's rules."""
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.labs.graduation import config, live_spec
from app.real_wallet import driver as drv

NOW = datetime(2026, 10, 26, 10, tzinfo=UTC)          # 14:00 Dubai


class _Rows:
    def __init__(self, rows): self._rows = rows
    def all(self): return self._rows


class _Session:
    """First execute: the feed rows; later ones: the rug-name query's rows."""
    def __init__(self, rows, rugged=()):
        self.rows, self.rugged, self.calls = rows, list(rugged), 0
    async def execute(self, _stmt):
        self.calls += 1
        return _Rows(self.rows if self.calls == 1 else self.rugged)


def _row(mint, symbol, pool, age_s=40, book="KARTHIK_Q50_5M"):
    opened = NOW - timedelta(seconds=10)
    return (mint, symbol, Decimal(pool), opened, NOW - timedelta(seconds=age_s), book)


async def _pick(rows, rugged=(), no_open_buy=False):
    d = drv.RealWalletDriver(_Session(rows, rugged))
    async def no(*_a, **_k): return False
    async def open_buy(*_a, **_k): return no_open_buy
    d._quiet_big_pool = no
    d._no_open_buy = open_buy
    return await d._next_pump_candidate(now=NOW, wallet="W")


@pytest.mark.asyncio
async def test_the_book_pool_rules_decide_the_coin():
    assert await _pick([_row("LONG", "LONGNAME", 45_000)]) is None       # long name under $50k
    assert await _pick([_row("SHRT", "ABC", 45_000)]) == "SHRT"          # short name: kept
    assert await _pick([_row("LOW", "ABC", 39_000)]) is None             # under $40k
    assert await _pick([_row("BAND", "ABCDEF", 160_000)]) is None        # $150-200k skipped
    assert await _pick([_row("AI", "DeepSeek", 55_000)]) is None         # AI name, $50-60k
    assert await _pick([_row("SPC", "GTA 6", 60_000)]) is None           # spaced name
    assert await _pick([_row("OLD", "ABC", 60_000, age_s=130)]) is None  # past the 2-minute guard
    assert await _pick([_row("BAD", "LONGNAME", 45_000), _row("OK", "ROCK", 60_000)]) == "OK"
    assert await _pick([_row("B80", "ABC", 80_000)]) is None             # Pump Catcher's skips (30 Oct)
    assert await _pick([_row("B300", "ABC", 300_000)]) is None
    assert await _pick([_row("B1M", "ABC", 1_000_000)]) is None


class _Redis:
    def __init__(self, exits): self.exits = exits
    async def hmget(self, _key, ids): return [self.exits.get(i) for i in ids]


def _closed(i, symbol, net5, hours_ago=2):
    from types import SimpleNamespace
    opened = NOW - timedelta(hours=hours_ago)
    return SimpleNamespace(id=i, symbol=symbol, opened_at=opened, closed_at=opened + timedelta(minutes=5),
                           net_return=Decimal(str(net5)))


@pytest.mark.asyncio
async def test_a_name_that_rugged_in_the_last_12_hours_is_refused(monkeypatch):
    import json

    import app.core.redis as r
    assert config.KARTHIK_LAB_RUGGED_NAME_BAN and config.KARTHIK_RUGGED_NAME_HOURS == 12
    exits = {"2": json.dumps({"net": -0.8, "held_s": 600})}     # fine at 5 min, rugged by 10
    async def redis(): return _Redis(exits)
    monkeypatch.setattr(r, "init_redis", redis)
    assert await _pick([_row("R", "Grok", 80_000)], rugged=[_closed("1", "Grok", -0.9)]) is None
    assert await _pick([_row("R", "Grok", 80_000)], rugged=[_closed("2", "Grok", 0.05)]) is None
    assert await _pick([_row("R", "Grok", 80_000)], rugged=[_closed("3", "Grok", 0.05)]) == "R"
    assert await _pick([_row("R", "Grok", 80_000)], rugged=[_closed("1", "ELON", -0.9)]) == "R"
    assert await _pick([_row("R", "Grok", 80_000)], rugged=[_closed("1", "Grok", -0.9, hours_ago=13)]) == "R"


def test_g_pump_is_registered_and_sized_like_the_lab():
    assert "G-PUMP" in live_spec.BY_ID and live_spec.pool_floor("G-PUMP") == 40_000
    assert drv.lab_sized("G-PUMP", Decimal(10), 60_000, 5, "USER1") == Decimal("10.00")


@pytest.mark.asyncio
async def test_no_buy_at_open_is_checked_only_where_the_book_checks_it():
    # The $40-50k arm is never read by the book, so a coin from it is bought (Grok, 26 Oct).
    assert await _pick([_row("G", "Grok", 48_000, book="KARTHIK_Q25_5M")], no_open_buy=True) == "G"
    assert await _pick([_row("Q", "ROCK", 60_000, book="KARTHIK_Q50_5M")], no_open_buy=True) is None


def test_lab_lets_three_groups_back_but_user1_keeps_its_skips():
    from types import SimpleNamespace

    from app.labs.graduation import pump_catcher as pc
    assert pc.skipped_pool(1_300_000) and not pc.lab_skipped_pool(1_300_000)   # lab only (31 Oct)
    assert pc.lab_skipped_pool(1_100_000) and pc.lab_skipped_pool(300_000)
    row = lambda age, pool: SimpleNamespace(opened_at=NOW, graduated_at=NOW - timedelta(seconds=age),
                                            liq_open_usd=Decimal(pool))
    assert pc.open_buy_waived(row(50, 80_000)) and pc.open_buy_waived(row(20, 45_000))
    assert not pc.open_buy_waived(row(20, 80_000))
