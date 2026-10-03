"""Where a live coin sits in the Checkpoint (2026-10-02), from its records."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.real_wallet.checkpoint_live import BASELINE_BOOK, QUIET_BOOK, QUIET_BOOKS, Coin, where

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


# Karthik, 2026-10-03: "in karthik lab only show as 50k pool". His Lab draws
# the belt at his book's $50k rule; HQ and the Real wallet keep the main
# wallet's $75k one.

FIFTY = {"floor": Decimal(50_000), "quiet_books": QUIET_BOOKS[50_000]}


def quiet60(**kw) -> Coin:
    return Coin(graduated=GRAD, liquidity=Decimal(60_000), **kw)


def test_a_60k_pool_passes_depth_at_50k_and_is_stopped_at_75k():
    assert where(quiet60(), at(40)) == {
        "status": "stopped", "robot": "depth", "code": None,
        "note": "pool $60,000, under $75,000"}
    assert where(quiet60(), at(40), **FIFTY)["robot"] == "hush"
    thin = where(Coin(graduated=GRAD, liquidity=Decimal("41234")), at(40), **FIFTY)
    assert (thin["status"], thin["robot"], thin["note"]) == (
        "stopped", "depth", "pool $41,234, under $50,000")


def test_a_coin_his_50k_rule_passed_ends_there_not_stuck_at_the_wallet():
    """The main wallet trades $75k+ pools only, so a $50-75k coin his rule
    bought will never reach its gate. It must not sit at the gate "checking"
    or be blamed on a robot; and a safety check of the same coin (USER 1's
    G-Q50 buys these pools, and evaluations carry no wallet) is not the main
    wallet signing it."""
    taken = quiet60(books={"KARTHIK_Q50_5M": at(35)},
                    evaluations=[(at(37), "ALLOW", [])])
    for t in (at(40), at(400)):
        assert where(taken, t, **FIFTY) == {
            "status": "stopped", "robot": None, "code": None,
            "note": "passed the $50,000 rule; the main wallet buys $75,000+ pools only"}


def test_at_50k_a_75k_plus_coin_still_follows_the_main_wallet():
    passed = where(deep(books={QUIET_BOOK: at(35)}), at(60), **FIFTY)
    assert (passed["status"], passed["robot"]) == ("checking", "switch")
    busy = where(deep(books={BASELINE_BOOK: at(35)}), at(60), **FIFTY)
    assert (busy["status"], busy["robot"]) == ("stopped", "hush")
    allowed = deep(books={QUIET_BOOK: at(35)}, intent_at=at(36),
                   evaluations=[(at(37), "ALLOW", [])])
    assert where(allowed, at(40), **FIFTY)["robot"] == "roundtrip"


def test_at_50k_a_quiet_coin_nothing_took_is_still_waited_on_then_let_go():
    """No buy-everything book covers $50-75k pools, so "too busy" cannot be
    told there: after the wait it says only that the rule did not take it."""
    assert where(quiet60(), at(60), **FIFTY)["status"] == "checking"
    late = where(quiet60(), at(400), **FIFTY)
    assert (late["status"], late["robot"], late["note"]) == (
        "stopped", "hush", "the rule did not take it")


def test_the_75k_rule_reads_the_same_whether_named_or_defaulted():
    """HQ and the Real wallet pass no floor: the default must be exactly the
    $75k rule, on every kind of coin."""
    coins = [
        Coin(graduated=GRAD), quiet60(), deep(), deep(blocked="known_rug_money"),
        quiet60(books={"KARTHIK_Q50_5M": at(35)}, evaluations=[(at(37), "ALLOW", [])]),
        deep(books={BASELINE_BOOK: at(35)}),
        deep(books={QUIET_BOOK: at(35)}, wallet_busy=True),
        deep(books={QUIET_BOOK: at(35)}, intent_at=at(36)),
        deep(books={QUIET_BOOK: at(35)}, bought_at=at(45)),
    ]
    for coin in coins:
        for t in (at(20), at(60), at(400)):
            assert where(coin, t) == where(coin, t, floor=Decimal(75_000),
                                           quiet_books=QUIET_BOOKS[75_000])
