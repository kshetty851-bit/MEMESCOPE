"""The early-buyer capture, and the one property that makes it worth having.

The event ring drops its OLDEST entries once a mint gets busy, which is
precisely the end that answers "who was early". If the capture ever starts
sharing that fate it will keep returning wallets — recent ones — and every
ranking built on it will quietly be measuring lateness.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.services.scanner.trade_events import Side, TradeEvent
from app.services.scanner.wallet_flow import WalletFlowTracker

NOW = datetime(2026, 9, 9, 12, 0, tzinfo=UTC)
MINT = "EarlyMint" + "1" * 20


def _trade(user: str, *, side: Side = Side.BUY, at: datetime = NOW) -> TradeEvent:
    return TradeEvent(mint=MINT, pool=None, user=user, side=side,
                      amount=1_000, observed_at=at)


def test_the_first_buyers_survive_a_ring_that_has_overflowed_many_times() -> None:
    """THE test. A hot coin trades thousands of times before it is worth
    writing down, and the ring holds a few hundred events — so anything read
    from the ring at that point describes the crowd, not the discoverers."""
    tracker = WalletFlowTracker(capacity=32, max_mints=10, early_buyers=5)

    for i in range(5):
        tracker.apply(MINT, _trade(f"early{i}", at=NOW + timedelta(seconds=i)))
    # Now flood it far past the ring's capacity.
    for i in range(500):
        tracker.apply(MINT, _trade(f"late{i}", at=NOW + timedelta(minutes=1, seconds=i)))

    early = tracker.early_buyers(MINT)
    assert [w for w, _ in early] == [f"early{i}" for i in range(5)]
    assert not any(w.startswith("late") for w, _ in early)


def test_it_stops_at_the_cap_and_keeps_the_earliest() -> None:
    tracker = WalletFlowTracker(capacity=256, max_mints=10, early_buyers=3)
    for i in range(10):
        tracker.apply(MINT, _trade(f"w{i}", at=NOW + timedelta(seconds=i)))

    assert [w for w, _ in tracker.early_buyers(MINT)] == ["w0", "w1", "w2"]


def test_a_wallet_is_recorded_once_however_often_it_buys() -> None:
    """Otherwise a single wallet buying twenty times IS the early list, and
    every coin looks like it was discovered by one bot."""
    tracker = WalletFlowTracker(capacity=256, max_mints=10, early_buyers=5)
    for i in range(20):
        tracker.apply(MINT, _trade("repeat", at=NOW + timedelta(seconds=i)))
    tracker.apply(MINT, _trade("second", at=NOW + timedelta(seconds=30)))

    assert [w for w, _ in tracker.early_buyers(MINT)] == ["repeat", "second"]


def test_sellers_are_not_early_buyers() -> None:
    """A seller is not a discoverer. Counting them would rank wallets for
    being present rather than for being right."""
    tracker = WalletFlowTracker(capacity=256, max_mints=10, early_buyers=5)
    tracker.apply(MINT, _trade("seller", side=Side.SELL))
    tracker.apply(MINT, _trade("buyer", side=Side.BUY, at=NOW + timedelta(seconds=1)))

    assert [w for w, _ in tracker.early_buyers(MINT)] == ["buyer"]


def test_the_buy_time_is_the_trade_time_not_the_write_time() -> None:
    """A forward test is split on this timestamp. If it recorded when the row
    was written, every wallet would look as though it bought at flush time and
    the split would be meaningless."""
    tracker = WalletFlowTracker(capacity=256, max_mints=10, early_buyers=5)
    when = NOW - timedelta(minutes=42)
    tracker.apply(MINT, _trade("w", at=when))

    assert tracker.early_buyers(MINT)[0][1] == when


def test_an_unknown_mint_returns_nothing_rather_than_raising() -> None:
    """The flush asks about every qualified mint, most of which the tracker
    has already evicted. That is a normal outcome, not an error."""
    tracker = WalletFlowTracker(capacity=256, max_mints=10, early_buyers=5)
    assert tracker.early_buyers("never" + "seen" * 8) == []


def test_capture_is_bounded_per_mint_regardless_of_traffic() -> None:
    """The memory argument, asserted rather than trusted: nothing here may
    grow with the number of distinct wallets, which has no natural limit."""
    tracker = WalletFlowTracker(capacity=64, max_mints=3, early_buyers=4)
    for m in range(3):
        for i in range(200):
            tracker.apply(f"mint{m}", TradeEvent(
                mint=f"mint{m}", pool=None, user=f"w{m}_{i}", side=Side.BUY,
                amount=1, observed_at=NOW + timedelta(seconds=i)))
    for m in range(3):
        assert len(tracker.early_buyers(f"mint{m}")) == 4
