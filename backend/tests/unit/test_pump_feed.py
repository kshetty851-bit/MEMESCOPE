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
    def __init__(self, rows, rugged=()):
        self.rows, self.rugged = rows, list(rugged)
    async def execute(self, _stmt): return _Rows(self.rows)
    async def scalars(self, _stmt): return _Rows(self.rugged)


def _row(mint, symbol, pool, age_s=40):
    opened = NOW - timedelta(seconds=10)
    return (mint, symbol, Decimal(pool), opened, NOW - timedelta(seconds=age_s))


async def _pick(rows, rugged=()):
    d = drv.RealWalletDriver(_Session(rows, rugged))
    async def no(*_a, **_k): return False
    d._quiet_big_pool = no
    d._no_open_buy = no
    return await d._next_pump_candidate(now=NOW, wallet="W")


@pytest.mark.asyncio
async def test_the_book_pool_rules_decide_the_coin():
    assert await _pick([_row("LONG", "LONGNAME", 45_000)]) is None       # long name under $50k
    assert await _pick([_row("SHRT", "ABC", 45_000)]) == "SHRT"          # short name: kept
    assert await _pick([_row("LOW", "ABC", 39_000)]) is None             # under $40k
    assert await _pick([_row("BAND", "ABCDEF", 160_000)]) is None        # $150-200k skipped
    assert await _pick([_row("AI", "DeepSeek", 55_000)]) is None         # AI name, $50-60k
    assert await _pick([_row("SPC", "GTA 6", 80_000)]) is None           # spaced name
    assert await _pick([_row("OLD", "ABC", 80_000, age_s=130)]) is None  # past the 2-minute guard
    assert await _pick([_row("BAD", "LONGNAME", 45_000), _row("OK", "ROCK", 60_000)]) == "OK"


@pytest.mark.asyncio
async def test_a_name_that_rugged_in_the_last_12_hours_is_refused():
    assert config.KARTHIK_LAB_RUGGED_NAME_BAN and config.KARTHIK_RUGGED_NAME_HOURS == 12
    assert await _pick([_row("R", "Grok", 80_000)], rugged=["GROK"]) is None
    assert await _pick([_row("R", "Grok", 80_000)], rugged=["ELON"]) == "R"


def test_g_pump_is_registered_and_sized_like_the_lab():
    assert "G-PUMP" in live_spec.BY_ID and live_spec.pool_floor("G-PUMP") == 40_000
    assert drv.lab_sized("G-PUMP", Decimal(10), 60_000, 5, "USER1") == Decimal("10.00")
