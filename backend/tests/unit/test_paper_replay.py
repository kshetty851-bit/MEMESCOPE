"""Deterministic replay, and the two fill conventions.

The point of this module is that V1.0's *signal* and V1.0's *fill* are separable
claims. The signal comes from `exits.resolve`, the same function the wallet ran,
so a reproduced timestamp is evidence about the wallet. The fill is a modelling
choice, and the tests below pin the arithmetic that measures how much the
optimistic choice was worth.

`TestSyntheticFillAdvantage` is the one that matters: it fixes the sign
convention. Getting it backwards would report the bias as a penalty and send the
research in the opposite direction.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import ClassVar

from app.paper.exits import ExitRules
from app.paper.models import ExitReason, Quote
from app.paper.replay import (
    OBSERVED_FILL_NOTE,
    RESOLUTION_NOTE,
    FillModel,
    Mismatch,
    reconcile,
    replay,
)

OPENED = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
ENTRY = Decimal(100)
SIZE = Decimal(100)
DEEP = Decimal(1_000_000)  # deep enough that impact is negligible


def quote(minutes: int, price: str) -> Quote:
    return Quote(price_usd=Decimal(price), captured_at=OPENED + timedelta(minutes=minutes))


TRAIL_25 = ExitRules(trailing_drawdown=Decimal("0.25"))


class TestSignalReplay:
    def test_trailing_stop_fires_at_the_breaching_observation(self) -> None:
        # Peak 200 at t=10, trigger is 150. t=15 at 140 breaches.
        path = [quote(5, "120"), quote(10, "200"), quote(15, "140")]
        exit_, peak = replay(
            rules=TRAIL_25,
            entry_price=ENTRY,
            opened_at=OPENED,
            quotes=path,
            size_usd=SIZE,
            entry_liquidity=DEEP,
        )
        assert exit_ is not None
        assert exit_.reason is ExitReason.STOP
        assert exit_.at == OPENED + timedelta(minutes=15)
        assert peak == Decimal(200)

    def test_no_breach_returns_no_exit_and_the_peak(self) -> None:
        path = [quote(5, "110"), quote(10, "130")]
        exit_, peak = replay(
            rules=TRAIL_25,
            entry_price=ENTRY,
            opened_at=OPENED,
            quotes=path,
            size_usd=SIZE,
            entry_liquidity=DEEP,
        )
        assert exit_ is None
        assert peak == Decimal(130)


class TestDualFill:
    """The same breach, priced two ways."""

    # Peak 200 → trigger 150. The breaching observation is far below at 120.
    path: ClassVar[list] = [quote(5, "200"), quote(10, "120")]

    def _exit(self):
        exit_, _ = replay(
            rules=TRAIL_25,
            entry_price=ENTRY,
            opened_at=OPENED,
            quotes=self.path,
            size_usd=SIZE,
            entry_liquidity=DEEP,
        )
        assert exit_ is not None
        return exit_

    def test_legacy_fills_at_the_trigger(self) -> None:
        exit_ = self._exit()
        assert exit_.legacy.model is FillModel.LEGACY_TRIGGER
        assert exit_.legacy.price_usd == Decimal(150)
        assert exit_.legacy.gross_return_pct == Decimal(50)

    def test_observed_fills_at_the_breaching_quote(self) -> None:
        exit_ = self._exit()
        assert exit_.observed.model is FillModel.OBSERVED_SNAPSHOT
        assert exit_.observed.price_usd == Decimal(120)
        assert exit_.observed.gross_return_pct == Decimal(20)

    def test_both_notes_are_carried(self) -> None:
        exit_ = self._exit()
        assert exit_.fill_note == OBSERVED_FILL_NOTE == "EXECUTION_AT_FIRST_OBSERVED_BREACH"
        assert exit_.resolution_note == RESOLUTION_NOTE == "SNAPSHOT_RESOLUTION_ONLY"


class TestSyntheticFillAdvantage:
    """The sign convention, pinned.

    Positive means V1.0 booked a *better* price than the market showed. If this
    inverts, the optimistic bias reads as a penalty.
    """

    def test_gap_down_gives_legacy_a_positive_advantage(self) -> None:
        exit_, _ = replay(
            rules=TRAIL_25,
            entry_price=ENTRY,
            opened_at=OPENED,
            quotes=[quote(5, "200"), quote(10, "120")],
            size_usd=SIZE,
            entry_liquidity=DEEP,
        )
        assert exit_ is not None
        # 150 / 120 - 1 = +25%
        assert exit_.synthetic_fill_advantage_pct == Decimal(25)
        assert exit_.legacy.gross_return_pct > exit_.observed.gross_return_pct

    def test_exact_touch_has_no_advantage(self) -> None:
        exit_, _ = replay(
            rules=TRAIL_25,
            entry_price=ENTRY,
            opened_at=OPENED,
            quotes=[quote(5, "200"), quote(10, "150")],
            size_usd=SIZE,
            entry_liquidity=DEEP,
        )
        assert exit_ is not None
        assert exit_.synthetic_fill_advantage_pct == Decimal(0)

    def test_records_the_gap_before_the_breach(self) -> None:
        exit_, _ = replay(
            rules=TRAIL_25,
            entry_price=ENTRY,
            opened_at=OPENED,
            quotes=[quote(5, "200"), quote(65, "100")],
            size_usd=SIZE,
            entry_liquidity=DEEP,
        )
        assert exit_ is not None
        assert exit_.seconds_since_previous_observation == 3600


class TestNoForwardSearch:
    def test_the_fill_is_the_first_breach_not_a_better_later_price(self) -> None:
        """A recovery after the breach must not be used."""
        path = [quote(5, "200"), quote(10, "120"), quote(15, "190")]
        exit_, _ = replay(
            rules=TRAIL_25,
            entry_price=ENTRY,
            opened_at=OPENED,
            quotes=path,
            size_usd=SIZE,
            entry_liquidity=DEEP,
        )
        assert exit_ is not None
        assert exit_.at == OPENED + timedelta(minutes=10)
        assert exit_.observed.price_usd == Decimal(120)

    def test_duplicate_timestamps_take_the_first(self) -> None:
        path = [
            quote(5, "200"),
            Quote(price_usd=Decimal(120), captured_at=OPENED + timedelta(minutes=10)),
            Quote(price_usd=Decimal(60), captured_at=OPENED + timedelta(minutes=10)),
        ]
        exit_, _ = replay(
            rules=TRAIL_25,
            entry_price=ENTRY,
            opened_at=OPENED,
            quotes=path,
            size_usd=SIZE,
            entry_liquidity=DEEP,
        )
        assert exit_ is not None
        assert exit_.observed.price_usd == Decimal(120)


class TestCosts:
    def test_missing_depth_leaves_net_unavailable_not_zero(self) -> None:
        exit_, _ = replay(
            rules=TRAIL_25,
            entry_price=ENTRY,
            opened_at=OPENED,
            quotes=[quote(5, "200"), quote(10, "120")],
            size_usd=SIZE,
            entry_liquidity=None,
        )
        assert exit_ is not None
        assert exit_.observed.net_return_pct is None
        assert exit_.observed.round_trip_cost_pct is None
        # Gross is still perfectly well defined.
        assert exit_.observed.gross_return_pct == Decimal(20)

    def test_net_is_below_gross_when_depth_is_thin(self) -> None:
        exit_, _ = replay(
            rules=TRAIL_25,
            entry_price=ENTRY,
            opened_at=OPENED,
            quotes=[quote(5, "200"), quote(10, "120")],
            size_usd=SIZE,
            entry_liquidity=Decimal(20_000),
        )
        assert exit_ is not None
        assert exit_.observed.net_return_pct is not None
        assert exit_.observed.net_return_pct < exit_.observed.gross_return_pct


class TestReconciliation:
    path: ClassVar[list] = [quote(5, "200"), quote(10, "120")]

    def _replayed(self):
        exit_, _ = replay(
            rules=TRAIL_25,
            entry_price=ENTRY,
            opened_at=OPENED,
            quotes=self.path,
            size_usd=SIZE,
            entry_liquidity=DEEP,
        )
        return exit_

    def test_a_faithful_replay_matches(self) -> None:
        result = reconcile(
            replayed=self._replayed(),
            recorded_reason="stop",
            recorded_at=OPENED + timedelta(minutes=10),
            recorded_exit_price=Decimal(150),
            recorded_peak=Decimal(200),
            had_path=True,
        )
        assert result.matched
        assert result.rule_match and result.timestamp_match
        assert result.peak_match
        assert result.legacy_price_match
        assert result.timestamp_delta_seconds == 0

    def test_observed_price_is_not_required_to_match_the_record(self) -> None:
        """The fill difference is a convention, not a replay error."""
        result = reconcile(
            replayed=self._replayed(),
            recorded_reason="stop",
            recorded_at=OPENED + timedelta(minutes=10),
            recorded_exit_price=Decimal(150),  # the trigger, not the observed 120
            recorded_peak=Decimal(200),
            had_path=True,
        )
        assert result.matched
        assert result.mismatch is None

    def test_manual_exits_are_classified_not_failed(self) -> None:
        result = reconcile(
            replayed=self._replayed(),
            recorded_reason="manual",
            recorded_at=OPENED + timedelta(minutes=10),
            recorded_exit_price=Decimal(150),
            recorded_peak=Decimal(200),
            had_path=True,
        )
        assert result.mismatch is Mismatch.MANUAL_EXIT
        assert result.matched is False

    def test_missing_path_is_its_own_category(self) -> None:
        result = reconcile(
            replayed=None,
            recorded_reason="stop",
            recorded_at=OPENED,
            recorded_exit_price=Decimal(150),
            recorded_peak=Decimal(200),
            had_path=False,
        )
        assert result.mismatch is Mismatch.MISSING_PATH

    def test_timestamp_drift_is_reported_with_its_delta(self) -> None:
        result = reconcile(
            replayed=self._replayed(),
            recorded_reason="stop",
            recorded_at=OPENED + timedelta(minutes=40),
            recorded_exit_price=Decimal(150),
            recorded_peak=Decimal(200),
            had_path=True,
        )
        assert result.mismatch is Mismatch.TIMESTAMP_DIFFERS
        assert result.timestamp_delta_seconds == -1800

    def test_rule_difference_outranks_timestamp_difference(self) -> None:
        result = reconcile(
            replayed=self._replayed(),
            recorded_reason="expiry",
            recorded_at=OPENED + timedelta(minutes=40),
            recorded_exit_price=Decimal(150),
            recorded_peak=Decimal(200),
            had_path=True,
        )
        assert result.mismatch is Mismatch.RULE_DIFFERS
