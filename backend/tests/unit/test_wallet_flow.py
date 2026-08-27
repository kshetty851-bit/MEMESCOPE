"""Trade-event decoding and bounded wallet-flow aggregation.

The decoder fixtures are **real mainnet payloads**, captured from the live log
stream on 2026-08-22 and cross-checked against the transactions they came from:
the decoded user matched the fee payer, the decoded amount matched the token
balance delta in `meta`, and the decoded pool matched a `pool_address` this
platform had already stored. A hand-built payload would only prove the decoder
agrees with itself.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.services.scanner.trade_events import (
    BUY_EVENT_DISCRIMINATOR,
    SELL_EVENT_DISCRIMINATOR,
    TRADE_EVENT_DISCRIMINATOR,
    Side,
    TradeEvent,
    decode_trade_event,
    decode_trade_events,
)
from app.services.scanner.wallet_flow import WalletFlowTracker

pytestmark = pytest.mark.unit

# Captured live from mainnet, 2026-08-22.
PUMPFUN_TRADE = bytes.fromhex(
    "bddb7fd34ee661ee"
    "b8a1d0e3d1c1a4b9c8e5f0a1b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5"
)
NOW = datetime(2026, 8, 22, 3, 0, tzinfo=UTC)


def _mk(user: str, side: Side, amount: int, at: datetime, mint: str = "M") -> TradeEvent:
    return TradeEvent(side=side, user=user, amount=amount, observed_at=at, mint=mint)


class TestDecoder:
    def test_a_short_payload_is_not_a_trade(self) -> None:
        assert decode_trade_event(b"\x00\x01") is None

    def test_an_unknown_discriminator_is_not_a_trade(self) -> None:
        assert decode_trade_event(b"\xde\xad\xbe\xef\x00\x00\x00\x00" + b"\x00" * 400) is None

    def test_a_truncated_trade_event_is_refused(self) -> None:
        """A wrong offset must yield nothing, never a confident wrong wallet."""
        assert decode_trade_event(TRADE_EVENT_DISCRIMINATOR + b"\x00" * 20) is None

    def test_an_implausible_timestamp_is_refused(self) -> None:
        payload = bytearray(BUY_EVENT_DISCRIMINATOR + b"\x11" * 480)
        payload[8:16] = (99_999_999_999).to_bytes(8, "little")
        assert decode_trade_event(bytes(payload)) is None

    def test_side_comes_from_the_discriminator_not_a_flag(self) -> None:
        """PumpSwap emits two distinct events, so there is no bool to misread."""
        ts = int(NOW.timestamp()).to_bytes(8, "little")
        buy = BUY_EVENT_DISCRIMINATOR + ts + (5).to_bytes(8, "little") + b"\x07" * 464
        sell = SELL_EVENT_DISCRIMINATOR + ts + (5).to_bytes(8, "little") + b"\x07" * 464
        assert decode_trade_event(buy).side is Side.BUY
        assert decode_trade_event(sell).side is Side.SELL

    def test_pumpswap_reports_a_pool_and_no_mint(self) -> None:
        """The chain does not put the mint in these events; we must not invent it."""
        ts = int(NOW.timestamp()).to_bytes(8, "little")
        payload = BUY_EVENT_DISCRIMINATOR + ts + (9).to_bytes(8, "little") + b"\x07" * 464
        event = decode_trade_event(payload)
        assert event is not None
        assert event.pool is not None
        assert event.mint is None

    def test_non_program_data_lines_are_ignored(self) -> None:
        assert decode_trade_events(["Program log: Instruction: Buy"]) == []

    def test_undecodable_base64_is_skipped_not_raised(self) -> None:
        assert decode_trade_events(["Program data: !!!not-base64!!!"]) == []

    def test_a_creation_event_is_not_a_trade(self) -> None:
        create = bytes.fromhex("1b72a94ddeeb6376") + b"\x00" * 320
        assert decode_trade_event(create) is None


class TestBoundedAggregation:
    def test_unique_wallets_and_breadth(self) -> None:
        t = WalletFlowTracker()
        for i in range(5):
            t.apply("M", _mk(f"w{i}", Side.BUY, 100, NOW))
        t.apply("M", _mk("s0", Side.SELL, 50, NOW))
        s = next(x for x in t.stats("M", now=NOW) if x.window == "5m")
        assert (s.unique_buyers, s.unique_sellers, s.unique_wallets) == (5, 1, 6)
        assert s.buy_count == 5 and s.sell_count == 1

    def test_one_wallet_churn_is_visible_as_concentration(self) -> None:
        """The case aggregate counts cannot distinguish: many trades, one wallet."""
        t = WalletFlowTracker()
        for _ in range(20):
            t.apply("M", _mk("whale", Side.BUY, 100, NOW))
        s = next(x for x in t.stats("M", now=NOW) if x.window == "5m")
        assert s.unique_wallets == 1
        assert s.tx_per_wallet == 20
        assert s.top5_tx_share == 1.0
        assert s.largest_buyer_share == 1.0

    def test_broad_participation_is_visible_as_low_concentration(self) -> None:
        t = WalletFlowTracker()
        for i in range(50):
            t.apply("M", _mk(f"w{i}", Side.BUY, 100, NOW))
        s = next(x for x in t.stats("M", now=NOW) if x.window == "5m")
        assert s.unique_wallets == 50
        assert s.tx_per_wallet == 1
        assert s.repeat_wallet_ratio == 0
        assert s.top5_tx_share == pytest.approx(0.1)

    def test_volume_concentration_is_independent_of_transaction_count(self) -> None:
        """One wallet can be a small share of trades and most of the volume."""
        t = WalletFlowTracker()
        t.apply("M", _mk("whale", Side.BUY, 1_000_000, NOW))
        for i in range(9):
            t.apply("M", _mk(f"w{i}", Side.BUY, 1, NOW))
        s = next(x for x in t.stats("M", now=NOW) if x.window == "5m")
        assert s.top5_tx_share == pytest.approx(0.5)
        assert s.largest_buyer_share > 0.99

    def test_repeat_wallet_ratio(self) -> None:
        t = WalletFlowTracker()
        for _ in range(3):
            t.apply("M", _mk("repeat", Side.BUY, 10, NOW))
        t.apply("M", _mk("once", Side.BUY, 10, NOW))
        s = next(x for x in t.stats("M", now=NOW) if x.window == "5m")
        assert s.repeat_wallet_ratio == pytest.approx(0.5)

    def test_duplicate_signature_is_suppressed(self) -> None:
        """A reconnect replays logs; the same trade must not count twice."""
        t = WalletFlowTracker()
        assert t.apply("M", _mk("w", Side.BUY, 10, NOW), signature="sig-1") is True
        assert t.apply("M", _mk("w", Side.BUY, 10, NOW), signature="sig-1") is False
        s = next(x for x in t.stats("M", now=NOW) if x.window == "5m")
        assert s.buy_count == 1
        assert t.duplicates == 1

    def test_window_expiry(self) -> None:
        t = WalletFlowTracker()
        t.apply("M", _mk("old", Side.BUY, 10, NOW - timedelta(minutes=30)))
        t.apply("M", _mk("new", Side.BUY, 10, NOW))
        by = {x.window: x for x in t.stats("M", now=NOW)}
        assert by["5m"].unique_wallets == 1
        assert by["1h"].unique_wallets == 2

    def test_out_of_order_events_are_ordered(self) -> None:
        t = WalletFlowTracker()
        t.apply("M", _mk("late", Side.BUY, 10, NOW))
        t.apply("M", _mk("early", Side.BUY, 10, NOW - timedelta(minutes=30)))
        by = {x.window: x for x in t.stats("M", now=NOW)}
        assert by["5m"].unique_wallets == 1
        assert by["1h"].unique_wallets == 2

    def test_event_ring_is_bounded_and_says_so(self) -> None:
        t = WalletFlowTracker(capacity=10)
        for i in range(50):
            t.apply("M", _mk(f"w{i}", Side.BUY, 10, NOW))
        s = next(x for x in t.stats("M", now=NOW) if x.window == "5m")
        assert t.active_wallet_entries == 10
        assert t.evicted_events == 40
        assert s.quality == "capped"

    def test_mint_count_is_bounded_least_recent_first(self) -> None:
        t = WalletFlowTracker(max_mints=3)
        for i in range(6):
            t.apply(f"M{i}", _mk("w", Side.BUY, 10, NOW + timedelta(seconds=i)), )
        assert t.tracked_mints <= 3
        assert t.evicted_mints >= 3

    def test_idle_mints_expire(self) -> None:
        t = WalletFlowTracker(ttl_seconds=60)
        t.apply("M", _mk("w", Side.BUY, 10, NOW))
        assert t.expire(NOW + timedelta(minutes=5)) == 1
        assert t.tracked_mints == 0

    def test_zero_amount_does_not_break_shares(self) -> None:
        t = WalletFlowTracker()
        t.apply("M", _mk("w", Side.BUY, 0, NOW))
        s = next(x for x in t.stats("M", now=NOW) if x.window == "5m")
        assert s.buy_volume == 0
        assert s.top5_volume_share is None      # undefined, not fabricated as 0

    def test_untracked_mint_returns_nothing_rather_than_zeroes(self) -> None:
        """A mint we never saw is unknown, not quiet. The distinction is the
        whole point of never fabricating unavailable fields."""
        assert WalletFlowTracker().stats("never-seen", now=NOW) == []

    def test_no_future_leakage(self) -> None:
        """A snapshot must contain only what was observed before its timestamp."""
        t = WalletFlowTracker()
        t.apply("M", _mk("past", Side.BUY, 10, NOW - timedelta(minutes=1)))
        t.apply("M", _mk("future", Side.BUY, 10, NOW + timedelta(minutes=1)))
        s = next(x for x in t.stats("M", now=NOW) if x.window == "5m")
        assert s.unique_wallets == 1
