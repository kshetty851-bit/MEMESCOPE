"""Where a live coin sits in the Checkpoint (2026-10-02), from its records."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.real_wallet.checkpoint_live import BASELINE_BOOK, QUIET_BOOK, Coin, where

GRAD = datetime(2026, 10, 2, 19, 0, tzinfo=UTC)


def at(seconds: float) -> datetime:
    return GRAD + timedelta(seconds=seconds)


def deep(**kw) -> Coin:
    return Coin(graduated=GRAD, liquidity=Decimal(120_000), **kw)


def test_it_waits_for_the_pool_then_calls_it_missing():
    assert where(Coin(graduated=GRAD), at(20)) == {
        "status": "checking", "robot": "depth", "code": None,
        "note": "waiting for the pool to show"}
    assert where(Coin(graduated=GRAD), at(200))["status"] == "stopped"


def test_a_shallow_pool_stops_at_depth_with_its_size():
    out = where(Coin(graduated=GRAD, liquidity=Decimal("20203")), at(40))
    assert (out["status"], out["robot"]) == ("stopped", "depth")
    assert out["note"] == "pool $20,203, under $75,000"


def test_a_rug_block_stops_it_by_its_code():
    out = where(deep(blocked="linked_to_recent_rug"), at(40))
    assert (out["status"], out["robot"]) == ("stopped", None)
    assert out["code"] == "linked_to_recent_rug"


def test_the_quiet_check_passes_it_on_or_stops_a_busy_pool():
    assert where(deep(), at(40))["robot"] == "hush"
    busy = where(deep(books={BASELINE_BOOK: at(35)}), at(60))
    assert (busy["status"], busy["robot"]) == ("stopped", "hush")
    passed = where(deep(books={QUIET_BOOK: at(35), BASELINE_BOOK: at(35)}), at(60))
    assert (passed["status"], passed["robot"]) == ("checking", "switch")


def test_the_wallet_gate_blames_limit_only_when_the_wallet_was_holding_a_coin():
    later = at(35 + 120)
    held = where(deep(books={QUIET_BOOK: at(35)}, wallet_busy=True), later)
    assert (held["status"], held["robot"]) == ("stopped", "limit")
    unknown = where(deep(books={QUIET_BOOK: at(35)}), later)
    assert (unknown["status"], unknown["robot"], unknown["code"]) == ("stopped", None, None)
    assert "not recorded" in unknown["note"]


def test_the_safety_check_stops_it_by_its_first_reason_or_passes_it():
    rejected = deep(books={QUIET_BOOK: at(35)}, intent_at=at(36),
                    evaluations=[(at(37), "REJECT", ["POSITION_TOO_LARGE_FOR_LIQUIDITY"])])
    assert where(rejected, at(40))["code"] == "POSITION_TOO_LARGE_FOR_LIQUIDITY"
    allowed = deep(books={QUIET_BOOK: at(35)}, intent_at=at(36),
                   evaluations=[(at(37), "ALLOW", [])])
    assert where(allowed, at(40))["robot"] == "roundtrip"
    # An evaluation from before this graduation is another coin's history.
    stale = deep(books={QUIET_BOOK: at(35)}, intent_at=at(36),
                 evaluations=[(at(-600), "REJECT", ["MARKET_DATA_STALE"])])
    assert where(stale, at(40))["robot"] == "probe"


def test_a_bought_coin_reaches_the_wallet():
    out = where(deep(books={QUIET_BOOK: at(35)}, bought_at=at(45)), at(50))
    assert (out["status"], out["robot"]) == ("bought", "wallet")
