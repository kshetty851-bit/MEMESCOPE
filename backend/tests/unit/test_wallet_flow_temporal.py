"""Wallet-flow temporal correctness: no future transaction in an earlier snapshot."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.services.scanner.flow_persistence import STORED, _columns
from app.services.scanner.trade_events import Side, TradeEvent
from app.services.scanner.wallet_flow import WalletFlowTracker

pytestmark = pytest.mark.unit

T0 = datetime(2026, 8, 24, 12, 0, tzinfo=UTC)


def trade(minutes, wallet, side=Side.BUY, amount=100):
    return TradeEvent(
        mint="MINT", pool=None, user=wallet, side=side,
        amount=amount, observed_at=T0 + timedelta(minutes=minutes),
    )


def test_snapshot_at_t_excludes_events_after_t():
    tracker = WalletFlowTracker()
    tracker.apply("MINT", trade(0, "alice"), signature="s1")
    tracker.apply("MINT", trade(1, "bob"), signature="s2")
    # An event stamped AFTER the snapshot moment — clock skew or replay.
    tracker.apply("MINT", trade(10, "carol"), signature="s3")

    snap_at = T0 + timedelta(minutes=2)
    stats = {s.window: s for s in tracker.stats("MINT", now=snap_at)}
    assert stats["1h"].unique_buyers == 2  # carol's future trade is not there
    later = {s.window: s for s in tracker.stats("MINT", now=T0 + timedelta(minutes=11))}
    assert later["1h"].unique_buyers == 3  # and appears once time reaches it


def test_duplicate_signature_never_counts_twice():
    tracker = WalletFlowTracker()
    assert tracker.apply("MINT", trade(0, "alice"), signature="sig")
    assert not tracker.apply("MINT", trade(0, "alice"), signature="sig")
    stats = {s.window: s for s in tracker.stats("MINT", now=T0 + timedelta(minutes=1))}
    assert stats["5m"].buy_count == 1


def test_persistence_column_mapping_is_total():
    """Every FlowStats field lands in a column for every stored window."""
    tracker = WalletFlowTracker()
    tracker.apply("MINT", trade(0, "alice"), signature="a")
    tracker.apply("MINT", trade(1, "bob", side=Side.SELL, amount=40), signature="b")
    stats = {s.window: s for s in tracker.stats("MINT", now=T0 + timedelta(minutes=2))}
    for window, prefix in STORED.items():
        cols = _columns(prefix, stats[window])
        assert cols[f"{prefix}_unique_buyers"] == 1
        assert cols[f"{prefix}_unique_sellers"] == 1
        assert cols[f"{prefix}_quality"] == "exact"
        # sixteen columns per window, none silently dropped
        assert len(cols) == 16
